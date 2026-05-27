"""Message posting and history service."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message, MessageType, RoomMember
from app.schemas import MessageCreate

logger = logging.getLogger(__name__)


async def post_message(db: AsyncSession, room_id: str, data: MessageCreate) -> Message:
    # Verify agent is a member of the room
    member_result = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.agent_id == data.agent_id,
        )
    )
    if not member_result.scalar_one_or_none():
        raise ValueError("Agent is not a member of this room")

    # Validate thread parent exists
    if data.parent_id:
        parent_result = await db.execute(
            select(Message).where(Message.id == data.parent_id, Message.room_id == room_id)
        )
        if not parent_result.scalar_one_or_none():
            raise ValueError("Parent message not found in this room")

    message = Message(
        room_id=room_id,
        agent_id=data.agent_id,
        type=data.type.value if isinstance(data.type, MessageType) else data.type,
        content=data.content,
        parent_id=data.parent_id,
        metadata_=data.metadata,
    )
    db.add(message)
    await db.flush()

    # Get agent name for broadcasting
    from app.models.agent import Agent
    agent_result = await db.execute(
        select(Agent.name).where(Agent.id == data.agent_id)
    )
    agent_name = agent_result.scalar() or str(data.agent_id)[:8]

    # Publish to event bus so WebSocket clients get notified
    try:
        from app.core.events import event_bus, Event
        await event_bus.publish(Event("message_posted", {
            "room_id": room_id,
            "id": str(message.id),
            "agent_id": str(data.agent_id),
            "agent_name": agent_name,
            "type": message.type,
            "content": message.content,
            "parent_id": str(data.parent_id) if data.parent_id else None,
        }))
    except Exception as e:
        logger.warning("Event bus publish failed: %s", e)

    # Notify moderator engine if one exists for this room
    try:
        from app.routers.moderator import _get_mod_engine
        engine = _get_mod_engine(room_id)
        if engine:
            # Get agent name for moderator
            from app.models.agent import Agent
            agent_result = await db.execute(
                select(Agent.name).where(Agent.id == data.agent_id)
            )
            agent_name = agent_result.scalar() or str(data.agent_id)[:8]
            actions = await engine.on_message_posted(message, db, agent_name=agent_name)
            if actions:
                from app.models.agent import Agent as AgentModel
                mod_agent_id = engine.state.moderator_agent_id
                for action in actions:
                    mod_msg = Message(
                        room_id=room_id,
                        agent_id=mod_agent_id,
                        type=action.get("type", "chat"),
                        content=action["content"],
                        metadata_={"moderator_action": action.get("action", "auto")},
                    )
                    db.add(mod_msg)
                await db.flush()
    except Exception as e:
        logger.warning("Moderator notification failed: %s", e)

    return message


async def get_messages(
    db: AsyncSession,
    room_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    msg_type: MessageType | None = None,
    parent_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[list[Message], int]:
    filters = [Message.room_id == room_id]
    if msg_type:
        filters.append(Message.type == msg_type.value)
    if parent_id is not None:
        filters.append(Message.parent_id == parent_id)
    if agent_id:
        filters.append(Message.agent_id == agent_id)

    count_result = await db.execute(select(func.count(Message.id)).where(*filters))
    total = count_result.scalar() or 0

    query = (
        select(Message)
        .where(*filters)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all()), total
