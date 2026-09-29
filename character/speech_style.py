"""Speech Style —— 说话风格参数。

与 Character Profile 解耦：Profile 管"是谁"，Speech Style 管"怎么说"。
第一版主要从 v0.1 Soul 的 catchphrases / vocabulary 迁移；后续可以扩展：
    - formality 正式度（0=市井 / 1=中立 / 2=正式）
    - terseness 简洁度（0=长篇 / 1=适中 / 2=短句）
    - emotional_modulation 情感表达克制度（0=克制 / 1=适中 / 2=外放）
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SpeechStyle:
    catchphrases: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)
    formality: int = 1        # 0 随意 / 1 中 / 2 正式
    terseness: int = 1        # 0 啰嗦 / 1 中 / 2 简短
    emotional_modulation: int = 0  # 0 克制 / 1 中 / 2 外放
    # 常见语气词：如 ["嗯", "……", "呵"]
    interjections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SpeechStyle":
        data = data or {}
        return cls(
            catchphrases=list(data.get("catchphrases") or []),
            vocabulary=list(data.get("vocabulary") or []),
            formality=int(data.get("formality", 1)),
            terseness=int(data.get("terseness", 1)),
            emotional_modulation=int(data.get("emotional_modulation", 0)),
            interjections=list(data.get("interjections") or []),
        )

    # ---------- v0.1 Soul 兼容构造 ----------
    @classmethod
    def from_soul_fields(
        cls,
        catchphrases: list[str] | None,
        vocabulary: list[str] | None,
    ) -> "SpeechStyle":
        return cls(
            catchphrases=list(catchphrases or []),
            vocabulary=list(vocabulary or []),
        )

    def render_prompt_section(self) -> str:
        """生成给 LLM 的「说话风格」段落。"""
        lines: list[str] = []
        if self.catchphrases:
            lines.append("口头禅（可随机穿插，不必每句出现）：")
            for cp in self.catchphrases:
                lines.append(f"- {cp}")
        if self.vocabulary:
            lines.append(f"常用词汇：{'、'.join(self.vocabulary)}")
        formality_labels = {0: "口语化、随意", 1: "中性、自然", 2: "正式、礼貌"}
        terseness_labels = {0: "表达充分、可适度展开", 1: "长度适中", 2: "简洁、点到为止"}
        modulation_labels = {0: "情感表达克制、不直接", 1: "情感表达适中", 2: "情感表达外放、直白"}
        lines.append(
            f"说话风格：{formality_labels.get(self.formality, '中性')} / "
            f"{terseness_labels.get(self.terseness, '适中')} / "
            f"{modulation_labels.get(self.emotional_modulation, '克制')}"
        )
        return "\n".join(lines)
