from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Request

from backend.config.settings import get_settings
from backend.models.user import AppUser
from backend.repositories.postgres_repository import PostgresRepository
from backend.schemas.auth import AdminAccountCreateRequest, AdminAccountResponse, AdminPasswordResetRequest, AuthUser, AuthUserResponse, LoginRequest, RegisterRequest
from backend.services.auth_session_service import AuthSessionService, MaxActiveSessionsReached
from backend.services.password_service import PasswordPolicyError, PasswordService
from backend.services.rate_limit_service import RateLimitExceeded, RateLimitService
from backend.services.whitelist_service import WhitelistService

_hash_semaphore: asyncio.Semaphore | None = None


def hash_semaphore() -> asyncio.Semaphore:
    global _hash_semaphore
    settings = get_settings()
    if _hash_semaphore is None:
        _hash_semaphore = asyncio.Semaphore(settings.auth_login_hash_max_concurrency)
    return _hash_semaphore


class AuthError(RuntimeError):
    pass


class InvalidCredentials(AuthError):
    pass


class RegistrationFailed(AuthError):
    pass


class SessionLimitReached(AuthError):
    pass


@dataclass(frozen=True)
class LoginResult:
    session_id: str
    user: AuthUserResponse


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.repo = PostgresRepository()
        self.password_service = PasswordService()
        self.whitelist_service = WhitelistService(self.repo)
        self.session_service = AuthSessionService()
        self.rate_limit_service = RateLimitService()

    async def register(self, payload: RegisterRequest, request: Request) -> None:
        ip_address = self._ip_address(request)
        try:
            self.rate_limit_service.check_register(ip_address=ip_address)
            if not self.whitelist_service.is_allowed(payload.email):
                self._audit(payload.email, "register", False, "not_whitelisted", request)
                raise RegistrationFailed("REGISTRATION_FAILED")
            password_hash = self.password_service.hash_password(payload.password)
            with self.repo.connection() as conn:
                row = conn.execute("SELECT id FROM app_users WHERE lower(email::text) = %s", (payload.email,)).fetchone()
                if row:
                    self._audit(payload.email, "register", False, "already_exists", request)
                    raise RegistrationFailed("REGISTRATION_FAILED")
                conn.execute(
                    """
                    INSERT INTO app_users (email, display_name, password_hash, auth_provider, role, is_active, is_email_verified)
                    VALUES (%s, %s, %s, 'local', %s, TRUE, TRUE)
                    """,
                    (payload.email, payload.display_name, password_hash, "admin" if payload.email == self.settings.admin_super_email.strip().lower() else "user"),
                )
            self._audit(payload.email, "register", True, None, request)
        except (PasswordPolicyError, RateLimitExceeded):
            self._audit(payload.email, "register", False, "policy_or_rate_limited", request)
            raise RegistrationFailed("REGISTRATION_FAILED")

    async def login(self, payload: LoginRequest, request: Request) -> LoginResult:
        ip_address = self._ip_address(request)
        try:
            self.rate_limit_service.check_login(email=payload.email, ip_address=ip_address)
        except RateLimitExceeded as exc:
            self._audit(payload.email, "login", False, "rate_limited", request)
            raise InvalidCredentials("INVALID_CREDENTIALS") from exc

        user = self._get_user_by_email(payload.email)
        if not user or not user.is_active or not self.whitelist_service.is_allowed(payload.email):
            self._audit(payload.email, "login", False, "not_allowed", request)
            await self._burn_hash_time(payload.password)
            raise InvalidCredentials("INVALID_CREDENTIALS")
        async with hash_semaphore():
            valid = await asyncio.to_thread(self.password_service.verify_password, payload.password, user.password_hash)
        if not valid:
            self._audit(payload.email, "login", False, "wrong_password", request)
            raise InvalidCredentials("INVALID_CREDENTIALS")
        if self.password_service.needs_rehash(user.password_hash):
            new_hash = self.password_service.hash_password(payload.password)
            self._update_password_hash(user.id, new_hash)
        auth_user = AuthUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            auth_provider=user.auth_provider,
        )
        try:
            session_id = self.session_service.create_session(auth_user)
        except MaxActiveSessionsReached as exc:
            self._audit(payload.email, "login", False, "session_limit_reached", request)
            raise SessionLimitReached("MAX_ACTIVE_SESSIONS_REACHED") from exc
        self._mark_login(user.id)
        self._audit(payload.email, "login", True, None, request)
        return LoginResult(
            session_id=session_id,
            user=AuthUserResponse(email=user.email, display_name=user.display_name, role=user.role),
        )

    def logout(self, session_id: str) -> None:
        self.session_service.delete_session(session_id)

    def list_admin_accounts(self) -> list[AdminAccountResponse]:
        return [AdminAccountResponse.model_validate(row) for row in self.whitelist_service.list_accounts()]

    async def admin_create_account(self, payload: AdminAccountCreateRequest, request: Request) -> AdminAccountResponse:
        if not self._is_bosch_email(payload.email):
            raise RegistrationFailed("BOSCH_EMAIL_REQUIRED")
        try:
            password_hash = await asyncio.to_thread(self.password_service.hash_password, payload.password)
        except PasswordPolicyError as exc:
            raise RegistrationFailed("INVALID_PASSWORD") from exc
        role = "admin" if payload.email == self.settings.admin_super_email.strip().lower() else "user"
        self.whitelist_service.set_allowed(payload.email, True, actor_email=self._actor_email(request))
        with self.repo.connection() as conn:
            conn.execute(
                """
                INSERT INTO app_users (email, display_name, password_hash, auth_provider, role, is_active, is_email_verified)
                VALUES (%s, %s, %s, 'local', %s, TRUE, TRUE)
                ON CONFLICT (email) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, app_users.display_name),
                    password_hash = EXCLUDED.password_hash, role = EXCLUDED.role,
                    is_active = TRUE, is_email_verified = TRUE, updated_at = NOW()
                """,
                (payload.email, payload.display_name, password_hash, role),
            )
        self._audit(payload.email, "admin_create_account", True, None, request)
        return self._admin_account(payload.email)

    async def admin_reset_password(self, email: str, payload: AdminPasswordResetRequest, request: Request) -> AdminAccountResponse:
        normalized = email.strip().lower()
        try:
            password_hash = await asyncio.to_thread(self.password_service.hash_password, payload.password)
        except PasswordPolicyError as exc:
            raise RegistrationFailed("INVALID_PASSWORD") from exc
        with self.repo.connection() as conn:
            row = conn.execute(
                """
                UPDATE app_users SET password_hash = %s, updated_at = NOW()
                WHERE lower(email::text) = %s
                RETURNING id::text
                """,
                (password_hash, normalized),
            ).fetchone()
            if row is None:
                raise RegistrationFailed("ACCOUNT_NOT_FOUND")
        self.session_service.delete_user_sessions(row["id"])
        self._audit(normalized, "admin_reset_password", True, None, request)
        return self._admin_account(normalized)

    def admin_set_whitelist(self, email: str, enabled: bool, request: Request) -> AdminAccountResponse:
        normalized = email.strip().lower()
        if not self._is_bosch_email(normalized):
            raise RegistrationFailed("BOSCH_EMAIL_REQUIRED")
        if normalized == self.settings.admin_super_email.strip().lower() and not enabled:
            raise RegistrationFailed("ADMIN_WHITELIST_REQUIRED")
        self.whitelist_service.set_allowed(normalized, enabled, actor_email=self._actor_email(request))
        user = self._get_user_by_email(normalized)
        if not enabled and user:
            with self.repo.connection() as conn:
                conn.execute("UPDATE app_users SET is_active = FALSE, updated_at = NOW() WHERE id = %s", (user.id,))
            self.session_service.delete_user_sessions(user.id)
        elif enabled and user:
            with self.repo.connection() as conn:
                conn.execute("UPDATE app_users SET is_active = TRUE, updated_at = NOW() WHERE id = %s", (user.id,))
        self._audit(normalized, "admin_update_whitelist", True, None, request)
        return self._admin_account(normalized)

    def admin_delete_account(self, email: str, request: Request) -> None:
        normalized = email.strip().lower()
        if normalized == self.settings.admin_super_email.strip().lower():
            raise RegistrationFailed("ADMIN_ACCOUNT_REQUIRED")
        with self.repo.connection() as conn:
            whitelist = conn.execute(
                "SELECT 1 FROM auth_whitelist WHERE lower(email::text) = %s",
                (normalized,),
            ).fetchone()
            user = conn.execute(
                "SELECT id::text FROM app_users WHERE lower(email::text) = %s",
                (normalized,),
            ).fetchone()
            if whitelist is None and user is None:
                raise RegistrationFailed("ACCOUNT_NOT_FOUND")
            conn.execute("DELETE FROM auth_whitelist WHERE lower(email::text) = %s", (normalized,))
            conn.execute(
                "UPDATE app_users SET is_active = FALSE, updated_at = NOW() WHERE lower(email::text) = %s",
                (normalized,),
            )
            if conn.execute("SELECT to_regclass('public.locust_test_credentials') AS table_name").fetchone()["table_name"]:
                conn.execute(
                    "UPDATE locust_test_credentials SET enabled = FALSE, updated_at = NOW() WHERE lower(email::text) = %s",
                    (normalized,),
                )
        if user:
            self.session_service.delete_user_sessions(user["id"])
        self._audit(normalized, "admin_delete_account", True, None, request)

    def _admin_account(self, email: str) -> AdminAccountResponse:
        normalized = email.strip().lower()
        rows = self.whitelist_service.list_accounts()
        row = next((item for item in rows if item["email"].lower() == normalized), None)
        if row is None:
            raise RegistrationFailed("ACCOUNT_NOT_FOUND")
        return AdminAccountResponse.model_validate(row)

    def _get_user_by_email(self, email: str) -> AppUser | None:
        with self.repo.connection() as conn:
            row = conn.execute(
                """
                SELECT id::text, email::text, display_name, password_hash, auth_provider,
                       provider_subject, role, is_active, is_email_verified
                FROM app_users
                WHERE lower(email::text) = %s
                """,
                (email.strip().lower(),),
            ).fetchone()
        if not row:
            return None
        return AppUser(**row)

    def _update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self.repo.connection() as conn:
            conn.execute("UPDATE app_users SET password_hash = %s, updated_at = NOW() WHERE id = %s", (password_hash, user_id))

    def _mark_login(self, user_id: str) -> None:
        with self.repo.connection() as conn:
            conn.execute("UPDATE app_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = %s", (user_id,))

    def _audit(self, email: str | None, event_type: str, success: bool, reason: str | None, request: Request) -> None:
        try:
            with self.repo.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO auth_audit_log (email, event_type, success, reason, ip_address, user_agent, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        email.strip().lower() if email else None,
                        event_type,
                        success,
                        reason,
                        self._ip_address(request),
                        request.headers.get("user-agent"),
                        datetime.now(timezone.utc),
                    ),
                )
        except Exception:
            return

    async def _burn_hash_time(self, password: str) -> None:
        async with hash_semaphore():
            await asyncio.to_thread(self.password_service.verify_password, password, "$argon2id$v=19$m=19456,t=2,p=1$bGltaXRlZGxvZ2luYnVybjE2Yg$4t8C5JTy1rAf0FwwaSYW4Hx2DKPbfv0QW3khn3Y/yfI")

    @staticmethod
    def _actor_email(request: Request) -> str | None:
        value = getattr(request.state, "auth_email", None)
        return str(value).strip().lower() if value else None

    @staticmethod
    def _is_bosch_email(email: str) -> bool:
        domain = email.strip().lower().partition("@")[2]
        return domain == "bosch.com" or domain.endswith(".bosch.com")

    @staticmethod
    def _ip_address(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
        return request.client.host if request.client else "0.0.0.0"
