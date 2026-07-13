from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.services.document_pipeline import DocumentPipeline


class FakeCache:
    def __init__(self, events: list[str]):
        self.events = events
        self.store: dict[str, dict] = {}
        self.keys: list[str] = []

    def namespaced(self, namespace: str, digest: str) -> str:
        key = f"test:{namespace}:{digest}"
        self.keys.append(key)
        return key

    def get_json(self, key: str):
        self.events.append(f"cache_get:{key}")
        return self.store.get(key)

    def set_json(self, key: str, value, ttl_seconds: int | None) -> None:
        self.events.append(f"cache_set:{key}:ttl={ttl_seconds}")
        self.store[key] = value


class FakeRouter:
    def __init__(self, events: list[str]):
        self.events = events
        self.calls: list[bool] = []

    def parse_file(self, path: Path, *, fast_mode: bool = False):
        self.calls.append(fast_mode)
        self.events.append(f"router_parse:{path.name}:fast={fast_mode}")
        return "员工姓名：测试员工\n关键目标：完成沟通准备。", {
            "parser": "fake",
            "structured_blocks": [{"type": "text", "text": "员工姓名：测试员工"}],
            "pages": [{"page": 1}],
            "tables": [],
            "images": [],
        }


def build_pipeline(events: list[str]) -> DocumentPipeline:
    pipeline = object.__new__(DocumentPipeline)
    pipeline.router = FakeRouter(events)
    pipeline.cache = FakeCache(events)
    pipeline.settings = SimpleNamespace(
        document_parse_cache_ttl_seconds=3600,
        mineru_enabled=True,
        mineru_backend="hybrid-engine",
        mineru_effort="high",
        mineru_parse_method="auto",
        mineru_lang="ch",
        kb_index_version="test-v1",
    )
    return pipeline


def test_parse_file_execution_order_and_cache_effect(tmp_path: Path):
    events: list[str] = []
    pipeline = build_pipeline(events)
    source = tmp_path / "employee-profile.md"
    source.write_text("员工姓名：测试员工", encoding="utf-8")

    first = pipeline.parse_file(source, "doc-1", fast_mode=True)
    second = pipeline.parse_file(source, "doc-2", fast_mode=True)

    assert first.document_id == "doc-1"
    assert first.metadata["parser"] == "fake"
    assert first.metadata.get("cache_hit") is None
    assert second.document_id == "doc-2"
    assert second.metadata["cache_hit"] is True
    assert second.metadata["input_path"] == str(source)
    assert pipeline.router.calls == [True]

    assert events[0].startswith("cache_get:test:doc_parse:")
    assert events[1] == "router_parse:employee-profile.md:fast=True"
    assert events[2].startswith("cache_set:test:doc_parse:")
    assert events[2].endswith(":ttl=3600")
    assert events[3] == events[0]
    assert len(events) == 4


def test_fast_mode_is_part_of_document_cache_key(tmp_path: Path):
    events: list[str] = []
    pipeline = build_pipeline(events)
    source = tmp_path / "same-file.pdf"
    source.write_bytes(b"same bytes")

    fast_key = pipeline._file_cache_key(source, source.read_bytes(), fast_mode=True)
    full_key = pipeline._file_cache_key(source, source.read_bytes(), fast_mode=False)

    assert fast_key != full_key
    assert fast_key.startswith("test:doc_parse:")
    assert full_key.startswith("test:doc_parse:")
