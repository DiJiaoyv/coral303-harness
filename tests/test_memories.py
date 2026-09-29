import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-memory-tests")

from app import create_app
from app.models.user import CharacterRecord
from app.services.auth_service import register_user
from extensions import db
from memory.io import memory_file_path
from memory.search import search_memories
from memory.writer import (
    add_memory,
    batch_delete_memories,
    delete_memory,
    restore_memory,
    update_memory,
)


def _write_test_memories(path: str, facts: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "max_messages": 20,
        "short_term": [],
        "long_term": facts,
        "use_vector": False,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class MemoryWriterTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.user = register_user("mem_user", "User1234")
        self.admin = register_user("mem_admin", "Admin1234")
        self.admin.is_admin = True
        self.other = register_user("other_user", "User1234")
        db.session.commit()

        self.character = CharacterRecord(
            user_id=self.user.id,
            character_key="hero",
            display_name="英雄",
        )
        self.other_char = CharacterRecord(
            user_id=self.other.id,
            character_key="villain",
            display_name="反派",
        )
        db.session.add_all([self.character, self.other_char])
        db.session.commit()

        self.temp_dir = tempfile.mkdtemp()
        self.mem_path = memory_file_path(self.user.id, "hero")
        ts = datetime.now(timezone.utc).isoformat()
        _write_test_memories(
            self.mem_path,
            [
                {
                    "id": "mem001",
                    "fact": "用户喜欢蓝色",
                    "importance": 5,
                    "timestamp": ts,
                    "source": "model",
                },
                {
                    "id": "mem002",
                    "fact": "住在空间站",
                    "importance": 3,
                    "timestamp": ts,
                    "source": "user",
                },
            ],
        )

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_update_memory_persists(self):
        result = update_memory(
            self.user.id,
            self.character.id,
            "mem001",
            content="用户非常喜欢蓝色",
            importance=4,
            operator="user:mem_user",
            require_owner=True,
        )
        self.assertIn("蓝色", result["content"])
        self.assertEqual(result["importance_raw"], 4)

    def test_soft_delete_hides_from_search(self):
        delete_memory(
            self.user.id,
            self.character.id,
            "mem001",
            operator="user:mem_user",
            require_owner=True,
        )
        items, total = search_memories(self.user.id, "hero", keyword="喜欢")
        self.assertEqual(total, 0)

    def test_restore_memory(self):
        delete_memory(
            self.user.id,
            self.character.id,
            "mem001",
            operator="admin",
            require_owner=True,
        )
        restore_memory(
            self.user.id,
            self.character.id,
            "mem001",
            operator="admin",
            require_owner=True,
        )
        items, total = search_memories(self.user.id, "hero", keyword="喜欢")
        self.assertEqual(total, 1)

    def test_search_keyword_filter(self):
        items, total = search_memories(self.user.id, "hero", keyword="喜欢")
        self.assertEqual(total, 1)
        self.assertIn("喜欢", items[0]["content"])

    def test_search_importance_five(self):
        items, total = search_memories(self.user.id, "hero", importance=5)
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["importance_raw"], 5)

    def test_batch_delete(self):
        count = batch_delete_memories(
            self.user.id,
            self.character.id,
            ["mem001", "mem002"],
            operator="user:mem_user",
            require_owner=True,
        )
        self.assertEqual(count, 2)
        items, total = search_memories(self.user.id, "hero")
        self.assertEqual(total, 0)

    def test_other_user_cannot_update(self):
        from memory.writer import MemoryPermissionError

        with self.assertRaises(MemoryPermissionError):
            update_memory(
                self.user.id,
                self.other_char.id,
                "mem001",
                content="hack",
                require_owner=True,
            )


class MemoryAdminViewTest(unittest.TestCase):
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

        self.admin = register_user("mem_admin2", "Admin1234")
        self.admin.is_admin = True
        db.session.commit()

        self.character = CharacterRecord(
            user_id=self.admin.id,
            character_key="c1",
            display_name="测试角色",
        )
        db.session.add(self.character)
        db.session.commit()
        self.cid = self.character.id

        path = memory_file_path(self.admin.id, "c1")
        _write_test_memories(
            path,
            [
                {
                    "id": "a001",
                    "fact": "喜欢咖啡",
                    "importance": 4,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "model",
                }
            ],
        )

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

    def test_admin_list_memories(self):
        self._login("mem_admin2", "Admin1234")
        res = self.client.get(f"/admin/memories/{self.cid}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("喜欢咖啡", res.get_data(as_text=True))

    def test_admin_edit_memory(self):
        self._login("mem_admin2", "Admin1234")
        res = self.client.post(
            f"/admin/memories/{self.cid}/a001/edit",
            data={"content": "非常喜欢咖啡", "importance": "5"},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        items, _ = search_memories(self.admin.id, "c1", keyword="非常")
        self.assertEqual(len(items), 1)

    def test_normal_user_forbidden_admin_memories(self):
        user = register_user("normal_mem", "User1234")
        db.session.commit()
        self._login("normal_mem", "User1234")
        res = self.client.get(f"/admin/memories/{self.cid}")
        self.assertEqual(res.status_code, 403)


class MemoryUserViewTest(unittest.TestCase):
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

        self.user = register_user("mem_owner", "User1234")
        self.other = register_user("mem_intruder", "User1234")
        db.session.commit()

        self.char = CharacterRecord(
            user_id=self.user.id, character_key="mine", display_name="我的角色"
        )
        self.other_char = CharacterRecord(
            user_id=self.other.id, character_key="other", display_name="他人角色"
        )
        db.session.add_all([self.char, self.other_char])
        db.session.commit()

        _write_test_memories(
            memory_file_path(self.user.id, "mine"),
            [
                {
                    "id": "u001",
                    "fact": "秘密信息",
                    "importance": 3,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "user",
                }
            ],
        )

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self, username):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": "User1234"},
            follow_redirects=False,
        )

    def test_user_manage_own_memories(self):
        self._login("mem_owner")
        res = self.client.get(f"/memory/manage/{self.char.id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("秘密信息", res.get_data(as_text=True))

    def test_user_cannot_manage_other_character(self):
        self._login("mem_owner")
        res = self.client.get(f"/memory/manage/{self.other_char.id}")
        self.assertEqual(res.status_code, 404)

    def test_user_edit_own_memory(self):
        self._login("mem_owner")
        res = self.client.post(
            f"/memory/manage/{self.char.id}/u001/edit",
            data={"content": "更新后的秘密", "importance": "4"},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        items, _ = search_memories(self.user.id, "mine", keyword="更新")
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
