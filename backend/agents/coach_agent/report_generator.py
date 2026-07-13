from __future__ import annotations

import json
from typing import Any

from backend.config.settings import get_settings
from backend.schemas.coach import CoachReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.task import CoachTaskResult
from backend.services.langchain_llm_service import LangChainLLMService
from backend.services.prompt_service import PromptService


def _prompt_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _prompt_payload(item)
            for key, item in value.items()
            if key not in {"created_at", "updated_at"}
        }
    if isinstance(value, (list, tuple)):
        return [_prompt_payload(item) for item in value]
    return value


class ReportGenerator:
    async def generate(
        self,
        session_id: str,
        task_results: list[CoachTaskResult],
        retrieved_chunks: list[RetrievedChunk] | None = None,
        profile: dict | None = None,
        intent: dict | None = None,
        persona: dict | None = None,
        difficulty: dict | None = None,
        personality: dict | None = None,
        motivation: dict | None = None,
        emotion_state: dict | None = None,
        conversation: list[dict] | None = None,
        emotion_log: list[dict] | None = None,
    ) -> CoachReport:
        prompt = PromptService().render(
            "coach/report.jinja2",
            session_id=session_id,
            profile=profile or {},
            intent=intent or {},
            persona=persona or {},
            difficulty=difficulty or {},
            conversation=conversation or [],
            task_results=[result.model_dump(exclude_none=True) for result in task_results],
            emotion_log=emotion_log or [],
            retrieved_chunks=[chunk.model_dump(exclude_none=True) for chunk in (retrieved_chunks or [])],
        )
        dynamic_context = {
            "personality": _prompt_payload(personality or {}),
            "motivation": _prompt_payload(motivation or {}),
            "emotion_state": _prompt_payload(emotion_state or {}),
            "emotion_log": _prompt_payload(emotion_log or []),
        }
        prompt += (
            "\n\n请在 summary、key_improvements 和 next_step 中，在有日志依据时概括 VAD 与诉求满足度的变化及其触发原因。"
            "Big Five、诉求和情绪状态只用于解释模拟中的员工反应与改进建议，不得作为 manager 评分、红线命中或事实结论的独立证据，也不得作心理诊断。"
            "评分与 evidence 仍只能来自 manager/employee 原话、task_results 和检索材料；不得把 system 记录当成 manager 证据。"
            f"\ndynamic_context={json.dumps(dynamic_context, ensure_ascii=False, default=str)}"
        )
        report = await LangChainLLMService().ainvoke_structured(
            prompt=prompt,
            schema=CoachReport,
            task_name="coach_report",
            timeout_seconds=get_settings().llm_timeout_seconds,
        )
        if report.session_id != session_id:
            raise ValueError(f"CoachReport structured_response session_id mismatch: expected {session_id}, got {report.session_id}")
        return report
