from __future__ import annotations

import asyncio
from pathlib import Path

from backend.config.settings import get_settings
from backend.repositories.document_repository import DocumentRepository
from backend.schemas.document import DocumentRecord
from backend.schemas.profile import EmployeeProfile
from backend.services.cache_service import CacheService, cache_digest, sha256_text
from backend.services.document_pipeline import DocumentPipeline
from backend.services.session_service import SessionService
from backend.workflows.setup_graph import ProfileExtractionWorkflow


class UploadDocumentService:
    def __init__(self):
        self.repo = DocumentRepository()
        self.pipeline = DocumentPipeline()
        self.profile_workflow = ProfileExtractionWorkflow()
        self.session_service = SessionService()
        self.settings = get_settings()
        self.cache = CacheService(self.settings)

    async def process_text(self, text: str, filename: str | None = None, session_id: str | None = None) -> DocumentRecord:
        document_id = self.repo.new_id()
        cached_record = await self._cached_text_record(
            text=text,
            document_id=document_id,
            filename=filename,
        )
        if cached_record is not None:
            await asyncio.to_thread(self.repo.save, cached_record)
            if session_id:
                await asyncio.to_thread(self._save_profile_to_session, session_id, cached_record.profile, include_missing_warning=True)
            return cached_record

        parsed = await asyncio.to_thread(self.pipeline.parse_text, text=text, document_id=document_id, filename=filename)
        profile = await self._extract_profile(parsed.text)
        record = DocumentRecord(
            document_id=document_id,
            filename=filename,
            parsed_text=parsed.text,
            profile=profile,
            pages=parsed.pages,
            blocks=parsed.blocks,
            tables=parsed.tables,
            images=parsed.images,
            metadata=parsed.metadata,
        )
        await asyncio.to_thread(self.repo.save, record)
        if session_id:
            await asyncio.to_thread(self._save_profile_to_session, session_id, profile, include_missing_warning=True)
        await self._cache_text_record(text=text, record=record)
        return record

    async def process_file(self, path: Path, session_id: str | None = None) -> DocumentRecord:
        document_id = self.repo.new_id()
        parsed = await asyncio.to_thread(self.pipeline.parse_file, path=path, document_id=document_id, fast_mode=True)
        profile = await self._extract_profile(parsed.text)
        record = DocumentRecord(
            document_id=document_id,
            filename=path.name,
            raw_path=str(path),
            parsed_text=parsed.text,
            profile=profile,
            pages=parsed.pages,
            blocks=parsed.blocks,
            tables=parsed.tables,
            images=parsed.images,
            metadata=parsed.metadata,
        )
        await asyncio.to_thread(self.repo.save, record)
        if session_id:
            await asyncio.to_thread(self._save_profile_to_session, session_id, profile, include_missing_warning=False)
        return record

    async def _extract_profile(self, text: str) -> EmployeeProfile:
        key = self._profile_cache_key(text)
        cached = await self.cache.get_json_async(key)
        if cached:
            return EmployeeProfile.model_validate(cached)

        profile = await self.profile_workflow.extract(text)
        await self.cache.set_json_async(
            key,
            profile.model_dump(mode="json"),
            self.settings.document_parse_cache_ttl_seconds,
        )
        return profile

    def _profile_cache_key(self, text: str) -> str:
        digest = cache_digest({
            "kind": "profile_extraction",
            "text_hash": sha256_text(text),
            "model": self.settings.profile_model,
            "version": "v2",
        })
        return self.cache.namespaced("profile_extract", digest)

    async def _cached_text_record(
        self,
        *,
        text: str,
        document_id: str,
        filename: str | None,
    ) -> DocumentRecord | None:
        payload = await self.cache.get_json_async(self._text_record_cache_key(text))
        if not payload:
            return None
        record = DocumentRecord.model_validate(payload)
        metadata = dict(record.metadata or {})
        metadata["cache_hit"] = True
        return record.model_copy(update={
            "document_id": document_id,
            "filename": filename,
            "metadata": metadata,
        })

    async def _cache_text_record(self, *, text: str, record: DocumentRecord) -> None:
        await self.cache.set_json_async(
            self._text_record_cache_key(text),
            record.model_dump(mode="json"),
            self.settings.document_parse_cache_ttl_seconds,
        )

    def _text_record_cache_key(self, text: str) -> str:
        digest = cache_digest({
            "kind": "text_document_record",
            "text_hash": sha256_text(text),
            "parser": "native_text",
            "profile_model": self.settings.profile_model,
            "version": "v2",
        })
        return self.cache.namespaced("doc_record", digest)

    def _save_profile_to_session(
        self,
        session_id: str,
        profile: EmployeeProfile,
        *,
        include_missing_warning: bool,
    ) -> None:
        state = self.session_service.get_session(session_id)
        state.employee_profile = profile
        state.stage = "profile_ready" if profile.is_ready_for_setup() else "created"
        if include_missing_warning and not profile.is_ready_for_setup():
            warning = f"缺少必填字段: {', '.join(profile.missing_required_fields())}"
            if warning not in state.warnings:
                state.warnings.append(warning)
        self.session_service.save_session(state)
