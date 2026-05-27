"""Agent REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import optional_auth
from app.database import get_db
from app.models.user import User
from app.schemas import AgentCreate, AgentResponse, AgentTokenResponse
from app.services import agent_service

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("", response_model=AgentResponse, status_code=201)
async def register_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    agent = await agent_service.register_agent(db, data)
    return agent


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    return await agent_service.list_agents(db)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/{agent_id}/token", response_model=AgentTokenResponse)
async def generate_token(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    try:
        aid, token = await agent_service.generate_agent_token(db, agent_id)
        return AgentTokenResponse(agent_id=aid, token=token)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
