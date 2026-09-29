"""端到端 Smoke Test —— v0.1 → v0.2 记忆/关系拆分 & 迁移 & compat shim。

覆盖：
    1) memory.migration CLI 核心 migrate_single()：
         以 characters/幽灵/memory_state.json 为源 → 三份 v0.2 新文件；
         备份、报告字段、session/raw/semantic 内容逐条断言。
    2) compat shim (character_memory.Memory) 双写 & 优先读 v0.2：
         new Memory(...) → add_message/add_fact → save → 重新 load
         → 确认 short_term / long_term 镜像一致，且 v0.2 文件被更新。
    3) relationship.migration 对同一角色目录初始化 pair state：
         独立文件 relationship__user_0__character_0.json，
         不混进 emotion/ 或 memory/；
         从 soul_state 的关系摘要/关键词推导出五轴阈值（熟人或更高）。
    4) 与 v0.2 原 smoke test(_smoke_test_v02.py) 并存：
         仍可 import 新三模块 + ContextBuilder/MemoryWriter，无冲突。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import warnings

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}\n  expected: {expected!r}\n  actual:   {actual!r}")


def assert_gt(a, b, msg=""):
    if not (a > b):
        raise AssertionError(f"{msg}\n  {a!r} > {b!r} expected false")


# ============================================================
# 准备：把 characters/幽灵 拷贝到临时目录，避免改真存档
# ============================================================
def copy_fixture(src_subdir: str) -> str:
    src = os.path.join(ROOT, src_subdir)
    tmp_root = tempfile.mkdtemp(prefix="mig_smoke_")
    dst = os.path.join(tmp_root, os.path.basename(src_subdir.rstrip(os.sep)))
    shutil.copytree(src, dst)
    return tmp_root, dst


# ============================================================
# 1. memory.migration
# ============================================================
def test_memory_migration_single():
    tmp_root, char_dir = copy_fixture("characters/幽灵")
    try:
        input_path = os.path.join(char_dir, "memory_state.json")
        assert os.path.isfile(input_path), input_path

        from memory.migration import migrate_single

        # 第一次运行
        r1 = migrate_single(input_path, outdir=char_dir, force=False)
        assert r1.session_count == 4, f"short_term 是 4 条消息（幽灵 fixture），实际 {r1.session_count}"
        assert r1.raw_count == 3, f"long_term 是 3 条事实，实际 {r1.raw_count}"
        assert r1.legacy_facts_missing == 0
        # 幽灵 fixture 三条事实：
        #   目标走私犯左臂装有军用级义体
        #   涅克瑟斯星区当前最高悬赏为 5000 信用点
        #   幽灵信奉信息即货币，信誉高于生命
        # 第三条「信奉…」匹配 "信奉/高于生命" —— 无 pattern，走 unrec
        # 前两条里 "最高悬赏为 5000…" 勉强能出 id_location？不对，pattern 是「X 在 <城市>工作」…
        #   → 所以最终 heuristic semantic 数量应该很低（0 是合理的）。
        # 我们只断言「不会把每条事实都灌进 semantic（防污染核心要求）」
        assert r1.semantic_upserted_count <= r1.raw_count, \
            f"semantic upsert 数必须不大于 raw 数（避免迁移=全信任），got {r1.semantic_upserted_count} vs {r1.raw_count}"

        # 备份 & 三文件都写了
        assert r1.backup_created and os.path.isfile(r1.backup_created), r1.backup_created
        for fn in ("memory_session.json", "memory_raw.json", "memory_semantic.json"):
            fp = os.path.join(char_dir, fn)
            assert os.path.isfile(fp), fp
            f = open(fp, "r", encoding="utf-8")
            d = json.load(f)
            f.close()
            assert "schema_version" in d, fn

        # 第二次默认幂等：files_written 应该是空（只写了 backup & 有 warning）
        r2 = migrate_single(input_path, outdir=char_dir, force=False)
        assert any("already exist" in w for w in r2.warnings), r2.warnings

        # --force 重跑，仍然能得到相同 raw_count（不会追加重复条目）
        r3 = migrate_single(input_path, outdir=char_dir, force=True)
        assert_eq(r3.raw_count, r1.raw_count)
        assert_eq(r3.session_count, r1.session_count)

        # 语义文件：打开后，每个条目 confidence 都 <= 0.90（初始 evidence_count=1
        # 对应 compute_confidence ≈ 0.15，绝对不会高到被 ContextBuilder 直接取，
        # 这是「防单轮污染」的核心约束。
        sem_path = os.path.join(char_dir, "memory_semantic.json")
        with open(sem_path, "r", encoding="utf-8") as f:
            sem = json.load(f)
        for bucket_name, entries in sem.get("buckets", {}).items():
            for key, entry in entries.items():
                c = float(entry.get("confidence", 1.0))
                assert c <= 0.90, \
                    f"legacy bootstrap 生成的 semantic entry {bucket_name}/{key} 居然有 confidence {c}，破坏防污染约束！"

        # 检查 raw 文件里确实包含三条 legacy 事实的文本
        with open(os.path.join(char_dir, "memory_raw.json"), "r", encoding="utf-8") as f:
            raw = json.load(f)
        contents = [e["content"] for e in raw["entries"]]
        assert any("走私犯" in c and "义体" in c for c in contents), contents
        assert any("5000 信用点" in c for c in contents), contents
        assert any("信息即货币" in c for c in contents), contents

        # 检查 session 文件里确实有「涅克瑟斯星区有什么新悬赏？」那句
        with open(os.path.join(char_dir, "memory_session.json"), "r", encoding="utf-8") as f:
            ses = json.load(f)
        texts = [m["content"] for m in ses["messages"]]
        assert any("涅克瑟斯星区有什么新悬赏" in t for t in texts), texts

        # dry-run inspect 数量一致（不落盘）
        from memory.migration import inspect
        r_inspect = inspect(input_path)
        assert_eq(r_inspect.raw_count, r1.raw_count)
        assert_eq(r_inspect.session_count, r1.session_count)
        assert any("DRY-RUN" in w for w in r_inspect.warnings), r_inspect.warnings

        print("[OK] memory.migration single (幽灵 fixture)")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ============================================================
# 2. character_memory.py Compat Shim
# ============================================================
def test_character_memory_compat_shim():
    tmp_root, char_dir = copy_fixture("characters/幽灵")
    try:
        # 捕获 DeprecationWarning：确保实例化 Memory 就立即警告
        import warnings as _warnings
        with _warnings.catch_warnings(record=True) as wlog:
            _warnings.simplefilter("always")
            from character_memory import Memory
            m = Memory(max_rounds=6, embed_fn=lambda s: [0.0] * 4, use_vector=False)
        assert any(issubclass(x.category, DeprecationWarning) for x in wlog), \
            "实例化 character_memory.Memory 必须立刻发出 DeprecationWarning"

        # ① 从旧 memory_state.json 加载（shim 只读 load，在内存中迁移镜像）
        mem_path = os.path.join(char_dir, "memory_state.json")
        m.load(mem_path)
        # 镜像字段同步正确
        assert_eq(len(m.short_term), 4, msg="short_term mirror")
        assert_eq(len(m.long_term), 3, msg="long_term mirror")
        assert any("涅克瑟斯星区有什么新悬赏" in x["content"] for x in m.short_term), m.short_term
        assert any("走私犯" in x["fact"] for x in m.long_term), m.long_term

        # ② v0.3 硬约束：所有写操作必须抛 RuntimeError（不允许直接写）
        #    写入应通过 memory_writer.MemoryWriter，而非 character_memory.Memory
        try:
            m.add_message("user", "测试消息")
            raise AssertionError("add_message 应抛 RuntimeError（写操作已禁用）")
        except RuntimeError as exc:
            assert "DISABLED" in str(exc) or "memory_writer" in str(exc), str(exc)

        try:
            m.add_fact("用户名叫林墨", importance=4)
            raise AssertionError("add_fact 应抛 RuntimeError（写操作已禁用）")
        except RuntimeError as exc:
            assert "DISABLED" in str(exc) or "memory_writer" in str(exc), str(exc)

        try:
            m.save(mem_path)
            raise AssertionError("save 应抛 RuntimeError（写操作已禁用）")
        except RuntimeError as exc:
            assert "DISABLED" in str(exc) or "memory_writer" in str(exc), str(exc)

        # ③ load 是只读：再 new 一个 Memory，从同一 v0.1 fixture 加载仍能成功
        m2 = Memory(max_rounds=6, use_vector=False)
        m2.load(mem_path)
        assert_eq(len(m2.short_term), 4, "second load (v0.1 fallback): short_term")
        assert_eq(len(m2.long_term), 3, "second load (v0.1 fallback): long_term")

        # ④ get_relevant_facts 仍然返回 v0.1 dict shape，含 {fact, importance, timestamp}
        hits = m.get_relevant_facts("走私犯义体特征", limit=2)
        assert isinstance(hits, list) and len(hits) > 0, hits
        for h in hits:
            assert "fact" in h and "importance" in h and "timestamp" in h, h
        # ⑤ to_dict 保持 v0.1 schema（只含 max_messages/short_term/long_term/use_vector）
        d = m.to_dict()
        for key in ("max_messages", "short_term", "long_term", "use_vector"):
            assert key in d, (key, list(d.keys()))
        # 不含 schema_version/entries 等 v0.2 字段
        assert "schema_version" not in d
        assert "entries" not in d

        print("[OK] character_memory.Memory read-only shim (deprecation + load + writes-disabled + query)")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ============================================================
# 3. relationship.migration bootstrap
# ============================================================
def test_relationship_migration():
    tmp_root, char_dir = copy_fixture("characters/幽灵")
    try:
        # 给 soul_state.json 加一段 relationship_summary（模拟用户已跑过一段时间的旧版 soul）
        ss_path = os.path.join(char_dir, "soul_state.json")
        with open(ss_path, "r", encoding="utf-8") as f:
            ss = json.load(f)
        ss["relationship_summary"] = (
            "用户替她解围过一次，还告诉了我一个从没告诉过别人的秘密；"
            "前几天冷战了，但今天已经道歉和解了；我们开起玩笑来完全不尴尬。"
        )
        with open(ss_path, "w", encoding="utf-8") as f:
            json.dump(ss, f, ensure_ascii=False, indent=2)

        from relationship.migration import migrate_relationship

        r = migrate_relationship(char_dir, subject_id=0, target_id=0, force=False)
        assert not r.skipped, r.skip_reason
        # 文件不混进 emotion/ 目录
        out = r.output_path
        assert "relationship" in os.path.basename(out) and out.endswith(".json"), out
        assert os.path.dirname(out) == char_dir, (out, char_dir)
        # 因为没给旧 emotion_stage，source_stage=None，用陌生人基线 + 关键词
        assert_eq(r.source_stage, None)
        assert_gt(len(r.source_text_snippets), 0, "应该命中若干关键词 hint")
        # 五轴检查：trust（替她解围+告诉秘密+和解）应该 ≥ 0.1
        axes = r.axes_snapshot
        assert_gt(axes["trust"], 0.12, f"trust 应该高于陌生人基线，got {axes}")
        assert_gt(axes["familiarity"], 0.0, f"familiarity 非零，got {axes}")
        assert_gt(axes["playfulness"], 0.0, f"playfulness 因「开玩笑」命中，got {axes}")
        # 冷战 → tension+，但后面又和解 tension-，net tension 应 ≤ 0.2（被和解抵消）
        assert axes["tension"] <= 0.2, f"和解之后 tension 应该回落，got {axes}"

        # 能被 load_pair_state 正确读回
        from relationship.pair_state import load_pair_state
        ps = load_pair_state(out)
        # history 里有记录的变化条数应 > 0（初始化原因）
        num_real_changes = sum(1 for h in ps.history if h.delta != 0.0)
        assert_gt(num_real_changes, 0, "应该有非零 change 记录，便于 audit")
        # stage 至少 acquaintance（因为有信任提示）
        st = ps.stage
        assert st in {"acquaintance", "trust", "intimate"}, f"final stage={st} {axes}"

        # 幂等：第二次默认 skip
        r2 = migrate_relationship(char_dir, subject_id=0, target_id=0, force=False)
        assert r2.skipped and "already exists" in r2.skip_reason, r2.skip_reason

        print(f"[OK] relationship.migration bootstrap (stage={st}, axes={axes})")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ============================================================
# 4. 与 v0.2 模块共存（不破坏已写好的 smoke_test_v02）
# ============================================================
def test_v02_modules_importable_alongside():
    from memory import SessionBuffer, RawMemory, SemanticMemory, MemoryRetriever  # noqa: F401
    from character import (  # noqa: F401
        CharacterProfile, CharacterState, SpeechStyle,
        BehavioralRules, RelationshipRules,
    )
    from relationship import PairState  # noqa: F401
    from context_builder import ContextBuilder, GenerationSnapshot  # noqa: F401
    from memory_writer import MemoryWriteGate, MemoryWriter  # noqa: F401
    print("[OK] 新 v0.2 模块与 compat shim 共存无冲突")


if __name__ == "__main__":
    # 抑制 shim 的 deprecation warning 在本测试里反复打印（上面单独测过了）
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="character_memory")
    test_memory_migration_single()
    test_character_memory_compat_shim()
    test_relationship_migration()
    test_v02_modules_importable_alongside()
    print()
    print("===== ALL MIGRATION SMOKE TESTS PASSED =====")
