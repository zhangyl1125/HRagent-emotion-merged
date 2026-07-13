from __future__ import annotations

from contextvars import ContextVar

_current_auth_user_id: ContextVar[str | None] = ContextVar("current_auth_user_id", default=None)


def set_current_auth_user_id(user_id: str | None) -> None:
    _current_auth_user_id.set(user_id)


def get_current_auth_user_id() -> str | None:
    return _current_auth_user_id.get()
