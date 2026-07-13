from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from threading import Lock
from typing import Any, Iterable, TypeVar

import httpx
from pydantic import BaseModel, Field, PrivateAttr

try:
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.prompts import ChatPromptTemplate
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise RuntimeError(
        "LangChain is required for all Agent LLM execution. "
        "Install dependencies from backend/requirements.txt before running the backend."
    ) from exc

from backend.config.settings import Settings, get_settings
from backend.exceptions.llm_errors import LLMError
from backend.services.model_api_auth import ModelAPIAuth

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


_HTTP_CLIENT_LOCK = Lock()
_SYNC_HTTP_CLIENT: httpx.Client | None = None
_ASYNC_HTTP_CLIENTS: dict[int, httpx.AsyncClient] = {}


def _http_limits() -> httpx.Limits:
    return httpx.Limits(max_connections=100, max_keepalive_connections=50, keepalive_expiry=30.0)


def _shared_sync_http_client(settings: Settings) -> httpx.Client:
    global _SYNC_HTTP_CLIENT
    with _HTTP_CLIENT_LOCK:
        if _SYNC_HTTP_CLIENT is None:
            _SYNC_HTTP_CLIENT = httpx.Client(timeout=settings.llm_timeout_seconds, limits=_http_limits())
        return _SYNC_HTTP_CLIENT


def _shared_async_http_client(settings: Settings) -> httpx.AsyncClient:
    loop_key = id(asyncio.get_running_loop())
    with _HTTP_CLIENT_LOCK:
        client = _ASYNC_HTTP_CLIENTS.get(loop_key)
        if client is None:
            client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, limits=_http_limits())
            _ASYNC_HTTP_CLIENTS[loop_key] = client
        return client


async def close_shared_http_clients() -> None:
    global _SYNC_HTTP_CLIENT
    with _HTTP_CLIENT_LOCK:
        sync_client = _SYNC_HTTP_CLIENT
        _SYNC_HTTP_CLIENT = None
        async_clients = list(_ASYNC_HTTP_CLIENTS.values())
        _ASYNC_HTTP_CLIENTS.clear()
    if sync_client is not None:
        sync_client.close()
    if async_clients:
        await asyncio.gather(*(client.aclose() for client in async_clients), return_exceptions=True)


class ModelFarmLangChainChatModel(BaseChatModel):
    """LangChain ChatModel adapter for the configured OpenAI-compatible/Bosch API.

    Agent modules must call this model through LangChain. The HTTP transport is
    encapsulated here so Agent modules never call raw APIs directly.
    """

    settings: Settings = Field(default_factory=get_settings)
    task_name: str | None = None
    explicit_model: str | None = None
    response_format: str | dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enable_thinking: bool | None = None
    profile: dict[str, Any] = Field(default_factory=lambda: {"structured_output": True, "tool_calling": True})

    _auth: ModelAPIAuth = PrivateAttr(default_factory=ModelAPIAuth)
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)
    _tool_choice: Any | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "model_farm_langchain_chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "endpoint": self.settings.chat_url,
            "provider": self.settings.llm_provider,
            "model": self.settings.model_for_task(self.task_name, self.explicit_model),
            "task_name": self.task_name,
        }

    def bind_tools(self, tools: Iterable[Any], *, tool_choice: Any | None = None, **kwargs: Any) -> "ModelFarmLangChainChatModel":
        """Bind tool definitions for LangChain ToolStrategy structured output.

        LangChain's ToolStrategy converts a schema into an artificial function/tool.
        The model adapter forwards that tool schema to the configured API instead of
        bypassing LangChain.
        """
        clone = self.model_copy(deep=True)
        clone._bound_tools = list(tools or [])
        clone._tool_choice = tool_choice if tool_choice is not None else kwargs.get("tool_choice") or kwargs.get("toolChoice")
        return clone

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        url = self.settings.chat_url
        if not url:
            raise LLMError("Chat API endpoint is not configured.")
        payload = self._build_payload(messages, stop=stop)
        headers = self._auth.sync_headers(self.settings.chat_api_key)
        headers.setdefault("Content-Type", "application/json")
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                resp = _shared_sync_http_client(self.settings).post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    raise LLMError(self._format_http_error(resp))
                return self._chat_result_from_response(resp.json())
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
        raise LLMError(f"LangChain chat model invocation failed: {self._format_exception(last_error)}")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        url = self.settings.chat_url
        if not url:
            raise LLMError("Chat API endpoint is not configured.")
        payload = self._build_payload(messages, stop=stop)
        headers = await self._auth.async_headers(self.settings.chat_api_key)
        headers.setdefault("Content-Type", "application/json")
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                resp = await _shared_async_http_client(self.settings).post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    raise LLMError(self._format_http_error(resp))
                return self._chat_result_from_response(resp.json())
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
        raise LLMError(f"LangChain chat model invocation failed: {self._format_exception(last_error)}")

    def _chat_result_from_response(self, data: dict[str, Any]) -> ChatResult:
        content = self._extract_content(data)
        tool_calls = self._extract_tool_calls(data)
        if content is None and not tool_calls:
            raise LLMError(f"Unable to extract chat content/tool calls from response keys: {list(data.keys())}")
        message_kwargs: dict[str, Any] = {"content": content or "", "response_metadata": {"raw": data, "usage": self._extract_usage(data)}}
        if tool_calls:
            message_kwargs["tool_calls"] = tool_calls
        message = AIMessage(**message_kwargs)
        generation = ChatGeneration(
            message=message,
            generation_info={"raw": data, "usage": self._extract_usage(data)},
        )
        return ChatResult(generations=[generation], llm_output={"raw": data, "usage": self._extract_usage(data)})

    async def astream_text(self, messages: list[BaseMessage], stop: list[str] | None = None) -> AsyncIterator[str]:
        url = self.settings.chat_url
        if not url:
            raise LLMError("Chat API endpoint is not configured.")
        payload = self._build_payload(messages, stop=stop, stream=True)
        headers = await self._auth.async_headers(self.settings.chat_api_key)
        headers.setdefault("Content-Type", "application/json")
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                client = _shared_async_http_client(self.settings)
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:1000]
                        raise LLMError(f"Chat API HTTP {resp.status_code}: {body}")
                    async for delta in self._iter_stream_deltas(resp):
                        if delta:
                            yield delta
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
        raise LLMError(f"LangChain chat model streaming failed: {self._format_exception(last_error)}")

    async def astream_events(self, messages: list[BaseMessage], stop: list[str] | None = None) -> AsyncIterator[tuple[str, str]]:
        """Stream both the chain-of-thought (``thinking``) and the answer (``content``) channels."""
        url = self.settings.chat_url
        if not url:
            raise LLMError("Chat API endpoint is not configured.")
        payload = self._build_payload(messages, stop=stop, stream=True)
        headers = await self._auth.async_headers(self.settings.chat_api_key)
        headers.setdefault("Content-Type", "application/json")
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                client = _shared_async_http_client(self.settings)
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:1000]
                        raise LLMError(f"Chat API HTTP {resp.status_code}: {body}")
                    async for channel, text in self._iter_stream_events(resp):
                        if text:
                            yield channel, text
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
        raise LLMError(f"LangChain chat model streaming failed: {self._format_exception(last_error)}")

    async def _iter_stream_deltas(self, resp: httpx.Response) -> AsyncIterator[str]:
        async for line in resp.aiter_lines():
            payload = self._stream_line_payload(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            delta = self._extract_stream_content_delta(data)
            if delta:
                yield delta

    async def _iter_stream_events(self, resp: httpx.Response) -> AsyncIterator[tuple[str, str]]:
        async for line in resp.aiter_lines():
            payload = self._stream_line_payload(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            reasoning = self._extract_stream_reasoning_delta(data)
            if reasoning:
                yield "thinking", reasoning
            delta = self._extract_stream_content_delta(data)
            if delta:
                yield "content", delta

    @staticmethod
    def _stream_line_payload(line: str) -> str | None:
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            return None
        if stripped.startswith("data:"):
            return stripped[5:].strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return stripped
        return None

    def _build_payload(self, messages: list[BaseMessage], stop: list[str] | None = None, stream: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model_for_task(task_name=self.task_name, explicit_model=self.explicit_model),
            "messages": self._normalize_messages(messages),
            "temperature": self.temperature if self.temperature is not None else self.settings.temperature_for_task(self.task_name),
            "stream": stream,
        }
        if stop:
            payload["stop"] = stop[:4]
        effective_max_tokens = self.max_tokens if self.max_tokens is not None else self.settings.max_tokens_for_task(self.task_name)
        enable_thinking = self.enable_thinking if self.enable_thinking is not None else self.settings.llm_enable_thinking
        optional_values = {
            "top_p": self.settings.llm_top_p,
            "max_tokens": effective_max_tokens,
            "enable_thinking": enable_thinking,
            "thinking_budget": self.settings.llm_thinking_budget,
        }
        for key, value in optional_values.items():
            if value is not None:
                payload[key] = value
        if self.settings.llm_web_search:
            payload["web_search"] = True
        formatted = self._format_response_format(self.response_format)
        if formatted is not None:
            payload["response_format"] = formatted
        if self._bound_tools:
            payload["tools"] = [self._normalize_tool(tool) for tool in self._bound_tools]
            tool_choice = self._normalize_tool_choice(self._tool_choice)
            if tool_choice is not None:
                if self.settings.llm_provider in {"openai_compatible", "bosch_openai_compatible"}:
                    payload["tool_choice"] = tool_choice
                else:
                    payload["toolChoice"] = tool_choice
        return payload

    def _normalize_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        system_parts: list[str] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                role = "system"
            elif isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            else:
                role = getattr(message, "type", "user") or "user"
                if role == "human":
                    role = "user"
                if role == "ai":
                    role = "assistant"
            content = message.content
            if role == "system" and self.settings.llm_provider == "bosch_messages":
                system_parts.append(str(content))
                continue
            if role not in {"system", "user", "assistant", "tool"}:
                role = "user"
            row: dict[str, Any] = {"role": role, "content": content}
            tool_call_id = getattr(message, "tool_call_id", None)
            if role == "tool" and tool_call_id:
                row["tool_call_id"] = tool_call_id
            normalized.append(row)
        if system_parts:
            prefix = "\n\n".join(system_parts)
            if normalized and normalized[0]["role"] == "user":
                normalized[0]["content"] = f"{prefix}\n\n{normalized[0]['content']}"
            else:
                normalized.insert(0, {"role": "user", "content": prefix})
        return normalized

    def _format_response_format(self, response_format: str | None) -> str | dict[str, str] | None:
        if not response_format or self.settings.llm_response_format_style == "none":
            return None
        if isinstance(response_format, dict):
            return response_format
        if response_format == "text":
            return "text" if self.settings.llm_response_format_style in {"auto", "bosch"} else None
        style = self.settings.llm_response_format_style
        if style == "auto":
            style = "bosch" if self.settings.llm_provider == "bosch_messages" else "openai"
        if style == "bosch":
            return response_format
        return {"type": response_format}

    @staticmethod
    def _normalize_tool_choice(tool_choice: Any | None) -> Any | None:
        if tool_choice in {None, False}:
            return None
        if tool_choice is True:
            return "required"
        if isinstance(tool_choice, str):
            if tool_choice.lower() == "any":
                return "required"
            return tool_choice
        return tool_choice

    @staticmethod
    def _normalize_tool(tool: Any) -> dict[str, Any]:
        if isinstance(tool, dict):
            if "type" in tool and "function" in tool:
                return tool
            if "name" in tool and "parameters" in tool:
                return {"type": "function", "function": tool}
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None) or "structured_output"
        description = getattr(tool, "description", None) or getattr(tool, "__doc__", None) or name
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            parameters = args_schema.model_json_schema()
        elif isinstance(tool, type) and issubclass(tool, BaseModel):
            parameters = tool.model_json_schema()
            description = parameters.get("description") or description
        else:
            parameters = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": str(name),
                "description": str(description),
                "parameters": parameters,
            },
        }

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> dict[str, Any] | None:
        usage = data.get("usage")
        if usage is None and isinstance(data.get("data"), dict):
            usage = data["data"].get("usage")
        return usage if isinstance(usage, dict) else None

    @classmethod
    def _extract_tool_calls(cls, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        candidates: list[Any] = []
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict):
                candidates.append(message.get("tool_calls"))
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict):
                candidates.append(delta.get("tool_calls"))
        inner = data.get("data")
        if isinstance(inner, dict):
            nested = cls._extract_tool_calls(inner)
            if nested:
                return nested
        messages = data.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict):
                    candidates.append(message.get("tool_calls"))
        candidates.append(data.get("tool_calls"))
        for raw_calls in candidates:
            if not isinstance(raw_calls, list):
                continue
            normalized: list[dict[str, Any]] = []
            for index, raw_call in enumerate(raw_calls):
                if not isinstance(raw_call, dict):
                    continue
                function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
                name = raw_call.get("name") or function.get("name")
                args_raw = raw_call.get("args") if raw_call.get("args") is not None else function.get("arguments")
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw or "{}")
                    except json.JSONDecodeError:
                        args = {"raw_arguments": args_raw}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}
                if name:
                    normalized.append(
                        {
                            "name": str(name),
                            "args": args,
                            "id": str(raw_call.get("id") or f"tool_call_{index}"),
                            "type": "tool_call",
                        }
                    )
            if normalized:
                return normalized
        return []

    @staticmethod
    def _extract_content(data: Any) -> str | None:
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return None
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return ModelFarmLangChainChatModel._stringify_content(message.get("content"))
            delta = choice.get("delta")
            if isinstance(delta, dict) and delta.get("content") is not None:
                return ModelFarmLangChainChatModel._stringify_content(delta.get("content"))
        inner = data.get("data")
        if isinstance(inner, dict):
            nested = ModelFarmLangChainChatModel._extract_content(inner)
            if nested is not None:
                return nested
        if isinstance(inner, list):
            for item in reversed(inner):
                nested = ModelFarmLangChainChatModel._extract_content(item)
                if nested is not None:
                    return nested
        messages = data.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict) and message.get("content") is not None:
                    return ModelFarmLangChainChatModel._stringify_content(message.get("content"))
        message = data.get("message")
        if isinstance(message, dict) and message.get("content") is not None:
            return ModelFarmLangChainChatModel._stringify_content(message.get("content"))
        if data.get("content") is not None:
            return ModelFarmLangChainChatModel._stringify_content(data.get("content"))
        if data.get("text") is not None:
            return str(data.get("text"))
        if data.get("msg") and not isinstance(data.get("msg"), (dict, list)):
            return str(data.get("msg"))
        return None

    @classmethod
    def _extract_stream_content_delta(cls, data: Any) -> str | None:
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return None
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict):
                for key in ("content", "text"):
                    if delta.get(key) is not None:
                        return cls._stringify_content(delta.get(key))
            if isinstance(choice, dict) and choice.get("text") is not None:
                return cls._stringify_content(choice.get("text"))
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict) and message.get("content") is not None:
                return cls._stringify_content(message.get("content"))
        inner = data.get("data")
        if isinstance(inner, dict):
            nested = cls._extract_stream_content_delta(inner)
            if nested is not None:
                return nested
        if isinstance(inner, list):
            parts = [part for item in inner if (part := cls._extract_stream_content_delta(item))]
            return "".join(parts) if parts else None
        messages = data.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict):
                    for key in ("delta", "content", "text"):
                        if message.get(key) is not None:
                            return cls._stringify_content(message.get(key))
        for key in ("delta", "content", "text"):
            if data.get(key) is not None:
                return cls._stringify_content(data.get(key))
        return None

    @classmethod
    def _extract_stream_reasoning_delta(cls, data: Any) -> str | None:
        """Extract the chain-of-thought delta (``reasoning_content``) from a stream chunk."""
        if not isinstance(data, dict):
            return None
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict):
                for key in ("reasoning_content", "reasoning", "thinking"):
                    if delta.get(key) is not None:
                        return cls._stringify_content(delta.get(key))
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict):
                for key in ("reasoning_content", "reasoning", "thinking"):
                    if message.get(key) is not None:
                        return cls._stringify_content(message.get(key))
        inner = data.get("data")
        if isinstance(inner, dict):
            nested = cls._extract_stream_reasoning_delta(inner)
            if nested is not None:
                return nested
        if isinstance(inner, list):
            parts = [part for item in inner if (part := cls._extract_stream_reasoning_delta(item))]
            return "".join(parts) if parts else None
        for key in ("reasoning_content", "reasoning", "thinking"):
            if data.get(key) is not None:
                return cls._stringify_content(data.get(key))
        return None

    @staticmethod
    def _stringify_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)


    @staticmethod
    def _format_exception(exc: Exception | None) -> str:
        if exc is None:
            return "unknown error"
        message = str(exc).strip()
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    @staticmethod
    def _format_http_error(resp: httpx.Response) -> str:
        body = resp.text[:1000]
        if resp.status_code == 400 and "response_format" in body:
            body += " Hint: Model Farm China chat/completions requires OpenAI-compatible response_format payloads; set LLM_RESPONSE_FORMAT_STYLE=openai."
        return f"Chat API HTTP {resp.status_code}: {body}"


class LangChainLLMService:
    """LangChain-only LLM facade for Agent modules."""

    def __init__(self):
        self.settings = get_settings()

    def chat_model(
        self,
        *,
        task_name: str | None = None,
        model: str | None = None,
        response_format: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
    ) -> ModelFarmLangChainChatModel:
        return ModelFarmLangChainChatModel(
            task_name=task_name,
            explicit_model=model,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
        )

    async def ainvoke_text(
        self,
        *,
        prompt: str,
        task_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        chain = (
            ChatPromptTemplate.from_messages([("user", "{prompt}")])
            | self.chat_model(
                task_name=task_name,
                model=model,
                response_format="text",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            | StrOutputParser()
        )
        content = await chain.ainvoke({"prompt": prompt})
        cleaned = str(content).strip()
        if not cleaned:
            raise LLMError("LangChain chat model returned empty content.")
        return cleaned

    async def astream_text(
        self,
        *,
        prompt: str,
        task_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        chat_model = self.chat_model(
            task_name=task_name,
            model=model,
            response_format="text",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        async for delta in chat_model.astream_text([HumanMessage(content=prompt)]):
            yield delta

    async def astream_reasoning_text(
        self,
        *,
        prompt: str,
        task_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool = True,
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream ``(channel, text)`` pairs where channel is ``thinking`` or ``content``."""
        chat_model = self.chat_model(
            task_name=task_name,
            model=model,
            response_format="text",
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
        )
        async for channel, text in chat_model.astream_events([HumanMessage(content=prompt)]):
            yield channel, text

    async def ainvoke_structured(
        self,
        *,
        prompt: str,
        schema: type[StructuredModelT],
        task_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        strategy: str | None = None,
        timeout_seconds: float | None = None,
    ) -> StructuredModelT:
        """Invoke a LangChain agent with structured output.

        The structured result must come from LangChain's ``structured_response``
        state key. Manual JSON extraction is not used for Agent structured tasks.
        """
        configured_strategy = (strategy or self.settings.langchain_structured_output_strategy).strip().lower()
        strategy_name = self._effective_structured_strategy(configured_strategy, explicit_strategy=strategy is not None)
        try:
            return await self._ainvoke_structured_once(
                prompt=prompt,
                schema=schema,
                strategy_name=strategy_name,
                task_name=task_name,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            if strategy_name in {"auto", "provider"} and self._should_retry_structured_with_tool(exc):
                return await self._ainvoke_structured_once(
                    prompt=prompt,
                    schema=schema,
                    strategy_name="tool",
                    task_name=task_name,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                )
            raise

    def _effective_structured_strategy(self, strategy_name: str, *, explicit_strategy: bool) -> str:
        if (
            not explicit_strategy
            and self.settings.llm_provider == "bosch_openai_compatible"
            and strategy_name in {"auto", "provider"}
        ):
            return "tool"
        return strategy_name

    @staticmethod
    def _should_retry_structured_with_tool(exc: Exception) -> bool:
        message = str(exc).lower()
        exc_name = type(exc).__name__.lower()
        return any(
            marker in message or marker in exc_name
            for marker in (
                "structuredoutputvalidationerror",
                "structured output",
                "structured_response",
                "json_schema must be provided",
                "native structured output expected valid json",
                "invalid control character",
                "response_format",
                "json_schema",
            )
        )

    async def _ainvoke_structured_once(
        self,
        *,
        prompt: str,
        schema: type[StructuredModelT],
        strategy_name: str,
        task_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> StructuredModelT:
        response_format = self._structured_response_format(schema, strategy_name)
        model_response_format = None
        if strategy_name in {"auto", "provider"}:
            model_response_format = self._json_schema_response_format(schema)
        agent = create_agent(
            model=self.chat_model(
                task_name=task_name,
                model=model,
                response_format=model_response_format,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            tools=[],
            response_format=response_format,
        )
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only the structured response required by the configured Pydantic schema. "
                        "Do not include prose outside structured fields."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        }
        if timeout_seconds is not None and timeout_seconds > 0:
            try:
                result = await asyncio.wait_for(agent.ainvoke(payload), timeout=timeout_seconds)
            except TimeoutError as exc:
                raise LLMError(
                    f"LangChain structured agent timed out after {timeout_seconds:.0f}s"
                    f" for task={task_name or 'default'}."
                ) from exc
        else:
            result = await agent.ainvoke(payload)
        if not isinstance(result, dict):
            raise LLMError("LangChain structured agent returned non-dict state.")
        structured = result.get("structured_response")
        if structured is None:
            raise LLMError("LangChain structured agent did not return structured_response.")
        if isinstance(structured, schema):
            return structured
        if isinstance(structured, dict):
            return schema.model_validate(structured)
        if hasattr(structured, "model_dump"):
            return schema.model_validate(structured.model_dump())
        raise LLMError(f"Unsupported structured_response type: {type(structured).__name__}")

    async def ainvoke_json(
        self,
        *,
        prompt: str,
        schema_hint: dict[str, Any] | None = None,
        task_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        raise LLMError(
            "ainvoke_json is disabled for Agent execution. "
            "Use ainvoke_structured(..., schema=YourPydanticModel) so LangChain returns structured_response."
        )


    @staticmethod
    def _json_schema_response_format(schema: type[StructuredModelT]) -> dict[str, Any]:
        json_schema = schema.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": json_schema,
                "strict": False,
            },
        }

    @staticmethod
    def _structured_response_format(schema: type[StructuredModelT], strategy_name: str) -> Any:
        if strategy_name == "auto":
            return schema
        if strategy_name == "provider":
            return ProviderStrategy(schema)
        if strategy_name == "tool":
            return ToolStrategy(schema)
        raise LLMError("LANGCHAIN_STRUCTURED_OUTPUT_STRATEGY must be one of: auto, provider, tool.")
