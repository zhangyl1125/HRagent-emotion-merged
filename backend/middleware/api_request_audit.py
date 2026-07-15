from __future__ import annotations
import time
from uuid import UUID
from starlette.middleware.base import BaseHTTPMiddleware
from backend.repositories.postgres_repository import PostgresRepository

class ApiRequestAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        started=time.perf_counter(); response=await call_next(request)
        path=request.url.path
        if not path.startswith('/api/') or path.endswith('/health') or path.startswith('/api/v1/auth') or path in {'/docs','/openapi.json'}:
            return response
        try:
            route=getattr(request.scope.get('route'),'path',None) or path
            with PostgresRepository().connection() as conn:
                conn.execute('INSERT INTO api_request_events(trace_id,user_id,email_snapshot,method,route_template,status_code,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)',(
                    request.state.trace_id if len(request.state.trace_id)==36 else None,
                    getattr(request.state,'auth_user_id',None),getattr(request.state,'auth_email',None),request.method,route,response.status_code,int((time.perf_counter()-started)*1000)))
        except Exception:
            pass
        return response
