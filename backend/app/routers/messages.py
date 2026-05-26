"""Message REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.protocol import MessageType
from app.schemas import MessageCreate, MessageListResponse, MessageResponse
from app.services import message_service

router = APIRouter(prefix="/api/rooms/{room_id}/messages", tags=["messages"])


@router.post("", response_model=MessageResponse, status_code=201)
async def post_message(room_id: str, data: MessageCreate, db: AsyncSession = Depends(get_db)):
    try:
        msg = await message_service.post_message(db, room_id, data)
        return msg
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=MessageListResponse)
async def get_messages(
    room_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type: MessageType | None = Query(None),
    parent_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    messages, total = await message_service.get_messages(
        db, room_id, limit=limit, offset=offset, msg_type=type, parent_id=parent_id, agent_id=agent_id,
    )
    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        total=total,
        offset=offset,
        limit=limit,
    )
