from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("INVALID_EMAIL")
        return email


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class AuthUser(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    role: str = "user"
    auth_provider: str = "local"


class AuthUserResponse(BaseModel):
    email: str
    display_name: str | None = None
    role: str = "user"


class AuthSuccessResponse(BaseModel):
    success: bool = True
    message: str | None = None
    user: AuthUserResponse | None = None


class AuthMeResponse(BaseModel):
    authenticated: bool
    user: AuthUserResponse | None = None


class AdminAccountCreateRequest(RegisterRequest):
    pass


class AdminPasswordResetRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class AdminWhitelistUpdateRequest(BaseModel):
    email: str
    enabled: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return RegisterRequest.normalize_email(value)


class AdminAccountResponse(BaseModel):
    email: str
    display_name: str | None = None
    role: str = "user"
    whitelist_enabled: bool
    registered: bool
    is_active: bool


class AdminAccountsResponse(BaseModel):
    items: list[AdminAccountResponse] = Field(default_factory=list)
