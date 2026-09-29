from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.schemas.character import (
    CharacterCreate,
    CharacterResponse,
    CharacterUpdate,
)
from api.services import character_service as svc
from database.models import User

router = APIRouter(prefix="/characters", tags=["characters"])


@router.get("", response_model=list[CharacterResponse])
def list_characters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return svc.get_characters(db, current_user.id)


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
def create_character(
    body: CharacterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return svc.create_character(db, current_user.id, body)
    except svc.CharacterConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.put("/{character_id}", response_model=CharacterResponse)
def update_character(
    character_id: int,
    body: CharacterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return svc.update_character(db, current_user.id, character_id, body)
    except svc.CharacterNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(
    character_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        svc.delete_character(db, current_user.id, character_id)
    except svc.CharacterNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
