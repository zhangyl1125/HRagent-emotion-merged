from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.agents.guidance_agent import (
    GUIDANCE_SECTION_KEYS,
    GUIDANCE_SECTION_TITLES,
    GuidanceSectionKey,
    GuidanceSectionValue,
    _supplemental_info_excerpt,
)
from backend.business_config.loader import get_config_loader
from backend.config.settings import get_settings
from backend.exceptions.workflow_errors import SetupNotReadyError
from backend.repositories.report_repository import ReportRepository
from backend.schemas.guidance import GuidanceReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.services.cache_service import CacheService, cache_digest
from backend.services.retrieval_service import RetrievalService
from backend.services.session_service import SessionService
from backend.workflows.guidance_graph import GuidanceWorkflow


logger = logging.getLogger(__name__)


def _semantic_payload(value: Any) -> Any:
    """Return cache/prompt content without non-semantic runtime timestamps."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _semantic_payload(item)
            for key, item in value.items()
            if key not in {"created_at", "updated_at"}
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_payload(item) for item in value]
    return value


class GuidanceService:
    def __init__(self):
        self.session_service = SessionService()
        self.report_repo = ReportRepository()
        self.retrieval = RetrievalService()
        self.workflow = GuidanceWorkflow()
        self.agent = self.workflow.agent
        self.config_loader = get_config_loader()
        self.settings = get_settings()
        self.cache = CacheService(self.settings)

    async def generate(self, session_id: str) -> GuidanceReport:
        state, chunks = await asyncio.to_thread(self._prepare, session_id)
        cache_key = self._cache_key(state, chunks)
        cached = await asyncio.to_thread(self._cached_report, cache_key, session_id)
        if cached is not None:
            await asyncio.to_thread(self._save_report_state, state, cached)
            return cached

        report = await self.workflow.run(state, chunks)
        await asyncio.to_thread(self._save_report_state, state, report)
        await self.cache.set_json_async(
            cache_key,
            report.model_dump(mode="json"),
            self.settings.guidance_cache_ttl_seconds,
        )
        return report

    async def stream_generate(self, session_id: str) -> AsyncIterator[dict]:
        try:
            state, chunks = await asyncio.to_thread(self._prepare, session_id)
            cache_key = self._cache_key(state, chunks)
            cached = await asyncio.to_thread(self._cached_report, cache_key, session_id)
            yield {"event": "start", "cached": cached is not None}

            if cached is not None:
                saved_state = await asyncio.to_thread(self._save_report_state, state, cached)
                for key, title, text in self._stream_sections(cached):
                    yield {
                        "event": "section_start",
                        "key": key,
                        "title": title,
                        "cached": True,
                    }
                    for delta in self._chunk_text(text):
                        yield {
                            "event": "delta",
                            "key": key,
                            "text": delta,
                            "cached": True,
                        }
                    yield {
                        "event": "section_done",
                        "key": key,
                        "title": title,
                        "cached": True,
                    }
                yield {
                    "event": "done",
                    "complete": True,
                    "cached": True,
                    "report": cached.model_dump(mode="json"),
                    "state": saved_state.model_dump(mode="json"),
                }
                return

            for key in GUIDANCE_SECTION_KEYS:
                yield {
                    "event": "section_start",
                    "key": key,
                    "title": GUIDANCE_SECTION_TITLES[key],
                }

            results: dict[GuidanceSectionKey, GuidanceSectionValue] = {}
            errors: list[dict[str, str]] = []
            queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
            tasks = [
                asyncio.create_task(self._stream_section(state, chunks, key, queue))
                for key in GUIDANCE_SECTION_KEYS
            ]
            pending = len(tasks)

            while pending:
                kind, payload = await queue.get()
                if kind == "event":
                    yield payload
                    continue
                if kind != "result" or not isinstance(payload, dict):
                    continue
                pending -= 1
                key = payload.get("key")
                if key not in GUIDANCE_SECTION_TITLES:
                    continue
                title = GUIDANCE_SECTION_TITLES[key]
                error = payload.get("error")
                value = payload.get("value")
                if error is not None:
                    message = str(error)
                    errors.append({"key": key, "title": title, "message": message})
                    yield {
                        "event": "section_error",
                        "key": key,
                        "title": title,
                        "message": message,
                    }
                    continue
                if value is None:
                    message = f"{title} 未返回内容。"
                    errors.append({"key": key, "title": title, "message": message})
                    yield {
                        "event": "section_error",
                        "key": key,
                        "title": title,
                        "message": message,
                    }
                    continue
                results[key] = value

            await asyncio.gather(*tasks, return_exceptions=True)
            if errors:
                yield {"event": "done", "complete": False, "errors": errors}
                return

            report = self.agent.report_from_sections(state, chunks, results)
            saved_state = await asyncio.to_thread(self._save_report_state, state, report)
            await self.cache.set_json_async(
                cache_key,
                report.model_dump(mode="json"),
                self.settings.guidance_cache_ttl_seconds,
            )
            yield {
                "event": "done",
                "complete": True,
                "cached": False,
                "report": report.model_dump(mode="json"),
                "state": saved_state.model_dump(mode="json"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Guidance stream failed for session_id=%s", session_id)
            yield {"event": "error", "message": str(exc) or type(exc).__name__}

    async def _stream_section(
        self,
        state: SessionState,
        chunks: list[RetrievedChunk],
        key: GuidanceSectionKey,
        queue: asyncio.Queue[tuple[str, object]],
    ) -> None:
        title = GUIDANCE_SECTION_TITLES[key]
        parts: list[str] = []
        try:
            async for delta in self.agent.stream_section(state, chunks, key):
                parts.append(delta)
                await queue.put(("event", {"event": "delta", "key": key, "text": delta}))
            value = "".join(parts).strip()
            if not value:
                raise ValueError(f"Guidance section {key} returned empty text.")
            await queue.put(
                ("event", {"event": "section_done", "key": key, "title": title})
            )
            await queue.put(("result", {"key": key, "value": value, "error": None}))
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Guidance section stream failed: session_id=%s section=%s",
                state.session_id,
                key,
            )
            await queue.put(
                (
                    "result",
                    {"key": key, "value": None, "error": str(exc) or type(exc).__name__},
                )
            )

    def _prepare(self, session_id: str):
        return self._prepare_state(self.session_service.get_session(session_id))

    def _prepare_state(self, state: SessionState):
        if not state.setup_ready:
            raise SetupNotReadyError("请先完成员工信息、面谈目的、人格与诉求设置。")
        context = {
            "intent": state.intent.config if state.intent else {},
            "profile": state.employee_profile,
            "supplemental_info": _supplemental_info_excerpt(state),
            "personality": state.personality,
            "motivation": state.motivation,
            "emotion_state": state.emotion_state,
            "emotion_log": state.emotion_log,
            "company_value_terms": self.config_loader.company_value_terms(),
            "run_mode": state.run_mode,
        }
        retrieval_specs = [("guidance", 8)]
        if self.config_loader.company_values_enabled():
            retrieval_specs.append(("guidance_culture", 4))

        chunks_by_name: dict[str, list[RetrievedChunk]] = {}
        errors_by_name: dict[str, Exception] = {}
        with ThreadPoolExecutor(max_workers=len(retrieval_specs)) as executor:
            futures = {
                executor.submit(self.retrieval.retrieve, name, context, top_k=top_k): name
                for name, top_k in retrieval_specs
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    chunks_by_name[name] = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Guidance retrieval failed for session_id=%s query=%s",
                        state.session_id,
                        name,
                    )
                    chunks_by_name[name] = []
                    errors_by_name[name] = exc

        guidance_chunks = chunks_by_name.get("guidance", [])
        if "guidance" in errors_by_name:
            self._append_warning(
                state,
                f"谈前指导 KB 检索失败，已基于员工信息和本地配置继续生成：{errors_by_name['guidance']}",
            )
        elif not guidance_chunks:
            self._append_warning(
                state,
                "谈前指导 KB 未检索到知识片段，已基于员工信息和本地配置继续生成。",
            )

        culture_chunks = chunks_by_name.get("guidance_culture", [])
        if self.config_loader.company_values_enabled():
            if "guidance_culture" in errors_by_name:
                self._append_warning(
                    state,
                    f"企业文化 KB 检索失败，已使用结构化价值观继续生成：{errors_by_name['guidance_culture']}",
                )
            elif not culture_chunks:
                self._append_warning(
                    state,
                    "企业文化 KB 未检索到知识片段，已使用结构化价值观继续生成。",
                )

        return state, self._merge_chunks(guidance_chunks, culture_chunks)

    @staticmethod
    def _append_warning(state: SessionState, warning: str) -> None:
        if warning not in state.warnings:
            state.warnings.append(warning)

    @staticmethod
    def _merge_chunks(*groups: list[RetrievedChunk]) -> list[RetrievedChunk]:
        merged: dict[str, RetrievedChunk] = {}
        for group in groups:
            for chunk in group:
                current = merged.get(chunk.chunk_id)
                if current is None or (chunk.score or 0.0) > (current.score or 0.0):
                    merged[chunk.chunk_id] = chunk
        return list(merged.values())

    def _save_report_state(self, state: SessionState, report: GuidanceReport):
        self.report_repo.save_guidance(report)
        state.guidance_report_id = state.session_id
        state.stage = "guidance_ready"
        return self.session_service.save_session(state)

    def _cached_report(self, cache_key: str, session_id: str) -> GuidanceReport | None:
        payload = self.cache.get_json(cache_key)
        if not payload:
            return None
        report = GuidanceReport.model_validate(payload)
        return report.model_copy(update={"session_id": session_id})

    def _cache_key(self, state: SessionState, chunks: list[RetrievedChunk]) -> str:
        digest = cache_digest(
            {
                "task": "guidance",
                "profile": _semantic_payload(state.employee_profile),
                "supplemental_info": _supplemental_info_excerpt(state),
                "intent": _semantic_payload(state.intent),
                "personality": _semantic_payload(state.personality),
                "motivation": _semantic_payload(state.motivation),
                "emotion_state": _semantic_payload(state.emotion_state),
                "emotion_log": _semantic_payload(state.emotion_log),
                "run_mode": state.run_mode,
                "culture_version": self.config_loader.culture_version(),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
                "model": self.settings.guidance_model,
                "kb_index_version": self.settings.kb_index_version,
            }
        )
        return self.cache.namespaced("guidance", digest)

    @staticmethod
    def _stream_sections(report: GuidanceReport) -> list[tuple[str, str, str]]:
        return [
            (
                "purpose",
                GUIDANCE_SECTION_TITLES["purpose"],
                GuidanceService._format_text(report.purpose),
            ),
            (
                "opening_suggestion",
                GUIDANCE_SECTION_TITLES["opening_suggestion"],
                GuidanceService._format_text(report.opening_suggestion),
            ),
            (
                "risk_preview",
                GUIDANCE_SECTION_TITLES["risk_preview"],
                GuidanceService._format_list(report.risk_preview),
            ),
            (
                "response_strategies",
                GUIDANCE_SECTION_TITLES["response_strategies"],
                GuidanceService._format_list(report.response_strategies),
            ),
            (
                "safer_phrases",
                GUIDANCE_SECTION_TITLES["safer_phrases"],
                GuidanceService._format_list(report.safer_phrases),
            ),
        ]

    @staticmethod
    def _format_text(value: str) -> str:
        text = str(value or "").strip()
        return f"{text or '未返回内容'}\n"

    @staticmethod
    def _format_list(values: list[str]) -> str:
        items = [str(item).strip() for item in values if str(item).strip()]
        if not items:
            return "未返回内容\n"
        return "".join(f"- {item}\n" for item in items)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 80) -> list[str]:
        if not text:
            return []
        return [text[index:index + chunk_size] for index in range(0, len(text), chunk_size)]

    def get(self, session_id: str) -> GuidanceReport:
        return self.report_repo.get_guidance(session_id)
