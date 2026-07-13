from __future__ import annotations

from fastapi import APIRouter, Depends
from backend.api.dependencies import get_app_settings
from backend.config.settings import Settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(settings: Settings = Depends(get_app_settings)) -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version, "environment": settings.environment}
