"""Agent registration and auth service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token
from app.models import Agent
from app.schemas import AgentCreate


async def register_agent(db: AsyncSession, data: AgentCreate) -> Agent:
    agent = Agent(
        name=data.name,
        connector_type=data.connector_type,
        capabilities=data.capabilities or {},
        owner_id=data.owner_id,
    )
    db.add(agent)
    await db.flush()
    return agent


async def list_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(select(Agent).order_by(Agent.created_at.desc()))
    return list(result.scalars().all())


async def get_agent(db: AsyncSession, agent_id: str) -> Agent | None:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def generate_agent_token(db: AsyncSession, agent_id: str) -> str:
    agent = await get_agent(db, agent_id)
    if not agent:
        raise ValueError("Agent not found")
    token = generate_token()
    agent.auth_token = token
    await db.flush()
    return token
