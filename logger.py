# logger.py - AI 角色对话执行轨迹记录
import json
import os
import random
import string
from datetime import datetime, timezone


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_session_id() -> str:
    """生成唯一会话 ID：时间戳 + 随机后缀。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"sess_{ts}_{suffix}"


class Logger:
    """记录 AI 角色对话的完整、不可篡改的执行轨迹。"""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or _generate_session_id()
        self._logs: list[dict] = []

    def _append(self, entry_type: str, data: dict) -> dict:
        """追加一条统一格式的日志条目。"""
        entry = {
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "type": entry_type,
            "data": data,
        }
        self._logs.append(entry)
        return entry

    def log_input(self, user_message: str) -> dict:
        """记录用户输入的原始文本。"""
        return self._append("user_input", {"message": user_message})

    def log_response(
        self,
        ai_message: str,
        prompt_used: str,
        api_response: dict,
    ) -> list[dict]:
        """记录 AI 回复及 Ollama API 调用的完整细节。"""
        response_entry = self._append(
            "ai_response",
            {"message": ai_message},
        )
        api_entry = self._append(
            "api_call",
            {
                "prompt": prompt_used,
                "request": api_response.get("request", {}),
                "response": api_response.get("response", api_response),
            },
        )
        return [response_entry, api_entry]

    def log_state_change(
        self,
        module: str,
        key: str,
        old_value,
        new_value,
    ) -> dict:
        """记录系统内部状态变化（如情绪分、记忆更新）。"""
        return self._append(
            "state_change",
            {
                "module": module,
                "key": key,
                "old_value": old_value,
                "new_value": new_value,
            },
        )

    # ------------------------------------------------------------------
    # v0.2 评估链路记录（候选→拒绝→重写→采纳）
    # ------------------------------------------------------------------
    def log_candidate(
        self,
        candidate: str,
        diagnosis: dict | None = None,
        *,
        attempt: int = 0,
        accepted: bool = False,
    ) -> dict:
        """记录一次 LLM 候选回复及其诊断结果。

        每个 candidate 都会被记入 session log，无论是否被采纳。
        Memory Writer 只读 accepted=True 的最终回复。
        """
        return self._append(
            "evaluation_candidate",
            {
                "candidate": candidate,
                "attempt": attempt,
                "accepted": accepted,
                "passed": diagnosis.get("passed") if diagnosis else None,
                "violations": diagnosis.get("violations") if diagnosis else None,
                "rewrite_instruction": diagnosis.get("rewrite_instruction") if diagnosis else None,
                "scores": diagnosis.get("scores") if diagnosis else None,
            },
        )

    def log_evaluation_link(
        self,
        *,
        user_message: str,
        candidates: list[dict],
        final_accepted_index: int,
        total_regen_count: int,
    ) -> dict:
        """记录完整「候选→拒绝→重写→采纳」链路摘要。

        Args:
            user_message: 用户原始输入
            candidates: [{"candidate": str, "passed": bool, "violations": [...], ...}, ...]
            final_accepted_index: 最终采纳的候选在 candidates 里的下标
            total_regen_count: 重生成总次数（0=首轮就通过）
        """
        return self._append(
            "evaluation_link",
            {
                "user_message": user_message,
                "candidates_count": len(candidates),
                "final_accepted_index": final_accepted_index,
                "total_regen_count": total_regen_count,
                "candidates": candidates,
            },
        )

    def log_error(self, error_message: str, detail: dict | None = None) -> dict:
        """记录运行时错误。"""
        data = {"message": error_message}
        if detail:
            data["detail"] = detail
        return self._append("error", data)

    # ------------------------------------------------------------------
    # v0.3 链路追踪（11.2 Observability）
    # ------------------------------------------------------------------
    def log_turn_step(
        self,
        turn_id: str,
        step_name: str,
        detail: dict | None = None,
        *,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> dict:
        """记录单步 turn step（context_built / llm_generated /
        harness_evaluated / regen_attempt / memory_written / turn_finalized）。

        与 log_candidate 等细粒度条目互补：log_turn_step 是粗粒度链路节点，
        便于一眼看出整轮 trace 的步骤序列；log_candidate 则是单个候选的明细。
        """
        return self._append(
            "turn_step",
            {
                "turn_id": turn_id,
                "step_name": step_name,
                "detail": detail or {},
                "start_ts": start_ts or _now_iso(),
                "end_ts": end_ts or _now_iso(),
            },
        )

    def log_turn_trace(self, trace) -> dict:
        """整轮 turn trace 落盘（接收 observability.TurnTrace 实例或其 dict 形式）。

        与单步 log_turn_step() 互补：trace 是整轮的「快照」，
        便于一次性查询某轮的全部步骤。
        """
        if hasattr(trace, "to_dict"):
            trace_data = trace.to_dict()
        else:
            trace_data = dict(trace)
        return self._append("turn_trace", trace_data)

    def get_logs(self) -> list[dict]:
        """返回当前会话的全部日志条目（副本）。"""
        return list(self._logs)

    def save_session(self, filepath_template: str = "logs/session_{session_id}.json") -> str:
        """将当前会话日志保存到文件，路径中的 {session_id} 会被替换。"""
        filepath = filepath_template.format(session_id=self.session_id)
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        payload = {
            "session_id": self.session_id,
            "log_count": len(self._logs),
            "logs": self._logs,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"[Logger] 会话日志已保存至 {filepath} ({len(self._logs)} 条)")
        return filepath

    def clear(self) -> None:
        """清空当前会话日志（session_id 保持不变）。"""
        self._logs.clear()
        print(f"[Logger] 会话 {self.session_id} 日志已清空")


# 快速测试：模拟一次简单对话循环
if __name__ == "__main__":
    logger = Logger()

    # 模拟用户输入
    logger.log_input("幽灵，接不接涅克瑟斯的走私犯悬赏？")

    # 模拟状态变化：情绪分更新、记忆写入
    logger.log_state_change("emotion", "score", 5.0, 4.5)
    logger.log_state_change("memory", "long_term", [], [{"fact": "用户询问走私犯悬赏", "importance": 3}])

    # 模拟 Ollama API 调用与 AI 回复
    assembled_prompt = (
        "你是幽灵，星际赏金猎人。\n"
        "用户: 幽灵，接不接涅克瑟斯的走私犯悬赏？\n"
        "助手:"
    )
    mock_api_response = {
        "request": {
            "model": "llama3",
            "messages": [{"role": "user", "content": assembled_prompt}],
            "stream": False,
        },
        "response": {
            "model": "llama3",
            "message": {"role": "assistant", "content": "钱收了，事办妥。把目标数据发来。"},
            "done": True,
        },
    }
    logger.log_response(
        ai_message="钱收了，事办妥。把目标数据发来。",
        prompt_used=assembled_prompt,
        api_response=mock_api_response,
    )

    # 保存并打印摘要
    saved_path = logger.save_session()
    print(f"\n会话 ID: {logger.session_id}")
    print(f"日志条数: {len(logger.get_logs())}")
    print("\n--- 日志条目类型 ---")
    for entry in logger.get_logs():
        print(f"  [{entry['type']}] {entry['timestamp']}")
