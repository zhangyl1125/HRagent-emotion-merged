from backend.config.settings import get_settings


def test_model_defaults_match_requested_configuration():
    settings = get_settings()
    assert settings.default_chat_model == "qwen3.6-flash"
    assert settings.profile_model == "qwen3.6-flash"
    assert settings.intent_model == "qwen3.6-flash"
    assert settings.employee_model == "qwen3.6-flash"
    assert settings.guidance_model == "qwen3.6-flash"
    assert settings.coach_evaluator_model == "qwen3.6-flash"
    assert settings.coach_redline_model == "qwen3-max-thinking"
    assert settings.coach_report_model == "qwen3.6-flash"
    assert settings.embedding_model == "text-embedding-v3"
    assert settings.rerank_model == "qwen3-rerank"
    assert settings.llm_response_format_style == "openai"
    assert settings.langchain_structured_output_strategy == "provider"
    assert settings.vectorstore_provider == "postgres_pgvector"
    assert settings.vector_collection_prefix == "hr_agent_kb"


def test_task_model_routing_uses_requested_models():
    settings = get_settings()
    assert settings.model_for_task("profile") == "qwen3.6-flash"
    assert settings.model_for_task("intent") == "qwen3.6-flash"
    assert settings.model_for_task("employee") == "qwen3.6-flash"
    assert settings.model_for_task("guidance") == "qwen3.6-flash"
    assert settings.model_for_task("coach_evaluator") == "qwen3.6-flash"
    assert settings.model_for_task("coach_redline") == "qwen3-max-thinking"
    assert settings.model_for_task("coach_report") == "qwen3.6-flash"
