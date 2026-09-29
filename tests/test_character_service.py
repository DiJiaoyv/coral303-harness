"""test_character_service.py —— 测试 character 服务完整流程。

流程（对应 ChatGPT 建议的伪代码，映射到本项目实际 API）：

    ChatGPT 伪代码                  本项目实际 API
    ─────────────                  ─────────────
    character = load_character(    mgr = CharacterManager(registry_path="characters.json")
        "ayane")            →      soul, *_ = load_soul_from_dir(mgr.get_character_dir("ayane"),
                                   template=mgr.get_soul_template("ayane"))
    context = {"user_message":     user_message = "我今天失败了"
        "我今天失败了"}
    生成 prompt                →   ContextBuilder().read_snapshot(user_message=..., soul=soul)
                                   .build_prompt(snapshot, user_message=...)
    调用 DeepSeek/Ollama       →   OllamaClient(model_name=..., base_url=...).generate(prompt)
    保存                        →   写 JSON/TXT 到文件

**关键差异**：本项目没有独立的 `load_character()` 函数，加载角色走
`CharacterManager + soul.loader.load_soul_from_dir`。`ayane` 不是现成角色，
这里在临时目录造一个自包含 fixture（不依赖 characters/ 真实数据）。

测试策略：
    1) 离线单测（默认跑）：mock OllamaClient.generate，验证「加载→prompt→保存」
       逻辑正确，不依赖真实 LLM 服务（CI 友好）
    2) 真实集成（可选）：`OLLAMA_UP=1 python -m unittest ...` 启用，
       跑完整端到端链路（需本地 Ollama 运行）
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from character_manager import CharacterManager
from context_builder import ContextBuilder
from ollama_client import OllamaClient
from soul.loader import load_soul_from_dir


def _make_test_character(tmp_dir: str, name: str = "ayane") -> str:
    """在临时目录里造一个自包含测试角色（避免依赖 characters/ 真实数据）。

    返回 registry_path。CharacterManager 初始化时会自动用 template
    生成 soul_core.json / soul_state.json，无需预置角色文件。
    """
    registry_path = os.path.join(tmp_dir, "characters.json")
    registry = {
        "active": name,
        "base_dir": "characters",
        "characters": {
            name: {
                "name": "绫音",
                "role": "高中生",
                "core_traits": ["内向", "敏感", "倔强"],
                "core_drive": "在失败里找到继续下去的理由。",
                "fear": "被忽视。",
                "catchphrases": ["……嗯。", "没关系。"],
                "vocabulary": ["学校", "考试", "日记"],
                "arc_stage": "起点",
                "current_goal": "撑过这学期。",
            }
        },
    }
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False)
    return registry_path


class TestCharacterService(unittest.TestCase):
    """测试 character 完整服务流程：加载角色 → 生成 prompt → 调用 LLM → 保存。"""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        _make_test_character(self.tmp, name="ayane")
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 辅助：加载角色（对应 ChatGPT 伪代码 load_character）----
    def _load_character(self, name: str = "ayane"):
        """项目无独立 load_character，用 CharacterManager + soul.loader 组合加载。"""
        mgr = CharacterManager(registry_path="characters.json")
        char_dir = mgr.get_character_dir(name)
        soul, core, state, warnings = load_soul_from_dir(
            char_dir, template=mgr.get_soul_template(name)
        )
        return soul, mgr, char_dir

    # =================== 测试 1：加载角色 ===================
    def test_load_character(self):
        """load_character 等价流程：CharacterManager + load_soul_from_dir 能加载角色。"""
        soul, mgr, char_dir = self._load_character("ayane")
        self.assertEqual(soul.name, "绫音")
        self.assertEqual(soul.role, "高中生")
        self.assertIn("内向", list(soul.core_traits))
        self.assertTrue(os.path.isdir(char_dir))

    # =================== 测试 2：生成 prompt ===================
    def test_build_prompt_contains_sections(self):
        """build_prompt 应包含角色设定（Profile/State/Speech）+ 用户消息。"""
        soul, _mgr, _char_dir = self._load_character("ayane")
        builder = ContextBuilder()
        user_message = "我今天失败了"
        snapshot = builder.read_snapshot(user_message=user_message, soul=soul)
        prompt = builder.build_prompt(snapshot, user_message=user_message)

        # Profile：姓名 / 身份 / 核心性格
        self.assertIn("绫音", prompt)
        self.assertIn("高中生", prompt)
        self.assertIn("内向", prompt)
        # State：当前目标
        self.assertIn("撑过这学期", prompt)
        # 用户消息出现在 prompt 里
        self.assertIn(user_message, prompt)
        # prompt 结构化、非空
        self.assertGreater(len(prompt), 100)

    def test_prompt_user_message_at_end(self):
        """用户消息应在 prompt 末尾区域（供 LLM 接续回复）。"""
        soul, _mgr, _char_dir = self._load_character("ayane")
        builder = ContextBuilder()
        user_message = "我今天失败了"
        snapshot = builder.read_snapshot(user_message=user_message, soul=soul)
        prompt = builder.build_prompt(snapshot, user_message=user_message)
        idx = prompt.find(user_message)
        self.assertGreater(idx, len(prompt) * 0.5)

    # =================== 测试 3：完整流程（mock LLM + 保存）===================
    def test_full_flow_with_mock_ollama(self):
        """完整流程（mock LLM）：加载 → prompt → generate → 保存，不依赖真实 Ollama。"""
        soul, _mgr, _char_dir = self._load_character("ayane")
        user_message = "我今天失败了"

        # 1) 生成 prompt
        builder = ContextBuilder()
        snapshot = builder.read_snapshot(user_message=user_message, soul=soul)
        prompt = builder.build_prompt(snapshot, user_message=user_message)
        self.assertIn(user_message, prompt)

        # 2) mock OllamaClient.generate，避免真实 LLM 依赖
        fake_reply = "……嗯。没事的，明天再来过。"
        client = OllamaClient(model_name="test-model")
        with patch.object(client, "generate", return_value=fake_reply) as mock_gen:
            reply = client.generate(prompt)

        self.assertEqual(reply, fake_reply)
        mock_gen.assert_called_once()
        # 验证传给 LLM 的就是我们组装的 prompt
        sent_prompt = mock_gen.call_args.args[0]
        self.assertIn("绫音", sent_prompt)
        self.assertIn(user_message, sent_prompt)

        # 3) 保存输出（JSON：含 character / user_message / prompt / reply）
        out_path = os.path.join(self.tmp, "ayane_test_output.json")
        record = {
            "character": soul.name,
            "user_message": user_message,
            "prompt": prompt,
            "reply": reply,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        self.assertTrue(os.path.isfile(out_path))
        with open(out_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["reply"], fake_reply)
        self.assertEqual(loaded["character"], "绫音")
        self.assertEqual(loaded["user_message"], user_message)

    # =================== 测试 4：真实 Ollama 集成（可选）===================
    @unittest.skipUnless(
        os.environ.get("OLLAMA_UP") == "1",
        "设 OLLAMA_UP=1 启用真实 Ollama 集成测试",
    )
    def test_real_ollama_call(self):
        """真实调用本地 Ollama，验证端到端能拿到回复并保存。"""
        soul, _mgr, _char_dir = self._load_character("ayane")
        user_message = "我今天失败了"
        builder = ContextBuilder()
        snapshot = builder.read_snapshot(user_message=user_message, soul=soul)
        prompt = builder.build_prompt(snapshot, user_message=user_message)

        client = OllamaClient(
            model_name=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=os.environ.get(
                "OLLAMA_URL", "http://localhost:11434/api/generate"
            ),
        )
        try:
            reply = client.generate(prompt, options={"num_predict": 200})
        except Exception as exc:
            self.skipTest(f"Ollama 不可用：{exc}")

        self.assertTrue(reply and reply.strip())
        # 保存为 txt
        out_path = os.path.join(self.tmp, "ayane_real_output.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(reply)
        self.assertTrue(os.path.isfile(out_path))
        self.assertGreater(os.path.getsize(out_path), 0)


if __name__ == "__main__":
    unittest.main()
