"""Agent registration and auth service."""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.schemas import AgentCreate


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_agent(db: AsyncSession, data: AgentCreate, owner_id: str | None = None) -> Agent:
    agent = Agent(
        name=data.name,
        connector_type=data.connector_type,
        capabilities=data.capabilities or {},
        owner_id=owner_id,
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


async def generate_agent_token(db: AsyncSession, agent_id: str) -> tuple[str, str]:
    """Generate a token for an agent. Returns (plain_token, agent_id)."""
    import secrets
    agent = await get_agent(db, agent_id)
    if not agent:
        raise ValueError("Agent not found")
    token = f"amp_{secrets.token_hex(32)}"
    agent.auth_token_hash = _hash_token(token)
    await db.flush()
    return str(agent.id), token


async def validate_token(db: AsyncSession, token: str) -> Agent | None:
    token_hash = _hash_token(token)
    result = await db.execute(select(Agent).where(Agent.auth_token_hash == token_hash))
    return result.scalar_one_or_none()
