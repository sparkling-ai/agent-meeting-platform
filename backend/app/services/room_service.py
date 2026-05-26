"""Async CRUD service for rooms."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.protocol import is_valid_status_transition
from app.models.agent import Agent
from app.models.room import Room
from app.models.message import RoomMember
from app.schemas import RoomCreate, RoomDetailResponse, RoomJoinRequest, RoomMemberResponse


async def create_room(db: AsyncSession, data: RoomCreate) -> Room:
    room = Room(
        name=data.name,
        topic=data.topic,
        settings=data.settings or {},
    )
    db.add(room)
    await db.flush()
    return room


async def list_rooms(db: AsyncSession, status: str | None = None) -> list[Room]:
    query = select(Room).order_by(Room.created_at.desc())
    if status:
        query = query.where(Room.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_room(db: AsyncSession, room_id: str) -> Room | None:
    result = await db.execute(
        select(Room).options(selectinload(Room.members).selectinload(RoomMember.agent)).where(Room.id == room_id)
    )
    return result.scalar_one_or_none()


async def join_room(db: AsyncSession, room_id: str, data: RoomJoinRequest) -> RoomMember:
    room = await get_room(db, room_id)
    if not room:
        raise ValueError("Room not found")

    agent_result = await db.execute(select(Agent).where(Agent.id == data.agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise ValueError("Agent not found")

    existing = await db.execute(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.agent_id == data.agent_id)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Agent is already a member of this room")

    member = RoomMember(room_id=room_id, agent_id=data.agent_id, role=data.role)
    db.add(member)
    await db.flush()
    return member


async def leave_room(db: AsyncSession, room_id: str, agent_id: str) -> bool:
    result = await db.execute(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.agent_id == agent_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        return False
    await db.delete(member)
    await db.flush()
    return True


async def update_room_status(db: AsyncSession, room_id: str, new_status: str) -> Room:
    room = await get_room(db, room_id)
    if not room:
        raise ValueError("Room not found")
    if not is_valid_status_transition(room.status, new_status):
        raise ValueError(f"Cannot transition room from {room.status} to {new_status}")
    room.status = new_status
    await db.flush()
    return room


def room_to_detail_response(room: Room) -> RoomDetailResponse:
    members = [
        RoomMemberResponse(
            agent_id=m.agent_id,
            agent_name=m.agent.name if m.agent else "Unknown",
            role=m.role,
            joined_at=m.joined_at,
        )
        for m in room.members
    ]
    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        topic=room.topic,
        status=room.status,
        settings=room.settings,
        created_at=room.created_at,
        updated_at=room.updated_at,
        members=members,
    )
