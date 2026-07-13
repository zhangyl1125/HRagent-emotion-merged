from __future__ import annotations

from backend.schemas.retrieval import Citation, RetrievedChunk


def chunks_to_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    seen: set[str] = set()
    citations: list[Citation] = []
    for chunk in chunks:
        key = f"{chunk.source_id}:{chunk.title}"
        if key in seen:
            continue
        seen.add(key)
        citations.append(Citation(source_id=chunk.source_id, title=chunk.title, scope=chunk.scope, quote=chunk.text[:160]))
    return citations
