"""Decisions API — CRUD for meeting decisions."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import optional_auth, get_current_user
from app.auth.permissions import RoomRole, check_room_permission
from app.database import get_db
from app.models import Decision, ActionItem, Room
from app.models.user import User

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("")
async def list_decisions(
    room_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """List decisions, optionally filtered by room and status."""
    query = select(Decision)
    count_query = select(func.count()).select_from(Decision)

    if room_id:
        query = query.where(Decision.room_id == room_id)
        count_query = count_query.where(Decision.room_id == room_id)
    if status:
        query = query.where(Decision.status == status)
        count_query = count_query.where(Decision.status == status)

    total = (await db.execute(count_query)).scalar()
    results = await db.execute(
        query.order_by(Decision.decided_at.desc().nullsfirst(), Decision.id)
        .offset(offset).limit(limit)
    )
    decisions = results.scalars().all()

    return {
        "decisions": [
            {
                "id": str(d.id),
                "room_id": str(d.room_id),
                "title": d.title,
                "description": d.description,
                "status": d.status,
                "proposer_agent_id": str(d.proposer_agent_id) if d.proposer_agent_id else None,
                "summary": d.summary,
                "decided_at": d.decided_at.isoformat() if d.decided_at else None,
            }
            for d in decisions
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{decision_id}")
async def get_decision(
    decision_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Get a decision by ID, including its action items."""
    d = await db.get(Decision, decision_id)
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Get action items for this decision
    items_result = await db.execute(
        select(ActionItem).where(ActionItem.decision_id == decision_id)
    )
    items = items_result.scalars().all()

    return {
        "id": str(d.id),
        "room_id": str(d.room_id),
        "title": d.title,
        "description": d.description,
        "status": d.status,
        "proposer_agent_id": str(d.proposer_agent_id) if d.proposer_agent_id else None,
        "summary": d.summary,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "action_items": [
            {
                "id": str(ai.id),
                "description": ai.description,
                "status": ai.status,
                "assignee_agent_id": str(ai.assignee_agent_id) if ai.assignee_agent_id else None,
                "due_at": ai.due_at.isoformat() if ai.due_at else None,
            }
            for ai in items
        ],
    }


@router.post("")
async def create_decision(
    room_id: str,
    title: str,
    proposer_agent_id: str | None = None,
    description: str | None = None,
    status: str = "proposed",
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Create a new decision manually."""
    if current_user:
        await check_room_permission(db, room_id, current_user, RoomRole.MEMBER)

    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    d = Decision(
        room_id=room_id,
        title=title,
        description=description,
        status=status,
        proposer_agent_id=proposer_agent_id,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)

    return {
        "id": str(d.id),
        "room_id": str(d.room_id),
        "title": d.title,
        "description": d.description,
        "status": d.status,
        "proposer_agent_id": str(d.proposer_agent_id) if d.proposer_agent_id else None,
    }


@router.patch("/{decision_id}")
async def update_decision(
    decision_id: str,
    status: str | None = None,
    summary: str | None = None,
    title: str | None = None,
    description: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Update a decision (status, summary, etc)."""
    if current_user:
        # Get room_id from decision
        d_check = await db.get(Decision, decision_id)
        if d_check:
            await check_room_permission(db, str(d_check.room_id), current_user, RoomRole.MEMBER)

    d = await db.get(Decision, decision_id)
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found")

    if status is not None:
        if status not in ("proposed", "accepted", "rejected"):
            raise HTTPException(status_code=400, detail="Invalid status")
        d.status = status
        if status in ("accepted", "rejected"):
            d.decided_at = datetime.utcnow()
    if summary is not None:
        d.summary = summary
    if title is not None:
        d.title = title
    if description is not None:
        d.description = description

    await db.commit()
    await db.refresh(d)

    return {
        "id": str(d.id),
        "room_id": str(d.room_id),
        "title": d.title,
        "description": d.description,
        "status": d.status,
        "summary": d.summary,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
    }


@router.delete("/{decision_id}")
async def delete_decision(
    decision_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Delete a decision."""
    if current_user:
        d_check = await db.get(Decision, decision_id)
        if d_check:
            await check_room_permission(db, str(d_check.room_id), current_user, RoomRole.MODERATOR)

    d = await db.get(Decision, decision_id)
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found")
    await db.delete(d)
    await db.commit()
    return {"detail": "Decision deleted"}
