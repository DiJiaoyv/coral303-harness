"""配置管理：加载、校验、写入、备份与热重载。"""
from config_manager.backup import create_backup, list_backups, restore_backup
from config_manager.loader import export_dict, get_config, load_all_configs, load_grouped
from config_manager.registry import MASK, REGISTRY, get_defaults, get_item
from config_manager.validator import validate, validate_many
from config_manager.writer import (
    import_configs,
    reset_keys,
    save_config,
    save_configs,
    undo_last,
)

__all__ = [
    "REGISTRY",
    "MASK",
    "get_item",
    "get_defaults",
    "validate",
    "validate_many",
    "load_all_configs",
    "load_grouped",
    "get_config",
    "export_dict",
    "save_config",
    "save_configs",
    "import_configs",
    "reset_keys",
    "undo_last",
    "create_backup",
    "list_backups",
    "restore_backup",
]
