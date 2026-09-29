import unittest

from memory_extractor import MemoryExtractor


class TestMemoryExtractorParse(unittest.TestCase):
    def test_plain_json(self):
        raw = '[{"fact": "测试", "importance": 4}]'
        facts = MemoryExtractor._parse_facts_json(raw)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact"], "测试")

    def test_codeblock_json(self):
        raw = '```json\n[{"fact": "包裹", "importance": 3}]\n```'
        facts = MemoryExtractor._parse_facts_json(raw)
        self.assertEqual(facts[0]["fact"], "包裹")

    def test_invalid_returns_empty(self):
        self.assertEqual(MemoryExtractor._parse_facts_json("无效"), [])

    def test_dedup(self):
        existing = [{"fact": "已有事实", "importance": 3}]
        candidates = [
            {"fact": "已有事实", "importance": 5},
            {"fact": "新事实", "importance": 3},
        ]
        result = MemoryExtractor.filter_new_facts(candidates, existing)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fact"], "新事实")


if __name__ == "__main__":
    unittest.main()
