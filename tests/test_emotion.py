import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-emotion-tests")

from app import create_app
from app.models.user import CharacterRecord
from app.services.auth_service import register_user
from emotion.analyzer import analyze_user_input
from emotion.decay import apply_decay
from emotion.manager import PADEmotionManager
from emotion.models import EmotionRuntimeState, PADState
from emotion.rules import get_offset_for_behavior, load_rules
from emotion.stage import check_stage_transition
from emotion.models import EmotionStats
from extensions import db


class EmotionBehaviorTest(unittest.TestCase):
    def setUp(self):
        self.manager = PADEmotionManager()

    def test_praise_increases_pleasure_and_arousal(self):
        before = self.manager.pad.copy()
        self.manager.process_user_turn("你真棒，太厉害了")
        self.assertGreater(self.manager.pad.pleasure, before.pleasure)
        self.assertGreater(self.manager.pad.arousal, before.arousal)

    def test_criticism_decreases_pleasure_increases_arousal(self):
        before = self.manager.pad.copy()
        self.manager.process_user_turn("你真笨，差劲")
        self.assertLess(self.manager.pad.pleasure, before.pleasure)
        self.assertGreater(self.manager.pad.arousal, before.arousal)

    def test_share_secret_increases_dominance(self):
        before = self.manager.pad.copy()
        self.manager.process_user_turn("告诉你一个秘密，其实我一直在关注你")
        self.assertGreater(self.manager.pad.dominance, before.dominance)
        self.assertEqual(self.manager.state.stats.secret_share_count, 1)

    def test_three_criticisms_enter_conflict(self):
        for _ in range(3):
            self.manager.process_user_turn("讨厌，差劲")
        self.assertEqual(self.manager.stage, "conflict")

    def test_ten_rounds_reach_acquaintance(self):
        for i in range(10):
            self.manager.process_user_turn(f"普通消息 {i}")
        self.assertEqual(self.manager.stage, "acquaintance")


class EmotionDecayTest(unittest.TestCase):
    def test_decay_moves_toward_baseline(self):
        pad = PADState(pleasure=0.8, arousal=0.6, dominance=0.5)
        baseline = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)
        apply_decay(pad, baseline, rounds=5)
        self.assertLess(pad.pleasure, 0.8)
        self.assertLess(pad.arousal, 0.6)
        self.assertGreater(pad.pleasure, 0.0)


class EmotionFailOpenTest(unittest.TestCase):
    def test_missing_rules_file_uses_defaults(self):
        with patch("emotion.rules.RULES_FILE", "/nonexistent/rules.json"):
            with patch("emotion.rules._cache", None):
                rules = load_rules(force=True)
        self.assertGreater(len(rules), 0)
        offset = get_offset_for_behavior("praise")
        self.assertAlmostEqual(offset["pleasure"], 0.2)

    def test_manager_survives_rule_load_failure(self):
        manager = PADEmotionManager()
        with patch("emotion.manager.load_rules", side_effect=OSError("boom")):
            behavior = manager.process_user_turn("你好棒")
        self.assertEqual(behavior, "neutral")


class EmotionIsolationTest(unittest.TestCase):
    def test_different_characters_have_independent_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "a.json")
            path_b = os.path.join(tmp, "b.json")

            mgr_a = PADEmotionManager()
            mgr_a.process_user_turn("你真棒，厉害")
            mgr_a.save(path_a)

            mgr_b = PADEmotionManager()
            mgr_b.load(path_b)
            pleasure_b_before = mgr_b.pad.pleasure

            mgr_a_loaded = PADEmotionManager()
            mgr_a_loaded.load(path_a)

            self.assertGreater(mgr_a_loaded.pad.pleasure, pleasure_b_before)
            self.assertEqual(mgr_b.pad.pleasure, pleasure_b_before)


class EmotionAnalyzerTest(unittest.TestCase):
    def test_analyze_categories(self):
        self.assertEqual(analyze_user_input("你真棒"), "praise")
        self.assertEqual(analyze_user_input("你真笨讨厌"), "criticism")
        self.assertEqual(analyze_user_input("告诉你一个秘密"), "share_secret")
        self.assertEqual(analyze_user_input("今天天气不错"), "neutral")


class EmotionStageTest(unittest.TestCase):
    def test_stage_cannot_regress(self):
        stats = EmotionStats(total_rounds=50, positive_interaction_count=5)
        stage = check_stage_transition("intimate", stats)
        self.assertEqual(stage, "intimate")

    def test_conflict_exit_on_positive(self):
        stats = EmotionStats(
            total_rounds=15,
            positive_since_conflict=1,
        )
        stage = check_stage_transition("conflict", stats)
        self.assertEqual(stage, "acquaintance")


class EmotionAdminViewTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

            admin = register_user("emotion_admin", "Admin1234")
            admin.is_admin = True
            db.session.commit()

            state = EmotionRuntimeState.default()
            state.pad.pleasure = 0.6
            state.pad.arousal = 0.3
            state.pad.dominance = 0.5
            state.stage = "trust"
            state.stats.total_rounds = 12

            character = CharacterRecord(
                user_id=admin.id,
                character_key="test_char",
                display_name="测试角色",
                role="测试",
                emotion_state=json.dumps(state.to_dict(), ensure_ascii=False),
            )
            db.session.add(character)
            db.session.commit()
            self.character_id = character.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, username: str, password: str):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_parse_emotion_display(self):
        from admin.views.characters import _parse_emotion_display

        with self.app.app_context():
            character = CharacterRecord.query.get(self.character_id)
            display = _parse_emotion_display(character)
        self.assertIsNotNone(display)
        self.assertEqual(display["pleasure"], 0.6)
        self.assertEqual(display["stage_label"], "信任")
        self.assertEqual(display["total_rounds"], 12)

    def test_admin_character_edit_shows_emotion_readonly(self):
        self._login("emotion_admin", "Admin1234")
        resp = self.client.get(
            f"/admin/characters/{self.character_id}/edit",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("情绪状态（只读）", body)
        self.assertIn("0.6", body)
        self.assertIn("信任", body)


class EmotionRendererTest(unittest.TestCase):
    def test_render_contains_pad_dimensions(self):
        manager = PADEmotionManager()
        manager.process_user_turn("你真棒")
        text = manager.render_prompt_section()
        self.assertIn("愉悦度", text)
        self.assertIn("激活度", text)
        self.assertIn("支配度", text)
        self.assertIn("综合表现", text)


if __name__ == "__main__":
    unittest.main()
