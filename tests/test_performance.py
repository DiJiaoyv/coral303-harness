import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-performance-tests")
os.environ["GPU_ENABLED"] = "false"

from app import create_app
from app.models.user import PerformanceLog, User
from app.services.auth_service import register_user
from extensions import db
from performance.config import PerformanceSettings, get_config, reload_config
from performance.gpu_check import detect_gpu
from performance.queue_manager import QueueBusyError, RequestQueue
from performance.runtime import run_inference
from performance.timeout_handler import InferenceTimeoutError, execute_with_timeout


class GpuCheckTest(unittest.TestCase):
    @patch("performance.gpu_check._parse_nvidia_smi", return_value=None)
    def test_no_gpu_graceful(self, _mock):
        info = detect_gpu(force_refresh=True)
        self.assertFalse(info["available"])

    @patch("performance.gpu_check.get_config")
    @patch("performance.gpu_check._parse_nvidia_smi")
    def test_gpu_detected(self, mock_smi, mock_cfg):
        mock_cfg.return_value = PerformanceSettings(GPU_ENABLED=True, GPU_DEVICE_INDEX=0)
        mock_smi.return_value = [{
            "index": 0,
            "name": "NVIDIA Test GPU",
            "memory_total_mb": 8192,
            "memory_free_mb": 4096,
            "memory_used_mb": 4096,
            "utilization_pct": 12.0,
        }]
        info = detect_gpu(force_refresh=True)
        self.assertTrue(info["available"])
        self.assertEqual(info["name"], "NVIDIA Test GPU")
        self.assertEqual(info["device_index"], 0)


class TimeoutHandlerTest(unittest.TestCase):
    def test_execute_with_timeout_success(self):
        result = execute_with_timeout(lambda: 42, timeout=2)
        self.assertEqual(result, 42)

    def test_execute_with_timeout_raises(self):
        def slow():
            time.sleep(0.3)
            return "late"

        with self.assertRaises(InferenceTimeoutError):
            execute_with_timeout(slow, timeout=0.05)


class QueueManagerTest(unittest.TestCase):
    def setUp(self):
        reload_config()

    @patch("performance.queue_manager.get_config")
    def test_enqueue_when_not_full(self, mock_cfg):
        mock_cfg.return_value = PerformanceSettings(
            QUEUE_MAX_SIZE=10,
            TIMEOUT_SECONDS=5,
        )
        q = RequestQueue()
        result = q.enqueue(lambda: "ok")
        self.assertEqual(result, "ok")

    @patch("performance.queue_manager.get_config")
    def test_enqueue_when_full(self, mock_cfg):
        mock_cfg.return_value = PerformanceSettings(
            QUEUE_MAX_SIZE=1,
            TIMEOUT_SECONDS=5,
            BUSY_MESSAGE="系统繁忙，请稍后重试",
        )
        q = RequestQueue()
        gate = threading.Event()
        started = threading.Event()

        def blocking():
            started.set()
            gate.wait(timeout=5)

        t = threading.Thread(target=lambda: q.enqueue(blocking))
        t.start()
        self.assertTrue(started.wait(timeout=2))

        with self.assertRaises(QueueBusyError):
            q.enqueue(lambda: "should-not-run")
        gate.set()
        t.join(timeout=5)

    @patch("performance.queue_manager.get_config")
    def test_concurrent_requests_no_deadlock(self, mock_cfg):
        mock_cfg.return_value = PerformanceSettings(
            QUEUE_MAX_SIZE=10,
            TIMEOUT_SECONDS=10,
        )
        q = RequestQueue()
        results = []

        def worker(n):
            results.append(q.enqueue(lambda: n))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=15)
        self.assertEqual(sorted(results), [0, 1, 2, 3, 4])


class RunInferenceTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        with self.app.app_context():
            db.create_all()

    @patch("performance.runtime.get_request_queue")
    @patch("performance.runtime.record_performance")
    def test_timeout_returns_friendly_message(self, mock_record, mock_get_q):
        cfg = get_config()
        mock_get_q.return_value.enqueue.side_effect = InferenceTimeoutError()
        result = run_inference(lambda: "x", user_id=1, character_id=1)
        self.assertEqual(result, cfg.TIMEOUT_MESSAGE)
        mock_record.assert_called_once()

    @patch("performance.runtime.get_request_queue")
    @patch("performance.runtime.record_performance")
    def test_busy_returns_message(self, mock_record, mock_get_q):
        cfg = get_config()
        mock_get_q.return_value.queue_length = 10
        mock_get_q.return_value.enqueue.side_effect = QueueBusyError(cfg.BUSY_MESSAGE)
        result = run_inference(lambda: "x", user_id=1, character_id=1)
        self.assertEqual(result, cfg.BUSY_MESSAGE)


class FlaskWebChatPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            register_user("flaskchat", "Chat1234")

    def _login(self):
        return self.client.post(
            "/auth/login",
            data={"username": "flaskchat", "password": "Chat1234"},
            follow_redirects=False,
        )

    @patch("app.routes.data_routes.get_user_engine")
    @patch("app.routes.data_routes.run_inference")
    def test_api_chat_uses_run_inference(self, mock_run, mock_engine):
        from harness_core import TurnResult

        mock_engine.return_value.get_active_character.return_value = "hero"
        mock_engine.return_value.format_status_text.return_value = "ok"
        mock_run.return_value = TurnResult(response="你好", new_facts=[], arc_changes=[])

        self._login()
        res = self.client.post(
            "/api/chat",
            json={"message": "hello"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["response"], "你好")
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        self.assertIn("user_id", call_kwargs)
        self.assertIn("character_id", call_kwargs)

    @patch("app.routes.data_routes.get_user_engine")
    @patch("app.routes.data_routes.run_inference")
    def test_api_chat_busy_message(self, mock_run, mock_engine):
        cfg = get_config()
        mock_engine.return_value.get_active_character.return_value = "hero"
        mock_engine.return_value.format_status_text.return_value = "ok"
        mock_run.return_value = cfg.BUSY_MESSAGE

        self._login()
        res = self.client.post(
            "/api/chat",
            json={"message": "hello"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["response"], cfg.BUSY_MESSAGE)
        self.assertEqual(data["new_facts"], [])


class AdminPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            admin = register_user("adminperf", "Admin1234")
            admin.is_admin = True
            normal = register_user("userperf", "User1234")
            db.session.add(
                PerformanceLog(
                    user_id=admin.id,
                    character_id=None,
                    duration_ms=120.5,
                    gpu_util=0.0,
                    queue_length=1,
                    success=True,
                )
            )
            db.session.commit()
            self.admin_id = admin.id
            self.normal_id = normal.id

    def _login(self, username, password):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_admin_can_view_performance(self):
        self._login("adminperf", "Admin1234")
        res = self.client.get("/admin/performance")
        self.assertEqual(res.status_code, 200)
        self.assertIn("推理性能监控", res.get_data(as_text=True))

    def test_normal_user_forbidden(self):
        self._login("userperf", "User1234")
        res = self.client.get("/admin/performance")
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
