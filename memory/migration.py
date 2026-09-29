"""v0.1 character_memory.Memory → v0.2 三层（Session/Raw/Semantic）迁移工具。

使用方法（CLI）：

    # 把单个 memory_state.json 迁移成三份 v0.2 文件
    python -m memory.migration migrate \\
        --input   characters/幽灵/memory_state.json \\
        --outdir  characters/幽灵/

    # 扫描整个 characters/ 目录，批量迁移（已有 v0.2 文件的角色跳过，
    # 除非给 --force）
    python -m memory.migration migrate-all \\
        --root  characters/  [--force]

    # 做 dry-run：只打印报告，不落盘
    python -m memory.migration inspect \\
        --input characters/幽灵/memory_state.json

迁移策略（严格对应你在架构图里给的拆分去向）：
    v0.1 `short_term[]`  + max_messages    → SessionBuffer
    v0.1 `long_term[]`   事实/事件部分    → RawMemory（全部 category=fact，
                                             重要性 1:1 复制，memory_id 带
                                             "raw_legacy_" 前缀方便追溯）
    v0.1 `long_term[]`   可提炼画像的部分 → SemanticMemory（跑一次启发式提炼，
                                             初始 confidence 0.15，evidence_count=1，
                                             source_tag="legacy_bootstrap"，避免
                                             迁移后 Context Builder 直接当高置信
                                             度事实用。这个流程与 memory_writer 的
                                             真实写入路径一致。）

迁移后同一目录产出：
    <outdir>/memory_session.json
    <outdir>/memory_raw.json
    <outdir>/memory_semantic.json
    <outdir>/memory_legacy_backup.<timestamp>.json   # 原文件备份
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 同层模块 import（注意：文件在 memory/migration.py，因此 from .xxx import）
from .session_buffer import SessionBuffer
from .raw_memory import RawMemory
from .semantic_memory import SemanticMemory

MIGRATION_SCHEMA_VERSION = "2.0.0-migration"
DEFAULT_SESSION_FN = "memory_session.json"
DEFAULT_RAW_FN = "memory_raw.json"
DEFAULT_SEMANTIC_FN = "memory_semantic.json"
LEGACY_FN = "memory_state.json"


# =====================================================================
# 1) 启发式：从 v0.1 long_term fact 文本 → 提炼 1+ semantic candidate(s)
#    原则：**保守**。无法识别的，不进 semantic，只留在 raw。
#    这样迁移出来的 Semantic Memory 不会比真实写入路径更激进。
# =====================================================================

_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # 喜欢 / 爱 / 偏好
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色|[^，。！？,]{1,10})?"
                r"(?P<verb>喜欢|爱|最喜|偏要|偏好)了?"
                r"(?P<obj>[^，。！？,；:：]{1,20})"),
     "preferences", "pref_likes_{obj}"),
    # 不喜欢 / 讨厌 / 反感 / 嫌弃
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色|[^，。！？,]{1,10})?"
                r"(?P<verb>不喜欢|讨厌|反感|嫌弃|厌恶|怕|害怕|畏惧|受不了)"
                r"(?P<obj>[^，。！？,；:：]{1,20})"),
     "preferences", "pref_dislikes_{obj}"),
    # 身份 / 职业 / 居住地 / 家乡
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色)是"
                r"(?P<obj>[^，。！？,；:：]{1,15})"),
     "identity", "id_role_{obj}"),
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色)在"
                r"(?P<obj>上海|北京|广州|深圳|杭州|成都|重庆|南京|苏州|武汉|"
                r"西安|天津|东京|纽约|伦敦|巴黎|首尔|[^，。！？,；:：]{2,15}工作)"),
     "identity", "id_location_{obj}"),
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色)?来自"
                r"(?P<obj>[^，。！？,；:：]{1,15})"),
     "identity", "id_from_{obj}"),
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色)叫"
                r"(?P<obj>[^，。！？,；:：]{1,12})"),
     "identity", "id_name_{obj}"),
    (re.compile(r"(?P<subj>我|用户|主角|玩家|你|角色)老家"
                r"(?P<obj>[^，。！？,；:：]{1,12})"),
     "identity", "id_hometown_{obj}"),
]


def _slug_suffix(s: str) -> str:
    """把中文/空格 文本转成短 slug（截断到 15 字）。"""
    import re as _re
    s = s.strip()
    s = _re.sub(r"\s+", "_", s)
    s = _re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    return s[:15]


def _heuristic_semantic_candidates_from_fact(
    fact: str,
    *,
    raw_memory_ref: str | None = None,
) -> list[dict[str, Any]]:
    """保守地把一条 legacy fact 转成一组 semantic candidate。

    完全镜像 memory_writer.MemoryWriteGate._heuristic_semantic_from_raw() 的
    规则子集（去掉情绪事件那一条，因为那需要更明确的情绪分析输入）。
    """
    if not isinstance(fact, str):
        return []
    text = fact.strip()
    if not text or len(text) > 200:
        return []

    cands: list[dict[str, Any]] = []
    for pattern, bucket, key_tpl in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            groups = m.groupdict()
            obj_s = _slug_suffix(groups.get("obj") or "x")
            subj_s = _slug_suffix(groups.get("subj") or "u") or "u"
            key = key_tpl.format(obj=obj_s, subj=subj_s)
            cands.append({
                "bucket": bucket,
                "key": key,
                "value": True,
                "raw_memory_ref": raw_memory_ref,
                "source_tag": "legacy_bootstrap",
                "_text_preview": text,
            })
        except Exception:
            continue
    return cands


# =====================================================================
# 2) 迁移结果结构化报告（可用于 dry-run）
# =====================================================================

@dataclass
class MigrationReport:
    input_path: str
    output_dir: str
    schema_version: str = MIGRATION_SCHEMA_VERSION
    session_count: int = 0
    raw_count: int = 0
    semantic_candidates_count: int = 0
    semantic_upserted_count: int = 0
    legacy_facts_missing: int = 0          # long_term 里 fact 字段是空/坏的
    semantic_skipped_unrecognized: int = 0 # 没匹配到任何 pattern
    backup_created: str | None = None
    files_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_path": self.input_path,
            "output_dir": self.output_dir,
            "session_count": self.session_count,
            "raw_count": self.raw_count,
            "semantic_candidates_count": self.semantic_candidates_count,
            "semantic_upserted_count": self.semantic_upserted_count,
            "legacy_facts_missing": self.legacy_facts_missing,
            "semantic_skipped_unrecognized": self.semantic_skipped_unrecognized,
            "backup_created": self.backup_created,
            "files_written": list(self.files_written),
            "warnings": list(self.warnings),
        }

    def pretty(self) -> str:
        d = self.to_dict()
        lines = [
            "===== Migration Report =====",
            f"input : {d['input_path']}",
            f"outdir: {d['output_dir']}",
            f"  session messages (v0.1 short_term → SessionBuffer) : {d['session_count']}",
            f"  raw entries      (v0.1 long_term  → RawMemory)     : {d['raw_count']}",
            f"    └ broken fact fields skipped                      : {d['legacy_facts_missing']}",
            f"  semantic candidates generated (heuristic only)     : {d['semantic_candidates_count']}",
            f"    └ semantic entries upserted into SemanticMemory   : {d['semantic_upserted_count']}",
            f"    └ not recognized / left in raw only               : {d['semantic_skipped_unrecognized']}",
        ]
        if d["backup_created"]:
            lines.append(f"  backup : {d['backup_created']}")
        if d["files_written"]:
            lines.append("  written:")
            for p in d["files_written"]:
                lines.append(f"    - {p}")
        if d["warnings"]:
            lines.append("  warnings:")
            for w in d["warnings"]:
                lines.append(f"    ! {w}")
        return "\n".join(lines)


# =====================================================================
# 3) 核心迁移函数
# =====================================================================

def load_legacy_dict(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"legacy memory file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def migrate_memory_dict(
    legacy: dict[str, Any],
    *,
    output_dir: str,
    input_path: str,
    backup_legacy: bool = True,
    force: bool = False,
) -> MigrationReport:
    """把一个 v0.1 Memory.to_dict() 字典拆成三份 v0.2 存储，落盘。

    返回 MigrationReport（可用于 dry-run / 打印 / CI 断言）。
    """
    report = MigrationReport(input_path=input_path, output_dir=output_dir)

    # --- 输出文件路径 ---
    session_path = os.path.join(output_dir, DEFAULT_SESSION_FN)
    raw_path = os.path.join(output_dir, DEFAULT_RAW_FN)
    semantic_path = os.path.join(output_dir, DEFAULT_SEMANTIC_FN)

    # 幂等：三个 v0.2 文件都齐全则默认跳过（除非 --force）
    if all(os.path.isfile(p) for p in (session_path, raw_path, semantic_path)) and not force:
        report.warnings.append(
            "v0.2 files already exist; skipping. Use --force to overwrite."
        )
        return report

    os.makedirs(output_dir, exist_ok=True)

    # --- Step A. Session Buffer（1:1 映射） ---
    session = SessionBuffer.from_legacy_memory_dict(legacy)
    report.session_count = len(session.messages)

    # --- Step B. Raw Memory（1:1 映射，除了坏条目） ---
    raw = RawMemory.from_legacy_memory_dict(legacy)
    report.raw_count = len(raw.entries)
    # 从输入里看哪些 long_term 因为 fact 字段非法被跳过了
    total_long_term = len(legacy.get("long_term") or [])
    report.legacy_facts_missing = total_long_term - report.raw_count

    # --- Step C. Semantic Memory（保守启发式） ---
    semantic = SemanticMemory()
    raw_entries_by_ref: dict[str, str] = {}
    for e in raw.entries:
        raw_entries_by_ref[e.memory_id] = e.content

    cands_total = 0
    upserted_ids: set[tuple[str, str]] = set()
    for e in raw.entries:
        text = e.content
        if not text:
            continue
        cands = _heuristic_semantic_candidates_from_fact(
            text, raw_memory_ref=e.memory_id,
        )
        cands_total += len(cands)
        if not cands:
            report.semantic_skipped_unrecognized += 1
            continue
        for c in cands:
            bucket = c.get("bucket") or "preferences"
            key = c.get("key")
            if not key:
                continue
            _entry, action = semantic.upsert_candidate(
                bucket=bucket,
                key=str(key),
                value=c.get("value", True),
                raw_memory_ref=c.get("raw_memory_ref"),
            )
            if action in {"created", "confirmed"}:
                upserted_ids.add((bucket, str(key)))
    report.semantic_candidates_count = cands_total
    report.semantic_upserted_count = len(upserted_ids)

    # --- Step D. 备份原 legacy 文件 ---
    if backup_legacy and os.path.isfile(input_path):
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup_name = f"memory_legacy_backup.{ts}.json"
        backup_path = os.path.join(output_dir, backup_name)
        try:
            shutil.copy2(input_path, backup_path)
            report.backup_created = backup_path
        except OSError as exc:
            report.warnings.append(f"backup failed: {exc}")

    # --- Step E. 落盘 v0.2 三份 ---
    session.save(session_path)
    report.files_written.append(session_path)
    raw.save(raw_path)
    report.files_written.append(raw_path)
    semantic.save(semantic_path)
    report.files_written.append(semantic_path)

    return report


def migrate_single(
    input_path: str,
    *,
    outdir: str | None = None,
    force: bool = False,
) -> MigrationReport:
    legacy = load_legacy_dict(input_path)
    output_dir = outdir or os.path.dirname(os.path.abspath(input_path))
    return migrate_memory_dict(
        legacy,
        output_dir=output_dir,
        input_path=input_path,
        backup_legacy=True,
        force=force,
    )


def migrate_all_characters(
    root: str,
    *,
    force: bool = False,
) -> list[MigrationReport]:
    """扫描 <root>/<角色名>/memory_state.json 批量迁移。"""
    reports: list[MigrationReport] = []
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    for name in sorted(os.listdir(root)):
        char_dir = os.path.join(root, name)
        if not os.path.isdir(char_dir):
            continue
        legacy_path = os.path.join(char_dir, LEGACY_FN)
        if not os.path.isfile(legacy_path):
            continue
        try:
            reports.append(migrate_single(legacy_path, outdir=char_dir, force=force))
        except Exception as exc:
            r = MigrationReport(input_path=legacy_path, output_dir=char_dir)
            r.warnings.append(f"migration failed: {exc!r}")
            reports.append(r)
    return reports


def inspect(input_path: str) -> MigrationReport:
    """Dry-run：只跑结构/数量检查，不落盘。"""
    legacy = load_legacy_dict(input_path)
    output_dir = os.path.dirname(os.path.abspath(input_path))

    # 用临时对象跑一遍，不 save
    session = SessionBuffer.from_legacy_memory_dict(legacy)
    raw = RawMemory.from_legacy_memory_dict(legacy)
    semantic = SemanticMemory()

    cands_total = 0
    upserted = 0
    missing = len(legacy.get("long_term") or []) - len(raw.entries)
    unrec = 0
    for e in raw.entries:
        cands = _heuristic_semantic_candidates_from_fact(e.content, raw_memory_ref=e.memory_id)
        cands_total += len(cands)
        if not cands:
            unrec += 1
            continue
        for c in cands:
            _entry, action = semantic.upsert_candidate(
                bucket=c.get("bucket") or "preferences",
                key=str(c.get("key")),
                value=c.get("value", True),
                raw_memory_ref=c.get("raw_memory_ref"),
            )
            if action in {"created", "confirmed"}:
                upserted += 1

    r = MigrationReport(input_path=input_path, output_dir=output_dir)
    r.session_count = len(session.messages)
    r.raw_count = len(raw.entries)
    r.legacy_facts_missing = missing
    r.semantic_candidates_count = cands_total
    r.semantic_upserted_count = upserted
    r.semantic_skipped_unrecognized = unrec
    r.warnings.append("DRY-RUN: no files written")
    return r


# =====================================================================
# 4) CLI
# =====================================================================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="memory.migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__.split("迁移策略（严格")[0]),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("migrate", help="迁移单个 memory_state.json")
    sp.add_argument("--input", required=True)
    sp.add_argument("--outdir", default=None, help="默认与 --input 同目录")
    sp.add_argument("--force", action="store_true")

    ap = sub.add_parser("migrate-all", help="扫描 characters/ 目录批量迁移")
    ap.add_argument("--root", default="characters/")
    ap.add_argument("--force", action="store_true")

    ip = sub.add_parser("inspect", help="Dry-run 结构检查，不落盘")
    ip.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "migrate":
        r = migrate_single(args.input, outdir=args.outdir, force=args.force)
    elif args.cmd == "migrate-all":
        reports = migrate_all_characters(args.root, force=args.force)
        if not reports:
            print(f"[migrate-all] 没有在 {args.root} 下发现 {LEGACY_FN}")
            return 0
        for r in reports:
            print(r.pretty())
            print()
        return 0
    elif args.cmd == "inspect":
        r = inspect(args.input)
    else:
        parser.print_help()
        return 2

    print(r.pretty())
    return 0


if __name__ == "__main__":
    sys.exit(main())
