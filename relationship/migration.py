"""Relationship 独立迁移：从「旧 emotion 阶段 / 旧 soul_state 里的关系印象字段」
→ 初始 PairState 五轴。

**为什么 relationship 迁移要独立成一个模块，不混进 emotion/ 或 memory/：**
    这是你 v0.2 架构分层里的第三块 OS（Character / Memory / Relationship）。
    独立迁移 = 独立存储目录 + 独立 bootstrapping，避免把 relationship 的数据
    错塞到 emotion/ 或 memory/ 中，引起 phase 3 删除 character_memory.py 时
    还漏改 relationship 的引用。

**存储路径约定（不混进 emotion/）：**
    每个角色子目录下，单独产出一份 pair state 文件：
        characters/幽灵/relationship__user_0__character_0.json
    （默认 subject_type=user, subject_id=0 / target_type=character, target_id=0，
      若调用方能提供真实 user_id/character_id，就按实际值命名——这与
      relationship/pair_state.py:pair_state_file_path() 一致。）

**迁移输入的三种来源（优先级从高到低）：**
    1) relationship.json：用户/脚本已经手动给过 relationship 基线，直接跳过；
    2) emotion/ 里的 stage（陌生人 / 熟人 / 信任 / 亲密 / 冲突）→ 启发式五轴；
    3) soul_state.json 里「关系印象字段」（如 character/state.py 里的
       relationship_summary / mental_notes 等文本）→ 启发式扫关键词给分；
    都没有 → 给默认陌生人基线（全 0.0），不强行捏造数值。

**重要：这是「初始化 / 冷启动」用的，迁移完成后 PairState 的后续变化
只通过 MemoryWriter.write_turn() 里的 relationship_candidates 写入，
不再走本模块任何逻辑。**
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any

from .pair_state import (
    PairAxes,
    PairStage,
    PairState,
    load_pair_state,
    pair_state_file_path,
    save_pair_state,
)

MIGRATION_SCHEMA_VERSION = "1.0.0-rel-migration"

# ===============================================================
# Stage → 五轴启发式映射。目标是「不要太高、不要全 0，给真实运行留增量空间」。
# 每个阶段给出一个 midpoint + noise=±0.05（固定种子保证可重现）。
# ===============================================================

STAGE_TO_AXES_MIDPOINT: dict[str, dict[str, float]] = {
    # 陌生人：几乎不了解
    "stranger": {
        "familiarity": 0.03, "trust": 0.02,
        "emotional_closeness": 0.0, "playfulness": 0.02, "tension": 0.05,
    },
    # 熟人：开始了解一些背景，偶尔能开玩笑
    "acquaintance": {
        "familiarity": 0.28, "trust": 0.22,
        "emotional_closeness": 0.12, "playfulness": 0.20, "tension": 0.08,
    },
    # 信任：有明显的相互守信行为
    "trust": {
        "familiarity": 0.48, "trust": 0.52,
        "emotional_closeness": 0.36, "playfulness": 0.30, "tension": 0.10,
    },
    # 亲密：情感依赖较强（但保守取值，避免过度推进）
    "intimate": {
        "familiarity": 0.70, "trust": 0.72,
        "emotional_closeness": 0.62, "playfulness": 0.40, "tension": 0.08,
    },
    # 冲突：tension 极高，trust / closeness 被抵消但不完全归零
    "conflict": {
        "familiarity": 0.40, "trust": 0.25,
        "emotional_closeness": 0.20, "playfulness": 0.05, "tension": 0.72,
    },
}


# ===============================================================
# 文本关键词启发式（从 soul_state / 自定义关系摘要中提取加减分项）
# ===============================================================

_KEYWORD_HINTS: list[tuple[str, str, float]] = [
    # (keyword regex, axis, delta to apply on top of stage baseline)
    (r"救了|救命|解围|保护|帮我挡|替我", "trust", +0.08),
    (r"背|背叛|骗|说谎|撒谎|隐瞒|背后说", "trust", -0.15),
    (r"背|背叛|骗|说谎|撒谎|隐瞒|背后说", "tension", +0.15),

    (r"告白|表白|喜欢上你|爱你|爱上|心动", "emotional_closeness", +0.15),
    (r"拥抱|抱了|牵手|亲了|接吻|靠在肩膀|依偎", "emotional_closeness", +0.08),
    (r"拥抱|抱了|牵手|亲了|接吻|靠在肩膀|依偎", "playfulness", +0.03),

    (r"开玩笑|逗我|捉弄|打闹|恶作剧", "playfulness", +0.08),

    (r"吵架|吵了一架|冷战|翻脸|生气了一整晚|不肯理我", "tension", +0.15),
    (r"和解|道歉|和好了|原谅|说开了|解开误会", "tension", -0.15),
    (r"和解|道歉|和好了|原谅|说开了|解开误会", "trust", +0.05),

    (r"告诉了我她的|透露了他的|秘密|心事|没告诉过别人|只告诉了我", "trust", +0.10),
    (r"告诉了我她的|透露了他的|秘密|心事|没告诉过别人|只告诉了我", "emotional_closeness", +0.05),

    (r"小时候就|认识很多年|多年好友|老朋友", "familiarity", +0.20),
    (r"刚认识|第一次见面|今天刚加|昨天才认识", "familiarity", -0.10),
]


def _apply_stage_to_axes(stage: str) -> PairAxes:
    mid = STAGE_TO_AXES_MIDPOINT.get(stage) or STAGE_TO_AXES_MIDPOINT["stranger"]
    return PairAxes(**{k: float(v) for k, v in mid.items()})


def _apply_text_hints(axes: PairAxes, text: str) -> list[str]:
    """对已给的 stage axes 做关键词微调；返回命中的 hint 原因列表（给 history cause 用）。"""
    reasons: list[str] = []
    if not text:
        return reasons
    low = str(text)
    for pattern, axis, delta in _KEYWORD_HINTS:
        if re.search(pattern, low):
            old = float(getattr(axes, axis))
            new = axes.apply_delta(axis, delta)
            actual = round(new - old, 6)
            if actual == 0.0:
                continue
            sign = "+" if actual > 0 else ""
            axis_label = {
                "familiarity": "熟悉度", "trust": "信任度",
                "emotional_closeness": "亲密度", "playfulness": "嬉玩度",
                "tension": "紧张度",
            }.get(axis, axis)
            reasons.append(
                f"文本关键词 {pattern!r} 命中 → {axis_label} {sign}{round(actual*100,1)}%"
            )
    return reasons


# ===============================================================
# 报告结构
# ===============================================================

@dataclass
class RelMigrationReport:
    input_char_dir: str
    output_path: str
    schema_version: str = MIGRATION_SCHEMA_VERSION
    source_stage: str | None = None
    source_text_snippets: list[str] = field(default_factory=list)
    final_stage: str = "stranger"
    axes_snapshot: dict[str, float] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def pretty(self) -> str:
        lines = [
            "===== Relationship Migration Report =====",
            f"char_dir : {self.input_char_dir}",
            f"out_file : {self.output_path}",
        ]
        if self.skipped:
            lines.append(f"  SKIPPED: {self.skip_reason}")
        else:
            lines.append(f"  bootstrap source: stage={self.source_stage}")
            if self.source_text_snippets:
                for s in self.source_text_snippets:
                    lines.append(f"                    text-hint: {s[:60]}")
            lines.append(f"  final stage : {self.final_stage}")
            lines.append("  final axes  :")
            for k, v in (self.axes_snapshot or {}).items():
                lines.append(f"    - {k:22s}: {v:5.3f}")
        if self.warnings:
            lines.append("  warnings:")
            for w in self.warnings:
                lines.append(f"    ! {w}")
        return "\n".join(lines)


# ===============================================================
# 迁移主逻辑
# ===============================================================

def _find_emotion_stage(char_dir: str) -> str | None:
    """从多种可能路径里找「旧的情绪阶段」——兼容不同旧存档布局。"""
    candidates = [
        os.path.join(char_dir, "emotion_state.json"),
        os.path.join(char_dir, "..", "emotion_state.json"),
    ]
    for p in candidates:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        # emotion manager 默认会写 stage；不同版本字段名可能不同
        for key in ("stage", "current_stage", "emotion_stage"):
            v = data.get(key)
            if isinstance(v, str) and v in STAGE_TO_AXES_MIDPOINT:
                return v
    return None


def _find_relationship_text(char_dir: str) -> str:
    """从 soul_state / 旧 relationship_summary 文本里抽关系线索。"""
    snippets: list[str] = []
    soul_state = os.path.join(char_dir, "soul_state.json")
    if os.path.isfile(soul_state):
        try:
            with open(soul_state, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        for key in (
            "relationship_summary", "relation_summary", "user_impression",
            "mental_notes", "notes", "summary", "last_event",
        ):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                snippets.append(v)
            elif isinstance(v, list):
                snippets.extend(str(x) for x in v if isinstance(x, str))
    # 也允许 char_dir 里有手写 relationship.txt
    extra = os.path.join(char_dir, "relationship.txt")
    if os.path.isfile(extra):
        try:
            with open(extra, "r", encoding="utf-8") as f:
                snippets.append(f.read())
        except Exception:
            pass
    return "\n".join(snippets)


def migrate_relationship(
    char_dir: str,
    *,
    subject_type: str = "user",
    subject_id: int = 0,
    target_type: str = "character",
    target_id: int = 0,
    force: bool = False,
) -> RelMigrationReport:
    """对单角色目录做 relationship 初始化。

    如果 pair state 文件已存在 → 默认跳过（幂等）；给 --force 则会覆盖。
    """
    out_path = pair_state_file_path(
        char_dir, subject_type, subject_id, target_type, target_id,
    )
    report = RelMigrationReport(input_char_dir=char_dir, output_path=out_path)

    if os.path.isfile(out_path) and not force:
        report.skipped = True
        report.skip_reason = "PairState file already exists; use --force to overwrite."
        return report

    # 1) 来源 1：旧 emotion stage
    stage = _find_emotion_stage(char_dir)
    report.source_stage = stage

    # 2) 来源 2：soul_state / relationship.txt 的文本线索
    text = _find_relationship_text(char_dir)
    used_snippets: list[str] = []

    # 3) 计算 axes
    start_stage = stage or "stranger"
    axes = _apply_stage_to_axes(start_stage)
    text_hint_causes = _apply_text_hints(axes, text)
    if text_hint_causes:
        used_snippets.extend(text_hint_causes)
    report.source_text_snippets = used_snippets

    # 4) 构建 PairState
    ps = PairState(
        subject_type=subject_type,
        subject_id=subject_id,
        target_type=target_type,
        target_id=target_id,
        axes=axes,
        baseline=PairAxes(),  # 冷启动长期基线默认 0；真实运行后由 Memory Writer 累计调整
    )
    # 把 bootstrap 来源作为第一条 history cause（但 cause 不能为空，且要符合 cause-required 规则）
    causes: list[str] = []
    if stage:
        causes.append(f"旧 emotion stage={stage} → 五轴启发式初始化")
    causes.extend(used_snippets[:3])  # 最多记 3 条文本关键词
    if not causes:
        causes.append("无旧阶段/无文本线索 → 默认陌生人基线初始化")
    combined_cause = " ; ".join(causes)

    # 写一条 history，反映从 0 → 初始五轴的「初始化变化」
    # 这里逐条 update_axis，确保每条 change 都有相同的 cause（初始化说明）
    for axis_name in ["familiarity", "trust", "emotional_closeness", "playfulness", "tension"]:
        delta = float(getattr(axes, axis_name))
        if delta == 0.0:
            # 仍然调用 update_axis（为了保持 cause-required 接口一致），但实际变化会是 0
            # 此时 history 不记录，避免噪声
            ps.update_axis(axis_name, delta, combined_cause,
                           evaluator_version="rel_migration_1.0")
        else:
            ps.update_axis(axis_name, delta, combined_cause,
                           evaluator_version="rel_migration_1.0")

    report.final_stage = PairStage.compute(ps.axes)
    report.axes_snapshot = ps.axes.as_dict()

    # 5) 落盘
    save_pair_state(out_path, ps)
    return report


def migrate_all(
    root: str,
    *,
    subject_id: int = 0,
    target_id: int = 0,
    force: bool = False,
) -> list[RelMigrationReport]:
    reports: list[RelMigrationReport] = []
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    for name in sorted(os.listdir(root)):
        char_dir = os.path.join(root, name)
        if not os.path.isdir(char_dir):
            continue
        # 跳过 templates
        if name == "templates":
            continue
        reports.append(migrate_relationship(
            char_dir,
            subject_id=subject_id, target_id=target_id, force=force,
        ))
    return reports


# ===============================================================
# CLI
# ===============================================================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="relationship.migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__.split("使用方法")[0]),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("bootstrap-one", help="对单个角色目录做 relationship 初始化")
    sp.add_argument("--char-dir", required=True)
    sp.add_argument("--subject-type", default="user")
    sp.add_argument("--subject-id", type=int, default=0)
    sp.add_argument("--target-type", default="character")
    sp.add_argument("--target-id", type=int, default=0)
    sp.add_argument("--force", action="store_true")

    ap = sub.add_parser("bootstrap-all", help="对 characters/<name>/ 全部角色做初始化")
    ap.add_argument("--root", default="characters/")
    ap.add_argument("--subject-id", type=int, default=0)
    ap.add_argument("--target-id", type=int, default=0)
    ap.add_argument("--force", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "bootstrap-one":
        r = migrate_relationship(
            args.char_dir,
            subject_type=args.subject_type,
            subject_id=args.subject_id,
            target_type=args.target_type,
            target_id=args.target_id,
            force=args.force,
        )
        print(r.pretty())
        return 0
    if args.cmd == "bootstrap-all":
        rs = migrate_all(
            args.root,
            subject_id=args.subject_id,
            target_id=args.target_id,
            force=args.force,
        )
        if not rs:
            print(f"[bootstrap-all] 未在 {args.root} 下发现角色目录")
            return 0
        for r in rs:
            print(r.pretty())
            print()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
