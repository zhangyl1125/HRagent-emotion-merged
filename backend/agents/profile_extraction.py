from __future__ import annotations

import json
from typing import Any

from backend.schemas.profile import EmployeeProfile
from backend.services.langchain_llm_service import LangChainLLMService
from backend.services.prompt_service import PromptService
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class ProfileExtractionAgent:
    """Employee profile extraction with a local structured fast path."""

    async def extract(self, document_text: str) -> EmployeeProfile:
        local_profile = self._extract_from_json_text(document_text)
        if local_profile and local_profile.employee_alias:
            logger.info(
                "profile.extract.local_json employee_alias_set=%s ready=%s",
                bool(local_profile.employee_alias),
                local_profile.is_ready_for_setup(),
            )
            return local_profile
        return await self._extract_with_llm(document_text)

    async def _extract_with_llm(self, document_text: str) -> EmployeeProfile:
        logger.info("profile.extract.start text_chars=%s", len(document_text or ""))
        prompt = PromptService().render("profile/extraction.jinja2", document_text=document_text)
        profile = await LangChainLLMService().ainvoke_structured(
            prompt=prompt,
            schema=EmployeeProfile,
            task_name="profile",
        )
        profile = self._fill_missing_fields_from_json_text(profile, document_text)
        if not profile.employee_alias:
            raise ValueError("Profile extraction failed: employee_alias is missing from structured_response.")
        logger.info("profile.extract.done employee_alias_set=%s ready=%s", bool(profile.employee_alias), profile.is_ready_for_setup())
        return profile

    @staticmethod
    def _extract_from_json_text(document_text: str) -> EmployeeProfile | None:
        try:
            raw = json.loads(document_text)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return EmployeeProfile.model_validate(raw)
        except Exception:
            return None

    @staticmethod
    def _fill_missing_fields_from_json_text(profile: EmployeeProfile, document_text: str) -> EmployeeProfile:
        fallback = ProfileExtractionAgent._extract_from_json_text(document_text)
        if fallback is None:
            return profile

        fields: dict[str, Any] = getattr(EmployeeProfile, "model_fields", {})
        for field_name in fields:
            current = getattr(profile, field_name, None)
            candidate = getattr(fallback, field_name, None)
            if ProfileExtractionAgent._is_empty(current) and not ProfileExtractionAgent._is_empty(candidate):
                setattr(profile, field_name, candidate)
        return profile

    @staticmethod
    def _is_empty(value: Any) -> bool:
        return value is None or value == [] or value == {}
