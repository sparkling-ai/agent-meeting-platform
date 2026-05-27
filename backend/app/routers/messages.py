"""Message REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.auth.dependencies import optional_auth
from app.database import get_db
from app.models.message import MessageType
from app.models.user import User
from app.schemas import MessageCreate, MessageListResponse, MessageResponse
from app.services import message_service

router = APIRouter(prefix="/api/rooms/{room_id}/messages", tags=["messages"])


@router.post("", response_model=MessageResponse, status_code=201)
async def post_message(
    room_id: str,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
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
    current_user: User | None = Depends(optional_auth),
):
    messages, total = await message_service.get_messages(
        db, room_id, limit=limit, offset=offset, msg_type=type, parent_id=parent_id, agent_id=agent_id,
    )
    # Enrich messages with agent names
    enriched = []
    for m in messages:
        resp = MessageResponse.model_validate(m)
        if resp.agent_id:
            from app.models.agent import Agent
            agent_result = await db.execute(
                select(Agent.name).where(Agent.id == resp.agent_id)
            )
            resp.agent_name = agent_result.scalar()
        enriched.append(resp)
    return MessageListResponse(
        messages=enriched,
        total=total,
        offset=offset,
        limit=limit,
    )
