from __future__ import annotations

from pathlib import Path
from typing import NoReturn


def build_local_chunk_index(raw_dir: Path, output_path: Path) -> NoReturn:
    """Local JSON chunk indexes are forbidden in the strict PostgreSQL pgvector pipeline.

    KB ingest must run through:
      MinerU -> chunking -> EmbeddingService -> PostgreSQL pgvector upsert.

    This function is intentionally kept only to fail fast for any stale import or
    accidental caller that still tries to build a local chunk index.
    """
    raise RuntimeError(
        "Local chunk index is disabled. Use services.kb_ingestion.KBIngestionService "
        "to parse with MinerU, embed chunks, and write to PostgreSQL pgvector."
    )
