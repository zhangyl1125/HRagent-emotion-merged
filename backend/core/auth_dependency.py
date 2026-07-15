from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from backend.config.settings import Settings, get_settings
from backend.core.session_context import set_current_auth_user_id
from backend.core.usage_context import update_usage_request_context
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication is required")
    session_id = request.cookies.get(settings.auth_cookie_name)
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    set_current_auth_user_id(session.user_id)
    request.state.auth_user_id = session.user_id
    request.state.auth_email = session.user.email.strip().lower()
    request.state.auth_role = session.role
    update_usage_request_context(user_id=session.user_id, email=session.user.email.strip().lower(), role=session.role)
    return session


def get_current_user(session: AuthSession = Depends(get_current_session)) -> AuthUserResponse:
    return session.user


def require_admin_session(session: AuthSession = Depends(get_current_session)) -> AuthSession:
    if session.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return session


def require_super_admin_session(
    settings: Settings = Depends(get_settings),
    session: AuthSession = Depends(get_current_session),
) -> AuthSession:
    if (not settings.admin_console_enabled or not settings.auth_enabled or session.role != "admin"
            or session.user.email.strip().lower() != settings.admin_super_email.strip().lower()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super administrator access required")
    return session
