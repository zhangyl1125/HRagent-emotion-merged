from __future__ import annotations

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
        report = await self.report_generator.generate(
            state.session_id,
            [],
            retrieved_chunks=self._merge_chunks(retrieved_chunks_by_task or {}),
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            intent=state.intent.model_dump(mode="json", exclude_none=True) if state.intent else {},
            persona=state.persona.model_dump(mode="json", exclude_none=True) if state.persona else {},
            difficulty=state.difficulty.model_dump(mode="json", exclude_none=True) if state.difficulty else {},
            personality=state.personality.model_dump(mode="json", exclude_none=True) if state.personality else {},
            motivation=state.motivation.model_dump(mode="json", exclude_none=True) if state.motivation else {},
            emotion_state=state.emotion_state.model_dump(mode="json", exclude_none=True) if state.emotion_state else {},
            conversation=[turn.model_dump(mode="json", exclude_none=True) for turn in state.conversation],
            emotion_log=[item.model_dump(mode="json", exclude_none=True) for item in state.emotion_log],
        )
        return self._validate_full_report(report)

    async def finalize_report(
        self,
        state: SessionState,
        results: list[CoachTaskResult],
        chunks: dict[str, list[RetrievedChunk]] | None = None,
    ) -> CoachReport:
        failed_tasks = [result.task_name for result in results if result.status == "failed"]
        if failed_tasks:
            raise LLMError(f"Coach LLM subtasks failed: {', '.join(failed_tasks)}")
        report = await self.report_generator.generate(
            state.session_id,
            results,
            retrieved_chunks=self._merge_chunks(chunks or {}),
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            intent=state.intent.model_dump(mode="json", exclude_none=True) if state.intent else {},
            persona=state.persona.model_dump(mode="json", exclude_none=True) if state.persona else {},
            difficulty=state.difficulty.model_dump(mode="json", exclude_none=True) if state.difficulty else {},
            personality=state.personality.model_dump(mode="json", exclude_none=True) if state.personality else {},
            motivation=state.motivation.model_dump(mode="json", exclude_none=True) if state.motivation else {},
            emotion_state=state.emotion_state.model_dump(mode="json", exclude_none=True) if state.emotion_state else {},
            conversation=[turn.model_dump(mode="json", exclude_none=True) for turn in state.conversation],
            emotion_log=[item.model_dump(mode="json", exclude_none=True) for item in state.emotion_log],
        )
        return self._normalize_report_status(report, results)

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
