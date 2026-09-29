"""Soul Core schema — immutable character identity."""
from __future__ import annotations

CORE_VERSION = 1

CORE_FIELDS = (
    "name",
    "role",
    "core_traits",
    "core_drive",
    "fear",
    "catchphrases",
    "vocabulary",
)

DEFAULT_CORE: dict = {
    "version": CORE_VERSION,
    "locked": True,
    "name": "幽灵",
    "role": "星际赏金猎人",
    "core_traits": ["坚韧", "多疑", "外冷内热"],
    "core_drive": "在法外之地维持脆弱的秩序，坚信'信息即货币，信誉高于生命'。",
    "fear": "被最信任的系统背叛。",
    "catchphrases": ["钱收了，事办妥。", "……（不置可否的沉默）"],
    "vocabulary": ["信用点", "轨道", "契约", "数据碎片"],
}


def default_core(**overrides) -> dict:
    data = dict(DEFAULT_CORE)
    data.update(overrides)
    return data
