from langchain_core.messages import HumanMessage

from backend.services.llm_service import LLMService
from backend.services.embedding_service import EmbeddingService
from backend.services.rerank_service import RerankService
from backend.services.langchain_llm_service import ModelFarmLangChainChatModel
from backend.config.settings import Settings


def test_llm_extracts_standard_openai_content():
    data = {"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}}
    result = LLMService._extract_chat_result(data)
    assert result.content == "hello"
    assert result.usage == {"total_tokens": 3}


def test_llm_extracts_bosch_messages_content():
    data = {"data": {"messages": [{"role": "assistant", "content": "你好"}]}}
    result = LLMService._extract_chat_result(data)
    assert result.content == "你好"


def test_llm_parses_json_from_fenced_content():
    parsed = LLMService._parse_json_content('```json\n{"a": 1}\n```')
    assert parsed == {"a": 1}


def test_embedding_extracts_v2_data_shape():
    data = {"model": "m", "data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}
    assert EmbeddingService._extract_embeddings(data) == [[0.1], [0.2]]


def test_rerank_extracts_results():
    data = {"results": [{"index": 2, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.6}]}
    assert RerankService._extract_ranked_indexes(data) == [(2, 0.8), (0, 0.6)]


def test_bosch_openai_compatible_auto_response_format_uses_openai_payload():
    model = ModelFarmLangChainChatModel(
        settings=Settings(
            llm_provider="bosch_openai_compatible",
            llm_response_format_style="auto",
        )
    )
    assert model._format_response_format("json_schema") == {"type": "json_schema"}


def test_bosch_openai_compatible_tool_choice_uses_openai_payload():
    model = ModelFarmLangChainChatModel(
        settings=Settings(
            llm_provider="bosch_openai_compatible",
            llm_response_format_style="auto",
        )
    ).bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "structured_output",
                    "description": "Return structured output",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice="required",
    )

    payload = model._build_payload([HumanMessage(content="hi")])

    assert payload["tool_choice"] == "required"
    assert "toolChoice" not in payload


def test_bosch_messages_auto_response_format_uses_native_payload():
    model = ModelFarmLangChainChatModel(
        settings=Settings(
            llm_provider="bosch_messages",
            llm_response_format_style="auto",
        )
    )
    assert model._format_response_format("json_schema") == "json_schema"


def test_stream_line_payload_handles_sse_data_lines():
    assert ModelFarmLangChainChatModel._stream_line_payload('data: {"a": 1}') == '{"a": 1}'
    assert ModelFarmLangChainChatModel._stream_line_payload('data: [DONE]') == '[DONE]'
    assert ModelFarmLangChainChatModel._stream_line_payload(': keepalive') is None


def test_stream_delta_extracts_openai_delta_content():
    data = {"choices": [{"delta": {"content": "你"}}]}
    assert ModelFarmLangChainChatModel._extract_stream_content_delta(data) == "你"


def test_stream_delta_extracts_bosch_nested_message_content():
    data = {"data": {"messages": [{"role": "assistant", "content": "你好"}]}}
    assert ModelFarmLangChainChatModel._extract_stream_content_delta(data) == "你好"
