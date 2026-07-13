from backend.config.settings import get_settings
from backend.services.llm_service import LLMService


def test_llm_payload_routes_profile_model():
    service = LLMService()
    payload = service._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        response_format="json_object",
        temperature=None,
        max_tokens=None,
        task_name="profile",
    )
    assert payload["model"] == get_settings().profile_model
    assert payload["response_format"] == "json_object" or payload["response_format"] == {"type": "json_object"}
