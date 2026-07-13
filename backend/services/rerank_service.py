from __future__ import annotations

from typing import Any

import httpx

from backend.config.settings import get_settings
from backend.exceptions.llm_errors import LLMError
from backend.services.model_api_auth import ModelAPIAuth


class RerankService:
    """Strict Bosch rerank API adapter."""

    def __init__(self):
        self.settings = get_settings()
        self.auth = ModelAPIAuth()

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
        if not documents:
            return []
        if not query.strip():
            raise LLMError("Rerank query cannot be empty.")
        url = self.settings.rerank_url
        if not url:
            raise LLMError("Rerank API endpoint is not configured.")
        payload = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": documents,
            "return_documents": False,
        }
        if top_n is not None:
            payload["top_n"] = top_n
        headers = self.auth.sync_headers(self.settings.rerank_api_key or self.settings.chat_api_key)
        headers.setdefault("Content-Type", "application/json")
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise LLMError(f"Rerank API HTTP {resp.status_code}: {resp.text[:1000]}")
            return self._extract_ranked_indexes(resp.json())

    @staticmethod
    def _extract_ranked_indexes(data: dict[str, Any]) -> list[tuple[int, float]]:
        results = data.get("results")
        if results is None and isinstance(data.get("data"), dict):
            results = data["data"].get("results")
        if not isinstance(results, list):
            raise LLMError(f"Unable to extract rerank results from response keys: {list(data.keys())}")
        ranked: list[tuple[int, float]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            ranked.append((int(item.get("index", 0)), float(item.get("relevance_score", 0.0))))
        return ranked
