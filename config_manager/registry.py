"""配置注册表：可配置项元信息（键、类型、默认值、分组、校验、来源、模块）。"""
from __future__ import annotations

import os
from typing import Any

# 需重启后生效的 registry 键（其余默认可热重载）
_REQUIRE_RESTART_KEYS = frozenset({"WEB_PORT", "SECRET_KEY", "ADMIN_PASSWORD"})

PIN_MARKER = "[PIN]"

# source: config.json | performance.env | safety.env | .env
# module: harness | performance | safety | flask（flask/.env 多数需重启，仅暴露非敏感项）

REGISTRY: dict[str, dict[str, Any]] = {
    "general": {
        "label": "通用设置",
        "items": [
            {
                "key": "ENGINE_HOT_RELOAD",
                "path": "engine.hot_reload",
                "type": "bool",
                "default": True,
                "label": "引擎热重载",
                "source": "config.json",
                "module": "harness",
                "help": "开启后每轮对话自动重载 config.json",
            },
            {
                "key": "ENGINE_STREAM",
                "path": "engine.stream",
                "type": "bool",
                "default": True,
                "label": "默认流式输出",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "WEB_HOST",
                "path": "web.host",
                "type": "string",
                "default": "127.0.0.1",
                "label": "Web 监听地址",
                "source": "config.json",
                "module": "harness",
                "max_length": 128,
            },
            {
                "key": "WEB_PORT",
                "path": "web.port",
                "type": "int",
                "min": 1,
                "max": 65535,
                "default": 7860,
                "label": "Web 端口",
                "source": "config.json",
                "module": "harness",
                "help": "修改端口需重启服务后生效",
            },
        ],
    },
    "model": {
        "label": "模型参数",
        "items": [
            {
                "key": "CHAT_MODEL",
                "path": "ollama.chat_model",
                "type": "string",
                "default": "qwen2.5:7b",
                "label": "对话模型",
                "source": "config.json",
                "module": "harness",
                "max_length": 128,
                "depends_on": ["OLLAMA_BASE_URL", "OLLAMA_NUM_PREDICT"],
                "depends_hint": "修改模型后建议同步检查 Ollama 地址与最大生成 Token",
            },
            {
                "key": "ANALYSIS_MODEL",
                "path": "ollama.analysis_model",
                "type": "string",
                "default": "deepseek-r1:8b",
                "label": "分析模型",
                "source": "config.json",
                "module": "harness",
                "max_length": 128,
                "depends_on": ["OLLAMA_BASE_URL", "OLLAMA_NUM_PREDICT"],
                "depends_hint": "修改模型后建议同步检查 Ollama 地址与最大生成 Token",
            },
            {
                "key": "OLLAMA_BASE_URL",
                "path": "ollama.base_url",
                "type": "string",
                "default": "http://localhost:11434/api/generate",
                "label": "Ollama API 地址",
                "source": "config.json",
                "module": "harness",
                "max_length": 256,
            },
            {
                "key": "OLLAMA_TIMEOUT",
                "path": "ollama.timeout",
                "type": "int",
                "min": 5,
                "max": 600,
                "default": 300,
                "label": "Ollama 超时(秒)",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "OLLAMA_NUM_PREDICT",
                "path": "ollama.num_predict",
                "type": "int",
                "min": 64,
                "max": 8192,
                "default": 200,
                "label": "最大生成 Token",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "OLLAMA_MAX_RETRIES",
                "path": "ollama.max_retries",
                "type": "int",
                "min": 0,
                "max": 10,
                "default": 2,
                "label": "最大重试次数",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "MEMORY_EXTRACT_TEMPERATURE",
                "path": "memory_extractor.temperature",
                "type": "float",
                "min": 0.0,
                "max": 2.0,
                "step": 0.1,
                "default": 0.3,
                "label": "记忆提取温度",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "ARC_UPDATE_TEMPERATURE",
                "path": "arc_updater.temperature",
                "type": "float",
                "min": 0.0,
                "max": 2.0,
                "step": 0.1,
                "default": 0.2,
                "label": "弧光更新温度",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "UNIFIED_ANALYZER_TEMPERATURE",
                "path": "unified_analyzer.temperature",
                "type": "float",
                "min": 0.0,
                "max": 2.0,
                "step": 0.1,
                "default": 0.25,
                "label": "统一分析温度",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "UNIFIED_ANALYZER_ENABLED",
                "path": "unified_analyzer.enabled",
                "type": "bool",
                "default": True,
                "label": "启用统一分析器",
                "source": "config.json",
                "module": "harness",
            },
        ],
    },
    "memory": {
        "label": "记忆设置",
        "items": [
            {
                "key": "FACT_EXTRACT_INTERVAL",
                "path": "engine.fact_extract_interval",
                "type": "int",
                "min": 1,
                "max": 100,
                "default": 3,
                "label": "事实提取间隔(轮)",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "ARC_UPDATE_INTERVAL",
                "path": "engine.arc_update_interval",
                "type": "int",
                "min": 1,
                "max": 100,
                "default": 3,
                "label": "弧光更新间隔(轮)",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "AUTO_SAVE_INTERVAL",
                "path": "engine.auto_save_interval",
                "type": "int",
                "min": 1,
                "max": 100,
                "default": 5,
                "label": "自动保存间隔(轮)",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "MEMORY_MAX_ROUNDS",
                "path": "engine.memory_max_rounds",
                "type": "int",
                "min": 1,
                "max": 200,
                "default": 10,
                "label": "短期记忆最大轮数",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "RECENT_DIALOGUE_ROUNDS",
                "path": "engine.recent_dialogue_rounds",
                "type": "int",
                "min": 1,
                "max": 50,
                "default": 5,
                "label": "近期对话轮数",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "RELEVANT_FACTS_LIMIT",
                "path": "engine.relevant_facts_limit",
                "type": "int",
                "min": 1,
                "max": 50,
                "default": 3,
                "label": "相关事实条数上限",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "EMOTION_DEFAULT_SCORE",
                "path": "emotion.default_score",
                "type": "float",
                "min": 1.0,
                "max": 10.0,
                "step": 0.5,
                "default": 5.0,
                "label": "默认情绪分",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "EMBEDDINGS_ENABLED",
                "path": "embeddings.enabled",
                "type": "bool",
                "default": True,
                "label": "启用向量记忆",
                "source": "config.json",
                "module": "harness",
            },
            {
                "key": "EMBEDDINGS_MODEL",
                "path": "embeddings.model",
                "type": "string",
                "default": "nomic-embed-text",
                "label": "嵌入模型",
                "source": "config.json",
                "module": "harness",
                "max_length": 128,
            },
        ],
    },
    "performance": {
        "label": "性能设置",
        "items": [
            {
                "key": "GPU_ENABLED",
                "path": "GPU_ENABLED",
                "type": "bool",
                "default": True,
                "label": "启用 GPU 监控",
                "source": "performance.env",
                "module": "performance",
            },
            {
                "key": "GPU_DEVICE_INDEX",
                "path": "GPU_DEVICE_INDEX",
                "type": "int",
                "min": 0,
                "max": 8,
                "default": 0,
                "label": "GPU 设备序号",
                "source": "performance.env",
                "module": "performance",
            },
            {
                "key": "QUEUE_MAX_SIZE",
                "path": "QUEUE_MAX_SIZE",
                "type": "int",
                "min": 1,
                "max": 100,
                "default": 10,
                "label": "队列最大长度",
                "source": "performance.env",
                "module": "performance",
            },
            {
                "key": "TIMEOUT_SECONDS",
                "path": "TIMEOUT_SECONDS",
                "type": "float",
                "min": 5.0,
                "max": 300.0,
                "step": 1.0,
                "default": 30.0,
                "label": "推理超时(秒)",
                "source": "performance.env",
                "module": "performance",
            },
            {
                "key": "BUSY_MESSAGE",
                "path": "BUSY_MESSAGE",
                "type": "string",
                "default": "系统繁忙，请稍后重试",
                "label": "繁忙提示语",
                "source": "performance.env",
                "module": "performance",
                "max_length": 256,
            },
            {
                "key": "TIMEOUT_MESSAGE",
                "path": "TIMEOUT_MESSAGE",
                "type": "string",
                "default": "抱歉，我思考太久了，请再问一次",
                "label": "超时提示语",
                "source": "performance.env",
                "module": "performance",
                "max_length": 256,
            },
        ],
    },
    "safety": {
        "label": "安全设置",
        "items": [
            {
                "key": "WORD_LISTS_DIR",
                "path": "WORD_LISTS_DIR",
                "type": "string",
                "default": "safety/word_lists",
                "label": "敏感词目录",
                "source": "safety.env",
                "module": "safety",
                "max_length": 256,
                "depends_hint": "修改目录后请确认词库文件存在，并检查输入/输出拦截提示语是否仍适用",
            },
            {
                "key": "INPUT_BLOCKED_MESSAGE",
                "path": "INPUT_BLOCKED_MESSAGE",
                "type": "string",
                "default": "内容不合规，请重新输入",
                "label": "输入拦截提示",
                "source": "safety.env",
                "module": "safety",
                "max_length": 256,
            },
            {
                "key": "OUTPUT_BLOCKED_MESSAGE",
                "path": "OUTPUT_BLOCKED_MESSAGE",
                "type": "string",
                "default": "抱歉，我无法回答这个问题",
                "label": "输出拦截提示",
                "source": "safety.env",
                "module": "safety",
                "max_length": 256,
            },
            {
                "key": "UNICODE_NORMALIZE",
                "path": "UNICODE_NORMALIZE",
                "type": "bool",
                "default": True,
                "label": "Unicode 规范化",
                "source": "safety.env",
                "module": "safety",
            },
            {
                "key": "LOG_RETENTION_DAYS",
                "path": "LOG_RETENTION_DAYS",
                "type": "int",
                "min": 1,
                "max": 3650,
                "default": 90,
                "label": "安全日志保留天数",
                "source": "safety.env",
                "module": "safety",
            },
            {
                "key": "FAIL_OPEN",
                "path": "FAIL_OPEN",
                "type": "bool",
                "default": True,
                "label": "审核失败时放行",
                "source": "safety.env",
                "module": "safety",
            },
            {
                "key": "HOT_RELOAD_INTERVAL_SEC",
                "path": "HOT_RELOAD_INTERVAL_SEC",
                "type": "float",
                "min": 0.5,
                "max": 60.0,
                "step": 0.5,
                "default": 1.0,
                "label": "词库热重载间隔(秒)",
                "source": "safety.env",
                "module": "safety",
            },
        ],
    },
    "secrets": {
        "label": "敏感信息",
        "items": [
            {
                "key": "SECRET_KEY",
                "path": "SECRET_KEY",
                "type": "string",
                "default": "",
                "label": "Flask SECRET_KEY",
                "source": ".env",
                "module": "flask",
                "sensitive": True,
                "max_length": 256,
                "help": "修改后通常需重启服务；界面显示为掩码",
            },
            {
                "key": "ADMIN_PASSWORD",
                "path": "ADMIN_PASSWORD",
                "type": "string",
                "default": "",
                "label": "初始管理员密码",
                "source": ".env",
                "module": "flask",
                "sensitive": True,
                "max_length": 256,
                "help": "仅影响 bootstrap；已有账户密码不由此修改",
            },
        ],
    },
}

MASK = "******"
DEFAULT_MAX_BACKUPS = 50
UNDO_WINDOW_SEC = 300


def get_max_backups() -> int:
    """从环境变量 CONFIG_MAX_BACKUPS 读取备份保留上限，默认 50。"""
    raw = os.environ.get("CONFIG_MAX_BACKUPS", "")
    try:
        n = int(raw) if raw.strip() else DEFAULT_MAX_BACKUPS
    except ValueError:
        n = DEFAULT_MAX_BACKUPS
    return max(1, n)


# 兼容旧引用
MAX_BACKUPS = get_max_backups()


def get_effective(item: dict[str, Any]) -> str:
    """返回 hot_reload 或 require_restart。"""
    if item.get("effective") in ("hot_reload", "require_restart"):
        return item["effective"]
    if item["key"] in _REQUIRE_RESTART_KEYS:
        return "require_restart"
    if item.get("source") == ".env" or item.get("module") == "flask":
        return "require_restart"
    return "hot_reload"


def enrich_item(item: dict[str, Any]) -> dict[str, Any]:
    """为模板/API 补充 effective、depends_on 等派生字段。"""
    out = dict(item)
    out["effective"] = get_effective(item)
    if "depends_on" in item:
        out["depends_on"] = list(item["depends_on"])
    return out


def iter_items():
    """遍历全部配置项元数据。"""
    for group_id, group in REGISTRY.items():
        for item in group["items"]:
            yield group_id, group["label"], item


def get_item(key: str) -> dict[str, Any] | None:
    for _gid, _glabel, item in iter_items():
        if item["key"] == key:
            return item
    return None


def get_defaults() -> dict[str, Any]:
    return {item["key"]: item["default"] for _g, _l, item in iter_items()}


def is_sensitive(key: str) -> bool:
    item = get_item(key)
    return bool(item and item.get("sensitive"))


def requires_restart(key: str) -> bool:
    item = get_item(key)
    return bool(item and get_effective(item) == "require_restart")


def get_depends_hint(key: str) -> str:
    item = get_item(key)
    if not item:
        return ""
    return item.get("depends_hint") or ""


def get_depends_on_labels(key: str) -> list[str]:
    """返回 depends_on 关联项的显示标签。"""
    item = get_item(key)
    if not item:
        return []
    labels: list[str] = []
    for dep_key in item.get("depends_on") or []:
        dep = get_item(dep_key)
        labels.append(dep["label"] if dep else dep_key)
    hint = item.get("depends_hint")
    if hint and not labels:
        return [hint]
    return labels
