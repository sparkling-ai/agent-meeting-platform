"""Action Items API — CRUD for meeting action items."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ActionItem

router = APIRouter(prefix="/api/action-items", tags=["action-items"])


@router.get("")
async def list_action_items(
    room_id: str | None = Query(None),
    status: str | None = Query(None),
    assignee_agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List action items with filters."""
    query = select(ActionItem)
    count_query = select(func.count()).select_from(ActionItem)

    if room_id:
        query = query.where(ActionItem.room_id == room_id)
        count_query = count_query.where(ActionItem.room_id == room_id)
    if status:
        query = query.where(ActionItem.status == status)
        count_query = count_query.where(ActionItem.status == status)
    if assignee_agent_id:
        query = query.where(ActionItem.assignee_agent_id == assignee_agent_id)
        count_query = count_query.where(ActionItem.assignee_agent_id == assignee_agent_id)

    total = (await db.execute(count_query)).scalar()
    results = await db.execute(
        query.order_by(ActionItem.created_at.desc()).offset(offset).limit(limit)
    )
    items = results.scalars().all()

    return {
        "action_items": [
            {
                "id": str(ai.id),
                "room_id": str(ai.room_id),
                "decision_id": str(ai.decision_id) if ai.decision_id else None,
                "assignee_agent_id": str(ai.assignee_agent_id) if ai.assignee_agent_id else None,
                "description": ai.description,
                "status": ai.status,
                "due_at": ai.due_at.isoformat() if ai.due_at else None,
            }
            for ai in items
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("")
async def create_action_item(
    room_id: str,
    description: str,
    decision_id: str | None = None,
    assignee_agent_id: str | None = None,
    status: str = "pending",
    due_at: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a new action item."""
    ai = ActionItem(
        room_id=room_id,
        description=description,
        decision_id=decision_id,
        assignee_agent_id=assignee_agent_id,
        status=status,
        due_at=datetime.fromisoformat(due_at) if due_at else None,
    )
    db.add(ai)
    await db.commit()
    await db.refresh(ai)

    return {
        "id": str(ai.id),
        "room_id": str(ai.room_id),
        "decision_id": str(ai.decision_id) if ai.decision_id else None,
        "assignee_agent_id": str(ai.assignee_agent_id) if ai.assignee_agent_id else None,
        "description": ai.description,
        "status": ai.status,
        "due_at": ai.due_at.isoformat() if ai.due_at else None,
    }


@router.patch("/{item_id}")
async def update_action_item(
    item_id: str,
    status: str | None = None,
    assignee_agent_id: str | None = None,
    description: str | None = None,
    due_at: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Update an action item."""
    ai = await db.get(ActionItem, item_id)
    if not ai:
        raise HTTPException(status_code=404, detail="Action item not found")

    if status is not None:
        if status not in ("pending", "in_progress", "done"):
            raise HTTPException(status_code=400, detail="Invalid status. Must be: pending, in_progress, done")
        ai.status = status
    if assignee_agent_id is not None:
        ai.assignee_agent_id = assignee_agent_id
    if description is not None:
        ai.description = description
    if due_at is not None:
        ai.due_at = datetime.fromisoformat(due_at)

    await db.commit()
    await db.refresh(ai)

    return {
        "id": str(ai.id),
        "room_id": str(ai.room_id),
        "description": ai.description,
        "status": ai.status,
        "assignee_agent_id": str(ai.assignee_agent_id) if ai.assignee_agent_id else None,
        "due_at": ai.due_at.isoformat() if ai.due_at else None,
    }


@router.delete("/{item_id}")
async def delete_action_item(item_id: str, db: AsyncSession = Depends(get_db)):
    """Delete an action item."""
    ai = await db.get(ActionItem, item_id)
    if not ai:
        raise HTTPException(status_code=404, detail="Action item not found")
    await db.delete(ai)
    await db.commit()
    return {"detail": "Action item deleted"}
