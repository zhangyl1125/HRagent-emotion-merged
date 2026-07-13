from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings
from backend.parsers.parser_router import ParserRouter
from backend.rag.chunking import chunk_blocks
from backend.repositories.manifest_repository import ManifestRepository
from backend.repositories.vector_index_repository import VectorIndexRepository
from backend.schemas.retrieval import RetrievedChunk
from backend.services.embedding_service import EmbeddingService
from backend.vectorstore.pgvector_client import PGVectorClient


class IndexManager:
    """Build KB chunks, embed them, and write them into PostgreSQL pgvector."""

    def __init__(self):
        self.settings = get_settings()
        self.parser = ParserRouter()
        self.embedding_service = EmbeddingService()
        self.manifest_repo = ManifestRepository()
        self.vector_repo = VectorIndexRepository()
        self.last_summary: dict[str, Any] = {}

    def rebuild(self, raw_dir: Path | None = None) -> list[dict]:
        raw_root = raw_dir or self.settings.data_dir / "kb_raw"
        if not raw_root.exists():
            raise FileNotFoundError(f"KB raw directory does not exist: {raw_root}")
        started_at = time.time()
        chunks_by_scope, documents = self._build_chunks(raw_root)
        if not chunks_by_scope:
            raise RuntimeError(f"没有可索引的 KB 文件: {raw_root}")

        vector_count = 0
        collections: dict[str, dict[str, Any]] = {}
        for scope, chunks in sorted(chunks_by_scope.items()):
            collection_name = self.settings.collection_name_for_scope(scope)
            store = PGVectorClient(embedding_service=self.embedding_service, collection_name=collection_name)
            store.reset_collection()
            for doc in documents:
                if doc["scope"] == scope:
                    store.upsert_document(doc)
            count = self._embed_and_upsert(store, chunks)
            vector_count += count
            collections[scope] = {
                "collection_name": collection_name,
                "chunk_count": len(chunks),
                "vector_count": count,
            }

        built_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        elapsed = round(time.time() - started_at, 3)
        summary = {
            "raw_dir": str(raw_root),
            "chunk_count": sum(len(v) for v in chunks_by_scope.values()),
            "vector_count": vector_count,
            "collections": collections,
            "database_url_configured": bool(self.settings.database_url),
            "vectorstore_provider": self.settings.vectorstore_provider,
            "embedding_provider": self.settings.embedding_provider,
            "embedding_model": self.settings.embedding_model,
            "index_version": self.settings.kb_index_version,
            "errors": [],
            "elapsed_seconds": elapsed,
            "built_at": built_at,
        }
        self.last_summary = summary
        self.manifest_repo.save({"documents": documents, "collections": collections, "errors": [], "built_at": built_at})
        self.vector_repo.save(summary)
        return [chunk.model_dump() for chunks in chunks_by_scope.values() for chunk in chunks]

    def _build_chunks(self, raw_root: Path) -> tuple[dict[str, list[RetrievedChunk]], list[dict[str, Any]]]:
        supported = {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx"}
        chunks_by_scope: dict[str, list[RetrievedChunk]] = {}
        documents: list[dict[str, Any]] = []
        for path in sorted(raw_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in supported:
                continue
            scope = self._scope_from_path(raw_root, path)
            source_id = str(path.relative_to(raw_root)).replace("\\", "/")
            doc_id = self._doc_id(source_id)
            content_hash = self._file_hash(path)
            text, parse_metadata = self.parser.parse_file(path)
            chunk_entries = chunk_blocks(
                text=text,
                blocks=list(parse_metadata.get("structured_blocks") or []),
                chunk_size=self.settings.kb_chunk_size,
                overlap=self.settings.kb_chunk_overlap,
            )
            if not chunk_entries:
                raise RuntimeError(f"解析后未生成 chunk: {path}")
            doc_chunk_ids: list[str] = []
            collection_name = self.settings.collection_name_for_scope(scope)
            for entry in chunk_entries:
                idx = int(entry.get("chunk_index") or len(doc_chunk_ids))
                chunk_text = str(entry["text"])
                chunk_id = self._stable_chunk_id(doc_id=doc_id, index=idx, text=chunk_text)
                doc_chunk_ids.append(chunk_id)
                chunk = RetrievedChunk(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    title=path.stem,
                    scope=scope,
                    text=chunk_text,
                    metadata={
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "source_path": str(path),
                        "relative_path": source_id,
                        "scope": scope,
                        "tag": path.stem,
                        "page": entry.get("page"),
                        "section": entry.get("section"),
                        "content_hash": content_hash,
                        "index_version": self.settings.kb_index_version,
                        "chunk_index": idx,
                        "collection_name": collection_name,
                        "parser": parse_metadata.get("parser"),
                    },
                )
                chunks_by_scope.setdefault(scope, []).append(chunk)
            documents.append({
                "doc_id": doc_id,
                "scope": scope,
                "source_path": str(path),
                "relative_path": source_id,
                "content_hash": content_hash,
                "chunk_count": len(doc_chunk_ids),
                "chunk_ids": doc_chunk_ids,
                "collection_name": collection_name,
                "embedding_model": self.settings.embedding_model,
                "index_version": self.settings.kb_index_version,
                "index_status": "indexed",
                "parse_metadata": parse_metadata,
            })
        return chunks_by_scope, documents

    def _embed_and_upsert(self, store: PGVectorClient, chunks: list[RetrievedChunk]) -> int:
        total = 0
        batch_size = max(1, self.settings.kb_ingest_batch_size)
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embeddings = self.embedding_service.embed([chunk.text for chunk in batch])
            if len(embeddings) != len(batch):
                raise RuntimeError("Embedding API returned unexpected vector count.")
            total += store.upsert_chunks(batch, embeddings)
        return total

    @staticmethod
    def _scope_from_path(raw_root: Path, path: Path) -> str:
        relative = path.relative_to(raw_root)
        return relative.parts[0] if len(relative.parts) > 1 else "general"

    @staticmethod
    def _doc_id(source_id: str) -> str:
        safe = source_id.replace("/", "__").replace("\\", "__")
        digest = hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:10]
        return f"{safe}__{digest}"

    @staticmethod
    def _stable_chunk_id(doc_id: str, index: int, text: str) -> str:
        digest = hashlib.sha1(f"{doc_id}:{index}:{text}".encode("utf-8")).hexdigest()[:16]
        return f"{doc_id}::{index}::{digest}"

    @staticmethod
    def _file_hash(path: Path) -> str:
        h = hashlib.sha1()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
