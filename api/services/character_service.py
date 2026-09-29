"""角色 CRUD（所有查询均按 user_id 过滤）。"""
import json
import os

from sqlalchemy.orm import Session

from api.schemas.character import CharacterCreate, CharacterUpdate
from database.models import Character
from soul import Soul

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class CharacterConflictError(Exception):
    pass


class CharacterNotFoundError(Exception):
    pass


def _user_root(user_id: int) -> str:
    return os.path.join(BASE_DIR, "users", str(user_id))


def _registry_path(user_id: int) -> str:
    return os.path.join(_user_root(user_id), "characters.json")


def _load_registry(user_id: int) -> dict:
    path = _registry_path(user_id)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "active": "",
        "base_dir": "characters",
        "characters": {},
    }


def _save_registry(user_id: int, registry: dict) -> None:
    root = _user_root(user_id)
    os.makedirs(root, exist_ok=True)
    with open(_registry_path(user_id), "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def _ensure_character_files(user_id: int, character_key: str, meta: dict) -> None:
    char_dir = os.path.join(_user_root(user_id), "characters", character_key)
    os.makedirs(char_dir, exist_ok=True)
    soul_path = os.path.join(char_dir, "soul_state.json")
    if not os.path.exists(soul_path):
        soul = Soul(
            name=meta.get("display_name", character_key),
            role=meta.get("role") or "未知",
        )
        soul.save(soul_path)


def get_characters(db: Session, user_id: int) -> list[Character]:
    return (
        db.query(Character)
        .filter(Character.user_id == user_id, Character.deleted.is_(False))
        .order_by(Character.id)
        .all()
    )


def get_character_by_id(
    db: Session, user_id: int, character_id: int
) -> Character | None:
    return (
        db.query(Character)
        .filter(
            Character.id == character_id,
            Character.user_id == user_id,
            Character.deleted.is_(False),
        )
        .first()
    )


def create_character(
    db: Session, user_id: int, data: CharacterCreate
) -> Character:
    existing = (
        db.query(Character)
        .filter(
            Character.user_id == user_id,
            Character.character_key == data.character_key,
            Character.deleted.is_(False),
        )
        .first()
    )
    if existing:
        raise CharacterConflictError("角色标识已存在")

    character = Character(
        user_id=user_id,
        character_key=data.character_key,
        display_name=data.display_name,
        role=data.role,
    )
    db.add(character)
    db.commit()
    db.refresh(character)

    registry = _load_registry(user_id)
    registry.setdefault("characters", {})[data.character_key] = {
        "name": data.display_name,
        "role": data.role or "未知",
    }
    if not registry.get("active"):
        registry["active"] = data.character_key
    _save_registry(user_id, registry)
    _ensure_character_files(
        user_id,
        data.character_key,
        {"display_name": data.display_name, "role": data.role},
    )
    return character


def update_character(
    db: Session,
    user_id: int,
    character_id: int,
    data: CharacterUpdate,
) -> Character:
    character = get_character_by_id(db, user_id, character_id)
    if not character:
        raise CharacterNotFoundError("角色不存在")

    if data.display_name is not None:
        character.display_name = data.display_name
    if data.role is not None:
        character.role = data.role

    db.commit()
    db.refresh(character)

    registry = _load_registry(user_id)
    entry = registry.get("characters", {}).get(character.character_key, {})
    if data.display_name is not None:
        entry["name"] = data.display_name
    if data.role is not None:
        entry["role"] = data.role
    registry.setdefault("characters", {})[character.character_key] = entry
    _save_registry(user_id, registry)
    return character


def delete_character(db: Session, user_id: int, character_id: int) -> None:
    character = get_character_by_id(db, user_id, character_id)
    if not character:
        raise CharacterNotFoundError("角色不存在")

    character_key = character.character_key
    db.delete(character)
    db.commit()

    registry = _load_registry(user_id)
    chars = registry.get("characters", {})
    if character_key in chars:
        del chars[character_key]
    if registry.get("active") == character_key:
        registry["active"] = next(iter(chars), "")
    _save_registry(user_id, registry)
