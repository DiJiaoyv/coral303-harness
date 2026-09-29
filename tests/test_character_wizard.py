import os
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-wizard-tests")

from app import create_app
from app.models.user import CharacterRecord
from app.services.auth_service import register_user
from admin.character_wizard import (
    create_character_record,
    load_character_templates,
    load_worlds,
    name_exists_for_user,
)
from extensions import db


class CharacterWizardUnitTest(unittest.TestCase):
    def test_load_templates(self):
        templates = load_character_templates()
        self.assertGreaterEqual(len(templates), 3)
        ids = {t["id"] for t in templates}
        self.assertIn("cold_killer", ids)
        self.assertIn("gentle_butler", ids)
        self.assertIn("funny_pet", ids)

    def test_load_worlds(self):
        worlds = load_worlds()
        ids = {w["id"] for w in worlds}
        self.assertIn("", ids)
        self.assertIn("low_gravity", ids)


class CharacterWizardAdminTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.admin = register_user("wiz_admin", "Admin1234")
        self.admin.is_admin = True
        self.user = register_user("wiz_user", "User1234")
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self, username, password):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_admin_sees_step1(self):
        self._login("wiz_admin", "Admin1234")
        res = self.client.get("/admin/characters/create?reset=1")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("基本信息", body)
        self.assertIn("冷酷杀手", body)

    def test_step1_to_step2_saves_session(self):
        self._login("wiz_admin", "Admin1234")
        res = self.client.post(
            "/admin/characters/create",
            data={
                "name": "测试角色甲",
                "description": "描述内容",
                "avatar_url": "",
                "template_id": "",
                "next_btn": "下一步",
            },
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/admin/characters/create/2", res.headers.get("Location", ""))

        res2 = self.client.get("/admin/characters/create/2")
        self.assertEqual(res2.status_code, 200)
        self.assertIn("角色设定", res2.get_data(as_text=True))

    def test_full_wizard_creates_character(self):
        self._login("wiz_admin", "Admin1234")
        self.client.post(
            "/admin/characters/create",
            data={
                "name": "向导角色",
                "description": "完整创建",
                "avatar_url": "",
                "template_id": "cold_killer",
                "next_btn": "下一步",
            },
        )
        self.client.post(
            "/admin/characters/create/2",
            data={
                "system_prompt": "你是测试角色。",
                "style_tags": "测试,简洁",
                "next_btn": "下一步",
            },
        )
        self.client.post(
            "/admin/characters/create/3",
            data={
                "temperature": "0.7",
                "max_tokens": "1024",
                "top_p": "0.9",
                "next_btn": "下一步",
            },
        )
        self.client.post(
            "/admin/characters/create/4",
            data={
                "world_id": "low_gravity",
                "owner_user_id": str(self.admin.id),
                "next_btn": "预览",
            },
        )
        res = self.client.post(
            "/admin/characters/create/preview",
            data={"confirm_btn": "确认创建"},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        char = CharacterRecord.query.filter_by(
            display_name="向导角色", deleted=False
        ).first()
        self.assertIsNotNone(char)
        self.assertEqual(char.user_id, self.admin.id)
        self.assertIn("测试角色", char.system_prompt)

    def test_duplicate_name_rejected(self):
        create_character_record(
            owner_user_id=self.admin.id,
            wizard_data={
                "step1": {"name": "重复名", "description": "", "avatar_url": "", "template_id": ""},
                "step2": {"system_prompt": "prompt", "style_tags": ""},
                "step3": {"temperature": 0.7, "max_tokens": 1024, "top_p": 0.9},
                "step4": {"world_id": "", "owner_user_id": self.admin.id},
            },
            operator="admin:wiz_admin",
            is_admin=True,
        )
        self.assertTrue(name_exists_for_user(self.admin.id, "重复名"))
        with self.assertRaises(ValueError):
            create_character_record(
                owner_user_id=self.admin.id,
                wizard_data={
                    "step1": {"name": "重复名", "description": "", "avatar_url": "", "template_id": ""},
                    "step2": {"system_prompt": "x", "style_tags": ""},
                    "step3": {"temperature": 0.7, "max_tokens": 1024, "top_p": 0.9},
                    "step4": {"world_id": "", "owner_user_id": self.admin.id},
                },
                operator="admin:wiz_admin",
                is_admin=True,
            )

    def test_empty_required_blocks_step2(self):
        self._login("wiz_admin", "Admin1234")
        self.client.post(
            "/admin/characters/create",
            data={
                "name": "空提示词角色",
                "description": "",
                "avatar_url": "",
                "template_id": "",
                "next_btn": "下一步",
            },
        )
        res = self.client.post(
            "/admin/characters/create/2",
            data={
                "system_prompt": "",
                "style_tags": "",
                "next_btn": "下一步",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("请填写系统提示词", res.get_data(as_text=True))

    def test_template_prefills_step2(self):
        self._login("wiz_admin", "Admin1234")
        self.client.post(
            "/admin/characters/create",
            data={
                "name": "模板角色",
                "description": "来自模板",
                "avatar_url": "",
                "template_id": "gentle_butler",
                "next_btn": "下一步",
            },
        )
        res = self.client.get("/admin/characters/create/2")
        body = res.get_data(as_text=True)
        self.assertIn("私人管家", body)

    def test_normal_user_forbidden_admin_wizard(self):
        self._login("wiz_user", "User1234")
        res = self.client.get("/admin/characters/create")
        self.assertEqual(res.status_code, 403)


class CharacterWizardUserTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.user = register_user("front_user", "User1234")
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self):
        return self.client.post(
            "/auth/login",
            data={"username": "front_user", "password": "User1234"},
            follow_redirects=False,
        )

    def test_user_create_belongs_to_self(self):
        self._login()
        self.client.post(
            "/characters/create",
            data={
                "name": "我的角色",
                "description": "用户自建",
                "avatar_url": "",
                "template_id": "",
                "next_btn": "下一步",
            },
        )
        self.client.post(
            "/characters/create/2",
            data={
                "system_prompt": "你是我的角色。",
                "style_tags": "友好",
                "next_btn": "下一步",
            },
        )
        self.client.post(
            "/characters/create/3",
            data={
                "temperature": "0.8",
                "max_tokens": "512",
                "top_p": "0.9",
                "next_btn": "下一步",
            },
        )
        self.client.post(
            "/characters/create/4",
            data={"world_id": "", "owner_user_id": str(self.user.id), "next_btn": "预览"},
        )
        res = self.client.post(
            "/characters/create/preview",
            data={"confirm_btn": "确认创建"},
            follow_redirects=False,
        )
        self.assertIn(res.status_code, (302, 200))
        char = CharacterRecord.query.filter_by(
            display_name="我的角色", deleted=False
        ).first()
        self.assertIsNotNone(char)
        self.assertEqual(char.user_id, self.user.id)


if __name__ == "__main__":
    unittest.main()
