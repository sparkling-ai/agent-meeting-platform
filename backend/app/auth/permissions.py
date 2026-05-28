"""RBAC permissions system — platform-level and room-level role checks."""

import uuid
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.message import RoomMember
from app.models.room import Room
from app.models.user import User


# ── Role Enums ───────────────────────────────────────────────────────────────

class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"
    AGENT = "agent"
    VIEWER = "viewer"


class RoomRole(StrEnum):
    OWNER = "owner"
    MODERATOR = "moderator"
    MEMBER = "member"
    OBSERVER = "observer"


class RoomVisibility(StrEnum):
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


# ── Permission Matrix ────────────────────────────────────────────────────────

# Room-level permission hierarchy: owner > moderator > member > observer
ROOM_ROLE_HIERARCHY: dict[str, int] = {
    RoomRole.OWNER: 4,
    RoomRole.MODERATOR: 3,
    RoomRole.MEMBER: 2,
    RoomRole.OBSERVER: 1,
}


def _role_level(role: str) -> int:
    return ROOM_ROLE_HIERARCHY.get(role, 0)


def has_min_room_role(member_role: str, required_role: str) -> bool:
    """Check if member_role meets or exceeds required_role in the hierarchy."""
    return _role_level(member_role) >= _role_level(required_role)


# ── Platform-Level Dependencies ──────────────────────────────────────────────

def require_role(*roles: str):
    """FastAPI dependency: require one of the specified platform-level roles."""
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            role_names = "/".join(roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {role_names}",
            )
        return user
    return _check


# ── Room-Level Helpers ───────────────────────────────────────────────────────

async def get_room_membership(
    db: AsyncSession, room_id: str, user: User,
) -> RoomMember | None:
    """Get the current user's RoomMember record for a room, if any.

    Agents owned by the user are considered the user's proxy.
    """
    # Check if user owns an agent in this room
    from app.models.agent import Agent

    # First try: agent owned by this user
    result = await db.execute(
        select(RoomMember)
        .join(Agent, RoomMember.agent_id == Agent.id)
        .where(
            RoomMember.room_id == room_id,
            Agent.owner_id == str(user.id),
        )
    )
    members = result.scalars().all()
    # Return highest-role member
    if members:
        return max(members, key=lambda m: _role_level(m.role))

    # Second try: check all agents in the room for a match
    # (for backward compat with agents that don't have owner_id set)
    return None


async def get_room_with_membership(
    db: AsyncSession, room_id: str, user: User,
) -> tuple[Room, RoomMember | None]:
    """Get room and optionally the user's membership."""
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    membership = await get_room_membership(db, room_id, user)
    return room, membership


def require_room_role(*roles: str):
    """FastAPI dependency: require one of the specified room-level roles.

    Provides the room and membership as part of the dependency chain.
    """
    async def _check(
        room_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> tuple[Room, RoomMember]:
        room, membership = await get_room_with_membership(db, room_id, user)

        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this room",
            )

        if membership.role not in roles:
            role_names = "/".join(roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires room role: {role_names}",
            )

        return room, membership
    return _check


async def check_room_permission(
    db: AsyncSession,
    room_id: str,
    user: User,
    min_role: str = RoomRole.MEMBER,
) -> tuple[Room, RoomMember | None]:
    """Check room permission — returns room and membership.

    Raises 403 if user is a member but below min_role.
    Returns (room, None) if user is not a member (caller decides what to do).
    """
    room, membership = await get_room_with_membership(db, room_id, user)

    if membership and not has_min_room_role(membership.role, min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires room role: {min_role} or above",
        )

    return room, membership


# ── Room Visibility Helpers ──────────────────────────────────────────────────

def can_join_room(room: Room, membership: RoomMember | None, is_invited: bool = False) -> str | None:
    """Check if a user can join a room based on visibility.

    Returns the default role to assign, or None if joining is not allowed.
    """
    if membership is not None:
        return None  # Already a member

    if room.visibility == RoomVisibility.PUBLIC:
        return RoomRole.OBSERVER
    elif room.visibility == RoomVisibility.UNLISTED:
        return RoomRole.MEMBER
    elif room.visibility == RoomVisibility.PRIVATE:
        if is_invited:
            return RoomRole.MEMBER
        return None  # Must be invited

    return None
