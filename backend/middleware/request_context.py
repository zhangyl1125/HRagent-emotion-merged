from __future__ import annotations
import re
from uuid import UUID, uuid4
from starlette.middleware.base import BaseHTTPMiddleware
from backend.core.usage_context import UsageRequestContext, reset_usage_request_context, set_usage_request_context

_SAFE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        supplied = request.headers.get('X-Request-ID', '')
        trace = supplied if _SAFE.fullmatch(supplied) else str(uuid4())
        parts = [part for part in request.url.path.split('/') if part]
        business_session_id = parts[3] if len(parts) > 3 and parts[2] in {'guidance', 'rehearsal', 'reports', 'setup'} else None
        token = set_usage_request_context(UsageRequestContext(trace_id=trace, business_session_id=business_session_id))
        request.state.trace_id = trace
        try:
            response = await call_next(request)
        finally:
            reset_usage_request_context(token)
        response.headers['X-Request-ID'] = trace
        return response
