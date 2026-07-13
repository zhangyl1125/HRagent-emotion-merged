from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from backend.config.settings import Settings, get_settings
from backend.core.session_context import set_current_auth_user_id
from backend.schemas.auth import AuthUserResponse
from backend.services.auth_session_service import AuthSession, AuthSessionService


@lru_cache
def get_auth_session_service() -> AuthSessionService:
    return AuthSessionService()


async def get_current_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    session_service: AuthSessionService = Depends(get_auth_session_service),
) -> AuthSession:
    if not settings.auth_enabled:
        set_current_auth_user_id("auth-disabled")
        return AuthSession(
            session_id="auth-disabled",
            user=AuthUserResponse(email="local@bosch.com", display_name="Local user", role="admin"),
            user_id="auth-disabled",
            role="admin",
            created_at=0,
            last_seen_at=0,
        )
    session_id = request.cookies.get(settings.auth_cookie_name)
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    set_current_auth_user_id(session.user_id)
    return session


def get_current_user(session: AuthSession = Depends(get_current_session)) -> AuthUserResponse:
    return session.user


def require_admin_session(session: AuthSession = Depends(get_current_session)) -> AuthSession:
    if session.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return session
