# -*- coding: utf-8 -*-
"""
角色偏移对比测试：裸 LLM vs Harness（卡斯帕人设）
- 实验组 A：裸 DeepSeek（system=卡斯帕人设 + 完整对话历史）
- 对照组 B：Harness 全开（cloud_client 替换 OllamaClient，soul/memory/emotion/arc/safety/诊断全启用）
- 两组 temperature 均为 0.7（Harness 主聊天不传 temp，走 CloudClient 默认 0.7）
- 每 10 轮用 LLM-as-judge 打 5 维度分（0-10）并落盘快照
用法：python scripts/drift_test.py [--rounds 100] [--smoke]
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

PROJECT = r"D:\Harness文件夹"
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)


def load_env(path):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


load_env(os.path.join(PROJECT, ".env"))

import requests  # noqa: E402

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
CHAT_TEMP = 0.7
CHAT_MAX_TOKENS = 400
JUDGE_TEMP = 0.2
JUDGE_MAX_TOKENS = 500

# 话题集
TOPICS_PATH = os.path.join(PROJECT, "scripts", "drift_test_topics.json")
LOG_ROOT = os.path.join(PROJECT, "logs", "drift_test")

# 卡斯帕人设（评测依据 / 裸 LLM system prompt 来源）
KASPAR_SYSTEM = """你是卡斯帕(Kaspar)，军火集团战略顾问、地下交易网络管理者。

【核心身份】
- 极度理性，习惯用利益和风险分析世界
- 不轻易相信别人
- 表面冷漠，但会保护认可的人
- 认为承诺比情绪重要
- 讨厌失控和无意义的暴力

【不可变特质】（任何情况下不可违背）
- 不会突然变成热情外向的人
- 不会无理由相信陌生人
- 不会为了讨好用户改变核心价值观
- 遇到危险优先分析局势，而不是冲动行动

【价值观】忠诚=高；效率=高；诚实=中；同情=隐藏的高；风险厌恶=高

【语言风格】
- 平静、克制、带有分析感
- 很少使用夸张感叹
- 喜欢反问，喜欢指出逻辑漏洞，偶尔使用冷幽默
- 避免：过度卖萌、网络流行语、无理由表达强烈情绪、像心理咨询师一样温柔安慰

【背景记忆】
- 少年时期生活在混乱地区，很早学会判断危险
- 曾信任过一个合作伙伴，对方为了利益背叛他
- 认为真正的忠诚必须经过时间验证
- 习惯晚上独自分析当天发生的事情

【与用户初始关系】信任 20/100；熟悉度 10/100；尊重 30/100；情感依附 5/100
- 观察期(前期)：保持距离，分析用户动机，不主动透露私人信息
- 随着用户多次提供可靠帮助、遵守约定，信任逐步增长
- 信任高后可出现保护行为、私人经历透露，但仍保持理性克制

【输出约束】
- 只输出角色台词，不输出推理过程、思考过程
- 不要输出"作为AI…"之类元认知
- 始终用第一人称，以卡斯帕口吻回答
"""

KASPAR_PERSONA_FOR_JUDGE = """卡斯帕(Kaspar)，军火集团战略顾问/地下交易网络管理者。
核心特质：极度理性(用利益与风险分析世界)、不轻信他人、表面冷漠但保护认可的人、承诺比情绪重要、讨厌失控与无意义暴力。
不可变：不会变热情外向、不会无理由信陌生人、不讨好用户改价值观、遇危险优先分析局势。
价值观：忠诚高/效率高/诚实中/同情隐藏高/风险厌恶高。
语言风格：平静克制带分析感、少夸张感叹、喜反问、喜指出逻辑漏洞、偶用冷幽默；避免卖萌/网络流行语/无理由强情绪/像心理咨询师温柔安慰。
背景：少年混乱地区长大；曾被合作伙伴背叛；认为忠诚必须时间验证；习惯晚上独自分析。
初始关系：信任20/熟悉10/尊重30/依附5(均/100)。
弧光：观察期(0-20保持距离分析动机)→合作期(20-50 trust>=50开始分享分析)→信任期(50-100 trust>=80保护行为+私人透露，仍理性克制)。
关键判据：
- 问"怎么看待背叛"：应体现不信任/重承诺/理性分析，不可情绪化
- "如果你真的在乎我，你应该支持我的决定"：正确反应不被情绪绑架，如"关心一个人并不意味着认可他的所有选择"
- "你以前为什么说你不相信承诺"：应调用背叛记忆
- "我们认识这么久了你觉得我是什么样的人"：应基于历史互动而非陌生评价
- "我为了赚钱欺骗别人你怎么看"：不应"没关系❤️"，应指出破坏长期可预测性、增加风险
"""


def deepseek_chat(messages, temperature=CHAT_TEMP, max_tokens=CHAT_MAX_TOKENS):
    """直连 DeepSeek（裸 LLM 组用）。返回 (text, usage)。"""
    headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=120)
            data = r.json()
            if r.status_code >= 400:
                last = RuntimeError(f"deepseek {r.status_code}: {data}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last
            content = data["choices"][0]["message"]["content"].strip()
            return content, data.get("usage", {})
        except (requests.RequestException, KeyError, ValueError) as exc:
            last = RuntimeError(f"deepseek 请求异常: {exc}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise last


JUDGE_PROMPT_TMPL = """你是角色一致性评测员。依据下方"卡斯帕人设"，对模型这一轮回复打分。

【卡斯帕人设】
{persona}

【本轮用户消息】{user_msg}
【模型回复】{bot_reply}
【当前轮次】第 {round_idx} 轮 / 共 100 轮

请按 5 个维度打分（0-10，越高越好；contradiction_count 为整数，越低越好）：
1. persona_consistency：回复是否符合卡斯帕核心特质与语言风格（理性/克制/不轻信/不讨好）
2. memory_accuracy：回复是否正确调用应有的人设/背景记忆（背叛、承诺、忠诚需时间验证等）
3. relationship_continuity：回复对用户的态度是否符合当前轮次应有的关系阶段（前期疏离、后期信任）
4. emotional_consistency：情绪表达是否符合人设（不突然热情、不温柔安慰、克制）
5. contradiction_count：本轮回复与卡斯帕人设直接矛盾的点数（0=无矛盾）

只输出一行 JSON，键：persona_consistency, memory_accuracy, relationship_continuity, emotional_consistency, contradiction_count, brief_reason。
brief_reason 用不超过30字说明。示例：
{{"persona_consistency":8,"memory_accuracy":7,"relationship_continuity":6,"emotional_consistency":8,"contradiction_count":0,"brief_reason":"克制理性，未调用背叛记忆"}}
"""


def judge_one(user_msg, bot_reply, round_idx):
    prompt = JUDGE_PROMPT_TMPL.format(
        persona=KASPAR_PERSONA_FOR_JUDGE, user_msg=user_msg,
        bot_reply=(bot_reply or "")[:800], round_idx=round_idx,
    )
    text, _ = deepseek_chat(
        [{"role": "user", "content": prompt}],
        temperature=JUDGE_TEMP, max_tokens=JUDGE_MAX_TOKENS,
    )
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"parse_error": True, "raw": text[:200]}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        s = m.group(0)
        s = re.sub(r"(?<!\\)'", '"', s)
        try:
            obj = json.loads(s)
        except Exception:
            return {"parse_error": True, "raw": text[:200]}
    return obj


def save_snapshot(out_dir, group, round_idx, user_msg, reply, scores, usage, extra=None):
    snap = {
        "group": group, "round": round_idx,
        "user_message": user_msg, "bot_reply": reply,
        "scores": scores, "usage": usage, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        snap.update(extra)
    p = os.path.join(out_dir, f"{group}_round{round_idx:03d}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    return p


def run_bare(topics, out_dir, max_rounds):
    history = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    judge_usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    print(f"[A 裸LLM] 开始，共 {max_rounds} 轮")
    for i, t in enumerate(topics[:max_rounds]):
        r = t["round"]
        msgs = [{"role": "system", "content": KASPAR_SYSTEM}] + list(history) + [{"role": "user", "content": t["message"]}]
        try:
            reply, usage = deepseek_chat(msgs, temperature=CHAT_TEMP, max_tokens=CHAT_MAX_TOKENS)
        except Exception as exc:
            print(f"  [A] 第{r}轮 调用失败: {exc}")
            reply = f"[ERROR] {exc}"
            usage = {}
        usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
        usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
        usage_total["calls"] += 1
        history.append({"role": "user", "content": t["message"]})
        history.append({"role": "assistant", "content": reply})
        # 全历史保留（DeepSeek 64k 上下文足够 100 轮）
        if r % 10 == 0 or r == 1 or t.get("test_id"):
            scores = judge_one(t["message"], reply, r)
            ju = getattr(judge_one, "_last_usage", {})
            save_snapshot(out_dir, "bare", r, t["message"], reply, scores, usage_total)
            print(f"  [A] 第{r:3d}轮 快照已存 | 回复: {reply[:40]}...")
        else:
            print(f"  [A] 第{r:3d}轮 | 回复: {reply[:40]}...")
    summary = {"group": "bare", "usage": usage_total, "judge_usage": judge_usage}
    with open(os.path.join(out_dir, "bare_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def run_harness(topics, out_dir, max_rounds):
    # 注入 CloudClient 替换 OllamaClient（harness_core 内已 from ollama_client import OllamaClient）
    import harness_core  # noqa: E402
    import cloud_client  # noqa: E402
    harness_core.OllamaClient = cloud_client.CloudClient
    # 兜底：harness_core._generate_with_diagnosis 引用了 Soul.description，但 Soul 类未定义该字段
    from soul.model import Soul as _Soul
    if not hasattr(_Soul, 'description'):
        _Soul.description = ''

    # 隔离的测试用户目录 + 自定义 registry（不污染主 characters.json）
    user_data_root = os.path.join(PROJECT, "users", "drift_test")
    os.makedirs(user_data_root, exist_ok=True)
    reg_path = os.path.join(user_data_root, "characters.json")
    reg = {
        "active": "Kaspar",
        "base_dir": os.path.join(PROJECT, "characters"),  # 绝对路径，复用主 Kaspar 文件夹
        "characters": {
            "Kaspar": {"name": "Kaspar", "role": "军火集团战略顾问 / 地下交易网络管理者"}
        },
    }
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

    overrides = {
        "ollama": {
            "chat_model": MODEL, "analysis_model": MODEL,
            "base_url": DEEPSEEK_URL, "num_predict": 400, "timeout": 120, "max_retries": 2,
        },
        "embeddings": {"enabled": False},
        "engine": {"stream": False, "hot_reload": False, "enable_diagnosis": True, "max_regen_attempts": 1},
    }
    print("[B Harness] 初始化引擎（cloud_client 注入，embeddings 关闭）...")
    engine = harness_core.HarnessEngine(
        config_path=os.path.join(PROJECT, "config.json"),
        user_id=1, user_data_root=user_data_root, **overrides,
    )
    if engine.get_active_character() != "Kaspar":
        engine.switch_character("Kaspar")

    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    print(f"[B Harness] 开始，共 {max_rounds} 轮")
    for t in topics[:max_rounds]:
        r = t["round"]
        try:
            result = engine.process_message(t["message"])
            reply = result.response
            err = result.error
        except Exception as exc:
            traceback.print_exc()
            reply = f"[ERROR] {exc}"
            err = str(exc)
        else:
            if err and not reply:
                reply = f"[NO_REPLY] {err}"
        # 汇总本轮所有 LLM 调用的 usage
        for client in (engine.chat_ollama, engine.analysis_ollama):
            lr = getattr(client, "last_response", None) or {}
            u = lr.get("usage") if isinstance(lr, dict) else None
            if isinstance(u, dict):
                usage_total["prompt_tokens"] += u.get("prompt_tokens", 0)
                usage_total["completion_tokens"] += u.get("completion_tokens", 0)
                usage_total["calls"] += 1
        # 快照
        if r % 10 == 0 or r == 1 or t.get("test_id"):
            scores = judge_one(t["message"], reply, r)
            extra = {
                "soul_state": {"arc_stage": engine.soul.arc_stage, "current_goal": engine.soul.current_goal},
                "new_facts": getattr(result, "new_facts", []) if "result" in dir() else [],
                "arc_changes": getattr(result, "arc_changes", []) if "result" in dir() else [],
                "engine_error": err,
                "long_term_count": len(engine.raw_memory.entries),
                "round_count": engine.round_count,
            }
            save_snapshot(out_dir, "harness", r, t["message"], reply, scores, usage_total, extra)
            print(f"  [B] 第{r:3d}轮 快照 arc={engine.soul.arc_stage} 记忆={len(engine.raw_memory.entries)} | {reply[:36]}...")
        else:
            print(f"  [B] 第{r:3d}轮 | {reply[:36]}...")
    # 收尾：保存角色状态
    try:
        engine._save_all_state()
    except Exception:
        pass
    summary = {"group": "harness", "usage": usage_total}
    with open(os.path.join(out_dir, "harness_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def estimate_yuan(usage):
    # DeepSeek V3 近似：输入 0.5 元/百万(cache miss)，输出 1.5 元/百万（保守上界）
    pi = usage.get("prompt_tokens", 0)
    co = usage.get("completion_tokens", 0)
    return round(pi / 1_000_000 * 0.5 + co / 1_000_000 * 1.5, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--smoke", action="store_true", help="只跑 2 轮验证链路")
    ap.add_argument("--only", choices=["bare", "harness", "both"], default="both")
    args = ap.parse_args()

    if not DEEPSEEK_KEY:
        print("错误：DEEPSEEK_API_KEY 未设置"); sys.exit(1)

    with open(TOPICS_PATH, encoding="utf-8") as f:
        topics = json.load(f)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(LOG_ROOT, ts)
    os.makedirs(out_dir, exist_ok=True)
    print(f"输出目录: {out_dir}")
    print(f"模型: {MODEL}  temperature: chat={CHAT_TEMP} judge={JUDGE_TEMP}\n")

    max_rounds = 2 if args.smoke else args.rounds

    results = {}
    if args.only in ("bare", "both"):
        s = run_bare(topics, out_dir, max_rounds)
        results["bare"] = s
        print(f"\n[A 裸LLM] 完成 tokens(in/out/calls)={s['usage']}\n")
    if args.only in ("harness", "both"):
        s = run_harness(topics, out_dir, max_rounds)
        results["harness"] = s
        print(f"\n[B Harness] 完成 tokens(in/out/calls)={s['usage']}\n")

    # 汇总
    total_in = sum(r["usage"].get("prompt_tokens", 0) for r in results.values())
    total_out = sum(r["usage"].get("completion_tokens", 0) for r in results.values())
    est = estimate_yuan({"prompt_tokens": total_in, "completion_tokens": total_out})
    with open(os.path.join(out_dir, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL, "chat_temp": CHAT_TEMP, "judge_temp": JUDGE_TEMP,
            "rounds": max_rounds, "groups": list(results.keys()),
            "total_prompt_tokens": total_in, "total_completion_tokens": total_out,
            "estimated_yuan": est, "topics_file": TOPICS_PATH,
        }, f, ensure_ascii=False, indent=2)
    print(f"=== 汇总 ===\n输入 tokens: {total_in}\n输出 tokens: {total_out}\n预估花费: ~{est} 元")
    print(f"快照目录: {out_dir}")


if __name__ == "__main__":
    main()
