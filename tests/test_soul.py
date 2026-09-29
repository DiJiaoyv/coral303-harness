import unittest

from soul import Soul


class TestSoulArc(unittest.TestCase):
    def test_goal_update(self):
        s = Soul()
        changes = s.apply_narrative_update(current_goal="追踪走私犯")
        self.assertIn("current_goal", changes)
        self.assertEqual(s.current_goal, "追踪走私犯")

    def test_arc_advance_one_step(self):
        s = Soul()
        changes = s.apply_narrative_update(arc_stage="转折点")
        self.assertEqual(s.arc_stage, "转折点")
        self.assertIn("arc_stage", changes)

    def test_arc_no_rollback(self):
        s = Soul()
        s.apply_narrative_update(arc_stage="转折点")
        changes = s.apply_narrative_update(arc_stage="起点")
        self.assertEqual(changes, {})
        self.assertEqual(s.arc_stage, "转折点")

    def test_arc_no_skip(self):
        s = Soul()
        changes = s.apply_narrative_update(arc_stage="终点")
        self.assertEqual(changes, {})
        self.assertEqual(s.arc_stage, "起点")


if __name__ == "__main__":
    unittest.main()
