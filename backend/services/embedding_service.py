from __future__ import annotations

from typing import Any

import httpx

from backend.config.settings import get_settings
from backend.exceptions.llm_errors import LLMError
from backend.services.model_api_auth import ModelAPIAuth


class EmbeddingService:
    """Embedding API adapter. Endpoint and API key are mandatory."""

    def __init__(self):
        self.settings = get_settings()
        self.auth = ModelAPIAuth()

    def embed(self, texts: list[str]) -> list[list[float]]:
        cleaned = [str(text) for text in texts if text is not None and str(text).strip()]
        if not cleaned:
            return []
        url = self.settings.embedding_url
        if not url:
            raise LLMError("Embedding API endpoint is not configured.")
        payload = {"model": self.settings.embedding_model, "input": cleaned}
        headers = self.auth.sync_headers(self.settings.embedding_api_key or self.settings.chat_api_key)
        headers.setdefault("Content-Type", "application/json")
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        raise LLMError(f"Embedding API HTTP {resp.status_code}: {resp.text[:1000]}")
                    return self._extract_embeddings(resp.json())
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
        raise LLMError(f"Embedding invocation failed: {last_error}")

    @staticmethod
    def _extract_embeddings(data: dict[str, Any]) -> list[list[float]]:
        items = data.get("data")
        if isinstance(items, dict):
            items = items.get("data") or items.get("embeddings")
        if not isinstance(items, list):
            raise LLMError(f"Unable to extract embeddings from response keys: {list(data.keys())}")
        parsed = []
        for position, item in enumerate(items):
            if not isinstance(item, dict) or "embedding" not in item:
                raise LLMError("Embedding response item does not contain embedding.")
            parsed.append((int(item.get("index", position)), item["embedding"]))
        parsed.sort(key=lambda pair: pair[0])
        return [embedding for _, embedding in parsed]
