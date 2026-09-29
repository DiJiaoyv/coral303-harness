"""系统配置管理（热生效）测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-config-manager")
os.environ["GPU_ENABLED"] = "false"

from app import create_app
from app.services.auth_service import register_user
from extensions import db
from config_manager import registry as reg
from config_manager.backup import BACKUP_DIR, create_backup, list_backups, restore_backup, set_backup_pinned
from config_manager.loader import export_dict, get_config_version, load_all_configs, load_grouped
from config_manager.validator import validate
from config_manager.writer import save_configs, undo_last
from config_manager.registry import get_effective, get_item, requires_restart, UNDO_WINDOW_SEC
from performance.config import get_config as get_perf_config, reload_config as reload_perf


class ConfigRegistryMetadataTest(unittest.TestCase):
    def test_require_restart_metadata(self):
        self.assertEqual(get_effective(get_item("SECRET_KEY")), "require_restart")
        self.assertEqual(get_effective(get_item("ADMIN_PASSWORD")), "require_restart")
        self.assertEqual(get_effective(get_item("WEB_PORT")), "require_restart")
        self.assertEqual(get_effective(get_item("QUEUE_MAX_SIZE")), "hot_reload")
        self.assertTrue(requires_restart("SECRET_KEY"))
        self.assertFalse(requires_restart("CHAT_MODEL"))

    def test_undo_window_is_300_seconds(self):
        self.assertEqual(UNDO_WINDOW_SEC, 300)

    def test_depends_on_present_in_grouped(self):
        groups = load_grouped(mask_sensitive=False)
        model_items = next(g for g in groups if g["id"] == "model")["items"]
        chat = next(i for i in model_items if i["key"] == "CHAT_MODEL")
        self.assertIn("OLLAMA_BASE_URL", chat["depends_on"])
        self.assertIn("depends_hint", chat)

    def test_config_version_changes_with_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"engine": {"hot_reload": True}}, f)
            with patch("config_manager.loader.SOURCE_PATHS", {"config.json": path}):
                v1 = get_config_version()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"engine": {"hot_reload": False}}, f)
                v2 = get_config_version()
        self.assertNotEqual(v1, v2)


class ConfigValidatorTest(unittest.TestCase):
    def test_temperature_in_range(self):
        ok, err = validate("MEMORY_EXTRACT_TEMPERATURE", 0.5)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_temperature_out_of_range(self):
        ok, err = validate("MEMORY_EXTRACT_TEMPERATURE", 3.0)
        self.assertFalse(ok)
        self.assertIn("0.0", err)
        self.assertIn("2.0", err)

    def test_queue_max_size(self):
        ok, _ = validate("QUEUE_MAX_SIZE", 10)
        self.assertTrue(ok)
        ok, err = validate("QUEUE_MAX_SIZE", 0)
        self.assertFalse(ok)
        self.assertIn("1", err)


class ConfigManagerIsolatedTest(unittest.TestCase):
    """使用临时目录隔离配置文件写入。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.paths = {
            "config.json": os.path.join(root, "config.json"),
            "performance.env": os.path.join(root, "performance.env"),
            "safety.env": os.path.join(root, "safety.env"),
            ".env": os.path.join(root, ".env"),
        }
        with open(self.paths["config.json"], "w", encoding="utf-8") as f:
            json.dump({
                "memory_extractor": {"temperature": 0.3},
                "ollama": {"num_predict": 200},
                "engine": {"hot_reload": True},
            }, f)
        with open(self.paths["performance.env"], "w", encoding="utf-8") as f:
            f.write("QUEUE_MAX_SIZE=10\nTIMEOUT_SECONDS=30\n")
        with open(self.paths["safety.env"], "w", encoding="utf-8") as f:
            f.write("FAIL_OPEN=true\nLOG_RETENTION_DAYS=90\n")
        with open(self.paths[".env"], "w", encoding="utf-8") as f:
            f.write("SECRET_KEY=super-secret-key\nADMIN_PASSWORD=AdminPass1\n")

        self.backup_dir = os.path.join(root, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        self._patches = [
            patch("config_manager.loader.SOURCE_PATHS", self.paths),
            patch("config_manager.backup.SOURCE_PATHS", self.paths),
            patch("config_manager.writer.SOURCE_PATHS", self.paths),
            patch("config_manager.backup.BACKUP_DIR", self.backup_dir),
            patch("config_manager.writer.reload_modules_for_sources", return_value=(True, "")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_load_and_mask_sensitive(self):
        vals = load_all_configs(mask_sensitive=True)
        self.assertEqual(vals["SECRET_KEY"], reg.MASK)
        self.assertEqual(vals["QUEUE_MAX_SIZE"], 10)

    def test_save_temperature_updates_file(self):
        ok, msg, errs = save_configs({"MEMORY_EXTRACT_TEMPERATURE": 0.5}, skip_backup=True)
        self.assertTrue(ok, msg)
        self.assertEqual(errs, {})
        with open(self.paths["config.json"], encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["memory_extractor"]["temperature"], 0.5)

    def test_invalid_temperature_not_saved(self):
        with open(self.paths["config.json"], encoding="utf-8") as f:
            before = f.read()
        ok, msg, errs = save_configs({"MEMORY_EXTRACT_TEMPERATURE": 3.0}, skip_backup=True)
        self.assertFalse(ok)
        self.assertIn("MEMORY_EXTRACT_TEMPERATURE", errs)
        with open(self.paths["config.json"], encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_backup_create_and_list(self):
        ts = create_backup(note="test", redact=True)
        items = list_backups()
        self.assertTrue(any(i["timestamp"] == ts for i in items))
        path = os.path.join(self.backup_dir, f"backup_{ts}.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        # 敏感字段脱敏
        secret = snap["files"][".env"].get("SECRET_KEY")
        self.assertEqual(secret, reg.MASK)

    def test_restore_backup(self):
        save_configs({"QUEUE_MAX_SIZE": 7}, skip_backup=True)
        ts = create_backup(note="before-change", redact=False)
        # 再改
        save_configs({"QUEUE_MAX_SIZE": 99}, skip_backup=True)
        ok, msg = restore_backup(ts)
        self.assertTrue(ok, msg)
        with open(self.paths["performance.env"], encoding="utf-8") as f:
            text = f.read()
        self.assertIn("QUEUE_MAX_SIZE=7", text)

    def test_pinned_backup_not_pruned(self):
        with patch("config_manager.backup.get_max_backups", return_value=2):
            ts1 = create_backup(note="a", redact=False)
            ts2 = create_backup(note="b", redact=False)
            ts_pin = create_backup(note="critical", redact=False, pinned=True)
            ts3 = create_backup(note="c", redact=False)
            items = list_backups()
            timestamps = {i["timestamp"] for i in items}
            self.assertIn(ts_pin, timestamps)
            pinned = next(i for i in items if i["timestamp"] == ts_pin)
            self.assertTrue(pinned["pinned"])

    def test_optimistic_lock_conflict(self):
        with patch("config_manager.writer.get_config_version", return_value="current-v"):
            ok, msg, errs = save_configs(
                {"QUEUE_MAX_SIZE": 5},
                skip_backup=True,
                version="stale-v",
            )
        self.assertFalse(ok)
        self.assertIn("其他管理员", msg)
        self.assertIn("_version", errs)

    def test_undo_expired_message_mentions_backup(self):
        import config_manager.writer as writer_mod

        with patch.object(writer_mod, "_undo_stack", {"ts": 0, "snapshots": {}, "changes": {}}):
            with patch("config_manager.writer.time.time", return_value=UNDO_WINDOW_SEC + 1):
                ok, msg = undo_last()
        self.assertFalse(ok)
        self.assertIn("备份", msg)

    def test_export_redacts_sensitive(self):
        data = export_dict(include_sensitive=False)
        self.assertEqual(data["SECRET_KEY"], reg.MASK)
        raw = export_dict(include_sensitive=True)
        self.assertEqual(raw["SECRET_KEY"], "super-secret-key")


class ConfigHotReloadTest(unittest.TestCase):
    def test_performance_reload_after_write(self):
        """写入 performance.env 后 reload 可见新值。"""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = os.path.join(tmp, "performance.env")
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("QUEUE_MAX_SIZE=42\nTIMEOUT_SECONDS=30\n")

            with patch("performance.config._CONFIG_PATH", env_path):
                reload_perf()
                cfg = get_perf_config()
                self.assertEqual(cfg.QUEUE_MAX_SIZE, 42)

                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("QUEUE_MAX_SIZE=15\nTIMEOUT_SECONDS=30\n")
                reload_perf()
                cfg2 = get_perf_config()
                self.assertEqual(cfg2.QUEUE_MAX_SIZE, 15)


class ConfigAdminHttpTest(unittest.TestCase):
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
        admin = register_user("cfg_admin", "Admin1234")
        admin.is_admin = True
        register_user("cfg_user", "User1234")
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def _login(self, username: str, password: str):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_admin_can_view_config(self):
        self._login("cfg_admin", "Admin1234")
        res = self.client.get("/admin/config")
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)
        self.assertIn("系统配置", text)
        self.assertIn("模型参数", text)
        self.assertIn("性能设置", text)

    def test_normal_user_forbidden(self):
        self._login("cfg_user", "User1234")
        res = self.client.get("/admin/config")
        self.assertEqual(res.status_code, 403)

    def test_save_via_ajax(self):
        self._login("cfg_admin", "Admin1234")
        with patch("admin.views.config.save_configs", return_value=(True, "配置已更新", {})) as mock_save:
            with patch("admin.views.config.get_config_version", return_value="v1"):
                res = self.client.post(
                    "/admin/config/save",
                    json={"updates": {"MEMORY_EXTRACT_TEMPERATURE": 0.5}, "version": "v1"},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["ok"])
            self.assertIn("更新", data["message"])
            mock_save.assert_called_once()

    def test_save_version_conflict_returns_409(self):
        self._login("cfg_admin", "Admin1234")
        with patch(
            "admin.views.config.save_configs",
            return_value=(False, "配置已被其他管理员修改，请刷新后重试", {"_version": "冲突"}),
        ):
            res = self.client.post(
                "/admin/config/save",
                json={"updates": {"QUEUE_MAX_SIZE": 5}, "version": "stale"},
            )
        self.assertEqual(res.status_code, 409)
        self.assertFalse(res.get_json()["ok"])

    def test_config_page_shows_undo_minutes(self):
        self._login("cfg_admin", "Admin1234")
        res = self.client.get("/admin/config")
        self.assertEqual(res.status_code, 200)
        self.assertIn("5分钟内", res.get_data(as_text=True))
        self.assertIn('id="config-version"', res.get_data(as_text=True))

    def test_save_validation_error(self):
        self._login("cfg_admin", "Admin1234")
        with patch(
            "admin.views.config.save_configs",
            return_value=(False, "校验失败", {"MEMORY_EXTRACT_TEMPERATURE": "温度必须在 0.0-2.0 之间"}),
        ):
            res = self.client.post(
                "/admin/config/save",
                json={"updates": {"MEMORY_EXTRACT_TEMPERATURE": 3.0}},
            )
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertFalse(data["ok"])
            self.assertIn("MEMORY_EXTRACT_TEMPERATURE", data["errors"])

    def test_export_download(self):
        self._login("cfg_admin", "Admin1234")
        res = self.client.get("/admin/config/export")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/json", res.mimetype)
        data = json.loads(res.get_data(as_text=True))
        self.assertIn("QUEUE_MAX_SIZE", data)
        self.assertEqual(data.get("SECRET_KEY"), reg.MASK)

    def test_backup_page(self):
        self._login("cfg_admin", "Admin1234")
        res = self.client.get("/admin/config/backup")
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)
        self.assertIn("配置备份", text)
        self.assertIn("保留关键备份", text)

    def test_backup_pin_toggle(self):
        self._login("cfg_admin", "Admin1234")
        with patch("admin.views.config.set_backup_pinned", return_value=(True, "已固定备份")) as mock_pin:
            res = self.client.post(
                "/admin/config/backup/pin/20250101T000000Z",
                data={"pinned": "1"},
            )
        self.assertEqual(res.status_code, 302)
        mock_pin.assert_called_once_with("20250101T000000Z", True)

    def test_import_json(self):
        self._login("cfg_admin", "Admin1234")
        with patch(
            "admin.views.config.import_configs",
            return_value=(True, "配置已更新", {}),
        ) as mock_imp:
            res = self.client.post(
                "/admin/config/import",
                json={"QUEUE_MAX_SIZE": 8},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()["ok"])
            mock_imp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
