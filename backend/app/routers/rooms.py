"""Room REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, optional_auth
from app.database import get_db
from app.models.user import User
from app.schemas import (
    RoomCreate, RoomDetailResponse, RoomJoinRequest, RoomResponse, RoomStatusUpdate,
)
from app.services import room_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    data: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    room = await room_service.create_room(db, data)
    # If authenticated, set owner_id
    if current_user and room:
        room.owner_id = current_user.id
        await db.flush()
        await db.refresh(room)
    return room


@router.get("", response_model=list[RoomResponse])
async def list_rooms(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    return await room_service.list_rooms(db, status=status)


@router.get("/{room_id}", response_model=RoomDetailResponse)
async def get_room(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    room = await room_service.get_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room_service.room_to_detail_response(room)


@router.post("/{room_id}/join")
async def join_room(
    room_id: str,
    data: RoomJoinRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    try:
        member = await room_service.join_room(db, room_id, data)
        return {"room_id": str(member.room_id), "agent_id": str(member.agent_id), "role": member.role}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{room_id}/leave")
async def leave_room(
    room_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    left = await room_service.leave_room(db, room_id, agent_id)
    if not left:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"detail": "Left room successfully"}


@router.patch("/{room_id}/status", response_model=RoomResponse)
async def update_room_status(
    room_id: str,
    data: RoomStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    try:
        room = await room_service.update_room_status(db, room_id, data.status)
        return room
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
