from __future__ import annotations

from typing import Any

from backend.schemas.conversation import ConversationTurn
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.task import CoachTaskResult, EvidenceRef
from backend.services.langchain_llm_service import LangChainLLMService
from backend.services.prompt_service import PromptService


class GenericCoachAgent:
    def manager_turns(self, conversation: list[ConversationTurn]) -> list[ConversationTurn]:
        return [turn for turn in conversation if turn.speaker == "manager"]

    def employee_turns(self, conversation: list[ConversationTurn]) -> list[ConversationTurn]:
        return [turn for turn in conversation if turn.speaker == "employee"]

    def evidence_from_turn(self, turn: ConversationTurn, note: str | None = None) -> EvidenceRef:
        return EvidenceRef(turn_index=turn.turn_index, speaker=turn.speaker, quote=turn.text[:240], note=note)

    def conversation_payload(self, conversation: list[ConversationTurn]) -> list[dict[str, Any]]:
        return [turn.model_dump(exclude_none=True) for turn in conversation]

    async def run_llm_task(
        self,
        *,
        task_id: str,
        task_name: str,
        prompt_template: str,
        task_model_name: str,
        **prompt_vars: Any,
    ) -> CoachTaskResult:
        prompt = PromptService().render(prompt_template, **prompt_vars)
        result = await LangChainLLMService().ainvoke_structured(
            prompt=prompt,
            schema=CoachTaskResult,
            task_name=task_model_name,
            timeout_seconds=5,
        )
        if result.task_id != task_id:
            raise ValueError(f"Coach task structured_response task_id mismatch: expected {task_id}, got {result.task_id}")
        if result.task_name != task_name:
            raise ValueError(f"Coach task structured_response task_name mismatch: expected {task_name}, got {result.task_name}")
        return result

    @staticmethod
    def chunks_payload(chunks: list[RetrievedChunk] | None) -> list[dict[str, Any]]:
        return [chunk.model_dump(exclude_none=True) for chunk in (chunks or [])]
