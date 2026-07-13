from pathlib import Path

import pytest
from pydantic import BaseModel

from backend.config.settings import Settings
from backend.services.langchain_llm_service import LangChainLLMService


def test_all_agent_modules_use_langchain_service_not_legacy_llm_service():
    agent_dir = Path("backend/agents")
    files = [p for p in agent_dir.rglob("*.py") if p.name != "__init__.py"]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "from backend.services.llm_service import LLMService" not in text, path
        assert "LLMService().chat_" not in text, path
    llm_calling_files = [p for p in files if "LangChainLLMService" in p.read_text(encoding="utf-8")]
    assert llm_calling_files, "Agent LLM calls must be routed through LangChainLLMService."


def test_structured_agents_use_langchain_create_agent_response_format():
    service_text = Path("backend/services/langchain_llm_service.py").read_text(encoding="utf-8")
    assert "from langchain.agents import create_agent" in service_text
    assert "ProviderStrategy" in service_text
    assert "ToolStrategy" in service_text
    assert "response_format=response_format" in service_text
    assert "structured_response" in service_text


def test_agent_modules_do_not_call_manual_json_structured_invoke():
    agent_dir = Path("backend/agents")
    for path in agent_dir.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "ainvoke_json(" not in text, path
        if "LangChainLLMService" in text:
            assert "ainvoke_structured(" in text or "ainvoke_text(" in text, path


class ExampleStructuredResponse(BaseModel):
    value: str


@pytest.mark.asyncio
async def test_provider_structured_parse_error_falls_back_to_tool_strategy(monkeypatch):
    service = LangChainLLMService()
    calls = []

    async def fake_structured_once(**kwargs):
        calls.append(kwargs["strategy_name"])
        if kwargs["strategy_name"] == "provider":
            raise ValueError("Native structured output expected valid JSON: Invalid control character")
        return ExampleStructuredResponse(value="ok")

    monkeypatch.setattr(service, "_ainvoke_structured_once", fake_structured_once)

    result = await service.ainvoke_structured(
        prompt="hi",
        schema=ExampleStructuredResponse,
        strategy="provider",
    )

    assert result.value == "ok"
    assert calls == ["provider", "tool"]

@pytest.mark.asyncio
async def test_bosch_configured_provider_strategy_uses_tool_strategy(monkeypatch):
    service = LangChainLLMService()
    service.settings = Settings(
        llm_provider="bosch_openai_compatible",
        langchain_structured_output_strategy="provider",
    )
    calls = []

    async def fake_structured_once(**kwargs):
        calls.append(kwargs["strategy_name"])
        return ExampleStructuredResponse(value="ok")

    monkeypatch.setattr(service, "_ainvoke_structured_once", fake_structured_once)

    result = await service.ainvoke_structured(
        prompt="hi",
        schema=ExampleStructuredResponse,
    )

    assert result.value == "ok"
    assert calls == ["tool"]

