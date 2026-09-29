# ============================================================
# 触发式摘要伪代码（Pseudo-code）
# 说明：本文件为逻辑示意，不要求可直接运行
# ============================================================

# ---------- 全局变量 ----------
message_count = 0                          # 对话轮次计数器
MAX_ROUNDS_BEFORE_SUMMARY = 20             # 每 20 轮触发一次摘要
SUMMARY_FILE = "users/{user_id}/characters/{character_key}/memory_summary.txt"
RECENT_HISTORY_COUNT = 5                   # 拼入 Prompt 的最近对话轮数


# ---------- 核心流程 ----------
function on_new_message(user_input, character, history):
    """
    处理单轮用户输入：计数 → 可选摘要 → 组装 Prompt → 调用模型 → 更新历史。
    安全：摘要失败不中断对话；摘要路径按用户/角色隔离。
    """

    # 1. 计数器递增
    message_count += 1

    # 2. 判断是否触发摘要
    if message_count % MAX_ROUNDS_BEFORE_SUMMARY == 0:
        try:
            # 取最近 20 轮（刚满一个摘要窗口）
            recent_for_summary = get_last_n_rounds(history, MAX_ROUNDS_BEFORE_SUMMARY)

            # 调用 LLM 生成摘要（200 字以内；prompt 仅含对话内容，不含用户隐私字段）
            summary = call_llm_summary(recent_for_summary)

            if summary is not empty:
                # 追加写入角色专属摘要文件（数据隔离）
                append_to_file(SUMMARY_FILE, summary)

                # 裁剪历史：只去掉已总结部分，保留最近 5 轮，防止丢上下文
                trim_history(history, RECENT_HISTORY_COUNT)
            else:
                # 摘要为空：跳过本轮摘要，不影响对话
                log("摘要返回空，跳过写入")
        except Exception as e:
            # 超时 / API 失败：跳过摘要，继续正常对话
            log("摘要调用失败，跳过: " + e)

    # 3. 组装 Prompt
    worldview = load_worldview(character.world_id)   # 从 worlds/xxx.json 读取
    previous_summary = read_file(SUMMARY_FILE)       # 读取全部摘要；文件不存在则 ""
    recent_history = get_last_n_rounds(history, RECENT_HISTORY_COUNT)

    final_prompt = f"""
【角色设定】
{character.system_prompt}

【世界观规则】
{worldview}

【记忆摘要】
{previous_summary}

【最近对话】
{recent_history}

【用户输入】
{user_input}
"""

    # 4. 调用模型
    reply = call_model(final_prompt)

    # 5. 将本轮对话加入历史
    history.append({"user": user_input, "assistant": reply})

    return reply


# ---------- 辅助函数 ----------
function call_llm_summary(dialog_segments):
    """
    构造摘要 Prompt 并调用 LLM。
    约束：仅传入对话内容，不包含真实姓名等隐私字段。
    """
    summary_prompt = (
        "请用 200 字以内概括以下对话的关键信息（不要输出用户真实姓名等隐私）：\n"
        + format_dialog(dialog_segments)
    )
    return call_model(summary_prompt)


function get_last_n_rounds(history, n):
    """取历史中最后 n 轮对话。"""
    return history[-n:]


function trim_history(history, keep_n):
    """
    裁剪历史：只保留最近 keep_n 轮。
    已总结的更早轮次依赖 SUMMARY_FILE，不再占用短期上下文。
    """
    history = history[-keep_n:]
    return history


function append_to_file(filename, text):
    """
    以追加模式写入摘要文件。
    路径示例：users/{user_id}/characters/{character_key}/memory_summary.txt
    权限：仅当前用户可读写（OS 层设置）。
    """
    # write(filename, f"[{datetime.now()}]\n{text}\n---\n", mode="append")
    pass


function read_file(filename):
    """若文件不存在返回空字符串，否则返回全部内容。"""
    if not file_exists(filename):
        return ""
    return open(filename).read()


function load_worldview(world_id):
    """从 worlds/{world_id}.json 读取世界观规则文本。"""
    # return worlds[world_id].rules_text
    pass


# ---------- 安全边界（实现时必须遵守）----------
# 1. SUMMARY_FILE 放在 users/{user_id}/characters/{character_key}/ 下，与记忆文件同级，数据隔离。
# 2. 默认每 20 轮触发一次，避免过度消耗 API。
# 3. 摘要 Prompt 不含用户隐私（如真实姓名），仅使用对话内容。
# 4. 摘要文件设置合适权限（仅当前用户可读写）。
# 5. LLM 摘要失败（超时/空返回）时跳过本轮摘要，不中断对话。
# 6. trim_history 只裁剪已总结部分，保留最近 5 轮，防止丢失上下文。
