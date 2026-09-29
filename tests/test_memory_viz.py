import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-memory-viz")

from app import create_app
from app.models.user import CharacterRecord
from app.services.auth_service import register_user
from extensions import db
from memory.parser import parse_memory, parse_memory_file
from memory.reader import get_memories, memory_file_path


class MemoryParserTest(unittest.TestCase):
    def test_parse_long_term_fact(self):
        raw = {"fact": "用户喜欢蓝色", "importance": 5, "timestamp": "2026-06-01T10:00:00+00:00"}
        item = parse_memory(raw, index=0)
        self.assertEqual(item["importance"], "high")
        self.assertIn("喜欢", item["summary"])

    def test_parse_memory_file(self):
        data = {
            "long_term": [
                {"fact": "喜欢咖啡", "importance": 3, "timestamp": "2026-06-01T10:00:00+00:00"},
                {"fact": "讨厌等待", "importance": 5, "timestamp": "2026-06-02T10:00:00+00:00"},
            ]
        }
        items = parse_memory_file(data)
        self.assertEqual(len(items), 2)


class MemoryReaderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.user_id = 1
        self.key = "hero"
        char_dir = os.path.join(self.temp, "users", str(self.user_id), "characters", self.key)
        os.makedirs(char_dir)
        facts = []
        for i in range(25):
            facts.append(
                {
                    "fact": f"记忆条目{i} 喜欢测试",
                    "importance": 5 if i % 5 == 0 else 2,
                    "timestamp": f"2026-06-{1 + (i % 28):02d}T10:00:00+00:00",
                }
            )
        with open(os.path.join(char_dir, "memory_state.json"), "w", encoding="utf-8") as f:
            json.dump({"long_term": facts}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_search_and_pagination(self):
        import memory.reader as reader_mod
        with mock.patch.object(reader_mod, "BASE_DIR", self.temp):
            page1, total, stats = get_memories(
                self.user_id, self.key, keyword="喜欢", page=1, per_page=20
            )
            page2, total2, _ = get_memories(
                self.user_id, self.key, keyword="喜欢", page=2, per_page=20
            )
        self.assertEqual(total, 25)
        self.assertEqual(len(page1), 20)
        self.assertEqual(len(page2), 5)
        self.assertEqual(total2, 25)

    def test_importance_filter(self):
        import memory.reader as reader_mod
        with mock.patch.object(reader_mod, "BASE_DIR", self.temp):
            items, total, _ = get_memories(
                self.user_id, self.key, importance_filter="high"
            )
        self.assertGreater(total, 0)
        self.assertTrue(all(i["importance"] == "high" for i in items))


class MemoryViewTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        self.temp = tempfile.mkdtemp()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        import shutil
        shutil.rmtree(self.temp, ignore_errors=True)

    def _seed(self):
        with self.app.app_context():
            user_a = register_user("mem_a", "MemA1234")
            user_b = register_user("mem_b", "MemB1234")
            admin = register_user("mem_admin", "Admin1234")
            admin.is_admin = True
            char_a = CharacterRecord(
                user_id=user_a.id,
                character_key="ca",
                display_name="角色A",
                deleted=False,
            )
            char_b = CharacterRecord(
                user_id=user_b.id,
                character_key="cb",
                display_name="角色B",
                deleted=False,
            )
            db.session.add_all([char_a, char_b])
            db.session.commit()
            for uid, key in ((user_a.id, "ca"), (user_b.id, "cb")):
                d = os.path.join(self.temp, "users", str(uid), "characters", key)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "memory_state.json"), "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "long_term": [
                                {
                                    "fact": "喜欢冒险",
                                    "importance": 5,
                                    "timestamp": "2026-06-01T10:00:00+00:00",
                                }
                            ]
                        },
                        f,
                    )
            return user_a.id, char_a.id, char_b.id

    def test_user_memory_page(self):
        import memory.reader as reader_mod
        _ua, char_a_id, _cb = self._seed()
        with mock.patch.object(reader_mod, "BASE_DIR", self.temp):
            self.client.post("/auth/login", data={"username": "mem_a", "password": "MemA1234"})
            res = self.client.get(f"/memory?character_id={char_a_id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("喜欢冒险", res.data.decode())

    def test_user_cannot_access_other_character(self):
        import memory.reader as reader_mod
        _ua, _ca, char_b_id = self._seed()
        with mock.patch.object(reader_mod, "BASE_DIR", self.temp):
            self.client.post("/auth/login", data={"username": "mem_a", "password": "MemA1234"})
            res = self.client.get(f"/memory?character_id={char_b_id}")
        self.assertEqual(res.status_code, 404)

    def test_normal_user_forbidden_admin_memory(self):
        import memory.reader as reader_mod
        _ua, char_a_id, _cb = self._seed()
        with mock.patch.object(reader_mod, "BASE_DIR", self.temp):
            self.client.post("/auth/login", data={"username": "mem_a", "password": "MemA1234"})
            res = self.client.get(f"/admin/memory/{char_a_id}")
        self.assertEqual(res.status_code, 403)

    def test_admin_memory_view(self):
        import memory.reader as reader_mod
        _ua, char_a_id, _cb = self._seed()
        with mock.patch.object(reader_mod, "BASE_DIR", self.temp):
            self.client.post("/auth/login", data={"username": "mem_admin", "password": "Admin1234"})
            res = self.client.get(f"/admin/memory/{char_a_id}")
        self.assertEqual(res.status_code, 200)

    def test_empty_memory_list(self):
        with self.app.app_context():
            register_user("empty", "Empty1234")
        self.client.post("/auth/login", data={"username": "empty", "password": "Empty1234"})
        res = self.client.get("/memory")
        self.assertEqual(res.status_code, 200)
        self.assertIn("暂无记忆", res.data.decode())


if __name__ == "__main__":
    unittest.main()
