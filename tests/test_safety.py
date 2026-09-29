import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-safety-tests")

from app import create_app
from app.models.user import AuditLog
from app.services.auth_service import register_user
from extensions import db
from safety.config import SafetySettings, get_config
from safety.gateway import check_user_input, sanitize_model_output
from safety.input_filter import filter_input
from safety.loader import load_word_lists, reload_word_lists
from safety.output_filter import filter_output
from safety.scanner import normalize_text, scan_text


class SafetyFilterTest(unittest.TestCase):
    def setUp(self):
        import safety.loader as loader_mod

        self.temp_dir = tempfile.mkdtemp()
        self._write_lists(
            prohibited=["badword"],
            warning=["warnword"],
            monitor=["watchword"],
        )
        self.cfg = SafetySettings(
            WORD_LISTS_DIR=self.temp_dir,
            INPUT_BLOCKED_MESSAGE="内容不合规，请重新输入",
            OUTPUT_BLOCKED_MESSAGE="抱歉，我无法回答这个问题",
            HOT_RELOAD_INTERVAL_SEC=0.0,
        )
        self.patches = [
            patch("safety.config.get_config", return_value=self.cfg),
            patch("safety.loader.get_config", return_value=self.cfg),
            patch("safety.scanner.get_config", return_value=self.cfg),
        ]
        for p in self.patches:
            p.start()
        loader_mod._cache = None
        loader_mod._last_check = 0.0
        loader_mod._last_mtime = 0.0
        reload_word_lists()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _write_lists(self, **levels):
        for level, words in levels.items():
            path = os.path.join(self.temp_dir, f"{level}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(words, f)

    def test_prohibited_input_blocked(self):
        result = filter_input("this has badword inside")
        self.assertTrue(result.hit)
        self.assertEqual(result.level, "prohibited")
        self.assertEqual(result.action, "blocked")

    def test_warning_input_allowed(self):
        result = filter_input("hello warnword here")
        self.assertTrue(result.hit)
        self.assertEqual(result.level, "warning")
        self.assertEqual(result.action, "allowed")

    def test_output_prohibited_blocked(self):
        result = filter_output("reply badword end")
        self.assertEqual(result.action, "blocked")

    def test_clean_text_no_hit(self):
        result = scan_text("完全正常的对话内容")
        self.assertFalse(result.hit)

    def test_unicode_nfkc_bypass(self):
        text = "ｂａｄｗｏｒｄ"
        self.assertIn("badword", normalize_text(text))
        result = filter_input(text)
        self.assertTrue(result.hit)

    def test_hot_reload_picks_up_new_words(self):
        self._write_lists(
            prohibited=["badword", "newban"],
            warning=["warnword"],
            monitor=["watchword"],
        )
        reload_word_lists()
        result = filter_input("contains newban word")
        self.assertTrue(result.hit)

    @patch("safety.scanner.load_word_lists", side_effect=OSError("missing file"))
    def test_fail_open_on_scan_error(self, _mock):
        result = scan_text("anything")
        self.assertFalse(result.hit)


class SafetyGatewayLogTest(unittest.TestCase):
    def setUp(self):
        import safety.loader as loader_mod

        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.temp_dir = tempfile.mkdtemp()
        path = os.path.join(self.temp_dir, "prohibited.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(["blockme"], f)
        for name in ("warning.json", "monitor.json"):
            with open(os.path.join(self.temp_dir, name), "w", encoding="utf-8") as f:
                json.dump([], f)

        self.cfg = SafetySettings(
            WORD_LISTS_DIR=self.temp_dir,
            INPUT_BLOCKED_MESSAGE="内容不合规，请重新输入",
            OUTPUT_BLOCKED_MESSAGE="抱歉，我无法回答这个问题",
            HOT_RELOAD_INTERVAL_SEC=0.0,
        )
        self.patches = [
            patch("safety.config.get_config", return_value=self.cfg),
            patch("safety.loader.get_config", return_value=self.cfg),
            patch("safety.scanner.get_config", return_value=self.cfg),
        ]
        for p in self.patches:
            p.start()
        loader_mod._cache = None
        loader_mod._last_check = 0.0
        loader_mod._last_mtime = 0.0
        reload_word_lists()

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_prohibited_input_logs_and_blocks(self):
        with self.app.app_context():
            blocked = check_user_input("blockme please", user_id=1, character_id=2)
            self.assertEqual(blocked, "内容不合规，请重新输入")
            logs = AuditLog.query.all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].level, "prohibited")
            self.assertEqual(logs[0].stage, "input")

    def test_clean_input_no_log(self):
        with self.app.app_context():
            blocked = check_user_input("hello world", user_id=1)
            self.assertIsNone(blocked)
            self.assertEqual(AuditLog.query.count(), 0)

    def test_prohibited_output_replaced(self):
        with self.app.app_context():
            out = sanitize_model_output("blockme output", user_id=1)
            self.assertEqual(out, "抱歉，我无法回答这个问题")
            self.assertEqual(AuditLog.query.count(), 1)
            self.assertEqual(AuditLog.query.first().stage, "output")


class SafetyAdminTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            admin = register_user("safetyadmin", "Admin1234")
            admin.is_admin = True
            register_user("normaluser", "User1234")
            db.session.add(
                AuditLog(
                    user_id=admin.id,
                    stage="input",
                    level="prohibited",
                    matched_word="bl***rd",
                    original_content="secret blocked text",
                    action_taken="blocked",
                )
            )
            db.session.commit()
            self.log_id = AuditLog.query.first().id

    def _login(self, username, password):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_admin_safety_dashboard(self):
        self._login("safetyadmin", "Admin1234")
        res = self.client.get("/admin/safety")
        self.assertEqual(res.status_code, 200)
        self.assertIn("内容安全审核", res.get_data(as_text=True))

    def test_normal_user_forbidden(self):
        self._login("normaluser", "User1234")
        res = self.client.get("/admin/safety")
        self.assertEqual(res.status_code, 403)

    def test_reveal_original_requires_confirm(self):
        self._login("safetyadmin", "Admin1234")
        res = self.client.get(f"/admin/safety/{self.log_id}")
        self.assertNotIn("secret blocked text", res.get_data(as_text=True))
        res = self.client.post(f"/admin/safety/{self.log_id}/reveal", follow_redirects=True)
        self.assertIn("secret blocked text", res.get_data(as_text=True))


class HarnessCoreSafetyTest(unittest.TestCase):
    @patch("harness_core.HarnessEngine._generate_reply")
    @patch("harness_core.HarnessEngine._finalize_turn")
    def test_process_message_skips_model_on_prohibited_input(
        self, mock_finalize, mock_generate
    ):
        from harness_core import HarnessEngine, TurnResult

        with patch("safety.gateway.check_user_input", return_value="内容不合规，请重新输入"):
            engine = HarnessEngine.__new__(HarnessEngine)
            engine.user_id = 1
            engine.hot_reload = False
            result = HarnessEngine.process_message(engine, "bad", character_id=1)
            self.assertEqual(result.response, "内容不合规，请重新输入")
            mock_generate.assert_not_called()
            mock_finalize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
