"""FastAPI dependencies: auth, DB session, handler wiring."""
from __future__ import annotations

from typing import Annotated, Any, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from db.connection import get_db

security = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> dict[str, Any] | None:
    """Optional Bearer/JWT auth. Disabled by default (AUTH_ENABLED=false);
    enable in production. Returns the decoded claims when active."""
    if not settings.auth_enabled:
        return None
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience or None,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


DbSession = Annotated[AsyncSession, Depends(get_db)]
AuthClaims = Annotated[dict[str, Any] | None, Depends(verify_token)]
