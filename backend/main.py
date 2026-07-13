from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.error_handlers import register_error_handlers
from backend.api.routes import asr, auth, documents, employees, guidance, health, rehearsal, reports, sessions, setup, tts
from backend.config.settings import get_settings
from backend.core.auth_dependency import get_current_user
from backend.services.langchain_llm_service import close_shared_http_clients


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_shared_http_clients()



def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    protected_routers = [sessions.router, documents.router, employees.router, setup.router, guidance.router, rehearsal.router, reports.router, tts.router]
    for router in protected_routers:
        dependencies = [Depends(get_current_user)] if settings.auth_enabled else []
        app.include_router(router, prefix=settings.api_prefix, dependencies=dependencies)
    app.include_router(asr.router, prefix=settings.api_prefix)
    return app


app = create_app()
