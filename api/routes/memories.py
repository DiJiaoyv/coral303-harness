"""记忆管理 REST API。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.schemas.memory import (
    MemoryItemResponse,
    MemoryListResponse,
    MemoryUpdateRequest,
)
from database.models import Character, User
from memory.search import search_memories_by_character_id
from memory.writer import (
    MemoryNotFoundError,
    MemoryPermissionError,
    MemoryValidationError,
    delete_memory,
    get_raw_memory,
    update_memory,
)

router = APIRouter(prefix="/memories", tags=["memories"])


def _get_owned_character(db: Session, user_id: int, character_id: int) -> Character:
    char = (
        db.query(Character)
        .filter_by(id=character_id, user_id=user_id, deleted=False)
        .first()
    )
    if char is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
    return char


def _to_item(data: dict) -> MemoryItemResponse:
    return MemoryItemResponse(
        id=data["id"],
        summary=data["summary"],
        content=data["content"],
        importance_raw=data["importance_raw"],
        importance=data["importance"],
        source=data["source"],
        created_at=data["created_at"].isoformat() if data.get("created_at") else "",
        deleted=bool(data.get("deleted", False)),
    )


@router.get("/{character_id}", response_model=MemoryListResponse)
def list_memories(
    character_id: int,
    q: str | None = None,
    importance: str | None = None,
    source: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        items, total, _, _, _ = search_memories_by_character_id(
            character_id,
            user_id=current_user.id,
            keyword=q,
            importance=importance,
            source=source,
            page=page,
            require_owner=True,
        )
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")

    return MemoryListResponse(
        items=[_to_item(i) for i in items],
        total=total,
        page=page,
    )


@router.get("/{character_id}/{memory_id}", response_model=MemoryItemResponse)
def get_memory_detail(
    character_id: int,
    memory_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        data = get_raw_memory(
            current_user.id,
            character_id,
            memory_id,
            require_owner=True,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记忆不存在")
    except MemoryPermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    return _to_item(data)


@router.put("/{character_id}/{memory_id}", response_model=MemoryItemResponse)
def update_memory_item(
    character_id: int,
    memory_id: str,
    body: MemoryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        data = update_memory(
            current_user.id,
            character_id,
            memory_id,
            content=body.content,
            importance=body.importance,
            operator=f"api:{current_user.username}",
            require_owner=True,
        )
    except MemoryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except MemoryNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记忆不存在")
    except MemoryPermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    return _to_item(data)


@router.delete("/{character_id}/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory_item(
    character_id: int,
    memory_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        delete_memory(
            current_user.id,
            character_id,
            memory_id,
            operator=f"api:{current_user.username}",
            require_owner=True,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记忆不存在")
    except MemoryPermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
