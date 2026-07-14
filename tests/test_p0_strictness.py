from pathlib import Path

import pytest

from backend.rag.indexing import build_local_chunk_index


def test_local_chunk_index_is_disabled(tmp_path: Path):
    with pytest.raises(RuntimeError, match="Local chunk index is disabled"):
        build_local_chunk_index(tmp_path, tmp_path / "index.json")


def test_profile_agent_has_no_validation_fallback():
    text = Path("backend/agents/profile_extraction.py").read_text(encoding="utf-8")
    assert "except ValidationError" not in text
    assert "EmployeeProfile(**{k: v" not in text
    assert "schema=EmployeeProfile" in text
    assert "ainvoke_structured" in text


def test_guidance_agent_uses_five_parallel_sections_with_strict_report_validation():
    text = Path("backend/agents/guidance_agent.py").read_text(encoding="utf-8")
    assert "GuidanceReport(" not in text
    assert "GuidanceReport.model_validate(payload)" in text
    assert "准备绩效谈话" not in text
    assert "先说明谈话目的" not in text
    assert "GUIDANCE_SECTION_KEYS" in text
    assert "asyncio.gather" in text
    assert "ainvoke_text" in text
    assert "GuidanceStructuredOutput" not in text
    assert "ainvoke_structured" not in text


def test_tests_do_not_skip_missing_langchain_dependency():
    for path in Path("tests").glob("test_*.py"):
        assert "importorskip(\"langchain_core\")" not in path.read_text(encoding="utf-8")
