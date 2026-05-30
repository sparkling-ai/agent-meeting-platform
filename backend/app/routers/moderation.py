"""Predefined moderation task API."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.moderation_task import ModerationTask, EXPECTED_OUTPUTS
from app.schemas import PredefinedTaskCreate, PredefinedTaskResponse, PredefinedTaskListResponse

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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Moderation task not found")
    return task
