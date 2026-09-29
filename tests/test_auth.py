import os
import unittest

# 测试环境必须在导入 config 前设置 SECRET_KEY
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-harness-auth-tests")

from app import create_app
from app.models.user import CharacterRecord, User
from app.services.auth_service import register_user
from extensions import db


class AuthTestCase(unittest.TestCase):
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

    def test_register_success(self):
        res = self.client.post(
            "/auth/register",
            json={"username": "alice", "password": "Alice1234"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["username"], "alice")
        self.assertNotIn("password", data)
        self.assertNotIn("password_hash", data)
        with self.app.app_context():
            user = User.query.filter_by(username="alice").first()
            self.assertTrue(user.password_hash.startswith("$2b$"))

    def test_register_duplicate_username(self):
        with self.app.app_context():
            register_user("bob", "Bob12345")
        res = self.client.post(
            "/auth/register",
            json={"username": "bob", "password": "Bob12345"},
        )
        self.assertEqual(res.status_code, 409)

    def test_login_success_redirects(self):
        with self.app.app_context():
            register_user("carol", "Carol1234")
        res = self.client.post(
            "/auth/login",
            data={"username": "carol", "password": "Carol1234"},
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/", res.headers.get("Location", ""))

    def test_login_wrong_password(self):
        with self.app.app_context():
            register_user("dave", "Dave1234")
        res = self.client.post(
            "/auth/login",
            json={"username": "dave", "password": "WrongPass1"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["error"], "用户名或密码错误")

    def test_protected_route_redirects_when_not_logged_in(self):
        res = self.client.get("/characters", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/auth/login", res.headers.get("Location", ""))

    def test_user_data_isolation(self):
        with self.app.app_context():
            user_a = register_user("user_a", "UserA1234")
            user_b = register_user("user_b", "UserB1234")
            db.session.add(
                CharacterRecord(
                    user_id=user_a.id,
                    character_key="char_a",
                    display_name="角色A",
                    role="测试A",
                )
            )
            db.session.add(
                CharacterRecord(
                    user_id=user_b.id,
                    character_key="char_b",
                    display_name="角色B",
                    role="测试B",
                )
            )
            db.session.commit()

        with self.client.session_transaction() as sess:
            pass

        self.client.post(
            "/auth/login",
            data={"username": "user_a", "password": "UserA1234"},
        )
        res = self.client.get("/characters")
        self.assertEqual(res.status_code, 200)
        keys = {item["character_key"] for item in res.get_json()}
        self.assertIn("char_a", keys)
        self.assertNotIn("char_b", keys)

    def test_logout_clears_session(self):
        with self.app.app_context():
            register_user("eve", "Eve12345")
        self.client.post(
            "/auth/login",
            data={"username": "eve", "password": "Eve12345"},
        )
        self.client.get("/auth/logout")
        res = self.client.get("/characters", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/auth/login", res.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
