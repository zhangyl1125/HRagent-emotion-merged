from __future__ import annotations

import json
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
        rendered_prompt = PromptService().render(prompt_template, **prompt_vars)
        prompt = f"{rendered_prompt}\n\n只输出 CoachTaskResult JSON object，不要输出 Markdown 或额外解释。必须返回合法 JSON，所有字符串使用 JSON 双引号并正确转义。"
        raw_output = await LangChainLLMService().ainvoke_text(
            prompt=prompt,
            task_name=task_model_name,
            response_format="json_object",
        )
        result = self._parse_task_output(raw_output)
        if result.task_id != task_id:
            raise ValueError(f"Coach task JSON output task_id mismatch: expected {task_id}, got {result.task_id}")
        if result.task_name != task_name:
            raise ValueError(f"Coach task JSON output task_name mismatch: expected {task_name}, got {result.task_name}")
        return result

    @staticmethod
    def _parse_task_output(raw_output: str) -> CoachTaskResult:
        return CoachTaskResult.model_validate(GenericCoachAgent._extract_json_object(raw_output))

    @staticmethod
    def _extract_json_object(raw_output: str) -> dict[str, Any]:
        text = raw_output.strip()
        if not text:
            raise ValueError("Coach task returned empty output.")
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Coach task did not return a JSON object.") from exc
            data = json.loads(text[start : end + 1])
        if not isinstance(data, dict):
            raise ValueError("Coach task JSON must be an object.")
        return data

    @staticmethod
    def chunks_payload(chunks: list[RetrievedChunk] | None) -> list[dict[str, Any]]:
        return [chunk.model_dump(exclude_none=True) for chunk in (chunks or [])]
