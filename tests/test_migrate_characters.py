import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.utils.security import hash_password
from database.models import Base, Character, User
from scripts import migrate_characters as mc


class MigrateCharactersHelpersTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chars_dir = os.path.join(self.temp_dir, "characters")
        os.makedirs(self.chars_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_json(self, filename: str, data: dict) -> str:
        path = os.path.join(self.chars_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def test_parse_valid_file(self):
        path = self._write_json(
            "hero.json",
            {
                "description": "描述",
                "system_prompt": "提示",
                "temperature": 0.9,
                "max_tokens": 1000,
                "role": "战士",
            },
        )
        parsed = mc._parse_character_file(path)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["display_name"], "hero")
        self.assertIn("temperature", parsed["parameters_json"])

    def test_skip_invalid_json(self):
        path = os.path.join(self.chars_dir, "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(mc._parse_character_file(path))

    def test_reject_dangerous_name(self):
        path = self._write_json("bad..name.json", {"description": "x"})
        self.assertIsNone(mc._parse_character_file(path))


class MigrateCharactersIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chars_dir = os.path.join(self.temp_dir, "characters")
        os.makedirs(self.chars_dir)
        self.db_path = os.path.join(self.temp_dir, "test.db")

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(username="owner", password_hash=hash_password("Owner1234"))
        session.add(user)
        session.commit()
        self.user_id = user.id
        session.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_json(self, name: str, data: dict) -> None:
        path = os.path.join(self.chars_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    @patch("database.migrate_admin_schema.migrate_admin_schema")
    @patch("database.session.SessionLocal")
    @patch("database.session.get_database_url")
    @patch.object(mc, "_backup_characters_dir", return_value=None)
    def test_import_and_skip_duplicate(
        self, _mock_backup, mock_db_url, mock_session_local, _mock_schema
    ):
        mock_db_url.return_value = f"sqlite:///{self.db_path}"
        mock_session_local.side_effect = lambda: self.Session()
        with patch.object(mc, "BASE_DIR", self.temp_dir), patch.object(
            mc, "CHARACTERS_DIR", self.chars_dir
        ):
            self._write_json(
                "hero",
                {"description": "英雄", "system_prompt": "你是英雄"},
            )
            imported, skipped = mc.migrate_characters(user_id=self.user_id)

        self.assertEqual(imported, 1)
        session = self.Session()
        self.assertEqual(
            session.query(Character).filter_by(user_id=self.user_id).count(), 1
        )
        session.close()

        with patch.object(mc, "BASE_DIR", self.temp_dir), patch.object(
            mc, "CHARACTERS_DIR", self.chars_dir
        ), patch("database.session.get_database_url", return_value=f"sqlite:///{self.db_path}"), patch(
            "database.session.SessionLocal", side_effect=lambda: self.Session()
        ), patch("database.migrate_admin_schema.migrate_admin_schema"):
            imported2, skipped2 = mc.migrate_characters(user_id=self.user_id)
        self.assertEqual(imported2, 0)
        self.assertGreaterEqual(skipped2, 1)


if __name__ == "__main__":
    unittest.main()
