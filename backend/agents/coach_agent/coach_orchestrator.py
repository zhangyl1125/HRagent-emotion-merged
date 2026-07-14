from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from backend.agents.coach_agent.emotion_evaluator import EmotionEvaluator
from backend.agents.coach_agent.performance_evaluator import PerformanceEvaluator
from backend.agents.coach_agent.redline_evaluator import RedlineEvaluator
from backend.agents.coach_agent.report_generator import ReportGenerator
from backend.agents.coach_agent.rubric_evaluator import RubricEvaluator
from backend.exceptions.llm_errors import LLMError
from backend.schemas.coach import CoachReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult


_REQUIRED_TASK_IDS = {
    "rubric_evaluation",
    "emotion_evaluation",
    "performance_evaluation",
    "redline_check",
}
_TASK_ORDER = (
    "rubric_evaluation",
    "emotion_evaluation",
    "performance_evaluation",
    "redline_check",
)

_DYNAMIC_EMOTION_STATE_FIELDS = {
    "current_attitude",
    "previous_attitude",
    "intensity",
    "transition_reason",
    "emotion_band",
    "emotion_description",
    "turn_index",
    "current_vad",
    "current_anchor_id",
    "transition_strategy",
    "last_reason_summary",
    "reply_emotion_guidance",
    "has_manager_response",
}


class CoachOrchestrator:
    """Coordinate LLM-only Coach report generation."""

    def __init__(self):
        self.rubric = RubricEvaluator()
        self.emotion = EmotionEvaluator()
        self.performance = PerformanceEvaluator()
        self.redline = RedlineEvaluator()
        self.report_generator = ReportGenerator()

    async def run(
        self,
        state: SessionState,
        retrieved_chunks_by_task: dict[str, list[RetrievedChunk]] | None = None,
    ) -> CoachReport:
        chunks = retrieved_chunks_by_task or {}
        results = await self.run_tasks(state, chunks)
        return await self.finalize_report(state, results, chunks)

    async def run_tasks(
        self,
        state: SessionState,
        retrieved_chunks_by_task: dict[str, list[RetrievedChunk]] | None = None,
    ) -> list[CoachTaskResult]:
        chunks = retrieved_chunks_by_task or {}
        return list(
            await asyncio.gather(
                *(self.run_task(task_id, state, chunks.get(task_id, [])) for task_id in _TASK_ORDER),
            )
        )

    async def run_task(
        self,
        task_id: str,
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk] | None = None,
    ) -> CoachTaskResult:
        chunks = retrieved_chunks or []
        if task_id == "rubric_evaluation":
            return await self.rubric.evaluate(state, retrieved_chunks=chunks)
        if task_id == "emotion_evaluation":
            return await self.emotion.evaluate(state, retrieved_chunks=chunks)
        if task_id == "performance_evaluation":
            return await self.performance.evaluate(state, retrieved_chunks=chunks)
        if task_id == "redline_check":
            return await self.redline.evaluate(state, retrieved_chunks=chunks)
        raise ValueError(f"Unknown Coach task_id: {task_id}")

    async def finalize_report(
        self,
        state: SessionState,
        results: list[CoachTaskResult],
        chunks: dict[str, list[RetrievedChunk]] | None = None,
    ) -> CoachReport:
        failed_tasks = [result.task_name for result in results if result.status == "failed"]
        if failed_tasks:
            raise LLMError(f"Coach LLM subtasks failed: {', '.join(failed_tasks)}")
        report = await self.report_generator.generate(state.session_id, results, **self.report_context(state, chunks))
        return self._normalize_report_status(report, results)

    def report_context(
        self,
        state: SessionState,
        chunks: dict[str, list[RetrievedChunk]] | None = None,
    ) -> dict:
        return {
            "retrieved_chunks": (chunks or {}).get("report_generator", []),
            "profile": state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            "intent": state.intent.model_dump(mode="json", exclude_none=True) if state.intent else {},
            "personality": state.personality.model_dump(mode="json", exclude_none=True) if state.personality else {},
            "motivation": state.motivation.model_dump(mode="json", exclude_none=True) if state.motivation else {},
            "emotion_state": self._report_emotion_state(state),
            "conversation": [turn.model_dump(mode="json", exclude_none=True) for turn in state.conversation],
            "emotion_log": [item.model_dump(mode="json", exclude_none=True) for item in state.emotion_log],
        }

    def report_from_sections(
        self,
        state: SessionState,
        results: list[CoachTaskResult],
        sections: dict,
        chunks: dict[str, list[RetrievedChunk]] | None = None,
    ) -> CoachReport:
        report = self.report_generator.report_from_sections(
            state.session_id,
            results,
            sections,
            retrieved_chunks=(chunks or {}).get("report_generator", []),
        )
        return self._normalize_report_status(report, results)

    @staticmethod
    def _report_emotion_state(state: SessionState) -> dict:
        if not state.emotion_state:
            return {}
        payload = state.emotion_state.model_dump(mode="json", exclude_none=True)
        if state.motivation is None:
            return payload
        return {
            key: value
            for key, value in payload.items()
            if key in _DYNAMIC_EMOTION_STATE_FIELDS
        }

    @staticmethod
    async def _safe_evaluate(
        task_id: str,
        task_name: str,
        task: Awaitable[CoachTaskResult],
        state: SessionState,
    ) -> CoachTaskResult:
        del task_id, task_name, state
        return await task

    @staticmethod
    def _normalize_report_status(report: CoachReport, task_results: list[CoachTaskResult]) -> CoachReport:
        failed_tasks = [result.task_name for result in task_results if result.status == "failed"]
        if not failed_tasks:
            return report.model_copy(update={"task_results": task_results})
        summary = report.summary or "复盘报告已生成。"
        failure_note = f"部分评估模块未成功完成：{'、'.join(failed_tasks)}。"
        if failure_note not in summary:
            summary = f"{summary} {failure_note}"
        return report.model_copy(
            update={
                "status": "partial",
                "summary": summary,
                "task_results": task_results,
            }
        )

    @staticmethod
    def _merge_chunks(chunks_by_task: dict[str, list[RetrievedChunk]]) -> list[RetrievedChunk]:
        merged: list[RetrievedChunk] = []
        seen: set[str] = set()
        for chunks in chunks_by_task.values():
            for chunk in chunks:
                key = chunk.chunk_id or f"{chunk.source_id}:{chunk.text}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(chunk)
        return merged

    @staticmethod
    def _validate_full_report(report: CoachReport) -> CoachReport:
        task_ids = {result.task_id for result in report.task_results}
        missing = _REQUIRED_TASK_IDS - task_ids
        if missing:
            raise LLMError(f"CoachReport is missing LLM task results: {', '.join(sorted(missing))}")
        failed = [result.task_name for result in report.task_results if result.status == "failed"]
        if failed:
            raise LLMError(f"CoachReport contains failed LLM task results: {', '.join(failed)}")
        return report
