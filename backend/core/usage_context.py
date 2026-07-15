from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class UsageRequestContext:
    trace_id: str | None = None
    user_id: str | None = None
    email: str | None = None
    role: str | None = None
    business_session_id: str | None = None

_context: ContextVar[UsageRequestContext] = ContextVar("usage_request_context", default=UsageRequestContext())
def get_usage_request_context() -> UsageRequestContext: return _context.get()
def set_usage_request_context(context: UsageRequestContext) -> Token: return _context.set(context)
def update_usage_request_context(**values: str | None) -> Token: return _context.set(replace(_context.get(), **values))
def bind_business_session(session_id: str | None) -> Token: return update_usage_request_context(business_session_id=session_id)
def reset_usage_request_context(token: Token) -> None: _context.reset(token)
