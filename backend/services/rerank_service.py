from __future__ import annotations

import time
from typing import Any

import httpx

from backend.config.settings import get_settings
from backend.exceptions.llm_errors import LLMError
from backend.services.model_api_auth import ModelAPIAuth
from backend.services.usage_tracking_service import UsageTrackingService


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
        input_bytes = len(query.encode("utf-8")) + sum(len(document.encode("utf-8")) for document in documents)
        started_at = time.monotonic()
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    raise LLMError(f"Rerank API HTTP {resp.status_code}: {resp.text[:1000]}")
                data = resp.json()
                ranked = self._extract_ranked_indexes(data)
        except Exception as exc:
            UsageTrackingService().record(
                usage=UsageTrackingService.normalize_input_only(None, estimated_input_bytes=input_bytes),
                task_name="rerank", provider=self.settings.rerank_provider,
                model=self.settings.rerank_model, streaming=False, status="error",
                duration_ms=round((time.monotonic() - started_at) * 1000),
                error_code=type(exc).__name__,
                usage_metadata={"usage_kind": "rerank", "document_count": len(documents)},
            )
            raise
        UsageTrackingService().record(
            usage=UsageTrackingService.normalize_input_only(self._extract_usage(data), estimated_input_bytes=input_bytes),
            task_name="rerank", provider=self.settings.rerank_provider,
            model=self.settings.rerank_model, streaming=False, status="success",
            duration_ms=round((time.monotonic() - started_at) * 1000),
            usage_metadata={"usage_kind": "rerank", "document_count": len(documents)},
        )
        return ranked

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> dict[str, Any] | None:
        usage = data.get("usage")
        if usage is None and isinstance(data.get("data"), dict):
            usage = data["data"].get("usage")
        return usage if isinstance(usage, dict) else None

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
