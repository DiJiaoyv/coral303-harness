"""Soul Core / State layering tests."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-soul-layer-tests")

from app import create_app
from app.models.user import CharacterRecord
from app.services.auth_service import register_user
from extensions import db
from soul.loader import load_soul_from_dir, save_soul_state
from soul.migration import migrate_legacy, needs_migration, soul_paths
from soul.model import Soul
from soul.validator import validate_core, validate_state
from soul.writer import write_core, write_core_update, write_state


class SoulLayerUnitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="soul_layer_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _legacy_payload(self) -> dict:
        return {
            "name": "测试灵",
            "role": "赏金猎人",
            "core_traits": ["冷静"],
            "core_drive": "追求秩序",
            "fear": "背叛",
            "catchphrases": ["成交"],
            "vocabulary": ["信用点"],
            "arc_stage": "起点",
            "current_goal": "接一单",
        }

    def test_missing_core_defaults(self):
        paths = soul_paths(self.tmp)
        state = {"arc_stage": "转折点", "current_goal": "新目标"}
        write_state(state, paths["state"])

        soul, core, loaded_state, warnings = load_soul_from_dir(self.tmp)
        self.assertTrue(any("缺少核心" in w for w in warnings))
        self.assertEqual(core["name"], "幽灵")
        self.assertEqual(loaded_state["arc_stage"], "转折点")
        self.assertEqual(soul.current_goal, "新目标")

    def test_corrupt_state_reset(self):
        paths = soul_paths(self.tmp)
        write_core({"version": 1, "locked": True, "name": "A", "role": "B",
                    "core_traits": ["x"], "core_drive": "d", "fear": "f",
                    "catchphrases": [], "vocabulary": []}, paths["core"], backup=False)
        with open(paths["state"], "w", encoding="utf-8") as f:
            f.write("{not json")

        soul, _, state, warnings = load_soul_from_dir(self.tmp)
        self.assertTrue(any("无效" in w or "重置" in w for w in warnings))
        self.assertEqual(state["arc_stage"], "起点")
        self.assertIsInstance(soul, Soul)

    def test_migration_splits_legacy(self):
        paths = soul_paths(self.tmp)
        with open(paths["legacy"], "w", encoding="utf-8") as f:
            json.dump(self._legacy_payload(), f, ensure_ascii=False)

        self.assertTrue(needs_migration(self.tmp))
        ok, msgs = migrate_legacy(self.tmp)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(paths["core"]))
        self.assertTrue(os.path.isfile(paths["state"]))
        self.assertTrue(any("备份" in m for m in msgs))

        with open(paths["core"], encoding="utf-8") as f:
            core = json.load(f)
        with open(paths["state"], encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(core["name"], "测试灵")
        self.assertNotIn("arc_stage", core)
        self.assertEqual(state["current_goal"], "接一单")

    def test_core_version_increment_and_backup(self):
        paths = soul_paths(self.tmp)
        core = validate_core({"name": "V1", "role": "r", "core_traits": ["a"],
                              "core_drive": "d", "fear": "f", "catchphrases": [],
                              "vocabulary": []})[0]
        core["locked"] = False
        write_core(core, paths["core"], backup=False)

        new_core, diff, version = write_core_update(
            paths["core"],
            {"name": "V2"},
            force_unlock=False,
        )
        self.assertEqual(version, 2)
        self.assertIn("name", diff)
        backup_dir = paths["backups"]
        backups = os.listdir(backup_dir)
        self.assertTrue(any(name.startswith("soul_core_v") for name in backups))

    def test_state_update_persists(self):
        paths = soul_paths(self.tmp)
        soul = Soul(name="S", role="R")
        write_core(soul.to_core_dict() | {"version": 1, "locked": True}, paths["core"], backup=False)
        save_soul_state(soul, paths["state"])

        soul.apply_narrative_update(current_goal="追踪目标")
        save_soul_state(soul, paths["state"])

        _, _, state, _ = load_soul_from_dir(self.tmp)
        self.assertEqual(state["current_goal"], "追踪目标")


class SoulLayerAdminTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        self.tmp_users = tempfile.mkdtemp(prefix="soul_users_")

        with self.app.app_context():
            db.create_all()
            self.admin = register_user("soul_admin", "Admin1234")
            self.admin.is_admin = True
            self.user = register_user("soul_user", "User1234")
            db.session.commit()

            self.character = CharacterRecord(
                user_id=self.user.id,
                character_key="ghost",
                display_name="幽灵测试",
                role="猎人",
            )
            db.session.add(self.character)
            db.session.commit()
            self.user_id = self.user.id
            self.character_id = self.character.id

        char_dir = os.path.join(
            self.tmp_users,
            "users",
            str(self.user_id),
            "characters",
            "ghost",
        )
        os.makedirs(char_dir, exist_ok=True)
        paths = soul_paths(char_dir)
        core = validate_core({"name": "幽灵测试", "role": "猎人",
                              "core_traits": ["坚韧"], "core_drive": "drive",
                              "fear": "fear", "catchphrases": ["嗨"],
                              "vocabulary": ["词"]})[0]
        write_core(core, paths["core"], backup=False)
        write_state(validate_state(None)[0], paths["state"])

        # Patch BASE_DIR in admin.soul_paths for tests
        import admin.soul_paths as sp

        self._orig_base = sp.BASE_DIR
        sp.BASE_DIR = self.tmp_users

    def tearDown(self):
        import admin.soul_paths as sp

        sp.BASE_DIR = self._orig_base
        shutil.rmtree(self.tmp_users, ignore_errors=True)
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, username, password):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
        )

    def test_user_forbidden_on_core(self):
        self._login("soul_user", "User1234")
        res = self.client.get(f"/admin/soul/{self.character_id}/core")
        self.assertEqual(res.status_code, 403)

    def test_admin_core_update_requires_confirm(self):
        self._login("soul_admin", "Admin1234")
        res = self.client.post(
            f"/admin/soul/{self.character_id}/core",
            data={
                "name": "新名字",
                "role": "猎人",
                "core_traits": "坚韧",
                "core_drive": "drive",
                "fear": "fear",
                "catchphrases": "嗨",
                "vocabulary": "词",
                "submit": "保存核心",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("确认", res.data.decode())

    def test_admin_core_update_with_confirm(self):
        self._login("soul_admin", "Admin1234")
        res = self.client.post(
            f"/admin/soul/{self.character_id}/core",
            data={
                "name": "新名字",
                "role": "猎人",
                "core_traits": "坚韧",
                "core_drive": "drive",
                "fear": "fear",
                "catchphrases": "嗨",
                "vocabulary": "词",
                "confirm": "1",
                "force_unlock": "1",
                "submit": "保存核心",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("核心已更新", res.data.decode())

        char_dir = os.path.join(
            self.tmp_users,
            "users",
            str(self.user_id),
            "characters",
            "ghost",
        )
        with open(soul_paths(char_dir)["core"], encoding="utf-8") as f:
            core = json.load(f)
        self.assertEqual(core["name"], "新名字")
        self.assertEqual(core["version"], 2)

    def test_cancel_core_noop(self):
        self._login("soul_admin", "Admin1234")
        char_dir = os.path.join(
            self.tmp_users,
            "users",
            str(self.user_id),
            "characters",
            "ghost",
        )
        with open(soul_paths(char_dir)["core"], encoding="utf-8") as f:
            before = json.load(f)

        self.client.post(
            f"/admin/soul/{self.character_id}/core",
            data={
                "name": "不应保存",
                "role": "猎人",
                "core_traits": "坚韧",
                "core_drive": "drive",
                "fear": "fear",
                "catchphrases": "嗨",
                "vocabulary": "词",
                "submit": "保存核心",
            },
        )

        with open(soul_paths(char_dir)["core"], encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(before, after)

    def test_state_update(self):
        self._login("soul_admin", "Admin1234")
        res = self.client.post(
            f"/admin/soul/{self.character_id}/state",
            data={
                "arc_stage": "转折点",
                "current_goal": "完成委托",
                "submit": "保存状态",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        char_dir = os.path.join(
            self.tmp_users,
            "users",
            str(self.user_id),
            "characters",
            "ghost",
        )
        with open(soul_paths(char_dir)["state"], encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state["arc_stage"], "转折点")
        self.assertEqual(state["current_goal"], "完成委托")

    def test_user_can_edit_own_state(self):
        self._login("soul_user", "User1234")
        res = self.client.post(
            f"/admin/soul/{self.character_id}/state/user",
            data={
                "arc_stage": "起点",
                "current_goal": "用户改的目标",
                "submit": "保存状态",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        char_dir = os.path.join(
            self.tmp_users,
            "users",
            str(self.user_id),
            "characters",
            "ghost",
        )
        with open(soul_paths(char_dir)["state"], encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state["current_goal"], "用户改的目标")


if __name__ == "__main__":
    unittest.main()
