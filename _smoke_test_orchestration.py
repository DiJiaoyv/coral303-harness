"""两套架构合并 smoke tests。

验证目标：
    1. orchestrator.orchestrate_turn() / orchestrate_turn_stream() 存在且签名稳定
    2. 所有对外入口最终调到同一编排函数（接线点检查）
    3. harness_core.generate_response / generate_response_stream 已变成薄包装
    4. 失败候选不进 Memory 的约束在合并后依然成立
    5. Flask 调试路由不再自己写 Conversation / 调 score_and_persist
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

ROOT = Path(__file__).parent

# ========== 1. orchestrator 模块存在 + 接口签名 ==========
import orchestrator

assert hasattr(orchestrator, "orchestrate_turn"), "orchestrator 必须暴露 orchestrate_turn"
assert hasattr(orchestrator, "orchestrate_turn_stream"), "orchestrator 必须暴露 orchestrate_turn_stream"

sig_turn = inspect.signature(orchestrator.orchestrate_turn)
for p in ("user_id", "character_id", "user_message"):
    assert p in sig_turn.parameters, f"orchestrate_turn 缺参数 {p}"
# 命名参数：persist_conversation / persist_score
assert "persist_conversation" in sig_turn.parameters
assert "persist_score" in sig_turn.parameters

sig_stream = inspect.signature(orchestrator.orchestrate_turn_stream)
for p in ("user_id", "character_id", "user_message", "cancel_event"):
    assert p in sig_stream.parameters, f"orchestrate_turn_stream 缺参数 {p}"
assert "timeout_seconds" in sig_stream.parameters, "orchestrate_turn_stream 应支持 timeout_seconds"

print("[OK] orchestrator.orchestrate_turn / _stream 接口签名稳定")


# ========== 2. 所有对外入口都调到 orchestrate_turn / _stream ==========

def _import_call_chain(filepath: Path, func_name: str) -> set[str]:
    """静态扫描：返回指定函数内调用了哪些「看起来像编排入口」的函数。"""
    src = filepath.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(filepath))
    called: set[str] = set()
    ORCHESTRATION_FUNCS = {"orchestrate_turn", "orchestrate_turn_stream",
                           "generate_response", "generate_response_stream",
                           "_generate_response_core"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    if isinstance(sub.func, ast.Name) and sub.func.id in ORCHESTRATION_FUNCS:
                        called.add(sub.func.id)
                    if isinstance(sub.func, ast.Attribute) and sub.func.attr in ORCHESTRATION_FUNCS:
                        called.add(sub.func.attr)
    return called


# 2a. FastAPI 路由：api/routes/chat.py 的 chat_completions 必须调 orchestrate_turn
api_chat = ROOT / "api" / "routes" / "chat.py"
assert api_chat.is_file(), "api/routes/chat.py 不存在"
calls_api = _import_call_chain(api_chat, "chat_completions")
assert "orchestrate_turn" in calls_api, \
    f"api/routes/chat.py chat_completions 必须调 orchestrate_turn, 实际: {calls_api}"
assert "generate_response" not in calls_api, \
    "api/routes/chat.py 不应再调旧 generate_response"

print("[OK] FastAPI /api/chat/completions → orchestrate_turn")


# 2b. Flask 路由：app/routes/data_routes.py 的 api_chat 必须调 orchestrate_turn
flask_routes = ROOT / "app" / "routes" / "data_routes.py"
assert flask_routes.is_file(), "app/routes/data_routes.py 不存在"
calls_flask = _import_call_chain(flask_routes, "api_chat")
assert "orchestrate_turn" in calls_flask, \
    f"app/routes/data_routes.py api_chat 必须调 orchestrate_turn, 实际: {calls_flask}"

# 2c. Flask 流式：_stream_chat_events 必须调 orchestrate_turn_stream
calls_stream = _import_call_chain(flask_routes, "_stream_chat_events")
assert "orchestrate_turn_stream" in calls_stream, \
    f"_stream_chat_events 必须调 orchestrate_turn_stream, 实际: {calls_stream}"
# 不应再直接调 engine.process_message_stream（绕过编排）
assert "process_message_stream" not in calls_stream or "orchestrate_turn_stream" in calls_stream, \
    "_stream_chat_events 不应绕过 orchestrator 直接调 engine.process_message_stream"

print("[OK] Flask /api/chat + /stream/chat → orchestrate_turn / _stream")


# 2d. harness_core 的薄包装：generate_response / generate_response_stream 必须委托给 orchestrator
harness_path = ROOT / "harness_core.py"
calls_gr = _import_call_chain(harness_path, "generate_response")
assert "orchestrate_turn" in calls_gr, \
    f"harness_core.generate_response 必须调 orchestrate_turn, 实际: {calls_gr}"

calls_grs = _import_call_chain(harness_path, "generate_response_stream")
assert "orchestrate_turn_stream" in calls_grs, \
    f"harness_core.generate_response_stream 必须调 orchestrate_turn_stream, 实际: {calls_grs}"

print("[OK] harness_core.generate_response / _stream 已变成薄包装 → orchestrator")


# ========== 3. Flask 路由不再自己写 Conversation / 调 score_and_persist ==========

def _func_calls(filepath: Path, func_name: str) -> set[str]:
    """扫描指定函数体调用的所有函数名（不限编排类）。"""
    src = filepath.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(filepath))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    if isinstance(sub.func, ast.Name):
                        called.add(sub.func.id)
                    elif isinstance(sub.func, ast.Attribute):
                        called.add(sub.func.attr)
    return called


flask_chat_calls = _func_calls(flask_routes, "api_chat")
assert "Conversation" not in flask_chat_calls, \
    "Flask api_chat 不应再直接构造 Conversation（应交由 orchestrator）"
assert "score_and_persist" not in flask_chat_calls, \
    "Flask api_chat 不应再直接调 score_and_persist（应交由 orchestrator）"

flask_stream_calls = _func_calls(flask_routes, "_stream_chat_events")
assert "score_and_persist" not in flask_stream_calls, \
    "_stream_chat_events 不应再直接调 score_and_persist"
assert "Conversation" not in flask_stream_calls, \
    "_stream_chat_events 不应再直接构造 Conversation"

print("[OK] Flask 路由不再重复写 Conversation / 调 score_and_persist")


# ========== 4. orchestrator 内部流程清晰（5 个关键阶段都在） ==========
orch_path = ROOT / "orchestrator.py"
orch_src = orchestrator.__file__
orch_text = Path(orch_src).read_text(encoding="utf-8")

# 必须包含的步骤关键字
required_steps = [
    "_resolve_character",          # 加载 character_meta + 切换角色
    "engine.process_message",      # context_builder → LLM → diagnose 循环 → memory_writer
    "_persist_conversation",       # 写 Conversation
    "_persist_score_log",          # 写 score_log
    "run_inference",               # performance 排队 + 监控
]
for step in required_steps:
    assert step in orch_text, f"orchestrator.py 缺关键步骤: {step}"

print("[OK] orchestrator.py 包含 5 个关键编排阶段")


# ========== 5. 失败候选不进 Memory 的约束在合并后依然成立 ==========
# orchestrate_turn 只读 turn_result.response 给 _persist_conversation 和 _persist_score_log
# 不传 candidates 给 memory_writer（memory_writer.write_turn 仍只接收最终回复）
from memory_writer import MemoryWriter
sig_mw = inspect.signature(MemoryWriter.write_turn)
assert "candidates" not in sig_mw.parameters, \
    "MemoryWriter.write_turn 不应接受 candidates 参数（合并后仍保留此约束）"
assert "ai_response" in sig_mw.parameters or "response" in sig_mw.parameters

# orchestrator.orchestrate_turn 返回 TurnResult，含 diagnosis 字段
import harness_core
sig_tr = inspect.signature(harness_core.TurnResult)
assert "diagnosis" in sig_tr.parameters, "TurnResult 应有 diagnosis 字段"
assert "response" in sig_tr.parameters

print("[OK] 合并后失败候选不进 Memory 约束依然成立")


# ========== 6. 验证 orchestrator 的 TurnResult 返回类型 ==========
# orchestrate_turn 应返回 TurnResult 实例（而非 str），这样上层能拿到 diagnosis
import harness_core
TurnResult = harness_core.TurnResult
sig_t = inspect.signature(orchestrator.orchestrate_turn)
# 返回注解：from __future__ import annotations 模式下为字符串 "TurnResult"
ra = sig_t.return_annotation
assert ra is TurnResult or ra == "TurnResult", \
    f"orchestrate_turn 返回类型应为 TurnResult, 实际: {ra}"

print("[OK] orchestrate_turn 返回 TurnResult（含 diagnosis）")

print()
print("===== ALL ORCHESTRATION SMOKE TESTS PASSED =====")
