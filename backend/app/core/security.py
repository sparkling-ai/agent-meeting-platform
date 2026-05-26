"""Simple API key authentication for agents."""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Agent

security_scheme = HTTPBearer()


def generate_token() -> str:
    """Generate a secure random auth token."""
    return f"amp_{secrets.token_hex(32)}"


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """Dependency that resolves the Bearer token to an Agent."""
    token = credentials.credentials
    result = await db.execute(select(Agent).where(Agent.auth_token == token))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return agent
