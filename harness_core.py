# harness_core.py - AI 角色扮演引擎主循环
import sys
from dataclasses import dataclass, field
from typing import Any
import os
import shutil

from soul import Soul
from soul.loader import load_soul_from_paths, save_soul_state
from soul.migration import soul_paths
from memory import (
    SessionBuffer,
    RawMemory,
    SemanticMemory,
    MemoryRetriever,
)
from context_builder import ContextBuilder
from memory_writer import MemoryWriter
from logger import Logger
from emotion.manager import PADEmotionManager
from ollama_client import OllamaClient, OllamaError
from memory_extractor import MemoryExtractor
from arc_updater import ArcUpdater
from unified_analyzer import UnifiedAnalyzer
from harness_config import load_config, get_section
from character_manager import CharacterManager
from embeddings import EmbeddingClient


@dataclass
class TurnResult:
    """单轮对话处理结果。"""

    response: str
    new_facts: list[str] = field(default_factory=list)
    arc_changes: list[str] = field(default_factory=list)
    error: str | None = None
    diagnosis: dict[str, Any] | None = None  # v0.2 诊断报告


@dataclass
class StepProgress:
    """Web/CLI 分步进度。"""

    step: int = 1
    total: int = 3
    label: str = ""
    partial: str = ""
    done: bool = False
    result: TurnResult | None = None


# 角色台词约束（避免推理模型输出 thinking / 元认知）
_ROLE_OUTPUT_RULES = (
    "【输出约束】\n"
    "你只需要输出角色台词，不要输出任何推理过程、思考过程或分析内容。\n"
    "如果用户问你内心想法，用角色口吻回答，"
    "不要输出「作为AI，我认为…」之类的元认知内容。\n"
)


class HarnessEngine:
    """整合 Soul、Memory、Logger、OllamaClient 的角色扮演引擎。"""

    def __init__(
        self,
        config_path: str = "config.json",
        user_id: int | None = None,
        user_data_root: str | None = None,
        **overrides,
    ):
        self.config = load_config(config_path, overrides or None)
        self.config_path = config_path
        self.user_id = user_id
        self.user_data_root = user_data_root or "."
        if user_id is not None:
            os.makedirs(self.user_data_root, exist_ok=True)

        paths = get_section(self.config, "paths")
        ollama_cfg = get_section(self.config, "ollama")
        engine_cfg = get_section(self.config, "engine")
        mem_ext_cfg = get_section(self.config, "memory_extractor")
        arc_cfg = get_section(self.config, "arc_updater")
        unified_cfg = get_section(self.config, "unified_analyzer")
        emotion_cfg = get_section(self.config, "emotion")
        embed_cfg = get_section(self.config, "embeddings")
        char_cfg = get_section(self.config, "characters")
        registry_name = char_cfg.get("registry", "characters.json")
        registry_path = os.path.join(self.user_data_root, registry_name)
        if self.user_id is not None and not os.path.exists(registry_path):
            if os.path.exists(registry_name):
                shutil.copy2(registry_name, registry_path)

        legacy = paths if self.user_id is None else {}
        self.character_manager = CharacterManager(
            registry_path=registry_path,
            legacy_paths=legacy,
            user_data_root=self.user_data_root if self.user_id else None,
        )
        char_paths = self.character_manager.resolve_paths()
        self.soul_path = char_paths["soul"]
        self.soul_core_path = char_paths.get("soul_core", soul_paths(os.path.dirname(self.soul_path))["core"])
        self.soul_state_path = char_paths.get("soul_state", self.soul_path)
        self.memory_path = char_paths["memory"]
        self.emotion_path = char_paths["emotion"]
        self.log_session_template = os.path.join(
            self.user_data_root,
            paths.get("log_session", "logs/session_{session_id}.json"),
        )

        self.use_vector_memory = bool(embed_cfg.get("enabled", True))
        self.embed_client: EmbeddingClient | None = None
        if self.use_vector_memory:
            self.embed_client = EmbeddingClient(
                model=embed_cfg.get("model", "nomic-embed-text"),
                base_url=embed_cfg.get(
                    "base_url", "http://localhost:11434/api/embeddings"
                ),
                timeout=int(embed_cfg.get("timeout", 60)),
                max_retries=int(embed_cfg.get("max_retries", 2)),
            )

        self.fact_extract_interval = max(
            1, int(engine_cfg.get("fact_extract_interval", 1))
        )
        self.arc_update_interval = max(
            1, int(engine_cfg.get("arc_update_interval", 3))
        )
        self.auto_save_interval = max(
            1, int(engine_cfg.get("auto_save_interval", 5))
        )
        self.recent_dialogue_rounds = int(
            engine_cfg.get("recent_dialogue_rounds", 5)
        )
        self.relevant_facts_limit = int(
            engine_cfg.get("relevant_facts_limit", 3)
        )
        self.use_unified_analyzer = bool(
            unified_cfg.get("enabled", True)
        )
        self.hot_reload = bool(engine_cfg.get("hot_reload", True))
        self.stream = bool(engine_cfg.get("stream", True))
        self.ollama_num_predict = int(ollama_cfg.get("num_predict", 200))
        self.round_count = 0
        self.pending_character_id: int | None = None
        # v0.2 诊断 + 重生成循环
        self.max_regen_attempts = max(
            0, int(engine_cfg.get("max_regen_attempts", 2))
        )
        self.enable_diagnosis = bool(
            engine_cfg.get("enable_diagnosis", True)
        )

        chat_model = ollama_cfg.get("chat_model") or ollama_cfg.get(
            "model", "qwen2.5:7b"
        )
        analysis_model = ollama_cfg.get("analysis_model") or ollama_cfg.get(
            "model", "deepseek-r1:8b"
        )
        ollama_base = ollama_cfg.get(
            "base_url", "http://localhost:11434/api/generate"
        )
        ollama_timeout = int(ollama_cfg.get("timeout", 300))
        max_retries = int(ollama_cfg.get("max_retries", 2))

        self.soul = Soul()
        self._init_memory_v2(engine_cfg)
        self.emotion = PADEmotionManager(
            default_score=float(emotion_cfg.get("default_score", 5.0))
        )
        self.emotion.set_log_callback(self._log_emotion_change)
        self.logger = Logger()
        self.chat_ollama = OllamaClient(
            model_name=chat_model,
            base_url=ollama_base,
            timeout=ollama_timeout,
            max_retries=max_retries,
            allow_thinking_fallback=False,
        )
        self.analysis_ollama = OllamaClient(
            model_name=analysis_model,
            base_url=ollama_base,
            timeout=ollama_timeout,
            max_retries=max_retries,
            allow_thinking_fallback=True,
        )
        self.ollama = self.chat_ollama
        self.extractor = MemoryExtractor(
            self.analysis_ollama,
            num_predict=int(mem_ext_cfg.get("num_predict", 150)),
            temperature=float(mem_ext_cfg.get("temperature", 0.3)),
        )
        self.arc_updater = ArcUpdater(
            self.analysis_ollama,
            num_predict=int(arc_cfg.get("num_predict", 120)),
            temperature=float(arc_cfg.get("temperature", 0.2)),
        )
        self.unified = UnifiedAnalyzer(
            self.analysis_ollama,
            num_predict=int(unified_cfg.get("num_predict", 250)),
            temperature=float(unified_cfg.get("temperature", 0.25)),
        )

        template = self.character_manager.get_soul_template()
        self.soul, self._soul_core, self._soul_state, soul_warnings = load_soul_from_paths(
            self.soul_path,
            template=template,
            auto_migrate=True,
        )
        for msg in soul_warnings:
            print(f"[Soul] {msg}")
        self._load_memory_v2(self.memory_path)
        self.emotion.load(self.emotion_path)

        # v0.2 新架构：Context Builder + Memory Writer
        self.context_builder = ContextBuilder(
            recent_dialogue_rounds=self.recent_dialogue_rounds,
            relevant_raw_memory_limit=self.relevant_facts_limit,
        )
        self.memory_writer = MemoryWriter()

        # v0.3 链路追踪（observability.TurnTrace）：每轮对话一条 trace
        self._current_trace: Any = None  # observability.TurnTrace | None

    def _trace_step(
        self,
        step_name: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """记录一个 trace step。仅当 self._current_trace 非空时记录。

        关键 step_name:
            context_built / llm_generated / harness_evaluated /
            regen_attempt / memory_written / turn_finalized
        """
        if self._current_trace is None:
            return
        try:
            from observability import TurnStep

            self._current_trace.add_step(
                TurnStep(
                    step_name=step_name,
                    detail=detail or {},
                ).mark_end()
            )
        except Exception:
            # trace 失败不能影响主流程
            pass

    def _trace_log_step(
        self,
        step_name: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """同时记录到 logger（粗粒度链路节点）和当前 trace。"""
        if self._current_trace is None:
            return
        turn_id = self._current_trace.turn_id
        self.logger.log_turn_step(turn_id, step_name, detail)
        self._trace_step(step_name, detail)

    def _begin_trace(self, turn_id: str, user_message: str) -> Any:
        """开始一轮新 trace，返回 trace 实例。"""
        from observability import TurnTrace

        self._current_trace = TurnTrace(
            turn_id=turn_id,
            user_message=user_message,
        )
        # 附带版本号快照（11.1 Versioning）：便于审计回溯
        try:
            from scoring.config import SCORING_RULES_VERSION
            from scoring.engine import EVALUATOR_VERSION
            from safety.loader import SAFETY_RULES_VERSION

            self._current_trace.schema_versions = {
                "scoring_rules": SCORING_RULES_VERSION,
                "evaluator": EVALUATOR_VERSION,
                "safety_rules": SAFETY_RULES_VERSION,
            }
        except Exception:
            pass
        return self._current_trace

    def _finalize_trace(self, duration_ms: float = 0.0) -> None:
        """结束当前 trace，落盘到 logger。"""
        if self._current_trace is None:
            return
        self._current_trace.finalize(duration_ms=duration_ms)
        self.logger.log_turn_trace(self._current_trace)
        self._current_trace = None

    def _embed_text(self, text: str) -> list[float]:
        if not self.embed_client:
            return []
        return self.embed_client.embed(text)

    # ------------------------------------------------------------------
    # v0.2 三层记忆构造 / 加载 / 保存
    # ------------------------------------------------------------------
    def _init_memory_v2(self, engine_cfg: dict) -> None:
        """构造 v0.2 三层 + 检索器，替代旧 _create_memory()。"""
        max_rounds = int(engine_cfg.get("memory_max_rounds", 10))
        max_messages = max(2, max_rounds * 2)
        self.session_buffer = SessionBuffer(max_messages=max_messages)
        self.raw_memory = RawMemory()
        self.semantic_memory = SemanticMemory()
        # embedder 注入到 raw_memory（运行时算向量，不持久化）
        if self.use_vector_memory and self.embed_client:
            self.raw_memory.set_embedder(self._embed_text)
        self.retriever = MemoryRetriever(
            session_buffer=self.session_buffer,
            raw_memory=self.raw_memory,
            semantic_memory=self.semantic_memory,
        )

    def _load_memory_v2(self, memory_path: str) -> None:
        """从同目录加载 v0.2 三份文件；若不存在则回退旧 memory_state.json。"""
        dir_ = os.path.dirname(os.path.abspath(memory_path)) or "."
        session_path = os.path.join(dir_, "memory_session.json")
        raw_path = os.path.join(dir_, "memory_raw.json")
        sem_path = os.path.join(dir_, "memory_semantic.json")

        loaded_any = False
        if os.path.isfile(session_path):
            self.session_buffer.load(session_path, max_messages=self.session_buffer.max_messages)
            loaded_any = True
        if os.path.isfile(raw_path):
            self.raw_memory.load(raw_path)
            loaded_any = True
        if os.path.isfile(sem_path):
            try:
                import json as _json
                with open(sem_path, "r", encoding="utf-8") as f:
                    sem_data = _json.load(f)
                from memory.semantic_memory import SemanticMemory as _SM
                self.semantic_memory = _SM.from_dict(sem_data)
                # 重新绑定 retriever
                self.retriever = MemoryRetriever(
                    session_buffer=self.session_buffer,
                    raw_memory=self.raw_memory,
                    semantic_memory=self.semantic_memory,
                )
                loaded_any = True
            except Exception:
                pass

        if not loaded_any and os.path.isfile(memory_path):
            # 回退：旧 memory_state.json → 在内存做迁移（不落盘）
            import json as _json
            with open(memory_path, "r", encoding="utf-8") as f:
                legacy = _json.load(f)
            self.session_buffer = SessionBuffer.from_legacy_memory_dict(legacy)
            self.raw_memory = RawMemory.from_legacy_memory_dict(legacy)
            if self.use_vector_memory and self.embed_client:
                self.raw_memory.set_embedder(self._embed_text)
            self.retriever = MemoryRetriever(
                session_buffer=self.session_buffer,
                raw_memory=self.raw_memory,
                semantic_memory=self.semantic_memory,
            )
            print(f"[Memory] 从 v0.1 回退加载: {memory_path}")

    def _save_memory_v2(self, memory_path: str) -> None:
        """保存 v0.2 三层到 memory_path 同目录。

        v0.3 重构：所有 memory 写入通过 MemoryWriter.save_all，不再直接调
        session_buffer.save / raw_memory.save / semantic_memory.save。
        """
        dir_ = os.path.dirname(os.path.abspath(memory_path)) or "."
        # 集中通过 MemoryWriter 落盘三层 memory
        self.memory_writer.save_all(
            memory_dir=dir_,
            session_buffer=self.session_buffer,
            raw_memory=self.raw_memory,
            semantic_memory=self.semantic_memory,
        )
        # Phase 2 接口：旧 v0.1 双写开关（默认关）
        self.memory_writer.save_legacy_v01(
            memory_path=memory_path,
            session_buffer=self.session_buffer,
            raw_memory=self.raw_memory,
            use_vector=self.use_vector_memory,
        )

    def list_characters(self) -> list[str]:
        return self.character_manager.list_characters()

    def get_active_character(self) -> str:
        return self.character_manager.get_active()

    def switch_character(self, name: str) -> str:
        """保存当前角色状态，切换到另一角色并加载其状态。"""
        if name == self.character_manager.get_active():
            return f"已在角色 {name}"

        self._save_all_state()
        self.character_manager.set_active(name)
        char_paths = self.character_manager.resolve_paths()
        self.soul_path = char_paths["soul"]
        self.soul_core_path = char_paths.get("soul_core", soul_paths(os.path.dirname(self.soul_path))["core"])
        self.soul_state_path = char_paths.get("soul_state", self.soul_path)
        self.memory_path = char_paths["memory"]
        self.emotion_path = char_paths["emotion"]

        engine_cfg = get_section(self.config, "engine")
        self.soul = Soul()
        self._init_memory_v2(engine_cfg)
        self.emotion = PADEmotionManager(
            default_score=float(
                get_section(self.config, "emotion").get("default_score", 5.0)
            )
        )
        self.emotion.set_log_callback(self._log_emotion_change)
        template = self.character_manager.get_soul_template()
        self.soul, self._soul_core, self._soul_state, soul_warnings = load_soul_from_paths(
            self.soul_path,
            template=template,
            auto_migrate=True,
        )
        for msg in soul_warnings:
            print(f"[Soul] {msg}")
        self._load_memory_v2(self.memory_path)
        self.emotion.load(self.emotion_path)

        self.round_count = 0
        self.logger = Logger()
        return f"已切换到角色: {self.soul.name}（{self.soul.role}）"

    def get_status(self) -> dict:
        """返回当前引擎状态快照（供 Web UI /status 使用）。"""
        return {
            "角色": f"{self.soul.name}（{self.soul.role}）",
            "对话模型": self.chat_ollama.model_name,
            "分析模型": self.analysis_ollama.model_name,
            "会话": self.logger.session_id,
            "轮次": self.round_count,
            "情绪": (
                f"P={self.emotion.pad.pleasure:.1f} "
                f"A={self.emotion.pad.arousal:.1f} "
                f"D={self.emotion.pad.dominance:.1f} "
                f"({self.emotion.stage})"
            ),
            "弧光": self.soul.arc_stage,
            "目标": self.soul.current_goal,
            "短期记忆": len(self.session_buffer.messages),
            "长期记忆": len(self.raw_memory.entries),
            "向量记忆": "开启" if self.use_vector_memory else "关闭",
            "当前角色ID": self.character_manager.get_active(),
            "合并分析": "开启" if self.use_unified_analyzer else "关闭",
        }

    def format_status_text(self) -> str:
        """格式化为 Markdown 状态文本。"""
        s = self.get_status()
        return (
            f"**{s['角色']}**\n\n"
            f"- 对话模型: `{s['对话模型']}`\n"
            f"- 分析模型: `{s['分析模型']}`\n"
            f"- 情绪: {s['情绪']}\n"
            f"- 弧光: {s['弧光']}\n"
            f"- 目标: {s['目标']}\n"
            f"- 轮次: {s['轮次']} | 短期记忆: {s['短期记忆']} 条 | "
            f"长期记忆: {s['长期记忆']} 条\n"
            f"- 向量记忆: {s['向量记忆']} | 后处理: {s['合并分析']}"
        )

    def reload_config(self) -> None:
        """热重载 config.json（修改间隔、模型名等无需重启）。"""
        if not self.hot_reload:
            return
        self.config = load_config(
            self.config_path, create_if_missing=False, validate=True
        )
        ollama_cfg = get_section(self.config, "ollama")
        engine_cfg = get_section(self.config, "engine")
        unified_cfg = get_section(self.config, "unified_analyzer")

        self.fact_extract_interval = max(
            1, int(engine_cfg.get("fact_extract_interval", 3))
        )
        self.arc_update_interval = max(
            1, int(engine_cfg.get("arc_update_interval", 3))
        )
        self.auto_save_interval = max(
            1, int(engine_cfg.get("auto_save_interval", 5))
        )
        self.recent_dialogue_rounds = int(
            engine_cfg.get("recent_dialogue_rounds", 5)
        )
        self.relevant_facts_limit = int(
            engine_cfg.get("relevant_facts_limit", 3)
        )
        self.use_unified_analyzer = bool(unified_cfg.get("enabled", True))
        self.stream = bool(engine_cfg.get("stream", True))
        self.ollama_num_predict = int(ollama_cfg.get("num_predict", 200))

        chat_model = ollama_cfg.get("chat_model") or ollama_cfg.get("model")
        analysis_model = ollama_cfg.get("analysis_model") or ollama_cfg.get(
            "model"
        )
        if chat_model:
            self.chat_ollama.model_name = chat_model
        if analysis_model:
            self.analysis_ollama.model_name = analysis_model
        self.chat_ollama.timeout = int(ollama_cfg.get("timeout", 300))
        self.analysis_ollama.timeout = int(ollama_cfg.get("timeout", 300))
        retries = int(ollama_cfg.get("max_retries", 2))
        self.chat_ollama.max_retries = retries
        self.analysis_ollama.max_retries = retries

    def _soul_to_natural_language(self) -> str:
        d = self.soul.to_dict()
        traits = "、".join(d["core_traits"])
        catchphrases = "；".join(d["catchphrases"])
        vocabulary = "、".join(d["vocabulary"])

        return (
            f"名字：{d['name']}\n"
            f"职业：{d['role']}\n"
            f"核心特质：{traits}\n"
            f"核心驱动力：{d['core_drive']}\n"
            f"内心恐惧：{d['fear']}\n"
            f"口头禅：{catchphrases}\n"
            f"常用词汇：{vocabulary}\n"
            f"角色弧光阶段：{d['arc_stage']}\n"
            f"当前目标：{d['current_goal']}"
        )

    def _format_recent_dialogue(self, max_rounds: int | None = None) -> str:
        rounds = max_rounds if max_rounds is not None else self.recent_dialogue_rounds
        messages = self.session_buffer.turns(rounds)
        if not messages:
            return "（暂无历史对话）"
        lines = []
        for msg in messages:
            role_label = "用户" if msg.role == "user" else self.soul.name
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)

    def _format_relevant_facts(self, query: str) -> str:
        result = self.retriever.query(
            query,
            raw_limit_override=self.relevant_facts_limit,
        )
        if not result.raw_hits:
            return "（暂无相关长期记忆）"
        return "\n".join(
            f"- {e.content}（重要性 {e.importance}）"
            for e in result.raw_hits
        )

    def build_prompt(self, user_message: str) -> str:
        """委托给 ContextBuilder：read_snapshot → build_prompt。"""
        snapshot = self.context_builder.read_snapshot(
            user_message=user_message,
            soul=self.soul,
            retriever=self.retriever,
            emotion_manager=self.emotion,
        )
        prompt = self.context_builder.build_prompt(snapshot, user_message=user_message)
        # 末尾追加角色名冒号（v0.1 行为兼容）
        prompt = prompt.rstrip() + f"\n{self.soul.name}:"
        return prompt

    def _log_emotion_change(
        self, component: str, field: str, old_value, new_value
    ) -> None:
        self.logger.log_state_change(component, field, old_value, new_value)

    def _prepare_emotion_for_turn(
        self,
        user_message: str,
        character_id: int | None = None,
    ) -> None:
        """分析用户输入并更新 PAD 情绪状态（异常时 fail-open）。"""
        # v0.3：通过 MemoryWriter 统一 emotion 状态变更入口
        self.memory_writer.update_emotion(
            emotion_manager=self.emotion,
            user_message=user_message,
        )

    def _persist_emotion_state(self, character_id: int | None = None) -> None:
        # v0.3：通过 MemoryWriter 统一持久化（不直接调 emotion.save）
        self.memory_writer.save_emotion(
            emotion_manager=self.emotion,
            emotion_path=self.emotion_path,
            character_id=character_id,
        )

    def _stream_token_cli(self, token: str, field: str) -> None:
        if field == "response":
            sys.stdout.write(token)
            sys.stdout.flush()

    def _generate_reply(
        self,
        prompt: str,
        *,
        stream: bool | None = None,
        on_token=None,
    ) -> str:
        use_stream = self.stream if stream is None else stream
        gen_options = {"num_predict": self.ollama_num_predict}

        if use_stream:
            callback = on_token or self._stream_token_cli
            return self.chat_ollama.generate_stream(
                prompt, on_token=callback, options=gen_options
            )
        return self.chat_ollama.generate(
            prompt, stream=False, options=gen_options
        )

    # ------------------------------------------------------------------
    # v0.2 诊断 + 重生成循环
    # ------------------------------------------------------------------
    def _generate_with_diagnosis(
        self,
        prompt: str,
        user_message: str,
        character_id: int | None,
        *,
        stream: bool | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """生成 + 诊断 + 可选重生成。返回 (最终采纳回复, 诊断报告或 None)。

        第一轮：正常生成 → sanitize → diagnose → log_candidate
        若 failed 且 attempt < max_regen_attempts：
            → build_rewrite_prompt → 重新生成 → sanitize → diagnose → log_candidate
        最多重试 max_regen_attempts 次。

        所有候选（含被拒绝的）都记入 logger 的 evaluation_candidate 条目。
        Memory Writer 只读最终采纳的回复，不读候选数组。
        """
        from safety.gateway import sanitize_model_output
        from scoring.engine import diagnose, build_rewrite_prompt

        ai_response = self._generate_reply(prompt, stream=stream)
        ai_response = sanitize_model_output(
            ai_response,
            user_id=self.user_id,
            character_id=character_id,
        )

        if not self.enable_diagnosis or self.max_regen_attempts == 0:
            # 仍记录 llm_generated（无诊断时也算一轮生成）
            self._trace_log_step(
                "llm_generated",
                {"candidate_preview": ai_response[:100], "attempt": 0, "tokens": len(ai_response) // 4},
            )
            return ai_response, None

        # 构造诊断上下文
        character_meta = {
            "display_name": self.soul.name,
            "description": self.soul.description or "",
            "role": self.soul.role or "",
        }
        pad_state = None
        if self.emotion and hasattr(self.emotion, "pad"):
            try:
                pad = self.emotion.pad
                pad_state = {
                    "pleasure": float(getattr(pad, "pleasure", 5.0)),
                    "arousal": float(getattr(pad, "arousal", 5.0)),
                    "dominance": float(getattr(pad, "dominance", 5.0)),
                }
            except Exception:
                pass

        # 记录所有候选（含被拒绝的）
        all_candidates: list[dict] = []

        diagnosis = diagnose(
            user_message, ai_response, character_meta,
            pad_state=pad_state,
            attempt=0,
        )
        # llm_generated + harness_evaluated（首轮）
        self._trace_log_step(
            "llm_generated",
            {"candidate_preview": ai_response[:100], "attempt": 0, "tokens": len(ai_response) // 4},
        )
        self._trace_log_step(
            "harness_evaluated",
            {
                "candidate_preview": ai_response[:100],
                "scores": diagnosis.scores,
                "violations": [v.to_dict() for v in diagnosis.violations],
                "rewrite_instruction": diagnosis.rewrite_instruction,
                "passed": diagnosis.passed,
                "attempt": 0,
            },
        )
        # 记录第 0 轮候选
        self.logger.log_candidate(
            ai_response, diagnosis.to_dict(),
            attempt=0, accepted=diagnosis.passed,
        )
        all_candidates.append({
            "candidate": ai_response,
            "attempt": 0,
            "passed": diagnosis.passed,
            "violations": diagnosis.to_dict().get("violations", []),
            "rewrite_instruction": diagnosis.rewrite_instruction,
            "scores": diagnosis.scores,
        })

        attempt = 0
        while not diagnosis.passed and attempt < self.max_regen_attempts:
            attempt += 1
            # regen_attempt：进入重生成
            self._trace_log_step(
                "regen_attempt",
                {"attempt": attempt, "triggered_by_violation": (
                    diagnosis.violations[0].type if diagnosis.violations else ""
                )},
            )
            rewrite_prompt = build_rewrite_prompt(
                prompt, diagnosis,
                user_message=user_message,
                character_name=self.soul.name,
            )
            try:
                ai_response = self._generate_reply(rewrite_prompt, stream=stream)
            except OllamaError:
                break
            ai_response = sanitize_model_output(
                ai_response,
                user_id=self.user_id,
                character_id=character_id,
            )
            diagnosis = diagnose(
                user_message, ai_response, character_meta,
                pad_state=pad_state,
                attempt=attempt,
            )
            accepted = diagnosis.passed or attempt >= self.max_regen_attempts
            # llm_generated + harness_evaluated（重生成轮）
            self._trace_log_step(
                "llm_generated",
                {"candidate_preview": ai_response[:100], "attempt": attempt, "tokens": len(ai_response) // 4},
            )
            self._trace_log_step(
                "harness_evaluated",
                {
                    "candidate_preview": ai_response[:100],
                    "scores": diagnosis.scores,
                    "violations": [v.to_dict() for v in diagnosis.violations],
                    "rewrite_instruction": diagnosis.rewrite_instruction,
                    "passed": diagnosis.passed,
                    "attempt": attempt,
                },
            )
            self.logger.log_candidate(
                ai_response, diagnosis.to_dict(),
                attempt=attempt, accepted=accepted,
            )
            all_candidates.append({
                "candidate": ai_response,
                "attempt": attempt,
                "passed": diagnosis.passed,
                "violations": diagnosis.to_dict().get("violations", []),
                "rewrite_instruction": diagnosis.rewrite_instruction,
                "scores": diagnosis.scores,
            })

        # 记录完整评估链路摘要
        final_index = len(all_candidates) - 1
        self.logger.log_evaluation_link(
            user_message=user_message,
            candidates=all_candidates,
            final_accepted_index=final_index,
            total_regen_count=attempt,
        )

        # 记录诊断结果到 logger state_change（兼容旧格式）
        self.logger.log_state_change(
            "scoring", "diagnosis", None, diagnosis.to_dict()
        )
        if not diagnosis.passed and attempt >= self.max_regen_attempts:
            self.logger.log_state_change(
                "scoring", "regen_exhausted", None,
                {"attempts": attempt + 1, "final_response_preview": ai_response[:100]},
            )

        # 诊断报告附带候选链路信息，供 score_and_persist 使用
        diag_dict = diagnosis.to_dict()
        diag_dict["candidates"] = all_candidates
        diag_dict["final_accepted_index"] = final_index
        diag_dict["regen_count"] = attempt

        # 返回最终采纳的回复（可能被拒绝但已用完重试次数）
        # Memory Writer 只读这个 ai_response，不读 all_candidates
        return ai_response, diag_dict

    def _save_all_state(self) -> None:
        # v0.3：通过 MemoryWriter 统一入口落盘（不直接调 .save）
        self._save_memory_v2(self.memory_path)
        save_soul_state(self.soul, self.soul_state_path)
        self.memory_writer.save_emotion(
            emotion_manager=self.emotion,
            emotion_path=self.emotion_path,
        )

    def _maybe_auto_save(self) -> None:
        if self.round_count > 0 and self.round_count % self.auto_save_interval == 0:
            self._save_all_state()

    def _store_facts(self, candidates: list[dict]) -> list[str]:
        """委托给 MemoryWriter 的 Raw Memory 写入路径（不经过完整 write_turn）。

        注意：此方法在 v0.2 架构里只用于「非 unified_analyzer 模式下」的
        独立 extractor 调用。unified_analyzer 模式下，_post_process_turn
        会走完整 MemoryWriter.write_turn()。

        v0.3 重构：不再直接调 `self.raw_memory.add_from_extractor(...)`，
        所有 Raw Memory 写入通过 MemoryWriter.write_raw_entry。
        """
        # filter_new_facts 期望 v0.1 long_term dict 格式
        existing_facts = [
            {"fact": e.content, "importance": e.importance}
            for e in self.raw_memory.active_entries()
        ]
        new_facts = self.extractor.filter_new_facts(candidates, existing_facts)
        added: list[str] = []
        for item in new_facts:
            # 通过 MemoryWriter 统一入口写入
            memory_id = self.memory_writer.write_raw_entry(
                raw_memory=self.raw_memory,
                fact=item["fact"],
                importance=item["importance"],
                category="fact",
            )
            if memory_id is not None:
                added.append(item["fact"])
                self.logger.log_state_change(
                    "memory",
                    "raw_memory",
                    len(self.raw_memory.entries),
                    {
                        "fact": item["fact"],
                        "importance": item["importance"],
                    },
                )
        return added

    def _apply_arc_update(self, narrative: dict) -> list[str]:
        if not narrative.get("should_update"):
            return []

        update = {
            "arc_stage": narrative.get("arc_stage"),
            "current_goal": narrative.get("current_goal"),
            "reason": narrative.get("reason", ""),
        }
        changes = self.arc_updater.apply_to_soul(self.soul, update)
        if not changes:
            return []

        descriptions: list[str] = []
        for key, (old_val, new_val) in changes.items():
            self.logger.log_state_change("soul", key, old_val, new_val)
            if key == "arc_stage":
                descriptions.append(f"弧光: {old_val} → {new_val}")
            elif key == "current_goal":
                descriptions.append(f"目标: {new_val}")

        if update.get("reason"):
            self.logger.log_state_change(
                "soul", "update_reason", None, update["reason"]
            )

        save_soul_state(self.soul, self.soul_state_path)

        from arc.manager import on_engine_arc_update

        new_goal = None
        if "current_goal" in changes:
            new_goal = changes["current_goal"][1]
        new_arc = changes.get("arc_stage", (None, None))[1]

        on_engine_arc_update(
            self.pending_character_id,
            soul_arc_stage=new_arc or self.soul.arc_stage,
            current_goal=new_goal or self.soul.current_goal,
            reason=update.get("reason", ""),
            total_rounds=self.round_count,
            operator="system",
        )

        return descriptions

    def _post_process_needs(self) -> tuple[bool, bool]:
        need_facts = self.round_count % self.fact_extract_interval == 0
        need_arc = self.round_count % self.arc_update_interval == 0
        return need_facts, need_arc

    def _post_process_turn(
        self,
        user_message: str,
        ai_response: str,
        on_step=None,
    ) -> tuple[list[str], list[str]]:
        need_facts, need_arc = self._post_process_needs()

        if not need_facts and not need_arc:
            return [], []

        if self.use_unified_analyzer:
            if on_step and need_facts:
                on_step(2, "正在提取记忆…（2/3）")
            elif on_step and need_arc:
                on_step(2, "正在分析叙事状态…（2/3）")

            parsed, raw = self.unified.analyze(
                self.soul,
                user_message,
                ai_response,
                self.emotion.score,
                existing_facts=[
                    {"fact": e.content, "importance": e.importance}
                    for e in self.raw_memory.active_entries()
                ],
                analyze_facts=need_facts,
                analyze_arc=need_arc,
            )

            if on_step and need_arc:
                on_step(3, "正在评估弧光…（3/3）")

            new_facts = (
                self._store_facts(parsed["facts"]) if need_facts else []
            )
            arc_changes = (
                self._apply_arc_update(parsed["narrative"]) if need_arc else []
            )
            if raw and not new_facts and not arc_changes:
                self.logger.log_state_change(
                    "unified_analyzer",
                    "skipped",
                    None,
                    {"raw_preview": raw[:200]},
                )
            return new_facts, arc_changes

        new_facts: list[str] = []
        arc_changes: list[str] = []
        if need_facts:
            if on_step:
                on_step(2, "正在提取记忆…（2/3）")
            candidates, _ = self.extractor.extract(
                user_message, ai_response,
                [
                    {"fact": e.content, "importance": e.importance}
                    for e in self.raw_memory.active_entries()
                ],
            )
            new_facts = self._store_facts(candidates)
        if need_arc:
            if on_step:
                on_step(3, "正在评估弧光…（3/3）")
            update, _ = self.arc_updater.evaluate(
                self.soul, user_message, ai_response, self.emotion.score
            )
            if update:
                arc_changes = self._apply_arc_update(
                    {**update, "should_update": True}
                )
        return new_facts, arc_changes

    def _finalize_turn(
        self,
        user_message: str,
        ai_response: str,
        prompt: str,
        on_step=None,
        character_id: int | None = None,
        diagnosis: dict[str, Any] | None = None,
    ) -> TurnResult:
        self.logger.log_response(
            ai_message=ai_response,
            prompt_used=prompt,
            api_response=self.chat_ollama.get_last_call(),
        )
        # v0.3：通过 MemoryWriter 统一入口写短期 buffer
        self.memory_writer.add_session_message(
            role="assistant",
            content=ai_response,
            session_buffer=self.session_buffer,
        )
        self.round_count += 1
        self._persist_emotion_state(character_id)

        new_facts, arc_changes = self._post_process_turn(
            user_message, ai_response, on_step=on_step
        )
        self._maybe_auto_save()

        # memory_written：记录 Memory Writer 落盘结果
        try:
            self._trace_log_step(
                "memory_written",
                {
                    "new_facts_count": len(new_facts) if new_facts else 0,
                    "arc_changes_count": len(arc_changes) if arc_changes else 0,
                    "final_response_preview": ai_response[:100],
                },
            )
        except Exception:
            pass

        return TurnResult(
            response=ai_response,
            new_facts=new_facts,
            arc_changes=arc_changes,
            diagnosis=diagnosis,
        )

    def process_message(
        self,
        user_message: str,
        *,
        stream: bool | None = None,
        character_id: int | None = None,
    ) -> TurnResult:
        """公共 API：处理单条用户消息（CLI / Web 通用）。"""
        import time

        if self.hot_reload:
            self.reload_config()

        user_message = user_message.strip()
        if not user_message:
            return TurnResult(response="", error="空消息")

        from safety.gateway import check_user_input, sanitize_model_output
        from observability import new_turn_id

        # v0.3：开启本轮 trace
        self._begin_trace(new_turn_id(), user_message)

        blocked = check_user_input(
            user_message,
            user_id=self.user_id,
            character_id=character_id,
        )
        if blocked is not None:
            self._finalize_trace(duration_ms=0.0)
            return TurnResult(response=blocked)

        self.logger.log_input(user_message)
        self.memory_writer.add_session_message(
            role="user", content=user_message, session_buffer=self.session_buffer,
        )
        self.pending_character_id = character_id
        self._prepare_emotion_for_turn(user_message, character_id)
        prompt = self.build_prompt(user_message)

        # context_built：记录 prompt 长度 + 关系轴快照
        try:
            axes_snapshot = {}
            if hasattr(self, "pair_state") and self.pair_state is not None:
                axes_snapshot = self.pair_state.axes.as_dict()
            self._trace_log_step(
                "context_built",
                {
                    "prompt_tokens_approx": len(prompt) // 4,
                    "axes_values_at_turn": axes_snapshot,
                },
            )
        except Exception:
            pass

        try:
            ai_response, diagnosis_dict = self._generate_with_diagnosis(
                prompt, user_message, character_id, stream=stream,
            )
        except OllamaError as exc:
            self.logger.log_error(str(exc))
            self._finalize_trace(duration_ms=0.0)
            return TurnResult(
                response=f"[系统错误] 无法获取回复: {exc}",
                error=str(exc),
            )

        result = self._finalize_turn(
            user_message, ai_response, prompt,
            character_id=character_id,
            diagnosis=diagnosis_dict,
        )

        # turn_finalized：记录整轮摘要
        try:
            self._trace_log_step(
                "turn_finalized",
                {
                    "final_response_preview": result.response[:100],
                    "diagnosis_passed": (
                        diagnosis_dict.get("passed") if diagnosis_dict else None
                    ),
                    "regen_count": (
                        diagnosis_dict.get("regen_count") if diagnosis_dict else 0
                    ),
                },
            )
        except Exception:
            pass
        self._finalize_trace(duration_ms=0.0)
        return result

    def process_message_stream(
        self,
        user_message: str,
        *,
        cancel_event=None,
        character_id: int | None = None,
        timeout_seconds: float | None = None,
    ):
        """
        流式处理用户消息：逐 token yield，并在循环中检查取消标志。

        Yields:
            ("token", str) | ("done", TurnResult) | ("cancelled", TurnResult) | ("error", str)
        """
        import time

        if self.hot_reload:
            self.reload_config()

        user_message = user_message.strip()
        if not user_message:
            yield "error", "空消息"
            return

        from safety.gateway import check_user_input, sanitize_model_output

        blocked = check_user_input(
            user_message,
            user_id=self.user_id,
            character_id=character_id,
        )
        if blocked is not None:
            yield "done", TurnResult(response=blocked)
            return

        self.logger.log_input(user_message)
        self.memory_writer.add_session_message(
            role="user", content=user_message, session_buffer=self.session_buffer,
        )
        self.pending_character_id = character_id
        self._prepare_emotion_for_turn(user_message, character_id)
        prompt = self.build_prompt(user_message)

        if timeout_seconds is None:
            try:
                from performance.config import get_config

                timeout_seconds = float(get_config().TIMEOUT_SECONDS)
            except Exception:
                timeout_seconds = 300.0

        accumulated = ""
        cancelled = False
        started = time.monotonic()
        gen_options = {"num_predict": self.ollama_num_predict}

        try:
            for field, token in self.chat_ollama.iter_tokens(
                prompt,
                cancel_event=cancel_event,
                options=gen_options,
            ):
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if time.monotonic() - started > timeout_seconds:
                    yield "error", "抱歉，我思考太久了，请再问一次"
                    return
                if field != "response":
                    continue
                accumulated += token
                yield "token", token
        except OllamaError as exc:
            self.logger.log_error(str(exc))
            yield "error", f"[系统错误] 无法获取回复: {exc}"
            return

        if cancel_event is not None and cancel_event.is_set():
            cancelled = True

        if not accumulated.strip() and not cancelled:
            try:
                accumulated = self.chat_ollama._extract_text(
                    self.chat_ollama.last_response or {}
                )
            except OllamaError:
                accumulated = ""

        ai_response = sanitize_model_output(
            accumulated,
            user_id=self.user_id,
            character_id=character_id,
        )

        if cancelled:
            # 取消：保留已生成部分，写入会话但不做重后处理打断体验
            self.logger.log_response(
                ai_message=ai_response,
                prompt_used=prompt,
                api_response=self.chat_ollama.get_last_call(),
            )
            if ai_response:
                # v0.3：通过 MemoryWriter 写短期 buffer
                self.memory_writer.add_session_message(
                    role="assistant", content=ai_response, session_buffer=self.session_buffer,
                )
                self.round_count += 1
                self._persist_emotion_state(character_id)
            yield "cancelled", TurnResult(response=ai_response)
            return

        result = self._finalize_turn(
            user_message, ai_response, prompt, character_id=character_id
        )
        yield "done", result

    def iter_turn(self, user_message: str):
        """
        流式处理并 yield 分步进度（供 Web UI 使用）。

        Yields:
            StepProgress
        """
        if self.hot_reload:
            self.reload_config()

        user_message = user_message.strip()
        if not user_message:
            yield StepProgress(
                step=1, total=1, label="空消息", done=True,
                result=TurnResult(response="", error="空消息"),
            )
            return

        self.logger.log_input(user_message)
        self.memory_writer.add_session_message(
            role="user", content=user_message, session_buffer=self.session_buffer,
        )
        self._prepare_emotion_for_turn(user_message)
        prompt = self.build_prompt(user_message)

        accumulated = ""
        yield StepProgress(
            step=1, total=3, label="正在生成回复…（1/3）", partial=""
        )

        try:
            gen_options = {"num_predict": self.ollama_num_predict}
            for field, token in self.chat_ollama.iter_tokens(
                prompt, options=gen_options
            ):
                if field == "response":
                    accumulated += token
                    yield StepProgress(
                        step=1,
                        total=3,
                        label="正在生成回复…（1/3）",
                        partial=accumulated,
                    )
        except OllamaError as exc:
            self.logger.log_error(str(exc))
            result = TurnResult(
                response=f"[系统错误] 无法获取回复: {exc}",
                error=str(exc),
            )
            yield StepProgress(
                step=1, total=3, label="请求失败", partial=result.response,
                done=True, result=result,
            )
            return

        if not accumulated.strip():
            try:
                accumulated = self.chat_ollama._extract_text(
                    self.chat_ollama.last_response or {}
                )
            except OllamaError:
                accumulated = ""

        self.logger.log_response(
            ai_message=accumulated,
            prompt_used=prompt,
            api_response=self.chat_ollama.get_last_call(),
        )
        # v0.3：通过 MemoryWriter 写短期 buffer
        self.memory_writer.add_session_message(
            role="assistant", content=accumulated, session_buffer=self.session_buffer,
        )
        self.round_count += 1
        self._persist_emotion_state()

        need_facts, need_arc = self._post_process_needs()
        new_facts: list[str] = []
        arc_changes: list[str] = []

        if need_facts or need_arc:
            if need_facts:
                yield StepProgress(
                    step=2, total=3,
                    label="正在提取记忆…（2/3）",
                    partial=accumulated,
                )
            if need_arc:
                yield StepProgress(
                    step=3, total=3,
                    label="正在评估弧光…（3/3）",
                    partial=accumulated,
                )
            new_facts, arc_changes = self._post_process_turn(
                user_message, accumulated
            )

        self._maybe_auto_save()
        result = TurnResult(
            response=accumulated,
            new_facts=new_facts,
            arc_changes=arc_changes,
        )
        yield StepProgress(
            step=3, total=3, label="完成", partial=accumulated,
            done=True, result=result,
        )

    def iter_message(self, user_message: str):
        """兼容旧 API：(partial, done, TurnResult)。"""
        for progress in self.iter_turn(user_message):
            if progress.done:
                yield progress.partial, True, progress.result
            else:
                yield progress.partial, False, None

    def _print_welcome(self) -> None:
        mode = "流式" if self.stream else "非流式"
        unified = "合并" if self.use_unified_analyzer else "分离"
        print("=" * 50)
        print(f"  角色扮演引擎 — {self.soul.name}（{self.soul.role}）")
        print(f"  对话模型: {self.chat_ollama.model_name}")
        print(f"  分析模型: {self.analysis_ollama.model_name} | 输出: {mode}")
        print(f"  配置: {self.config_path} | 后处理: {unified}")
        print(f"  会话: {self.logger.session_id}")
        print(
            f"  情绪: P={self.emotion.pad.pleasure:.1f} "
            f"A={self.emotion.pad.arousal:.1f} "
            f"D={self.emotion.pad.dominance:.1f} "
            f"({self.emotion.stage})"
        )
        print(f"  弧光: {self.soul.arc_stage} | 目标: {self.soul.current_goal}")
        print("=" * 50)
        print(
            f"记忆: 每 {self.fact_extract_interval} 轮 | "
            f"弧光: 每 {self.arc_update_interval} 轮\n"
            "输入消息开始对话，/exit 退出，/status 查看状态，/stream 切换流式\n"
        )

    def _handle_command(self, user_input: str) -> bool:
        cmd = user_input.strip().lower()

        if cmd == "/exit":
            return False
        if cmd == "/status":
            for key, val in self.get_status().items():
                print(f"  {key}: {val}")
            print()
            return True
        if cmd == "/save":
            self._save_all_state()
            self.logger.save_session(self.log_session_template)
            print()
            return True
        if cmd == "/stream":
            self.stream = not self.stream
            print(f"\n[系统] 流式输出已{'开启' if self.stream else '关闭'}\n")
            return True

        return True

    def _print_turn_meta(self, result: TurnResult) -> None:
        if result.new_facts:
            print(f"[记忆] 新增 {len(result.new_facts)} 条长期记忆")
            for fact in result.new_facts:
                print(f"  [新记忆] {fact}")
        for change in result.arc_changes:
            print(f"  [弧光] {change}")

    def chat_loop(self) -> None:
        self._print_welcome()

        while True:
            try:
                user_input = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n[系统] 检测到中断，正在保存并退出...")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                if user_input.strip().lower() == "/exit":
                    print("\n[系统] 再见。")
                    break
                if not self._handle_command(user_input):
                    break
                continue

            if self.stream:
                print()
                print(f"{self.soul.name}: ", end="", flush=True)
                result = None
                last_len = 0
                for partial, done, turn in self.iter_message(user_input):
                    if not done:
                        sys.stdout.write(partial[last_len:])
                        sys.stdout.flush()
                        last_len = len(partial)
                    else:
                        if len(partial) > last_len:
                            sys.stdout.write(partial[last_len:])
                        result = turn
                print()
                if result:
                    self._print_turn_meta(result)
            else:
                print(f"\n{self.soul.name} 正在思考...\n")
                result = self.process_message(user_input, stream=False)
                print(f"{self.soul.name}: {result.response}")
                self._print_turn_meta(result)
            print()

        self.shutdown()

    def shutdown(self) -> None:
        self._save_all_state()
        self.logger.save_session(self.log_session_template)
        print("[系统] 状态已保存，会话结束。")


_engine_cache: dict[int, HarnessEngine] = {}


def _stress_config_overrides() -> dict | None:
    """压测模式：仅跑对话模型，避免 CPU 上双模型加载与后处理超时。"""
    if os.environ.get("HARNESS_STRESS_MODE", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return None
    cfg = load_config("config.json", create_if_missing=False, validate=False)
    chat_model = get_section(cfg, "ollama").get("chat_model", "qwen2.5:7b")
    return {
        "unified_analyzer": {"enabled": False},
        "embeddings": {"enabled": False},
        "engine": {
            "fact_extract_interval": 9999,
            "arc_update_interval": 9999,
            "stream": False,
            "hot_reload": False,
        },
        "ollama": {
            "analysis_model": chat_model,
            "num_predict": 128,
        },
    }


def _apply_stress_mode_to_engine(engine: HarnessEngine) -> None:
    """对已缓存引擎应用压测覆盖（热重载会读 config.json，需同步实例字段）。"""
    overrides = _stress_config_overrides()
    if not overrides:
        return
    from harness_config import _deep_merge

    _deep_merge(engine.config, overrides)
    engine.use_unified_analyzer = False
    engine.use_vector_memory = False
    engine.embed_client = None
    engine.raw_memory.set_embedder(None)
    engine.stream = False
    engine.hot_reload = False
    engine.fact_extract_interval = 9999
    engine.arc_update_interval = 9999
    ollama_cfg = get_section(engine.config, "ollama")
    chat_model = ollama_cfg.get("chat_model", "qwen2.5:7b")
    engine.analysis_ollama.model_name = chat_model
    engine.ollama_num_predict = int(ollama_cfg.get("num_predict", 128))


def _user_data_root(user_id: int) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "users", str(user_id))


def _get_engine_for_user(user_id: int) -> HarnessEngine:
    if user_id not in _engine_cache:
        root = _user_data_root(user_id)
        os.makedirs(root, exist_ok=True)
        stress_kw = _stress_config_overrides() or {}
        _engine_cache[user_id] = HarnessEngine(
            config_path="config.json",
            user_id=user_id,
            user_data_root=root,
            **stress_kw,
        )
    else:
        _apply_stress_mode_to_engine(_engine_cache[user_id])
    return _engine_cache[user_id]


def generate_response(user_id: int, character_id: int, user_input: str) -> str:
    """
    供 REST API 调用的对话生成入口（不依赖 Web/Gradio 上下文）。

    v0.3 重构：本函数已变为薄包装，统一委托给 orchestrator.orchestrate_turn()。
    保留本签名是为了向后兼容（已存在的 CLI / 测试 / 旧调用方无需改动）。
    新代码请直接调 orchestrator.orchestrate_turn() 拿 TurnResult。
    """
    from orchestrator import orchestrate_turn

    result = orchestrate_turn(user_id, character_id, user_input)
    return result.response


def generate_response_stream(
    user_id: int,
    character_id: int,
    user_input: str,
    cancel_event=None,
):
    """
    流式生成入口：yield token 文本，结束时评分并 yield 完整结果元数据。

    v0.3 重构：本函数已变为薄包装，统一委托给
    orchestrator.orchestrate_turn_stream()。

    Yields:
        ("token", str) | ("done", TurnResult) | ("cancelled", TurnResult) | ("error", str)
    """
    from orchestrator import orchestrate_turn_stream

    yield from orchestrate_turn_stream(
        user_id,
        character_id,
        user_input,
        cancel_event=cancel_event,
    )


def _generate_response_core(user_id: int, character_id: int, user_input: str) -> str:
    """v0.3 已废弃：保留向后兼容的内部实现引用。

    原逻辑已迁至 orchestrator.orchestrate_turn()，新代码请直接调
    orchestrator.orchestrate_turn()。
    """
    from orchestrator import orchestrate_turn

    result = orchestrate_turn(user_id, character_id, user_input)
    return result.response


def init_database(db_path: str | None = None) -> None:
    """初始化 SQLite 表结构（不依赖 Flask 应用上下文）。"""
    from database import init_sqlite_schema

    path = db_path or os.path.join(os.path.dirname(__file__), "harness.db")
    init_sqlite_schema(path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI 角色扮演引擎")
    parser.add_argument(
        "-c", "--config", default="config.json", help="配置文件路径"
    )
    args = parser.parse_args()
    HarnessEngine(config_path=args.config).chat_loop()
