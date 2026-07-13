from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from backend.config.settings import get_settings
from backend.exceptions.llm_errors import LLMError
from backend.services.langchain_llm_service import LangChainLLMService, ModelFarmLangChainChatModel


@dataclass
class ChatInvocationResult:
    content: str
    raw: dict[str, Any]
    usage: dict[str, Any] | None = None


class LLMService:
    """Backward-compatible LangChain-backed facade.

    Agent modules use LangChainLLMService directly. This class remains only for older
    service/tests imports and delegates actual model invocation to LangChain.
    """

    def __init__(self):
        self.settings = get_settings()

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        schema_hint: dict | None = None,
        *,
        model: str | None = None,
        task_name: str | None = None,
    ) -> dict[str, Any]:
        raise LLMError(
            "chat_json is disabled. Structured Agent output must use "
            "LangChainLLMService.ainvoke_structured(..., schema=YourPydanticModel), "
            "which reads LangChain's structured_response."
        )

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        task_name: str | None = None,
    ) -> str:
        prompt = self._messages_to_prompt(messages)
        return await LangChainLLMService().ainvoke_text(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            task_name=task_name,
        )

    def _build_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        response_format: str | None,
        temperature: float | None,
        max_tokens: int | None,
        model: str | None = None,
        task_name: str | None = None,
    ) -> dict[str, Any]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        lc_messages = []
        for item in messages:
            role = str(item.get("role") or "user")
            content = item.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))
        return ModelFarmLangChainChatModel(
            task_name=task_name,
            explicit_model=model,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )._build_payload(lc_messages)

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        parts = []
        for item in messages:
            role = str(item.get("role") or "user")
            parts.append(f"[{role}]\n{item.get('content', '')}")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_chat_result(data: dict[str, Any]) -> ChatInvocationResult:
        usage = ModelFarmLangChainChatModel._extract_usage(data)
        content = ModelFarmLangChainChatModel._extract_content(data)
        if content is None:
            raise LLMError(f"Unable to extract chat content from response keys: {list(data.keys())}")
        return ChatInvocationResult(content=content, raw=data, usage=usage)

    @staticmethod
    def _parse_json_content(content: str) -> Any:
        text = content.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
        if fence:
            return json.loads(fence.group(1).strip())
        start_candidates = [idx for idx in [text.find("{"), text.find("[")] if idx >= 0]
        if not start_candidates:
            raise LLMError(f"LLM response is not JSON: {text[:300]}")
        start = min(start_candidates)
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        end = text.rfind(closer)
        if end <= start:
            raise LLMError(f"LLM response is not complete JSON: {text[:300]}")
        return json.loads(text[start : end + 1])
