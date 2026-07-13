from __future__ import annotations

import json
from typing import Any

from backend.config.settings import get_settings
from backend.repositories.postgres_repository import PostgresRepository
from backend.schemas.retrieval import RetrievedChunk
from backend.services.embedding_service import EmbeddingService


class PGVectorClient:
    """PostgreSQL + pgvector vector store client.

    KB documents, chunks, embeddings, and metadata are stored in PostgreSQL
    tables and queried with pgvector cosine distance.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        collection_name: str | None = None,
        repository: PostgresRepository | None = None,
    ):
        self.settings = get_settings()
        self.embedding_service = embedding_service or EmbeddingService()
        self.collection_name = collection_name or self.settings.collection_name_for_scope("general")
        self.repo = repository or PostgresRepository()

    def reset_collection(self) -> None:
        with self.repo.connection() as conn:
            conn.execute("DELETE FROM kb_chunks WHERE collection_name = %s", (self.collection_name,))
            conn.execute(
                """
                DELETE FROM kb_documents d
                WHERE NOT EXISTS (
                    SELECT 1 FROM kb_chunks c WHERE c.doc_id = d.doc_id
                )
                """
            )

    def upsert_document(self, document: dict[str, Any]) -> None:
        with self.repo.connection() as conn:
            conn.execute(
                """
                INSERT INTO kb_documents (
                    doc_id, scope, source_path, relative_path, content_hash, metadata, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (doc_id) DO UPDATE SET
                    scope = excluded.scope,
                    source_path = excluded.source_path,
                    relative_path = excluded.relative_path,
                    content_hash = excluded.content_hash,
                    metadata = excluded.metadata,
                    updated_at = NOW()
                """,
                (
                    document["doc_id"],
                    document["scope"],
                    document["source_path"],
                    document["relative_path"],
                    document["content_hash"],
                    json.dumps(document, ensure_ascii=False),
                ),
            )

    def upsert_chunks(self, chunks: list[RetrievedChunk], embeddings: list[list[float]]) -> int:
        if not chunks:
            return 0
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        with self.repo.connection() as conn:
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                metadata = self._to_metadata(chunk)
                conn.execute(
                    """
                    INSERT INTO kb_chunks (
                        chunk_id, collection_name, doc_id, source_id, title, scope,
                        text, metadata, embedding, index_version, content_hash, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector, %s, %s, NOW())
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        collection_name = excluded.collection_name,
                        doc_id = excluded.doc_id,
                        source_id = excluded.source_id,
                        title = excluded.title,
                        scope = excluded.scope,
                        text = excluded.text,
                        metadata = excluded.metadata,
                        embedding = excluded.embedding,
                        index_version = excluded.index_version,
                        content_hash = excluded.content_hash,
                        updated_at = NOW()
                    """,
                    (
                        chunk.chunk_id,
                        self.collection_name,
                        str(metadata.get("doc_id") or chunk.source_id),
                        chunk.source_id,
                        chunk.title,
                        chunk.scope,
                        chunk.text,
                        json.dumps(metadata, ensure_ascii=False),
                        self.repo.vector_literal(embedding),
                        str(metadata.get("index_version") or self.settings.kb_index_version),
                        str(metadata.get("content_hash") or ""),
                    ),
                )
        return len(chunks)

    def count(self) -> int:
        with self.repo.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM kb_chunks WHERE collection_name = %s", (self.collection_name,)).fetchone()
        return int(row["n"] if row else 0)

    def search(self, query: str, top_k: int = 5, metadata_filter: dict | None = None) -> list[RetrievedChunk]:
        if not query.strip():
            raise ValueError("pgvector query cannot be empty.")
        if self.count() == 0:
            raise RuntimeError(f"pgvector collection is empty: {self.collection_name}. 请先运行 KB ingest。")
        embeddings = self.embedding_service.embed([query])
        if len(embeddings) != 1:
            raise RuntimeError("Embedding API did not return exactly one query vector.")
        vector = self.repo.vector_literal(embeddings[0])
        where_sql, params = self._where_from_filter(metadata_filter or {})
        sql = f"""
            SELECT
                chunk_id, source_id, title, scope, text, metadata,
                1 - (embedding <=> %s::vector) AS score
            FROM kb_chunks
            WHERE collection_name = %s
            {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        with self.repo.connection() as conn:
            rows = conn.execute(sql, (vector, self.collection_name, *params, vector, int(top_k))).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def _where_from_filter(self, metadata_filter: dict) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for key, expected in (metadata_filter or {}).items():
            if key in {"collection", "collections", "collection_name"}:
                continue
            if key == "scope":
                if isinstance(expected, list):
                    clauses.append("scope = ANY(%s)")
                    params.append([str(x) for x in expected])
                else:
                    clauses.append("scope = %s")
                    params.append(str(expected))
                continue
            if isinstance(expected, list):
                clauses.append("metadata ->> %s = ANY(%s)")
                params.extend([str(key), [str(x) for x in expected]])
            elif isinstance(expected, (str, int, float, bool)):
                clauses.append("metadata ->> %s = %s")
                params.extend([str(key), str(expected)])
        if not clauses:
            return "", []
        return " AND " + " AND ".join(f"({c})" for c in clauses), params

    @staticmethod
    def _to_metadata(chunk: RetrievedChunk) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "source_id": chunk.source_id,
            "title": chunk.title,
            "scope": chunk.scope,
        }
        metadata.update(chunk.metadata or {})
        return metadata

    @staticmethod
    def _row_to_chunk(row: dict[str, Any]) -> RetrievedChunk:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"]),
            scope=str(row["scope"]),
            text=str(row["text"]),
            score=float(row.get("score") or 0.0),
            metadata={k: v for k, v in dict(metadata).items() if k not in {"chunk_id", "source_id", "title", "scope"}},
        )
