# harness_config.py - Harness 引擎外置配置（config.json）加载与校验
import copy
import json
import os


class ConfigValidationError(ValueError):
    """配置校验失败。"""


DEFAULT_CONFIG: dict = {
    "paths": {
        "soul": "soul_state.json",
        "memory": "memory_state.json",
        "emotion": "emotion_state.json",
        "log_session": "logs/session_{session_id}.json",
    },
    "ollama": {
        "chat_model": "qwen2.5:7b",
        "analysis_model": "deepseek-r1:8b",
        "model": "deepseek-r1:8b",
        "base_url": "http://localhost:11434/api/generate",
        "timeout": 300,
        "num_predict": 200,
        "max_retries": 2,
    },
    "engine": {
        "stream": True,
        "fact_extract_interval": 3,
        "arc_update_interval": 3,
        "auto_save_interval": 5,
        "memory_max_rounds": 10,
        "recent_dialogue_rounds": 5,
        "relevant_facts_limit": 3,
        "hot_reload": True,
    },
    "memory_extractor": {"num_predict": 150, "temperature": 0.3},
    "arc_updater": {"num_predict": 120, "temperature": 0.2},
    "emotion": {"default_score": 5.0},
    "unified_analyzer": {"enabled": True, "num_predict": 250, "temperature": 0.25},
    "web": {"host": "127.0.0.1", "port": 7860, "share": False},
    "embeddings": {
        "enabled": True,
        "model": "nomic-embed-text",
        "base_url": "http://localhost:11434/api/embeddings",
        "timeout": 60,
        "max_retries": 2,
    },
    "characters": {"registry": "characters.json"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def validate_config(config: dict) -> None:
    errors: list[str] = []
    ollama = get_section(config, "ollama")
    for key in ("timeout", "num_predict", "max_retries"):
        val = ollama.get(key, DEFAULT_CONFIG["ollama"].get(key))
        if not isinstance(val, (int, float)) or int(val) < 0:
            errors.append(f"ollama.{key} 必须为非负整数")
    engine = get_section(config, "engine")
    for key in (
        "fact_extract_interval", "arc_update_interval", "auto_save_interval",
        "memory_max_rounds", "recent_dialogue_rounds", "relevant_facts_limit",
    ):
        val = engine.get(key, DEFAULT_CONFIG["engine"].get(key))
        if not isinstance(val, (int, float)) or int(val) < 1:
            errors.append(f"engine.{key} 必须为正整数")
    emotion = get_section(config, "emotion")
    score = emotion.get("default_score", 5.0)
    if not isinstance(score, (int, float)) or not (1.0 <= float(score) <= 10.0):
        errors.append("emotion.default_score 必须在 1.0–10.0 之间")
    web = get_section(config, "web")
    port = web.get("port", 7860)
    if not isinstance(port, (int, float)) or not (1 <= int(port) <= 65535):
        errors.append("web.port 必须在 1–65535 之间")
    if errors:
        raise ConfigValidationError("配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors))


def load_config(
    filepath: str = "config.json",
    overrides: dict | None = None,
    create_if_missing: bool = True,
    validate: bool = True,
) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            _deep_merge(config, json.load(f))
    elif create_if_missing:
        save_config(config, filepath)
        print(f"[Config] 已创建默认配置文件 {filepath}")
    if overrides:
        _deep_merge(config, overrides)
    if validate:
        validate_config(config)
    return config


def save_config(config: dict, filepath: str = "config.json") -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_section(config: dict, section: str) -> dict:
    value = config.get(section, {})
    return value if isinstance(value, dict) else {}
