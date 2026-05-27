"""FastAPI dependencies for authentication."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_api_key
from app.auth.jwt import verify_token
from app.database import get_db
from app.models.user import ApiKey, User

bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _resolve_user_from_jwt(
    token: str, db: AsyncSession
) -> User | None:
    """Resolve a JWT token to a User."""
    payload = verify_token(token)
    if payload is None:
        return None
    if payload.get("type") not in ("user", "api_key"):
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        user = await db.get(User, uuid.UUID(user_id))
    except (ValueError, TypeError):
        return None
    if user and not user.is_active:
        return None
    return user


async def _resolve_user_from_api_key(
    api_key: str, db: AsyncSession,
) -> User | None:
    """Resolve an X-API-Key header to a User via api_keys table."""
    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    api_key_obj = result.scalar_one_or_none()
    if api_key_obj is None:
        return None
    # Check expiry
    from datetime import datetime, timezone
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.now(timezone.utc):
        return None
    # Update last_used_at
    api_key_obj.last_used_at = datetime.now(timezone.utc)
    # Get user
    user = await db.get(User, api_key_obj.user_id)
    if user and not user.is_active:
        return None
    return user


async def get_current_user(
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    api_key: Annotated[str | None, Depends(api_key_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: require a valid authenticated user (JWT or API key).

    Raises 401 if no valid credentials.
    """
    user = await optional_auth(bearer, api_key, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def optional_auth(
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    api_key: Annotated[str | None, Depends(api_key_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Dependency: resolve auth if present, but don't require it.

    Returns User if valid credentials provided, None otherwise.
    """
    # Try Bearer token first
    if bearer is not None:
        user = await _resolve_user_from_jwt(bearer.credentials, db)
        if user is not None:
            return user

    # Try API key
    if api_key is not None:
        user = await _resolve_user_from_api_key(api_key, db)
        if user is not None:
            return user

    return None


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency: require an admin user."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
