from __future__ import annotations

from backend.services.kb_ingestion import KBIngestionService


def rebuild_kb_index_task() -> dict:
    return KBIngestionService().ingest()
