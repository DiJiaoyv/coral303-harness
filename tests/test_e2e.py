"""Harness 引擎端到端测试（Flask test_client + unittest，Mock Ollama）。"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-harness-e2e-tests")
os.environ["GPU_ENABLED"] = "false"

from api.utils.security import hash_password
from app import create_app
from app.models.user import (
    AuditLog,
    CharacterRecord,
    Conversation,
    PerformanceLog,
    ScoreLog,
    User,
)
from app.routes import data_routes
from character_memory import Memory
from extensions import db
from performance.config import PerformanceSettings, reload_config
from performance.queue_manager import RequestQueue
from performance.runtime import run_inference as _original_run_inference
from safety.config import get_config as get_safety_config

E2E_USER_ID = 8888
E2E_USERNAME = "e2e8888"
E2E_PASSWORD = "E2e88888"
USER_DATA_DIR = os.path.join("users", str(E2E_USER_ID))
MOCK_REPLY = "你好，我是幽灵，很高兴见到你！"


def _memory_get_recent_messages(self, limit: int) -> list[dict]:
    """测试用 shim：Memory 缺少 get_recent_messages 时的兼容实现。"""
    if limit <= 0:
        return []
    return list(self.short_term[-limit:])


class HarnessE2ETestCase(unittest.TestCase):
    """Harness 引擎 API 端到端场景。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not hasattr(Memory, "get_recent_messages"):
            Memory.get_recent_messages = _memory_get_recent_messages  # type: ignore[method-assign]

    @classmethod
    def tearDownClass(cls) -> None:
        if os.path.isdir(USER_DATA_DIR):
            shutil.rmtree(USER_DATA_DIR, ignore_errors=True)

    def _record_performance_flask(
        self,
        *,
        user_id: int | None,
        character_id: int | None,
        duration_ms: float,
        gpu_util: float,
        queue_length: int,
        success: bool,
    ) -> None:
        with self.app.app_context():
            db.session.add(
                PerformanceLog(
                    user_id=user_id,
                    character_id=character_id,
                    duration_ms=float(duration_ms),
                    gpu_util=float(gpu_util),
                    queue_length=int(queue_length),
                    success=bool(success),
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()

    def _run_inference_with_app_context(self, func, **kwargs):
        app = self.app

        def wrapped():
            with app.app_context():
                return func()

        return _original_run_inference(wrapped, **kwargs)

    def setUp(self) -> None:
        reload_config()
        self._db_fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(self._db_fd)
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self._db_path}",
            "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"check_same_thread": False}},
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        data_routes._engines.clear()
        if os.path.isdir(USER_DATA_DIR):
            shutil.rmtree(USER_DATA_DIR, ignore_errors=True)

        self._test_queue = RequestQueue()
        self._patches = [
            patch(
                "app.routes.data_routes.run_inference",
                side_effect=self._run_inference_with_app_context,
            ),
            patch(
                "performance.runtime.get_request_queue",
                return_value=self._test_queue,
            ),
            patch(
                "performance.queue_manager.get_request_queue",
                return_value=self._test_queue,
            ),
            patch(
                "app.routes.data_routes.get_request_queue",
                return_value=self._test_queue,
            ),
            patch(
                "performance.runtime.record_performance",
                side_effect=self._record_performance_flask,
            ),
            patch(
                "app.routes.data_routes.record_performance",
                side_effect=self._record_performance_flask,
            ),
            patch(
                "performance.runtime.detect_gpu",
                return_value={"available": False, "reason": "test"},
            ),
            patch(
                "performance.gpu_check.current_gpu_utilization",
                return_value=0.0,
            ),
        ]
        for p in self._patches:
            p.start()

        with self.app.app_context():
            user = User(
                id=E2E_USER_ID,
                username=E2E_USERNAME,
                password_hash=hash_password(E2E_PASSWORD),
            )
            db.session.add(user)
            db.session.flush()
            char = CharacterRecord(
                user_id=E2E_USER_ID,
                character_key="幽灵",
                display_name="幽灵",
                role="星际赏金猎人",
            )
            db.session.add(char)
            db.session.commit()
            self.character_id = char.id

        self._login()

    def tearDown(self) -> None:
        for p in reversed(getattr(self, "_patches", [])):
            p.stop()
        data_routes._engines.clear()
        with self.app.app_context():
            Conversation.query.filter_by(user_id=E2E_USER_ID).delete()
            ScoreLog.query.filter_by(user_id=E2E_USER_ID).delete()
            PerformanceLog.query.filter_by(user_id=E2E_USER_ID).delete()
            AuditLog.query.filter_by(user_id=E2E_USER_ID).delete()
            CharacterRecord.query.filter_by(user_id=E2E_USER_ID).delete()
            User.query.filter_by(id=E2E_USER_ID).delete()
            db.session.commit()
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

        if os.path.isdir(USER_DATA_DIR):
            shutil.rmtree(USER_DATA_DIR, ignore_errors=True)
        db_path = getattr(self, "_db_path", None)
        if db_path and os.path.isfile(db_path):
            os.remove(db_path)

    def _login(self, client=None) -> None:
        c = client or self.client
        res = c.post(
            "/auth/login",
            data={"username": E2E_USERNAME, "password": E2E_PASSWORD},
            follow_redirects=False,
        )
        self.assertIn(res.status_code, (200, 302))

    def _perf_settings(self, **overrides) -> PerformanceSettings:
        base = {
            "GPU_ENABLED": False,
            "QUEUE_MAX_SIZE": 10,
            "TIMEOUT_SECONDS": 30.0,
            "BUSY_MESSAGE": "系统繁忙，请稍后重试",
            "TIMEOUT_MESSAGE": "抱歉，我思考太久了，请再问一次",
        }
        base.update(overrides)
        return PerformanceSettings(**base)

    @patch("ollama_client.OllamaClient.generate")
    def test_normal_conversation(self, mock_generate) -> None:
        mock_generate.return_value = MOCK_REPLY

        res = self.client.post("/api/chat", json={"message": "你好"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["response"])
        self.assertEqual(data["response"], MOCK_REPLY)

        engine = data_routes.get_user_engine(E2E_USER_ID)
        roles = [m["role"] for m in engine.memory.short_term]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        user_msgs = [m for m in engine.memory.short_term if m["role"] == "user"]
        self.assertTrue(any("你好" in m["content"] for m in user_msgs))

        with self.app.app_context():
            scores = ScoreLog.query.filter_by(user_id=E2E_USER_ID).all()
            perf_logs = PerformanceLog.query.filter_by(user_id=E2E_USER_ID).all()
            self.assertGreaterEqual(len(scores), 1)
            self.assertGreaterEqual(len(perf_logs), 1)
            self.assertEqual(scores[0].user_message, "你好")
            self.assertEqual(scores[0].bot_reply, MOCK_REPLY)

        mock_generate.assert_called()

    @patch("safety.loader.load_word_lists")
    @patch("ollama_client.OllamaClient.generate")
    def test_sensitive_word_block(self, mock_generate, mock_word_lists) -> None:
        mock_word_lists.return_value = {
            "prohibited": ["test_prohibited"],
            "warning": [],
            "monitor": [],
        }
        blocked_msg = get_safety_config().INPUT_BLOCKED_MESSAGE
        res = self.client.post(
            "/api/chat",
            json={"message": "含有 test_prohibited 的输入"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["response"], blocked_msg)
        mock_generate.assert_not_called()

        with self.app.app_context():
            audits = AuditLog.query.filter_by(
                user_id=E2E_USER_ID,
                level="prohibited",
            ).all()
            self.assertGreaterEqual(len(audits), 1)
            self.assertEqual(audits[0].action_taken, "blocked")
            self.assertEqual(audits[0].stage, "input")

    def test_timeout(self) -> None:
        # 推理超时 1s 由 execute_with_timeout 强制；队列 wait 预算单独放宽避免线程竞争误判 BUSY
        cfg = self._perf_settings(TIMEOUT_SECONDS=1.0)
        queue_cfg = self._perf_settings(TIMEOUT_SECONDS=30.0)
        timeout_queue = RequestQueue()

        def slow_generate(*_args, **_kwargs):
            time.sleep(3)
            return "late reply"

        from performance.timeout_handler import execute_with_timeout as real_execute_with_timeout

        def enforce_one_second_timeout(func, timeout=None, **kwargs):
            return real_execute_with_timeout(func, timeout=cfg.TIMEOUT_SECONDS, **kwargs)

        with (
            patch("ollama_client.OllamaClient.generate", side_effect=slow_generate),
            patch("performance.config.get_config", return_value=queue_cfg),
            patch("performance.runtime.get_config", return_value=queue_cfg),
            patch("performance.queue_manager.get_config", return_value=queue_cfg),
            patch("performance.runtime.get_request_queue", return_value=timeout_queue),
            patch("performance.queue_manager.get_request_queue", return_value=timeout_queue),
            patch("app.routes.data_routes.get_request_queue", return_value=timeout_queue),
            patch(
                "performance.queue_manager.execute_with_timeout",
                side_effect=enforce_one_second_timeout,
            ),
        ):
            res = self.client.post("/api/chat", json={"message": "超时测试"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["response"], cfg.TIMEOUT_MESSAGE)

    @patch("performance.queue_manager.get_config")
    @patch("performance.runtime.get_config")
    @patch("performance.config.get_config")
    @patch("ollama_client.OllamaClient.generate")
    def test_queue_full(
        self,
        mock_generate,
        mock_cfg_root,
        mock_cfg_runtime,
        mock_cfg_queue,
    ) -> None:
        cfg = self._perf_settings(QUEUE_MAX_SIZE=1, TIMEOUT_SECONDS=30.0)
        mock_cfg_root.return_value = cfg
        mock_cfg_runtime.return_value = cfg
        mock_cfg_queue.return_value = cfg
        mock_generate.return_value = "blocking ok"

        gate = threading.Event()
        started = threading.Event()

        def hold_queue_slot() -> None:
            started.set()
            gate.wait(timeout=10)

        occupier = threading.Thread(
            target=lambda: self._test_queue.enqueue(hold_queue_slot),
            daemon=True,
        )
        occupier.start()
        self.assertTrue(started.wait(timeout=10), "队列槽位应已被占用")

        res = self.client.post("/api/chat", json={"message": "排队请求"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["response"], cfg.BUSY_MESSAGE)
        mock_generate.assert_not_called()

        gate.set()
        occupier.join(timeout=10)

    @patch("ollama_client.OllamaClient.iter_tokens")
    def test_streaming(self, mock_iter_tokens) -> None:
        def fake_iter(_prompt, cancel_event=None, options=None):
            for token in ("你", "好"):
                if cancel_event is not None and cancel_event.is_set():
                    break
                yield "response", token

        mock_iter_tokens.side_effect = fake_iter

        res = self.client.get("/stream/chat?message=你好")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/event-stream", res.content_type)

        body = res.get_data(as_text=True)
        self.assertIn("event: message", body)
        self.assertIn("event: done", body)
        self.assertIn('"token"', body)


if __name__ == "__main__":
    unittest.main()
