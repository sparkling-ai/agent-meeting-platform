"""Predefined moderation task API."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.moderation_task import ModerationTask, EXPECTED_OUTPUTS
from app.models.message import Message
from app.schemas import PredefinedTaskCreate, PredefinedTaskResponse, PredefinedTaskListResponse, ExecuteTaskRequest
from app.services.moderator_service import ModeratorEngine

router = APIRouter(prefix="/api/moderation", tags=["moderation"])


@router.post(
    "/predefined_task",
    response_model=PredefinedTaskResponse,
    status_code=201,
)
async def create_predefined_task(
    data: PredefinedTaskCreate,
    db: AsyncSession = Depends(get_db),
):
    task = ModerationTask(
        task_type=data.task_type,
        topic=data.topic,
        description=data.description,
        room_id=data.room_id,
        status="pending",
        expected_output=EXPECTED_OUTPUTS[data.task_type],
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.get("/predefined_task", response_model=PredefinedTaskListResponse)
async def list_predefined_tasks(
    task_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(ModerationTask)
    count_query = select(func.count()).select_from(ModerationTask)

    if task_type:
        query = query.where(ModerationTask.task_type == task_type)
        count_query = count_query.where(ModerationTask.task_type == task_type)

    total = (await db.execute(count_query)).scalar()
    results = await db.execute(
        query.order_by(ModerationTask.created_at.desc()).offset(offset).limit(limit)
    )
    tasks = results.scalars().all()

    return {"tasks": tasks, "total": total}


@router.get("/predefined_task/{task_id}", response_model=PredefinedTaskResponse)
async def get_predefined_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(ModerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Moderation task not found")
    return task


@router.post(
    "/predefined_task/{task_id}/execute",
    response_model=PredefinedTaskResponse,
)
async def execute_predefined_task(
    task_id: str,
    data: ExecuteTaskRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Execute a predefined moderation task deterministically.

    For consensus_vote tasks: tallies vote messages from the room and returns
    a structured result with vote counts and consensus decision.
    """
    task = await db.get(ModerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Moderation task not found")
    if task.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Task is already {task.status}")

    # Resolve room_id: explicit param > task's room_id
    room_id = (data.room_id if data else None) or task.room_id
    if not room_id:
        raise HTTPException(status_code=400, detail="room_id is required to execute the task (no room associated with this task)")

    # Fetch messages from the room
    result_q = await db.execute(
        select(Message).where(Message.room_id == room_id)
    )
    db_messages = result_q.scalars().all()
    messages = [{"content": m.content, "type": m.type} for m in db_messages]

    # Execute via engine
    try:
        result = ModeratorEngine.execute_task(task.task_type, task.topic, messages)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update task
    task.status = "completed"
    task.result = json.dumps(result)
    task.room_id = room_id
    await db.flush()
    await db.refresh(task)
    return task
