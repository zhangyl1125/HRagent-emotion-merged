from pathlib import Path

from backend.parsers.mineru import MinerUParser
from backend.vectorstore.pgvector_client import PGVectorClient


def test_mineru_uses_processed_output_dir(tmp_path: Path):
    parser = MinerUParser()
    parser.settings.mineru_output_dir = tmp_path / "kb_processed"

    output_dir = parser._make_output_dir(tmp_path / "sample.pdf")

    assert output_dir.parent == tmp_path / "kb_processed"
    assert output_dir.exists()
    assert output_dir.name.startswith("sample_")


def test_pgvector_where_from_filter_supports_scope_and_scalar():
    client = object.__new__(PGVectorClient)
    where, params = PGVectorClient._where_from_filter(client, {"scope": ["policy", "performance"], "intent_id": "pip"})
    assert "scope = ANY" in where
    assert "metadata ->>" in where
    assert params == [["policy", "performance"], "intent_id", "pip"]


def test_retrieval_filters_configured_scopes_to_indexed_scopes():
    from backend.services.retrieval_service import RetrievalService

    service = RetrievalService()

    class Repo:
        def load(self):
            return {
                "collections": {
                    "policy": {"vector_count": 0},
                    "performance": {"vector_count": 3},
                    "emotion": {"chunk_count": 2},
                }
            }

    service.vector_repo = Repo()
    assert service._available_scopes(["policy", "performance", "emotion", "examples"]) == ["performance", "emotion"]


def test_retrieval_raw_scope_fallback_uses_existing_kb_folders(tmp_path: Path):
    from backend.services.retrieval_service import RetrievalService

    raw_root = tmp_path / "kb_raw"
    (raw_root / "performance").mkdir(parents=True)
    (raw_root / "performance" / "a.md").write_text("x", encoding="utf-8")
    (raw_root / "empty").mkdir(parents=True)

    assert RetrievalService._raw_kb_scopes(raw_root) == {"performance"}


def test_retrieval_returns_empty_when_configured_scopes_are_unavailable():
    from backend.services.retrieval_service import RetrievalService

    service = RetrievalService()

    class Loader:
        def query_config(self):
            return {
                "queries": {
                    "redline_check": {
                        "enabled": True,
                        "scopes": ["policy"],
                        "query_templates": ["红线风险"],
                    }
                }
            }

    class Repo:
        def load(self):
            return {"collections": {"performance": {"vector_count": 3}, "emotion": {"chunk_count": 2}}}

    service.loader = Loader()
    service.vector_repo = Repo()

    assert service.retrieve("redline_check", {}) == []
