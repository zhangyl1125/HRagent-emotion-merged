from __future__ import annotations
from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from backend.config.settings import get_settings
from backend.services.auth_session_service import AuthSessionService

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path=request.url.path
        protected=(path.startswith('/api/v1/admin/') or path.startswith('/api/v1/auth/admin/')) and request.method in {'POST','PUT','PATCH','DELETE'}
        if not protected:
            return await call_next(request)
        settings=get_settings(); origin=request.headers.get('origin') or request.headers.get('referer','')
        if origin:
            parsed=urlparse(origin)
            host=request.headers.get('host','').split(':')[0]
            if parsed.hostname and parsed.hostname != host:
                return JSONResponse({'detail':'Invalid request origin'},status_code=403)
        session_id=request.cookies.get(settings.auth_cookie_name)
        if not AuthSessionService().validate_csrf_token(session_id,request.headers.get('x-csrf-token')):
            return JSONResponse({'detail':'Invalid CSRF token'},status_code=403)
        return await call_next(request)
