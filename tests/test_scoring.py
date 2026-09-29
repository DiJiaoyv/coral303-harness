import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-scoring-tests")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models.user import ScoreLog, User
from app.services.auth_service import register_user
from database.models import Base
from extensions import db
from scoring.engine import persist_score_log, score_conversation
from scoring import rules


class ScoringRulesTest(unittest.TestCase):
    CHARACTER = {
        "display_name": "幽灵",
        "role": "星际赏金猎人",
        "description": "冷酷 多疑 外冷内热",
        "system_prompt": "说话简短冷峻",
        "character_key": "幽灵",
    }

    def test_high_quality_reply(self):
        user_msg = "幽灵，今晚的任务是什么？"
        bot_reply = (
            "幽灵：今晚去涅克瑟斯星区接赏金。冷酷、多疑，我只信契约与信用点。"
        )
        scores = score_conversation(user_msg, bot_reply, self.CHARACTER)
        self.assertGreaterEqual(scores["total_score"], 7.5)
        self.assertEqual(scores["scoring_method"], "rule")

    def test_low_quality_reply(self):
        user_msg = "今天天气怎么样？"
        bot_reply = "色情 暴力 炸弹 今天天气哈哈哈 " + ("重复句子。" * 50)
        scores = score_conversation(user_msg, bot_reply, self.CHARACTER)
        self.assertLess(scores["total_score"], 3.0)
        self.assertEqual(scores["safety_score"], 0.0)

    def test_empty_reply(self):
        scores = rules.score_all("你好", "", self.CHARACTER)
        self.assertEqual(scores["relevance_score"], 0.0)
        self.assertEqual(scores["fluency_score"], 0.0)

    def test_long_reply_fluency_penalty(self):
        long_reply = "这是一段通顺的回复。" * 400
        fluency = rules.score_fluency("问题", long_reply, self.CHARACTER)
        self.assertLess(fluency, 6.0)


class ScorePersistenceTest(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
            "WTF_CSRF_ENABLED": False,
        })

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_persist_score_log(self):
        with self.app.app_context():
            user = register_user("scorer", "Scorer1234")
            scores = {
                "relevance_score": 8.0,
                "consistency_score": 7.5,
                "fluency_score": 9.0,
                "safety_score": 10.0,
                "total_score": 8.6,
                "scoring_method": "rule",
            }
            persist_score_log(
                user_id=user.id,
                character_id=None,
                conversation_id=None,
                user_message="hi",
                bot_reply="hello",
                scores=scores,
            )
            row = ScoreLog.query.filter_by(user_id=user.id).first()
            self.assertIsNotNone(row)
            self.assertEqual(row.total_score, 8.6)


class AdminScoresAccessTest(unittest.TestCase):
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

    def test_normal_user_forbidden(self):
        with self.app.app_context():
            register_user("normal2", "Normal123")
        self.client.post("/auth/login", data={"username": "normal2", "password": "Normal123"})
        res = self.client.get("/admin/scores")
        self.assertEqual(res.status_code, 403)

    def test_admin_can_view_scores(self):
        with self.app.app_context():
            user = register_user("adm", "Admin1234")
            user.is_admin = True
            db.session.commit()
        self.client.post("/auth/login", data={"username": "adm", "password": "Admin1234"})
        res = self.client.get("/admin/scores")
        self.assertEqual(res.status_code, 200)
        self.assertIn("对话质量评分", res.data.decode())


if __name__ == "__main__":
    unittest.main()
