from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from jinja2 import Template

from backend.business_config.loader import get_config_loader
from backend.config.settings import get_settings
from backend.repositories.vector_index_repository import VectorIndexRepository
from backend.schemas.retrieval import RetrievedChunk
from backend.vectorstore.pgvector_client import PGVectorClient
from backend.rag.reranker import Reranker


class RetrievalService:
    """Coach / Guidance retrieval entry backed by PostgreSQL pgvector and rerank API."""

    def __init__(self):
        self.loader = get_config_loader()
        self.settings = get_settings()
        self.reranker = Reranker()
        self.vector_repo = VectorIndexRepository()

    def retrieve(self, agent_name: str, context: dict[str, Any], top_k: int | None = None) -> list[RetrievedChunk]:
        query_config = self.loader.query_config()
        defaults = query_config.get("defaults", {})
        all_queries = query_config.get("queries") or query_config.get("agent_queries") or {}
        agent_cfg = all_queries.get(agent_name)
        if not agent_cfg or agent_cfg.get("enabled", True) is False:
            raise ValueError(f"Missing or disabled retrieval query config for agent: {agent_name}")

        templates = agent_cfg.get("query_templates") or agent_cfg.get("queries") or defaults.get("query_templates") or defaults.get("queries") or []
        if not templates:
            raise ValueError(f"No query templates configured for agent: {agent_name}")
        configured_scopes = self._normalize_scopes(agent_cfg.get("scopes") or defaults.get("scopes") or [])
        if not configured_scopes:
            raise ValueError(f"No pgvector scopes configured for agent: {agent_name}")
        scopes = self._available_scopes(configured_scopes)
        if not scopes:
            return []
        vector_top_k = int(
            agent_cfg.get("vector_top_k")
            or agent_cfg.get("top_k")
            or defaults.get("vector_top_k")
            or defaults.get("top_k")
            or 20
        )
        final_top_k = int(top_k or agent_cfg.get("rerank_top_n") or defaults.get("rerank_top_n") or 5)
        rerank_enabled = bool(agent_cfg.get("rerank_enabled", defaults.get("rerank_enabled", True)))
        metadata_filter = dict(defaults.get("metadata_filter") or {})
        metadata_filter.update(agent_cfg.get("metadata_filter") or {})

        rendered_queries: list[str] = []
        for template in templates:
            rendered = Template(str(template)).render(**context).strip()
            if rendered:
                rendered_queries.append(rendered)
        if not rendered_queries:
            raise ValueError(f"Rendered retrieval query is empty for agent: {agent_name}")

        search_jobs = [(rendered, str(scope)) for rendered in rendered_queries for scope in scopes]
        query_parallelism = self._worker_count(
            len(search_jobs),
            agent_cfg.get("query_parallelism") or defaults.get("query_parallelism"),
            default=8,
        )
        candidates: list[RetrievedChunk] = []
        with ThreadPoolExecutor(max_workers=query_parallelism) as executor:
            futures = [
                executor.submit(self._search_scope, rendered, scope, vector_top_k, metadata_filter)
                for rendered, scope in search_jobs
            ]
            for future in as_completed(futures):
                candidates.extend(future.result())

        merged: dict[str, RetrievedChunk] = {}
        for item in candidates:
            old = merged.get(item.chunk_id)
            if old is None or item.score > old.score:
                merged[item.chunk_id] = item
        merged_chunks = list(merged.values())
        if not merged_chunks:
            return []
        query_for_rerank = "\n".join(rendered_queries)
        if rerank_enabled:
            rerank_parallelism = self._worker_count(
                len(merged_chunks),
                agent_cfg.get("rerank_parallelism") or defaults.get("rerank_parallelism"),
                default=4,
            )
            return self.reranker.rerank(
                merged_chunks,
                query=query_for_rerank,
                top_k=final_top_k,
                parallelism=rerank_parallelism,
            )
        return sorted(merged_chunks, key=lambda c: c.score, reverse=True)[:final_top_k]

    def _search_scope(
        self,
        rendered_query: str,
        scope: str,
        vector_top_k: int,
        metadata_filter: dict[str, Any],
    ) -> list[RetrievedChunk]:
        collection_name = self.settings.collection_name_for_scope(scope)
        store = PGVectorClient(collection_name=collection_name)
        scope_filter = {**metadata_filter, "scope": scope}
        try:
            return store.search(rendered_query, top_k=vector_top_k, metadata_filter=scope_filter)
        except RuntimeError as exc:
            if "pgvector collection is empty" in str(exc):
                return []
            raise

    @staticmethod
    def _worker_count(job_count: int, configured: object, default: int) -> int:
        if job_count <= 0:
            return 1
        try:
            requested = int(configured or default)
        except (TypeError, ValueError):
            requested = default
        return max(1, min(job_count, max(1, requested)))

    def _available_scopes(self, configured_scopes: list[str]) -> list[str]:
        indexed_scopes = self._indexed_scopes()
        if not indexed_scopes:
            indexed_scopes = self._raw_kb_scopes(self.settings.data_dir / "kb_raw")
        return [scope for scope in configured_scopes if scope in indexed_scopes]

    def _indexed_scopes(self) -> set[str]:
        metadata = self.vector_repo.load()
        collections = metadata.get("collections") or {}
        indexed: set[str] = set()
        if not isinstance(collections, dict):
            return indexed
        for scope, info in collections.items():
            if not isinstance(info, dict):
                continue
            count = int(info.get("vector_count") or info.get("chunk_count") or 0)
            if count > 0:
                indexed.add(str(scope))
        return indexed

    @staticmethod
    def _raw_kb_scopes(raw_root: Path) -> set[str]:
        supported = {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx"}
        if not raw_root.exists():
            return set()
        scopes: set[str] = set()
        for path in raw_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in supported:
                continue
            relative = path.relative_to(raw_root)
            scopes.add(relative.parts[0] if len(relative.parts) > 1 else "general")
        return scopes

    @staticmethod
    def _normalize_scopes(raw_scopes: list | tuple | set) -> list[str]:
        scopes: list[str] = []
        seen: set[str] = set()
        for raw in raw_scopes or []:
            scope = str(raw).strip()
            if scope and scope not in seen:
                scopes.append(scope)
                seen.add(scope)
        return scopes
