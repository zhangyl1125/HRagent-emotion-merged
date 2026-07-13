from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from backend.config.settings import get_settings
from backend.exceptions.workflow_errors import WorkflowError
from backend.repositories.report_repository import ReportRepository
from backend.services.retrieval_service import RetrievalService
from backend.services.session_service import SessionService
from backend.services.cache_service import CacheService, cache_digest
from backend.schemas.coach import CoachReport
from backend.schemas.retrieval import RetrievedChunk
from backend.workflows.coach_graph import CoachWorkflow


logger = logging.getLogger(__name__)


def _semantic_payload(value: Any) -> Any:
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


_REPORT_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}
_REPORT_GATES: dict[tuple[int, int], asyncio.Semaphore] = {}


def _report_lock(session_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), session_id)
    lock = _REPORT_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _REPORT_LOCKS[key] = lock
    return lock


def _report_generation_gate(limit: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    safe_limit = max(1, limit)
    key = (id(loop), safe_limit)
    gate = _REPORT_GATES.get(key)
    if gate is None:
        gate = asyncio.Semaphore(safe_limit)
        _REPORT_GATES[key] = gate
    return gate


class CoachService:
    def __init__(self):
        self.session_service = SessionService()
        self.report_repo = ReportRepository()
        self.orchestrator = CoachWorkflow()
        self.retrieval = RetrievalService()
        self.settings = get_settings()
        self.cache = CacheService(self.settings)

    async def generate(self, session_id: str) -> CoachReport:
        state = await asyncio.to_thread(self.session_service.get_session, session_id)
        cached = await asyncio.to_thread(self._cached_report, session_id, state)
        if cached is not None:
            return cached
        cache_key = self._cache_key(state)
        cached = await self._cached_content_report(cache_key, session_id)
        if cached is not None:
            await asyncio.to_thread(self._save_report_state, state, cached)
            return cached

        async with _report_lock(session_id):
            state = await asyncio.to_thread(self.session_service.get_session, session_id)
            cached = await asyncio.to_thread(self._cached_report, session_id, state)
            if cached is not None:
                return cached
            cache_key = self._cache_key(state)
            cached = await self._cached_content_report(cache_key, session_id)
            if cached is not None:
                await asyncio.to_thread(self._save_report_state, state, cached)
                return cached

            report = await self._generate_uncached(session_id, state)
            await self.cache.set_json_async(
                cache_key,
                report.model_dump(mode="json"),
                self.settings.guidance_cache_ttl_seconds,
            )
            return report

    async def stream_generate(self, session_id: str) -> AsyncIterator[dict]:
        state = await asyncio.to_thread(self.session_service.get_session, session_id)
        if len([turn for turn in state.conversation if turn.speaker == "manager"]) == 0:
            raise WorkflowError("缺少预演对话，无法生成 CoachReport。")

        task_specs = (
            ("rubric_evaluation", "Rubric 综合评估"),
            ("emotion_evaluation", "情绪承接评估"),
            ("performance_evaluation", "绩效反馈质量评估"),
            ("redline_check", "话术红线检测"),
        )
        for task_id, task_name in task_specs:
            yield {"event": "task_start", "task_id": task_id, "task_name": task_name}

        report = await self.generate(session_id)
        results_by_task = {result.task_id: result for result in report.task_results}
        for task_id, task_name in task_specs:
            result = results_by_task.get(task_id)
            if result is None:
                raise WorkflowError(f"CoachReport 缺少大模型评估结果：{task_id}")
            yield {
                "event": "task_done",
                "task_id": task_id,
                "task_name": task_name,
                "result": result.model_dump(mode="json"),
            }

        refreshed = await asyncio.to_thread(self.session_service.get_session, session_id)
        async for event in self._stream_report_sections(report):
            yield event
        yield {
            "event": "done",
            "report": report.model_dump(mode="json"),
            "state": refreshed.model_dump(mode="json"),
        }

    async def _stream_report_sections(self, report: CoachReport) -> AsyncIterator[dict]:
        sections = [
            ("summary_score", "综合结论与评分", self._summary_score_text(report)),
            ("risks", "风险提示", self._bullet_text(report.top_risks, "explanation")),
            ("strengths_improvements", "优势与待改进", self._strengths_improvements_text(report)),
            ("better_phrases", "建议话术", self._bullet_text(report.better_phrases, "suggestion")),
            ("next_step", "下一步建议", report.next_step or report.disclaimer),
        ]
        for key, title, text in sections:
            yield {"event": "section_start", "key": key, "title": title}
            if text:
                yield {"event": "section_delta", "key": key, "text": text}
            yield {"event": "section_done", "key": key, "title": title}
            await asyncio.sleep(0)

    @staticmethod
    def _summary_score_text(report: CoachReport) -> str:
        score = f"{report.overall_score}/100" if report.overall_score is not None else "暂无评分"
        return f"综合评分：{score}\n{report.summary}"

    @staticmethod
    def _strengths_improvements_text(report: CoachReport) -> str:
        strengths = CoachService._bullet_text(report.key_strengths)
        improvements = CoachService._bullet_text(report.key_improvements)
        if strengths and improvements:
            return f"优势：\n{strengths}\n\n待改进：\n{improvements}"
        return strengths or improvements

    @staticmethod
    def _bullet_text(values: list[object], attr: str | None = None) -> str:
        lines: list[str] = []
        for value in values:
            if attr:
                item = getattr(value, attr, None)
                if item is None and isinstance(value, dict):
                    item = value.get(attr)
            else:
                item = value
            text = str(item or "").strip()
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines)

    def _cached_report(self, session_id: str, state) -> CoachReport | None:
        if state.coach_report_id:
            try:
                report = self.report_repo.get_coach(session_id)
            except KeyError:
                logger.warning("Coach report id exists but report is missing; regenerating session_id=%s", session_id)
            else:
                if self._is_complete_llm_report(report):
                    return report
                logger.warning("Cached Coach report is not a complete LLM report; regenerating session_id=%s", session_id)
        return None

    async def _cached_content_report(self, cache_key: str, session_id: str) -> CoachReport | None:
        payload = await self.cache.get_json_async(cache_key)
        if not payload:
            return None
        report = CoachReport.model_validate(payload).model_copy(update={"session_id": session_id})
        return report if self._is_complete_llm_report(report) else None

    @staticmethod
    def _is_complete_llm_report(report: CoachReport) -> bool:
        required_task_ids = {
            "rubric_evaluation",
            "emotion_evaluation",
            "performance_evaluation",
            "redline_check",
        }
        task_ids = {result.task_id for result in report.task_results}
        return (
            required_task_ids.issubset(task_ids)
            and all(result.status != "failed" for result in report.task_results)
            and all(not result.extra.get("local_fallback") for result in report.task_results)
        )

    def _save_report_state(self, state, report: CoachReport) -> None:
        self.report_repo.save_coach(report)
        state.coach_report_id = state.session_id
        state.stage = "report_ready"
        self.session_service.save_session(state)

    async def _generate_uncached(self, session_id: str, state) -> CoachReport:
        if len([turn for turn in state.conversation if turn.speaker == "manager"]) == 0:
            raise WorkflowError("缺少预演对话，无法生成 CoachReport。")
        context = {
            "intent": state.intent.config if state.intent else {},
            "profile": state.employee_profile,
            "persona": state.persona,
            "difficulty": state.difficulty,
            "personality": _semantic_payload(state.personality),
            "motivation": _semantic_payload(state.motivation),
            "emotion_state": _semantic_payload(state.emotion_state),
            "emotion_log": _semantic_payload(state.emotion_log),
            "conversation": state.conversation,
            "run_mode": state.run_mode,
        }
        task_ids = ("redline_check", "report_generator")
        retrieval_results = await asyncio.gather(
            *(self._retrieve_task_chunks(session_id, task_id, context) for task_id in task_ids)
        )
        chunks_by_task = {task_id: chunks for task_id, chunks, _warning in retrieval_results}
        gate = _report_generation_gate(self.settings.coach_report_max_concurrency_per_worker)
        async with gate:
            report = await self.orchestrator.run(state, retrieved_chunks_by_task=chunks_by_task)
        await asyncio.to_thread(self._save_report_state, state, report)
        return report

    def _cache_key(self, state) -> str:
        digest = cache_digest({
            "task": "coach_report",
            "profile": state.employee_profile.model_dump(mode="json") if state.employee_profile else None,
            "intent": state.intent.model_dump(mode="json") if state.intent else None,
            "persona": state.persona.model_dump(mode="json") if state.persona else None,
            "difficulty": state.difficulty.model_dump(mode="json") if state.difficulty else None,
            "personality": _semantic_payload(state.personality),
            "motivation": _semantic_payload(state.motivation),
            "emotion_state": _semantic_payload(state.emotion_state),
            "dynamic_emotion_log": _semantic_payload(state.emotion_log),
            "run_mode": state.run_mode,
            "conversation": [
                {
                    "turn_index": turn.turn_index,
                    "speaker": turn.speaker,
                    "text": turn.text,
                    "metadata": turn.metadata,
                }
                for turn in state.conversation
            ],
            "emotion_log": [
                {
                    "turn_index": item.turn_index,
                    "hrbp_text": item.hrbp_text,
                    "input_mode": item.input_mode,
                    "audio_emotion": item.audio_emotion,
                    "employee_attitude_before": item.employee_attitude_before,
                    "employee_attitude_after": item.employee_attitude_after,
                    "intensity": item.intensity,
                    "transition_reason": item.transition_reason,
                    "employee_reply": item.employee_reply,
                    "signal": item.signal.model_dump(mode="json") if item.signal else None,
                }
                for item in state.emotion_log
            ],
            "models": {
                task_name: self.settings.model_for_task(task_name)
                for task_name in ("coach_evaluator", "coach_redline", "coach_report")
            },
            "max_tokens": {
                task_name: self.settings.max_tokens_for_task(task_name)
                for task_name in ("coach_evaluator", "coach_redline", "coach_report")
            },
            "kb_index_version": self.settings.kb_index_version,
        })
        return self.cache.namespaced("coach_report", digest)

    async def _retrieve_task_chunks(
        self,
        session_id: str,
        task_id: str,
        context: dict,
    ) -> tuple[str, list[RetrievedChunk], None]:
        chunks = await asyncio.to_thread(self.retrieval.retrieve, task_id, context)
        if not chunks:
            raise WorkflowError(f"Coach KB 未检索到 {task_id} 所需知识片段，无法生成复盘报告。")
        logger.debug(
            "Coach retrieval completed session_id=%s task_id=%s chunks=%s",
            session_id,
            task_id,
            len(chunks),
        )
        return task_id, chunks, None

    def get(self, session_id: str) -> CoachReport:
        return self.report_repo.get_coach(session_id)
