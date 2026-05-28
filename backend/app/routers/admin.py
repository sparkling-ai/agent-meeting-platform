"""Admin API — dashboard stats, user management, room management."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models import Agent, Room, RoomMember, Message, Decision, ActionItem
from app.models.user import User
from app.schemas import AdminUserUpdate

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: str
    model_config = {"from_attributes": True}


class AdminRoomResponse(BaseModel):
    id: uuid.UUID
    name: str
    topic: str | None
    status: str
    visibility: str
    owner_id: uuid.UUID | None
    max_participants: int
    member_count: int
    created_at: str
    model_config = {"from_attributes": True}


# ── Dashboard Stats ──────────────────────────────────────────────────────────

@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    """Get admin dashboard statistics."""
    room_count = (await db.execute(select(func.count()).select_from(Room))).scalar()
    active_rooms = (await db.execute(
        select(func.count()).select_from(Room).where(Room.status == "active")
    )).scalar()
    agent_count = (await db.execute(select(func.count()).select_from(Agent))).scalar()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar()
    message_count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    decision_count = (await db.execute(select(func.count()).select_from(Decision))).scalar()
    action_item_count = (await db.execute(select(func.count()).select_from(ActionItem))).scalar()
    pending_actions = (await db.execute(
        select(func.count()).select_from(ActionItem).where(ActionItem.status == "pending")
    )).scalar()

    # Recent activity — last 10 messages
    recent_msgs_result = await db.execute(
        select(Message, Agent.name.label("agent_name"))
        .join(Agent, Message.agent_id == Agent.id, isouter=True)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_messages = [
        {
            "id": str(row.Message.id),
            "room_id": str(row.Message.room_id),
            "agent_name": row.agent_name or "Unknown",
            "type": row.Message.type,
            "content": row.Message.content[:200],
            "created_at": row.Message.created_at.isoformat() if row.Message.created_at else None,
        }
        for row in recent_msgs_result
    ]

    return {
        "rooms": {"total": room_count, "active": active_rooms},
        "agents": {"total": agent_count},
        "users": {"total": user_count},
        "messages": {"total": message_count},
        "decisions": {"total": decision_count},
        "action_items": {"total": action_item_count, "pending": pending_actions},
        "recent_messages": recent_messages,
    }


# ── User Management ──────────────────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all users (admin only)."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        AdminUserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str,
    data: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Update a user's platform role or active status (admin only)."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent admin from deactivating themselves
    if str(user.id) == str(current_user.id) and data.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active

    await db.flush()

    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


# ── Room Management ──────────────────────────────────────────────────────────

@router.get("/rooms", response_model=list[AdminRoomResponse])
async def list_all_rooms(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all rooms with member counts (admin only)."""
    result = await db.execute(select(Room).order_by(Room.created_at.desc()))
    rooms = result.scalars().all()

    response = []
    for r in rooms:
        member_count = (await db.execute(
            select(func.count()).select_from(RoomMember).where(RoomMember.room_id == r.id)
        )).scalar()
        response.append(AdminRoomResponse(
            id=r.id,
            name=r.name,
            topic=r.topic,
            status=r.status,
            visibility=r.visibility,
            owner_id=r.owner_id,
            max_participants=r.max_participants,
            member_count=member_count or 0,
            created_at=r.created_at.isoformat() if r.created_at else None,
        ))
    return response


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete a room and all its data (admin only)."""
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    await db.delete(room)
    await db.commit()
    return {"detail": "Room deleted", "room_id": room_id}


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete an agent and remove from all rooms."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Remove from all rooms
    await db.execute(
        RoomMember.__table__.delete().where(RoomMember.agent_id == agent_id)
    )
    await db.delete(agent)
    await db.commit()
    return {"detail": "Agent deleted", "agent_id": agent_id}


@router.post("/rooms/{room_id}/bulk-join")
async def bulk_join_room(
    room_id: str,
    agent_ids: list[str],
    role: str = "member",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add multiple agents to a room at once."""
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    added = []
    for aid in agent_ids:
        agent = await db.get(Agent, aid)
        if not agent:
            continue
        # Check if already a member
        existing = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.agent_id == aid,
            )
        )
        if existing.scalar_one_or_none():
            continue
        member = RoomMember(room_id=room_id, agent_id=aid, role=role)
        db.add(member)
        added.append(aid)

    await db.commit()
    return {"room_id": room_id, "added_agents": added}


@router.post("/reset-dev")
async def reset_dev_data(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Reset all data in the dev schema (dangerous — dev only!)."""
    for table in [ActionItem, Decision, Message, RoomMember, Room, Agent]:
        await db.execute(table.__table__.delete())
    await db.commit()
    return {"detail": "All dev data reset"}
