from __future__ import annotations

from backend.exceptions.llm_errors import LLMError
from backend.schemas.retrieval import RetrievedChunk
from backend.services.rerank_service import RerankService


class Reranker:
    def __init__(self):
        self.service = RerankService()

    def rerank(self, chunks: list[RetrievedChunk], query: str | None = None, top_k: int | None = None) -> list[RetrievedChunk]:
        if not chunks:
            return []
        if not query or not query.strip():
            raise LLMError("Reranker requires a non-empty query in strict mode.")
        ranked = self.service.rerank(query, [chunk.text for chunk in chunks], top_n=top_k or len(chunks))
        output: list[RetrievedChunk] = []
        for index, relevance_score in ranked:
            if 0 <= index < len(chunks):
                chunk = chunks[index]
                chunk.score = relevance_score
                output.append(chunk)
        return output[: top_k or len(output)]
