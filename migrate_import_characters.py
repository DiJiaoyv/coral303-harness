"""
将 characters.json 及根目录 characters/ 下的角色导入数据库。

已弃用：请优先使用 scripts/migrate_characters.py
"""
from __future__ import annotations

import sys

if __name__ == "__main__":
    print("此脚本已弃用，请运行: python scripts/migrate_characters.py", file=sys.stderr)
    sys.exit(1)
