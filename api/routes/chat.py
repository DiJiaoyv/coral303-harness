from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.schemas.chat import ChatRequest, ChatResponse
from api.services import character_service as char_svc
from database.models import User
from orchestrator import orchestrate_turn

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions", response_model=ChatResponse)
def chat_completions(
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    character = char_svc.get_character_by_id(
        db, current_user.id, body.character_id
    )
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在",
        )

    try:
        # 统一编排入口：Conversation + score_log + memory 全部由 orchestrator 落盘
        result = orchestrate_turn(
            current_user.id,
            body.character_id,
            body.message,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成回复失败",
        )

    return ChatResponse(reply=result.response)
