from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from backend.exceptions.llm_errors import LLMError
from backend.schemas.retrieval import RetrievedChunk
from backend.services.rerank_service import RerankService


class Reranker:
    def __init__(self):
        self.service = RerankService()

    def rerank(
        self,
        chunks: list[RetrievedChunk],
        query: str | None = None,
        top_k: int | None = None,
        parallelism: int = 1,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        if not query or not query.strip():
            raise LLMError("Reranker requires a non-empty query in strict mode.")
        worker_count = max(1, min(int(parallelism or 1), len(chunks)))
        if worker_count <= 1:
            return self._rerank_batch(chunks, query, top_k)
        batches = self._split_chunks(chunks, worker_count)
        output: list[RetrievedChunk] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(self._rerank_batch, batch, query, top_k) for batch in batches]
            for future in as_completed(futures):
                output.extend(future.result())
        output.sort(key=lambda chunk: chunk.score, reverse=True)
        return output[: top_k or len(output)]

    def _rerank_batch(self, chunks: list[RetrievedChunk], query: str, top_k: int | None) -> list[RetrievedChunk]:
        ranked = self.service.rerank(query, [chunk.text for chunk in chunks], top_n=top_k or len(chunks))
        output: list[RetrievedChunk] = []
        for index, relevance_score in ranked:
            if 0 <= index < len(chunks):
                chunk = chunks[index]
                chunk.score = relevance_score
                output.append(chunk)
        return output[: top_k or len(output)]

    @staticmethod
    def _split_chunks(chunks: list[RetrievedChunk], batch_count: int) -> list[list[RetrievedChunk]]:
        batch_count = max(1, min(batch_count, len(chunks)))
        batch_size = (len(chunks) + batch_count - 1) // batch_count
        return [chunks[index : index + batch_size] for index in range(0, len(chunks), batch_size)]
