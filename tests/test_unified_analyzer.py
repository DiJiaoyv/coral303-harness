import unittest

from unified_analyzer import UnifiedAnalyzer


class TestUnifiedAnalyzerParse(unittest.TestCase):
    def test_full_response(self):
        raw = (
            '{"facts": [{"fact": "用户委托任务", "importance": 4}], '
            '"narrative": {"should_update": true, "current_goal": "新目标"}}'
        )
        data = UnifiedAnalyzer._parse_json_object(raw)
        self.assertIsNotNone(data)
        self.assertEqual(len(data["facts"]), 1)
        self.assertTrue(data["narrative"]["should_update"])

    def test_no_update(self):
        raw = '{"facts": [], "narrative": {"should_update": false}}'
        data = UnifiedAnalyzer._parse_json_object(raw)
        self.assertFalse(data["narrative"]["should_update"])


if __name__ == "__main__":
    unittest.main()
