import os
import unittest
from unittest.mock import patch

# 必须在导入 api 包之前设置 SECRET_KEY
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-harness-api-tests")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.dependencies import get_db
from api.main import app
from database.models import Base, Character, User
from api.utils.security import hash_password


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestSession = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.test_engine
        )
        Base.metadata.create_all(bind=cls.test_engine)

    def setUp(self):
        Base.metadata.drop_all(bind=self.test_engine)
        Base.metadata.create_all(bind=self.test_engine)

        def override_get_db():
            db = self.TestSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _register(self, username: str, password: str):
        return self.client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )

    def _login(self, username: str, password: str):
        return self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )

    def _auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def test_register_success(self):
        res = self._register("alice", "Alice1234")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["username"], "alice")
        self.assertNotIn("password", data)
        self.assertNotIn("password_hash", data)

    def test_register_duplicate(self):
        self._register("bob", "Bob12345")
        res = self._register("bob", "Bob12345")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "用户名已存在")

    def test_login_success(self):
        self._register("carol", "Carol1234")
        res = self._login("carol", "Carol1234")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")

    def test_login_wrong_password(self):
        self._register("dave", "Dave1234")
        res = self._login("dave", "WrongPass1")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "用户名或密码错误")

    def test_chat_without_token(self):
        res = self.client.post(
            "/api/chat/completions",
            json={"character_id": 1, "message": "你好"},
        )
        self.assertEqual(res.status_code, 401)

    def test_characters_empty_list(self):
        self._register("eve", "Eve12345")
        login = self._login("eve", "Eve12345")
        token = login.json()["access_token"]
        res = self.client.get(
            "/api/characters",
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    def test_create_character(self):
        self._register("frank", "Frank1234")
        token = self._login("frank", "Frank1234").json()["access_token"]
        res = self.client.post(
            "/api/characters",
            headers=self._auth_headers(token),
            json={
                "character_key": "hero_01",
                "display_name": "测试英雄",
                "role": "冒险者",
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["character_key"], "hero_01")
        self.assertEqual(data["display_name"], "测试英雄")

    def test_user_cannot_delete_other_users_character(self):
        db = self.TestSession()
        try:
            user_a = User(username="user_a", password_hash=hash_password("UserA1234"))
            user_b = User(username="user_b", password_hash=hash_password("UserB1234"))
            db.add_all([user_a, user_b])
            db.commit()
            db.refresh(user_a)
            db.refresh(user_b)
            char_b = Character(
                user_id=user_b.id,
                character_key="secret_b",
                display_name="B的角色",
                role="测试",
            )
            db.add(char_b)
            db.commit()
            db.refresh(char_b)
            char_b_id = char_b.id
        finally:
            db.close()

        token_a = self._login("user_a", "UserA1234").json()["access_token"]
        res = self.client.delete(
            f"/api/characters/{char_b_id}",
            headers=self._auth_headers(token_a),
        )
        self.assertEqual(res.status_code, 404)

    @patch("api.routes.chat.generate_response", return_value="这是模拟回复")
    def test_chat_completions(self, mock_generate):
        self._register("grace", "Grace1234")
        token = self._login("grace", "Grace1234").json()["access_token"]
        create = self.client.post(
            "/api/characters",
            headers=self._auth_headers(token),
            json={
                "character_key": "grace_char",
                "display_name": "Grace角色",
                "role": "测试",
            },
        )
        char_id = create.json()["id"]
        res = self.client.post(
            "/api/chat/completions",
            headers=self._auth_headers(token),
            json={"character_id": char_id, "message": "你好"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["reply"], "这是模拟回复")
        mock_generate.assert_called_once()

    def test_docs_accessible_without_auth(self):
        res = self.client.get("/api/docs")
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
