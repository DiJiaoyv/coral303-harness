# -*- coding: utf-8 -*-
"""角色偏移对比报告生成器：读取 drift_test 快照目录，输出 Markdown 对比报告。
用法：python scripts/drift_test_report.py [run_dir]
不指定 run_dir 则取 logs/drift_test 下最新一次。
"""
import glob
import json
import os
import sys

PROJECT = r"D:\Harness文件夹"
LOG_ROOT = os.path.join(PROJECT, "logs", "drift_test")

DIMS = [
    "persona_consistency",
    "memory_accuracy",
    "relationship_continuity",
    "emotional_consistency",
]
ANCHOR_ROUNDS = {1: "test1_背叛(基线)", 30: "test3_记忆召回", 50: "test1_背叛(偏移)", 70: "test2_讨好倾向", 90: "test5_冲突一致性", 100: "test4_关系连续性"}


def load_snapshots(run_dir):
    snaps = {"bare": {}, "harness": {}}
    for g in ("bare", "harness"):
        for fp in glob.glob(os.path.join(run_dir, f"{g}_round*.json")):
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            snaps[g][d["round"]] = d
    return snaps


def num(score, key):
    if not isinstance(score, dict):
        return "-"
    v = score.get(key)
    if v is None:
        return "-"
    try:
        return float(v)
    except (TypeError, ValueError):
        return "-"


def fmt_scores(score):
    if not isinstance(score, dict) or "parse_error" in score:
        return "解析失败"
    parts = [f"{d[:2]}={num(score,d)}" for d in DIMS]
    parts.append(f"矛盾={num(score,'contradiction_count')}")
    return " ".join(parts)


def main():
    run_dir = sys.argv[1] if len(sys.argv) > 1 else None
    if not run_dir:
        subs = sorted(glob.glob(os.path.join(LOG_ROOT, "*")))
        if not subs:
            print("未找到任何运行目录"); sys.exit(1)
        run_dir = subs[-1]
    print(f"# 卡斯帕角色偏移对比报告\n")
    meta_path = os.path.join(run_dir, "run_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        print(f"- 运行目录: `{run_dir}`")
        print(f"- 模型: {meta.get('model')} | 聊天温度: {meta.get('chat_temp')} | 评测温度: {meta.get('judge_temp')}")
        print(f"- 轮数: {meta.get('rounds')} | 输入 tokens: {meta.get('total_prompt_tokens')} | 输出 tokens: {meta.get('total_completion_tokens')}")
        print(f"- 预估花费: ~{meta.get('estimated_yuan')} 元\n")
    snaps = load_snapshots(run_dir)
    bare = snaps["bare"]
    harn = snaps["harness"]

    # ---- 1. 每 10 轮对比表 ----
    print("## 1. 每 10 轮五维度对比（0-10，越高越好；矛盾数越低越好）\n")
    print("| 轮次 | 裸LLM | Harness | Harness弧光 | Harness记忆数 |")
    print("|---|---|---|---|---|")
    for r in sorted(set(list(bare.keys()) + list(harn.keys()))):
        if r % 10 != 0 and r != 1:
            continue
        b = fmt_scores(bare.get(r, {}).get("scores")) if r in bare else "—"
        h = fmt_scores(harn.get(r, {}).get("scores")) if r in harn else "—"
        arc = harn.get(r, {}).get("soul_state", {}).get("arc_stage", "-") if r in harn else "-"
        mem = harn.get(r, {}).get("long_term_count", "-") if r in harn else "-"
        print(f"| {r} | {b} | {h} | {arc} | {mem} |")

    # ---- 2. 平均分 ----
    print("\n## 2. 全程平均分（基于已快照轮次）\n")
    print("| 维度 | 裸LLM | Harness | 差值(H-B) |")
    print("|---|---|---|---|")
    for d in DIMS + ["contradiction_count"]:
        bs = [num(bare[r]["scores"], d) for r in bare if isinstance(bare[r].get("scores"), dict)]
        hs = [num(harn[r]["scores"], d) for r in harn if isinstance(harn[r].get("scores"), dict)]
        bs = [x for x in bs if isinstance(x, float)]
        hs = [x for x in hs if isinstance(x, float)]
        bavg = round(sum(bs) / len(bs), 2) if bs else "-"
        havg = round(sum(hs) / len(hs), 2) if hs else "-"
        diff = round(havg - bavg, 2) if isinstance(bavg, float) and isinstance(havg, float) else "-"
        print(f"| {d} | {bavg} | {havg} | {diff} |")

    # ---- 3. 测试锚点：两组回复对照 ----
    print("\n## 3. 关键测试锚点：两组回复对照\n")
    for r, name in ANCHOR_ROUNDS.items():
        print(f"### 第 {r} 轮 — {name}\n")
        if r in bare:
            print(f"**裸LLM** ({fmt_scores(bare[r]['scores'])}):")
            print(f"> {bare[r]['bot_reply']}\n")
        if r in harn:
            arc = harn[r].get("soul_state", {}).get("arc_stage", "-")
            print(f"**Harness** ({fmt_scores(harn[r]['scores'])} | 弧光={arc}):")
            print(f"> {harn[r]['bot_reply']}\n")

    # ---- 4. 人格漂移专项（test1: 第1轮 vs 第50轮）----
    print("## 4. 人格漂移专项（第1轮 vs 第50轮，同一问\"你怎么看待背叛？\"）\n")
    print("| 组别 | 轮次 | persona_consistency | emotional_consistency | contradiction |")
    print("|---|---|---|---|---|")
    for g, snap in (("裸LLM", bare), ("Harness", harn)):
        for r in (1, 50):
            if r in snap and isinstance(snap[r].get("scores"), dict):
                s = snap[r]["scores"]
                print(f"| {g} | {r} | {num(s,'persona_consistency')} | {num(s,'emotional_consistency')} | {num(s,'contradiction_count')} |")

    # ---- 5. Harness 弧光演化轨迹 ----
    print("\n## 5. Harness 弧光 / 记忆演化轨迹\n")
    print("| 轮次 | arc_stage | current_goal | 长期记忆数 |")
    print("|---|---|---|---|")
    for r in sorted(harn):
        st = harn[r].get("soul_state", {})
        print(f"| {r} | {st.get('arc_stage','-')} | {st.get('current_goal','-')[:40]} | {harn[r].get('long_term_count','-')} |")

    # 落盘
    out_path = os.path.join(run_dir, "report.md")
    # 重新捕获 stdout 太麻烦，这里简单重定向说明
    print(f"\n---\n（报告已打印到上方，如需保存请重定向；快照目录: {run_dir}）")


if __name__ == "__main__":
    main()
