import os
import tempfile
import unittest
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-harness-admin-tests")

from app import create_app
from app.models.user import CharacterRecord, Conversation, User
from app.services.auth_service import register_user
from extensions import db


class AdminTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def _make_admin(self, username="admin", password="Admin1234"):
        with self.app.app_context():
            user = register_user(username, password)
            user.is_admin = True
            db.session.commit()
            return user.id

    def _make_user(self, username="normal", password="Normal123"):
        with self.app.app_context():
            user = register_user(username, password)
            return user.id

    def _login(self, username, password):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_normal_user_forbidden(self):
        self._make_user()
        self._login("normal", "Normal123")
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 403)

    def test_unauthenticated_redirects_to_login(self):
        res = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/auth/login", res.headers.get("Location", ""))

    def test_admin_dashboard(self):
        self._make_admin()
        self._login("admin", "Admin1234")
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("仪表盘", res.data.decode())

    def test_admin_create_character(self):
        self._make_admin()
        self._login("admin", "Admin1234")
        res = self.client.post(
            "/admin/characters/new",
            data={
                "name": "测试角色",
                "role": "冒险者",
                "description": "描述",
                "system_prompt": "你是测试角色",
                "temperature": "0.8",
                "max_tokens": "1024",
                "submit": "保存",
            },
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/admin/characters", res.headers.get("Location", ""))
        with self.app.app_context():
            char = CharacterRecord.query.filter_by(display_name="测试角色").first()
            self.assertIsNotNone(char)
            self.assertFalse(char.deleted)

    def test_admin_edit_character(self):
        self._make_admin()
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").first()
            char = CharacterRecord(
                user_id=admin.id,
                character_key="hero",
                display_name="英雄",
                role="战士",
                deleted=False,
                version=1,
            )
            db.session.add(char)
            db.session.commit()
            char_id = char.id
            version = char.version

        self._login("admin", "Admin1234")
        res = self.client.post(
            f"/admin/characters/{char_id}/edit",
            data={
                "name": "英雄改",
                "role": "法师",
                "description": "",
                "system_prompt": "",
                "temperature": "0.7",
                "max_tokens": "2048",
                "version": str(version),
                "submit": "保存",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        with self.app.app_context():
            updated = db.session.get(CharacterRecord, char_id)
            self.assertEqual(updated.display_name, "英雄改")
            self.assertEqual(updated.role, "法师")
            self.assertEqual(updated.version, version + 1)

    def test_admin_soft_delete_character(self):
        self._make_admin()
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").first()
            char = CharacterRecord(
                user_id=admin.id,
                character_key="del_me",
                display_name="待删除",
                deleted=False,
                version=1,
            )
            db.session.add(char)
            db.session.commit()
            char_id = char.id

        self._login("admin", "Admin1234")
        res = self.client.post(
            f"/admin/characters/{char_id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        with self.app.app_context():
            deleted = db.session.get(CharacterRecord, char_id)
            self.assertTrue(deleted.deleted)
        list_res = self.client.get("/admin/characters")
        self.assertNotIn("待删除", list_res.data.decode())

    def test_duplicate_character_name(self):
        self._make_admin()
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").first()
            db.session.add(
                CharacterRecord(
                    user_id=admin.id,
                    character_key="dup",
                    display_name="重复名",
                    deleted=False,
                )
            )
            db.session.commit()

        self._login("admin", "Admin1234")
        res = self.client.post(
            "/admin/characters/new",
            data={
                "name": "重复名",
                "role": "",
                "description": "",
                "system_prompt": "",
                "temperature": "0.7",
                "max_tokens": "2048",
                "submit": "保存",
            },
        )
        self.assertEqual(res.status_code, 400)

    def test_dashboard_stats(self):
        self._make_admin()
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").first()
            db.session.add(
                CharacterRecord(
                    user_id=admin.id,
                    character_key="c1",
                    display_name="C1",
                    deleted=False,
                )
            )
            db.session.add(
                Conversation(
                    user_id=admin.id,
                    character_key="c1",
                    role="user",
                    content="hi",
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()
            char_count = CharacterRecord.query.filter_by(deleted=False).count()
            user_count = User.query.count()
            conv_count = Conversation.query.count()

        self._login("admin", "Admin1234")
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 200)
        text = res.data.decode()
        self.assertIn(str(char_count), text)
        self.assertIn(str(user_count), text)
        self.assertIn(str(conv_count), text)


if __name__ == "__main__":
    unittest.main()
