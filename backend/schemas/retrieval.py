from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievalQuery(BaseModel):
    agent_name: str
    intent_id: str | None = None
    run_mode: str | None = None
    query: str
    metadata_filter: dict = Field(default_factory=dict)
    top_k: int = 5


class RetrievedChunk(BaseModel):
    chunk_id: str
    source_id: str
    title: str
    scope: str = "unknown"
    text: str
    score: float = 0.0
    metadata: dict = Field(default_factory=dict)


class Citation(BaseModel):
    source_id: str
    title: str
    scope: str = "unknown"
    quote: str | None = None
