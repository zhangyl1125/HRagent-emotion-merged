from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the MinerU + PostgreSQL/pgvector + real model API build."""

    model_config = SettingsConfigDict(
        env_file=("backend/config/.env", "backend/config/env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HR 绩效反馈和对话预演 Agent POC"
    app_version: str = "0.5.0-postgres-pgvector"
    environment: str = "local"
    api_prefix: str = "/api/v1"

    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])
    runtime_data_dir: Path | None = None
    max_user_turns: int = 0

    llm_provider: Literal["openai_compatible", "bosch_openai_compatible", "bosch_messages"]
    chat_api_base_url: str = ""
    chat_api_endpoint: str
    chat_api_key: str
    chat_model: str = ""

    default_chat_model: str
    profile_model: str
    intent_model: str
    employee_model: str
    guidance_model: str
    coach_evaluator_model: str
    coach_redline_model: str
    coach_report_model: str

    embedding_provider: Literal["openai_compatible", "bosch"]
    embedding_api_base_url: str = ""
    embedding_api_endpoint: str
    embedding_api_key: str
    embedding_model: str

    rerank_provider: Literal["bosch"]
    rerank_api_base_url: str = ""
    rerank_api_endpoint: str
    rerank_api_key: str
    rerank_model: str

    model_api_auth_mode: Literal["api_key", "bearer", "client_credentials"]
    model_api_key_header_name: str
    oauth2_token_url: str = ""
    oauth2_client_id: str = ""
    oauth2_client_secret: str = ""
    oauth2_scope: str = ""

    llm_temperature: float
    llm_employee_temperature: float
    llm_top_p: float | None = None
    llm_max_tokens: int | None
    llm_profile_max_tokens: int | None
    llm_intent_max_tokens: int | None
    llm_employee_max_tokens: int | None
    llm_guidance_max_tokens: int | None
    llm_coach_evaluator_max_tokens: int | None
    llm_coach_redline_max_tokens: int | None
    llm_coach_report_max_tokens: int | None
    llm_enable_thinking: bool | None = None
    llm_thinking_budget: int | None = None
    llm_web_search: bool = False
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_response_format_style: Literal["auto", "bosch", "openai", "none"]
    langchain_structured_output_strategy: Literal["auto", "provider", "tool"]

    mineru_enabled: bool
    mineru_api_url: str
    mineru_backend: Literal["pipeline", "vlm-engine", "vlm-http-client", "hybrid-engine", "hybrid-http-client"]
    mineru_effort: Literal["medium", "high"]
    mineru_parse_method: Literal["auto", "txt", "ocr"]
    mineru_lang: str
    mineru_output_dir: Path | None = None
    mineru_timeout_seconds: float
    mineru_fail_on_error: bool

    vectorstore_provider: Literal["postgres_pgvector"]
    database_url: str
    postgres_create_hnsw_index: bool
    vector_collection_prefix: str
    kb_ingest_batch_size: int
    kb_chunk_size: int
    kb_chunk_overlap: int
    kb_index_version: str

    enable_trace: bool = False
    cors_allow_origins: list[str] = ["*"]

    # Auth / local login with SSO-ready account model
    auth_enabled: bool = True
    auth_cookie_name: str = "hragent_session"
    auth_cookie_secure: bool = True
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_session_idle_timeout_minutes: int = 30
    auth_session_absolute_timeout_hours: int = 8
    auth_whitelist_enabled: bool = True
    auth_allowed_emails: str = "aah5sgh@bosch.com"
    auth_password_kdf: Literal["argon2id"] = "argon2id"
    auth_argon2_memory_cost: int = 19456
    auth_argon2_time_cost: int = 2
    auth_argon2_parallelism: int = 1
    auth_argon2_hash_len: int = 32
    auth_argon2_salt_len: int = 16
    auth_login_hash_max_concurrency: int = 8
    auth_max_active_sessions: int = 100
    auth_login_rate_limit_per_email: str = "5/minute"
    auth_login_rate_limit_per_ip: str = "20/minute"
    auth_register_rate_limit_per_ip: str = "3/hour"
    auth_sso_enabled: bool = False
    auth_oidc_issuer: str = ""
    auth_oidc_client_id: str = ""
    auth_oidc_client_secret: str = ""
    auth_oidc_redirect_uri: str = ""
    auth_oidc_allowed_groups: str = ""
    web_concurrency: int = 4
    uvicorn_limit_concurrency: int = 200
    db_pool_size: int = 20
    db_max_overflow: int = 20
    redis_max_connections: int = 50
    coach_report_max_concurrency_per_worker: int = 2

    # Redis cache
    redis_url: str = ""
    cache_enabled: bool = True
    cache_key_prefix: str = "hragent05"
    redis_connect_timeout_seconds: float = 1.0
    redis_socket_timeout_seconds: float = 1.0
    guidance_cache_ttl_seconds: int = 21600
    tts_cache_ttl_seconds: int = 604800
    document_parse_cache_ttl_seconds: int = 2592000
    rehearsal_aux_cache_ttl_seconds: int = 3600

    # ASR / Speech-to-Text
    asr_enabled: bool = True
    asr_provider: Literal["qwen"] = "qwen"
    asr_model: str = "qwen3-asr-flash-realtime"
    asr_api_key: str = ""
    asr_ws_url: str = ""
    asr_http_url: str = ""
    asr_http_model: str = "qwen3-asr-flash"
    asr_language: str = "zh"
    asr_sample_rate: int = 16000
    asr_input_audio_format: str = "pcm"
    asr_enable_server_vad: bool = True
    asr_vad_threshold: float = 0.0
    asr_vad_silence_duration_ms: int = 400
    asr_connect_timeout_seconds: float = 15.0
    asr_session_timeout_seconds: float = 120.0
    asr_max_session_seconds: int = 300

    # TTS / Text-to-Speech
    tts_enabled: bool = True
    tts_provider: Literal["qwen"] = "qwen"
    tts_api_url: str = "https://aigc.bosch.com.cn/llmservice/api/v1/audio/speech"
    tts_api_key: str = ""
    tts_model: str = "qwen3-tts-flash"
    tts_voice: str = "Cherry"
    tts_response_format: str = "mp3"
    tts_speed: float = 1.0
    tts_timeout_seconds: float = 60.0
    tts_max_chars: int = 2000

    # Emotion Engine
    motivation_engine_enabled: bool = True
    motivation_primary_weight: float = 0.7
    motivation_secondary_weight: float = 0.3
    emotion_engine_enabled: bool = True
    emotion_analyzer_provider: str = "rules"
    emotion_analyzer_model: str = "qwen-plus"
    emotion_history_window: int = 5
    emotion_state_max_intensity: int = 75
    emotion_state_anti_jump: bool = True

    @property
    def auth_session_idle_timeout_seconds(self) -> int:
        return max(60, self.auth_session_idle_timeout_minutes * 60)

    @property
    def auth_session_absolute_timeout_seconds(self) -> int:
        return max(self.auth_session_idle_timeout_seconds, self.auth_session_absolute_timeout_hours * 3600)

    @property
    def asr_realtime_url(self) -> str:
        base = self.asr_ws_url.strip()
        if not base:
            return ""
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}model={self.asr_model}"

    @property
    def data_dir(self) -> Path:
        return self.runtime_data_dir or self.project_root / "data"

    @property
    def business_config_dir(self) -> Path:
        return self.project_root / "backend" / "business_config"

    @property
    def prompt_dir(self) -> Path:
        return self.project_root / "backend" / "prompts"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def resolved_mineru_output_dir(self) -> Path:
        return self.mineru_output_dir or self.kb_processed_dir

    @property
    def kb_processed_dir(self) -> Path:
        return self.data_dir / "kb_processed"

    @property
    def employee_database_dir(self) -> Path:
        return self.data_dir / "employee_database"

    @property
    def chat_url(self) -> str:
        return self._resolve_url(
            explicit_endpoint=self.chat_api_endpoint,
            base_url=self.chat_api_base_url,
            default_path="/chat/messages" if self.llm_provider == "bosch_messages" else "/chat/completions",
        )

    @property
    def embedding_url(self) -> str:
        return self._resolve_url(
            explicit_endpoint=self.embedding_api_endpoint,
            base_url=self.embedding_api_base_url,
            default_path="/embeddings",
        )

    @property
    def rerank_url(self) -> str:
        return self._resolve_url(
            explicit_endpoint=self.rerank_api_endpoint,
            base_url=self.rerank_api_base_url,
            default_path="/rerank",
        )

    def collection_name_for_scope(self, scope: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in scope.strip()).strip("_") or "general"
        return f"{self.vector_collection_prefix}_{safe}"

    def model_for_task(self, task_name: str | None = None, explicit_model: str | None = None) -> str:
        if explicit_model:
            return explicit_model
        if self.chat_model:
            return self.chat_model
        mapping = {
            "profile": self.profile_model,
            "intent": self.intent_model,
            "employee": self.employee_model,
            "guidance": self.guidance_model,
            "coach_evaluator": self.coach_evaluator_model,
            "coach_redline": self.coach_redline_model,
            "coach_report": self.coach_report_model,
        }
        if task_name and task_name in mapping and mapping[task_name]:
            return mapping[task_name]
        return self.default_chat_model

    def max_tokens_for_task(self, task_name: str | None = None) -> int | None:
        if task_name == "employee":
            return None
        mapping = {
            "profile": self.llm_profile_max_tokens,
            "intent": self.llm_intent_max_tokens,
            "guidance": self.llm_guidance_max_tokens,
            "coach_evaluator": self.llm_coach_evaluator_max_tokens,
            "coach_redline": self.llm_coach_redline_max_tokens,
            "coach_report": self.llm_coach_report_max_tokens,
        }
        if task_name and task_name in mapping:
            return mapping[task_name]
        return self.llm_max_tokens

    def temperature_for_task(self, task_name: str | None = None) -> float:
        if task_name == "employee":
            return self.llm_employee_temperature
        return self.llm_temperature

    @staticmethod
    def _resolve_url(explicit_endpoint: str, base_url: str, default_path: str) -> str:
        endpoint = explicit_endpoint.strip()
        if endpoint:
            return endpoint
        base = base_url.strip().rstrip("/")
        if not base:
            return ""
        known_suffixes = (
            "/chat/completions",
            "/chat/messages",
            "/embeddings",
            "/rerank",
        )
        if base.endswith(known_suffixes):
            return base
        return f"{base}{default_path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_mineru_output_dir.mkdir(parents=True, exist_ok=True)
    settings.kb_processed_dir.mkdir(parents=True, exist_ok=True)
    settings.employee_database_dir.mkdir(parents=True, exist_ok=True)
    return settings
