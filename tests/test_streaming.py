"""流式输出与取消生成测试。"""
from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-streaming-tests")
os.environ["GPU_ENABLED"] = "false"

from app import create_app
from app.models.user import User
from app.services.auth_service import register_user
from extensions import db
from harness_core import TurnResult
from performance.config import PerformanceSettings
from performance.queue_manager import RequestQueue
from streaming.cancel_manager import CancelManager, get_cancel_manager, stream_token_for_user
from streaming.sse import default_idle_timeout_sec, sse_generator, sse_pack
from streaming.stream_adapter import adapt_deepseek_stream, adapt_ollama_stream


class CancelManagerTest(unittest.TestCase):
    def test_set_and_is_cancelled(self):
        mgr = CancelManager()
        event = mgr.begin("user:1")
        self.assertFalse(event.is_set())
        self.assertFalse(mgr.is_cancelled("user:1"))
        self.assertTrue(mgr.set_cancel("user:1"))
        self.assertTrue(event.is_set())
        self.assertTrue(mgr.is_cancelled("user:1"))
        mgr.clear("user:1")
        self.assertFalse(mgr.is_cancelled("user:1"))

    def test_begin_cancels_previous(self):
        mgr = CancelManager()
        first = mgr.begin("user:2")
        second = mgr.begin("user:2")
        self.assertTrue(first.is_set())
        self.assertFalse(second.is_set())
        self.assertIs(mgr.get_event("user:2"), second)

    def test_set_cancel_runs_release_once(self):
        mgr = CancelManager()
        calls = []
        mgr.begin("user:3")
        mgr.set_release("user:3", lambda: calls.append(1))
        self.assertTrue(mgr.set_cancel("user:3"))
        mgr.release("user:3")  # 已释放，应 no-op
        self.assertEqual(calls, [1])

    def test_begin_releases_previous_slot(self):
        mgr = CancelManager()
        calls = []
        mgr.begin("user:4")
        mgr.set_release("user:4", lambda: calls.append("old"))
        mgr.begin("user:4")
        self.assertEqual(calls, ["old"])


class SsePackTest(unittest.TestCase):
    def test_sse_pack_format(self):
        out = sse_pack("message", {"token": "你好"})
        self.assertIn("event: message\n", out)
        self.assertIn('data: {"token": "你好"}', out)
        self.assertTrue(out.endswith("\n\n"))

    def test_sse_generator_cancel(self):
        event = threading.Event()

        def source():
            yield "message", {"token": "a"}
            event.set()
            yield "message", {"token": "b"}
            yield "done", {"response": "ab"}

        chunks = list(sse_generator(source(), cancel_event=event))
        joined = "".join(chunks)
        self.assertIn("event: message", joined)
        self.assertIn("event: cancelled", joined)
        self.assertNotIn("event: done", joined)

    def test_sse_idle_timeout(self):
        def source():
            yield "message", {"token": "x"}
            time.sleep(0.05)
            yield "message", {"token": "y"}

        times = [0.0, 0.0, 10.0]

        with patch("streaming.sse.time.monotonic", side_effect=lambda: times.pop(0) if times else 100.0):
            chunks = list(sse_generator(source(), idle_timeout_sec=5.0))
        joined = "".join(chunks)
        self.assertIn("event: error", joined)
        self.assertIn("超时", joined)

    def test_default_idle_matches_performance(self):
        with patch("performance.config.get_config") as mock_cfg:
            mock_cfg.return_value = PerformanceSettings(TIMEOUT_SECONDS=30.0)
            self.assertEqual(default_idle_timeout_sec(), 30.0)


class StreamAdapterTest(unittest.TestCase):
    def test_adapt_ollama_stream(self):
        chunks = [
            {"response": "你"},
            {"response": "好"},
            {"done": True, "response": ""},
        ]
        tokens = list(adapt_ollama_stream(chunks))
        self.assertEqual(tokens, ["你", "好"])

    def test_adapt_ollama_json_lines(self):
        lines = [
            '{"response": "Hi"}',
            '{"response": "!"}',
        ]
        tokens = list(adapt_ollama_stream(lines))
        self.assertEqual(tokens, ["Hi", "!"])

    def test_adapt_ollama_respects_cancel(self):
        event = threading.Event()
        event.set()
        tokens = list(adapt_ollama_stream([{"response": "x"}], cancel_event=event))
        self.assertEqual(tokens, [])

    def test_adapt_deepseek_stream(self):
        chunks = [
            {"choices": [{"delta": {"content": "A"}}]},
            {"choices": [{"delta": {"content": "B"}}]},
        ]
        self.assertEqual(list(adapt_deepseek_stream(chunks)), ["A", "B"])


class QueueStreamSlotTest(unittest.TestCase):
    @patch("performance.queue_manager.get_config")
    def test_try_begin_and_end_stream(self, mock_cfg):
        mock_cfg.return_value = PerformanceSettings(QUEUE_MAX_SIZE=1, TIMEOUT_SECONDS=5)
        q = RequestQueue()
        self.assertTrue(q.try_begin_stream())
        self.assertEqual(q.queue_length, 1)
        self.assertFalse(q.try_begin_stream())
        q.end_stream()
        self.assertEqual(q.queue_length, 0)
        self.assertTrue(q.try_begin_stream())
        q.end_stream()


class ProcessMessageStreamTest(unittest.TestCase):
    def test_stream_tokens_and_done(self):
        from harness_core import HarnessEngine

        engine = MagicMock(spec=HarnessEngine)
        # 直接测真实方法需要大量依赖；改测独立生成逻辑用 patch

        class FakeEngine:
            hot_reload = False
            user_id = 1
            ollama_num_predict = 50
            logger = MagicMock()
            memory = MagicMock()
            chat_ollama = MagicMock()
            pending_character_id = None

            def reload_config(self):
                pass

            def _prepare_emotion_for_turn(self, *a, **k):
                pass

            def build_prompt(self, msg):
                return "PROMPT:" + msg

            def _finalize_turn(self, user_message, ai_response, prompt, character_id=None):
                return TurnResult(response=ai_response, new_facts=[], arc_changes=[])

            def _persist_emotion_state(self, *a, **k):
                pass

            process_message_stream = HarnessEngine.process_message_stream

        fake = FakeEngine()
        fake.chat_ollama.iter_tokens = MagicMock(
            return_value=iter([("response", "你"), ("response", "好")])
        )
        fake.chat_ollama.get_last_call = MagicMock(return_value={})

        with patch("safety.gateway.check_user_input", return_value=None), patch(
            "safety.gateway.sanitize_model_output", side_effect=lambda t, **k: t
        ):
            events = list(
                HarnessEngine.process_message_stream(fake, "hello", character_id=1)
            )

        kinds = [e[0] for e in events]
        self.assertEqual(kinds[:2], ["token", "token"])
        self.assertEqual(kinds[-1], "done")
        self.assertEqual(events[-1][1].response, "你好")

    def test_stream_cancel_returns_partial(self):
        from harness_core import HarnessEngine

        class FakeEngine:
            hot_reload = False
            user_id = 1
            ollama_num_predict = 50
            logger = MagicMock()
            memory = MagicMock()
            chat_ollama = MagicMock()
            pending_character_id = None
            round_count = 0

            def reload_config(self):
                pass

            def _prepare_emotion_for_turn(self, *a, **k):
                pass

            def build_prompt(self, msg):
                return "P"

            def _persist_emotion_state(self, *a, **k):
                pass

        fake = FakeEngine()
        cancel = threading.Event()

        def _iter(prompt, cancel_event=None, **kwargs):
            yield "response", "部"
            cancel.set()
            yield "response", "分"
            if cancel_event is not None and cancel_event.is_set():
                return
            yield "response", "完"

        fake.chat_ollama.iter_tokens = _iter
        fake.chat_ollama.get_last_call = MagicMock(return_value={})

        with patch("safety.gateway.check_user_input", return_value=None), patch(
            "safety.gateway.sanitize_model_output", side_effect=lambda t, **k: t
        ):
            events = list(
                HarnessEngine.process_message_stream(
                    fake, "hi", cancel_event=cancel, character_id=1
                )
            )

        self.assertEqual(events[0], ("token", "部"))
        self.assertEqual(events[-1][0], "cancelled")
        self.assertIn("部", events[-1][1].response)


class StreamingHttpTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        register_user("streamer", "Stream1234")
        # 不 follow_redirects，避免初始化 HarnessEngine 时的控制台编码问题
        self.client.post(
            "/auth/login",
            data={"username": "streamer", "password": "Stream1234"},
            follow_redirects=False,
        )

    def tearDown(self):
        from app.routes import data_routes

        data_routes._engines.clear()
        db.session.remove()
        self.ctx.pop()

    def _login_ok(self):
        user = User.query.filter_by(username="streamer").first()
        self.assertIsNotNone(user)
        return user

    def test_cancel_endpoint(self):
        user = self._login_ok()
        token = stream_token_for_user(user.id)
        mgr = get_cancel_manager()
        mgr.begin(token)
        res = self.client.post("/cancel", json={"session_id": token})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["cancelled"])
        self.assertTrue(mgr.is_cancelled(token))
        mgr.clear(token)

    def test_cancel_rejects_foreign_session(self):
        res = self.client.post("/cancel", json={"session_id": "user:99999"})
        self.assertEqual(res.status_code, 403)

    def test_stream_chat_tokens(self):
        user = self._login_ok()

        def fake_events(**kwargs):
            yield "message", {"token": "你"}
            yield "message", {"token": "好"}
            yield "done", {
                "response": "你好",
                "new_facts": [],
                "arc_changes": [],
                "error": None,
                "status": "ok",
            }

        with patch(
            "app.routes.data_routes._stream_chat_events",
            side_effect=lambda **kw: fake_events(**kw),
        ):
            res = self.client.get("/stream/chat?message=hello")
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.mimetype.startswith("text/event-stream"))
            body = res.get_data(as_text=True)
            self.assertIn("event: message", body)
            self.assertIn("event: done", body)
            self.assertIn("你好", body)

        get_cancel_manager().clear(stream_token_for_user(user.id))

    def test_stream_empty_message(self):
        res = self.client.get("/stream/chat?message=")
        self.assertEqual(res.status_code, 400)

    def test_second_begin_cancels_first(self):
        """连续快速发送：新流 begin 会取消旧流。"""
        user = self._login_ok()
        token = stream_token_for_user(user.id)
        mgr = get_cancel_manager()
        first = mgr.begin(token)
        second = mgr.begin(token)
        self.assertTrue(first.is_set())
        self.assertFalse(second.is_set())
        mgr.clear(token)

    def test_scoring_after_stream_done(self):
        """流结束后评分写入 score_logs。"""
        user = self._login_ok()

        from app.models.user import CharacterRecord

        char = CharacterRecord(
            user_id=user.id,
            character_key="demo",
            display_name="Demo",
            role="tester",
            description="",
            system_prompt="",
        )
        db.session.add(char)
        db.session.commit()

        fake_result = TurnResult(response="完整回复", new_facts=[], arc_changes=[])

        def fake_stream(self, message, cancel_event=None, character_id=None, timeout_seconds=None):
            yield "token", "完"
            yield "token", "整"
            yield "done", fake_result

        with patch(
            "app.routes.data_routes.get_user_engine"
        ) as mock_eng, patch(
            "scoring.engine.score_and_persist"
        ) as mock_score, patch(
            "app.routes.data_routes.record_performance"
        ), patch.object(
            RequestQueue, "try_begin_stream", return_value=True
        ), patch.object(
            RequestQueue, "end_stream"
        ):
            engine = MagicMock()
            engine.get_active_character.return_value = "demo"
            engine.format_status_text.return_value = "status"
            engine.process_message_stream = fake_stream.__get__(engine, type(engine))
            mock_eng.return_value = engine

            from app.routes import data_routes

            events = list(
                data_routes._stream_chat_events(
                    user_id=user.id,
                    message="打分测试",
                    character_id=char.id,
                    cancel_event=threading.Event(),
                )
            )
            kinds = [e[0] for e in events]
            self.assertIn("done", kinds)
            mock_score.assert_called_once()
            args, kwargs = mock_score.call_args
            self.assertEqual(args[0], "打分测试")
            self.assertEqual(args[1], "完整回复")

    def test_static_stream_js_served(self):
        res = self.client.get("/static/js/stream_chat.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"HarnessStreamChat", res.data)
        self.assertIn(b"EventSource", res.data)

    def test_frontend_fallback_marker(self):
        """前端脚本包含 EventSource 降级逻辑。"""
        res = self.client.get("/static/js/stream_chat.js")
        text = res.get_data(as_text=True)
        self.assertIn("supportsEventSource", text)
        self.assertIn("sendSync", text)
        self.assertIn("textContent", text)  # XSS 防护
        self.assertIn("同步降级：始终隐藏停止按钮", text)
        # 同步路径指向 /api/chat（服务端走 run_inference）
        self.assertIn("syncUrl", text)

    def test_sync_api_chat_uses_run_inference(self):
        """确认降级同步路径走性能保障链。"""
        import inspect
        from app.routes import data_routes

        src = inspect.getsource(data_routes.api_chat)
        self.assertIn("run_inference", src)
        self.assertIn("process_message", src)


class OllamaCancelCloseTest(unittest.TestCase):
    def test_iter_tokens_closes_on_cancel(self):
        from ollama_client import OllamaClient

        client = OllamaClient()
        cancel = threading.Event()

        class FakeResp:
            def raise_for_status(self):
                pass

            def iter_lines(self, decode_unicode=True):
                yield '{"response": "a"}'
                cancel.set()
                yield '{"response": "b"}'
                yield '{"response": "c"}'

            def close(self):
                self.closed = True

        fake = FakeResp()
        fake.closed = False

        with patch.object(client, "_post", return_value=fake):
            tokens = list(client.iter_tokens("hi", cancel_event=cancel))

        self.assertTrue(fake.closed)
        # 取消后不应继续产出后续 token（至少在检查点停止）
        response_tokens = [t for f, t in tokens if f == "response"]
        self.assertTrue(len(response_tokens) <= 2)
        self.assertTrue(client.last_response.get("cancelled"))


class OllamaCancelApiTest(unittest.TestCase):
    def test_cancel_ollama_request_posts(self):
        from ollama_client import cancel_ollama_request

        with patch("ollama_client.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            ok = cancel_ollama_request(
                "http://localhost:11434/api/generate",
                model="qwen2.5:7b",
            )
            self.assertTrue(ok)
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertIn("/api/cancel", args[0])


class PartialScoreTest(unittest.TestCase):
    def test_partial_method_marked(self):
        from scoring.engine import score_and_persist

        with patch("scoring.engine.score_conversation") as mock_score, patch(
            "scoring.engine.persist_score_log"
        ) as mock_persist:
            mock_score.return_value = {
                "relevance_score": 2.0,
                "consistency_score": 2.0,
                "fluency_score": 2.0,
                "safety_score": 5.0,
                "total_score": 2.75,
                "scoring_method": "rule",
            }
            score_and_persist(
                "hi",
                "部",
                {"display_name": "x"},
                user_id=1,
                character_id=1,
                method="partial",
            )
            mock_persist.assert_called_once()
            scores = mock_persist.call_args.kwargs["scores"]
            self.assertEqual(scores["scoring_method"], "partial")


if __name__ == "__main__":
    unittest.main()
