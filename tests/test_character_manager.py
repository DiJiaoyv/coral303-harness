import os
import shutil
import tempfile
import unittest

from character_manager import CharacterManager


class TestCharacterManager(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        self.registry = os.path.join(self.tmp, "characters.json")
        with open(self.registry, "w", encoding="utf-8") as f:
            f.write(
                '{"active": "幽灵", "base_dir": "characters", '
                '"characters": {"幽灵": {"name": "幽灵", "role": "猎人"}, '
                '"老K": {"name": "老K", "role": "商人"}}}'
            )
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_and_paths(self):
        mgr = CharacterManager(registry_path="characters.json")
        self.assertIn("幽灵", mgr.list_characters())
        paths = mgr.resolve_paths("老K")
        self.assertIn(os.path.join("characters", "老K", "soul_state.json"), paths["soul"])

    def test_switch_active(self):
        mgr = CharacterManager(registry_path="characters.json")
        mgr.set_active("老K")
        self.assertEqual(mgr.get_active(), "老K")


if __name__ == "__main__":
    unittest.main()
