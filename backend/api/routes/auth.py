from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.config.settings import Settings, get_settings
from backend.core.auth_dependency import get_auth_session_service, get_current_session, require_super_admin_session
from backend.schemas.auth import AdminAccountCreateRequest, AdminAccountResponse, AdminAccountsResponse, AdminPasswordResetRequest, AdminWhitelistUpdateRequest, AuthMeResponse, AuthSuccessResponse, AuthUserResponse, LoginRequest, RegisterRequest
from backend.services.auth_service import AuthService, InvalidCredentials, RegistrationFailed, SessionLimitReached
from backend.services.auth_session_service import AuthSession, AuthSessionService

router = APIRouter(prefix="/auth", tags=["auth"])


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()


@router.post("/register", response_model=AuthSuccessResponse)
async def register(payload: RegisterRequest, request: Request, auth_service: AuthService = Depends(get_auth_service)):
    try:
        await auth_service.register(payload, request)
        return AuthSuccessResponse(success=True, message="Account created. Please sign in.")
    except RegistrationFailed:
        return AuthSuccessResponse(success=False, message="Registration failed. Please check your information or contact administrator.")


@router.post("/login", response_model=AuthSuccessResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        result = await auth_service.login(payload, request)
    except SessionLimitReached as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System is busy. Please try again later.") from exc
    except InvalidCredentials as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.") from exc
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=result.session_id,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.auth_session_absolute_timeout_seconds,
        path="/",
    )
    return AuthSuccessResponse(success=True, user=result.user)


@router.get("/csrf")
async def csrf_token(current_session: AuthSession = Depends(get_current_session), session_service: AuthSessionService = Depends(get_auth_session_service)):
    return {"csrf_token": session_service.create_csrf_token(current_session.session_id)}


@router.get("/me", response_model=AuthMeResponse)
async def me(current_session: AuthSession = Depends(get_current_session)):
    return AuthMeResponse(authenticated=True, user=current_session.user)


@router.post("/logout", response_model=AuthSuccessResponse)
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
    current_session: AuthSession = Depends(get_current_session),
):
    auth_service.logout(current_session.session_id)
    response.delete_cookie(settings.auth_cookie_name, path="/")
    return AuthSuccessResponse(success=True)


@router.get("/oidc/login")
async def oidc_login():
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="SSO login is reserved but not enabled yet.")


@router.get("/admin/accounts", response_model=AdminAccountsResponse)
async def admin_accounts(
    _admin: AuthSession = Depends(require_super_admin_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    return AdminAccountsResponse(items=auth_service.list_admin_accounts())


@router.post("/admin/accounts", response_model=AdminAccountResponse)
async def admin_create_account(
    payload: AdminAccountCreateRequest,
    request: Request,
    _admin: AuthSession = Depends(require_super_admin_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        return await auth_service.admin_create_account(payload, request)
    except RegistrationFailed as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to create account") from exc


@router.patch("/admin/accounts/{email}/password", response_model=AdminAccountResponse)
async def admin_reset_password(
    email: str,
    payload: AdminPasswordResetRequest,
    request: Request,
    _admin: AuthSession = Depends(require_super_admin_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        return await auth_service.admin_reset_password(email, payload, request)
    except RegistrationFailed as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found") from exc


@router.delete("/admin/accounts/{email}", response_model=AuthSuccessResponse)
async def admin_delete_account(
    email: str,
    request: Request,
    _admin: AuthSession = Depends(require_super_admin_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        auth_service.admin_delete_account(email, request)
        return AuthSuccessResponse(success=True, message="Account access removed.")
    except RegistrationFailed as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to delete account") from exc


@router.put("/admin/whitelist", response_model=AdminAccountResponse)
async def admin_update_whitelist(
    payload: AdminWhitelistUpdateRequest,
    request: Request,
    _admin: AuthSession = Depends(require_super_admin_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        return auth_service.admin_set_whitelist(payload.email, payload.enabled, request)
    except RegistrationFailed as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to update whitelist") from exc
