from __future__ import annotations

from functools import lru_cache

from backend.config.settings import Settings, get_settings
from backend.services.session_service import SessionService
from backend.services.setup_service import SetupService
from backend.services.upload_document import UploadDocumentService
from backend.services.guidance_service import GuidanceService
from backend.services.rehearsal_service import RehearsalService
from backend.services.coach_service import CoachService
from backend.services.employee_database_service import EmployeeDatabaseService


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache
def get_session_service() -> SessionService:
    return SessionService()


@lru_cache
def get_setup_service() -> SetupService:
    return SetupService()


@lru_cache
def get_document_service() -> UploadDocumentService:
    return UploadDocumentService()


@lru_cache
def get_employee_database_service() -> EmployeeDatabaseService:
    return EmployeeDatabaseService()


@lru_cache
def get_guidance_service() -> GuidanceService:
    return GuidanceService()


@lru_cache
def get_rehearsal_service() -> RehearsalService:
    return RehearsalService()


@lru_cache
def get_coach_service() -> CoachService:
    return CoachService()
