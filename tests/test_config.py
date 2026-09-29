import unittest

from harness_config import (
    ConfigValidationError,
    DEFAULT_CONFIG,
    load_config,
    validate_config,
)


class TestConfigValidation(unittest.TestCase):
    def test_default_config_valid(self):
        validate_config(DEFAULT_CONFIG)

    def test_invalid_emotion_score(self):
        import copy
        from harness_config import _deep_merge
        bad = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(bad, {"emotion": {"default_score": 15.0}})
        with self.assertRaises(ConfigValidationError):
            validate_config(bad)

    def test_invalid_interval(self):
        import copy
        from harness_config import _deep_merge
        bad = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(bad, {"engine": {"fact_extract_interval": 0}})
        with self.assertRaises(ConfigValidationError):
            validate_config(bad)


if __name__ == "__main__":
    unittest.main()
