"""弧光管理 REST API（JWT + 角色归属校验）。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.schemas.arc import (
    ArcGoalComplete,
    ArcGoalCreate,
    ArcGoalUpdate,
    ArcResponse,
    ArcStageUpdate,
    GoalResponse,
)
from arc.manager import (
    ArcNotFoundError,
    ArcValidationError,
    add_goal,
    complete_goal,
    delete_goal,
    get_arc,
    update_goal,
    update_stage,
)
from arc.models import ArcState
from database.models import Character, User

router = APIRouter(prefix="/arc", tags=["arc"])


def _arc_to_response(state: ArcState) -> ArcResponse:
    return ArcResponse(
        character_id=state.character_id,
        current_stage=state.current_stage,
        stages=state.stages,
        goals=[
            GoalResponse(
                id=g.id,
                title=g.title,
                description=g.description,
                completed=g.completed,
                created_at=g.created_at,
            )
            for g in state.goals
        ],
        progress=state.progress,
        auto_advance=state.auto_advance,
    )


def _get_owned_character(
    db: Session, user_id: int, character_id: int
) -> Character:
    char = (
        db.query(Character)
        .filter_by(id=character_id, user_id=user_id, deleted=False)
        .first()
    )
    if char is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
    return char


@router.get("/{character_id}", response_model=ArcResponse)
def get_character_arc(
    character_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    return _arc_to_response(get_arc(character_id))


@router.put("/{character_id}/stage", response_model=ArcResponse)
def update_character_arc_stage(
    character_id: int,
    body: ArcStageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        state = update_stage(
            character_id,
            body.new_stage,
            operator=f"api:{current_user.username}",
            user_id=current_user.id,
        )
    except ArcValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _arc_to_response(state)


@router.post("/{character_id}/goals", response_model=ArcResponse)
def create_arc_goal(
    character_id: int,
    body: ArcGoalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        state = add_goal(
            character_id,
            body.title,
            body.description,
            operator=f"api:{current_user.username}",
            user_id=current_user.id,
        )
    except ArcValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _arc_to_response(state)


@router.put("/{character_id}/goals/{goal_id}", response_model=ArcResponse)
def update_arc_goal(
    character_id: int,
    goal_id: str,
    body: ArcGoalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        state = update_goal(
            character_id,
            goal_id,
            body.title,
            body.description,
            operator=f"api:{current_user.username}",
            user_id=current_user.id,
        )
    except (ArcValidationError, ArcNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _arc_to_response(state)


@router.post("/{character_id}/goals/{goal_id}/complete", response_model=ArcResponse)
def complete_arc_goal(
    character_id: int,
    goal_id: str,
    body: ArcGoalComplete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        state = complete_goal(
            character_id,
            goal_id,
            completed=body.completed,
            operator=f"api:{current_user.username}",
            user_id=current_user.id,
        )
    except ArcNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _arc_to_response(state)


@router.delete("/{character_id}/goals/{goal_id}", response_model=ArcResponse)
def remove_arc_goal(
    character_id: int,
    goal_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_character(db, current_user.id, character_id)
    try:
        state = delete_goal(
            character_id,
            goal_id,
            operator=f"api:{current_user.username}",
            user_id=current_user.id,
        )
    except ArcNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _arc_to_response(state)
