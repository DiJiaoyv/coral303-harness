import json
import os
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-arc-tests")

from app import create_app
from app.models.user import ArcLogRecord, ArcRecord, CharacterRecord
from app.services.auth_service import register_user
from arc.manager import (
    add_goal,
    complete_goal,
    get_arc,
    get_recent_logs,
    set_auto_advance,
    try_auto_advance,
    update_stage,
)
from arc.renderer import render_arc_card
from extensions import db


class ArcManagerTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.user = register_user("arc_user", "User1234")
        self.character = CharacterRecord(
            user_id=self.user.id,
            character_key="hero",
            display_name="测试英雄",
            role="主角",
        )
        db.session.add(self.character)
        db.session.commit()
        self.character_id = self.character.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_get_arc_creates_default(self):
        state = get_arc(self.character_id)
        self.assertEqual(state.current_stage, "stranger")
        self.assertEqual(len(state.stages), 4)
        row = ArcRecord.query.filter_by(character_id=self.character_id).first()
        self.assertIsNotNone(row)

    def test_update_stage_persists_and_logs(self):
        update_stage(self.character_id, "trust", operator="admin:tester", user_id=1)
        state = get_arc(self.character_id)
        self.assertEqual(state.current_stage, "trust")
        logs = get_recent_logs(self.character_id)
        self.assertTrue(any(l["action"] == "update_stage" for l in logs))
        self.assertTrue(any("admin:tester" in l["operator"] for l in logs))

    def test_add_goal_appears_in_list(self):
        add_goal(self.character_id, "击败反派", "第一阶段目标", operator="admin:tester")
        state = get_arc(self.character_id)
        self.assertEqual(len(state.goals), 1)
        self.assertEqual(state.goals[0].title, "击败反派")

    def test_complete_goal_marks_completed(self):
        add_goal(self.character_id, "收集线索", operator="admin:tester")
        goal_id = get_arc(self.character_id).goals[0].id
        complete_goal(self.character_id, goal_id, completed=True, operator="admin:tester")
        state = get_arc(self.character_id)
        self.assertTrue(state.goals[0].completed)

    def test_auto_advance_disabled_skips(self):
        set_auto_advance(self.character_id, False, operator="admin:tester")
        result = try_auto_advance(self.character_id, total_rounds=100, operator="system")
        self.assertIsNone(result)
        self.assertEqual(get_arc(self.character_id).current_stage, "stranger")

    def test_render_arc_card_escapes_html(self):
        add_goal(self.character_id, "<script>alert(1)</script>", operator="admin")
        card = render_arc_card(get_arc(self.character_id))
        self.assertNotIn("<script>", card)
        self.assertIn("&lt;script&gt;", card)


class ArcAdminViewTest(unittest.TestCase):
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

        self.admin = register_user("arc_admin", "Admin1234")
        self.admin.is_admin = True
        self.user = register_user("normal_user", "User1234")
        db.session.commit()

        self.character = CharacterRecord(
            user_id=self.admin.id,
            character_key="c1",
            display_name="弧光角色",
            role="测试",
        )
        db.session.add(self.character)
        db.session.commit()
        self.character_id = self.character.id
        get_arc(self.character_id)

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

    def test_admin_can_view_arc_dashboard(self):
        self._login("arc_admin", "Admin1234")
        res = self.client.get(f"/admin/arc/{self.character_id}")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("弧光", body)
        self.assertIn("阶段进度", body)

    def test_admin_can_update_stage(self):
        self._login("arc_admin", "Admin1234")
        res = self.client.post(
            f"/admin/arc/{self.character_id}",
            data={
                "action": "update_stage",
                "new_stage": "acquaintance",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(get_arc(self.character_id).current_stage, "acquaintance")

    def test_normal_user_forbidden_admin_arc(self):
        self._login("normal_user", "User1234")
        res = self.client.get(f"/admin/arc/{self.character_id}")
        self.assertEqual(res.status_code, 403)


class ArcUserViewTest(unittest.TestCase):
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

        self.user_a = register_user("user_a", "User1234")
        self.user_b = register_user("user_b", "User1234")
        db.session.commit()

        self.char_a = CharacterRecord(
            user_id=self.user_a.id,
            character_key="a1",
            display_name="角色A",
        )
        self.char_b = CharacterRecord(
            user_id=self.user_b.id,
            character_key="b1",
            display_name="角色B",
        )
        db.session.add_all([self.char_a, self.char_b])
        db.session.commit()
        get_arc(self.char_a.id)
        update_stage(self.char_a.id, "trust", operator="admin")

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

    def test_user_sees_readonly_arc_card(self):
        self._login("user_a")
        res = self.client.get(f"/character/{self.char_a.id}")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("弧光进度", body)
        self.assertIn("信任", body)
        self.assertIn("仅供查看", body)

    def test_user_cannot_view_other_users_character(self):
        self._login("user_a")
        res = self.client.get(f"/character/{self.char_b.id}")
        self.assertEqual(res.status_code, 404)


class ArcLogTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        user = register_user("log_user", "User1234")
        char = CharacterRecord(user_id=user.id, character_key="x", display_name="X")
        db.session.add(char)
        db.session.commit()
        self.cid = char.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_log_contains_operator_and_details(self):
        update_stage(self.cid, "acquaintance", operator="admin:ops", user_id=99)
        log = (
            ArcLogRecord.query.filter_by(
                character_id=self.cid, action="update_stage"
            )
            .order_by(ArcLogRecord.created_at.desc())
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.operator, "admin:ops")
        self.assertIn("acquaintance", log.details)


if __name__ == "__main__":
    unittest.main()
