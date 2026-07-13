import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.agents.coach_agent.coach_orchestrator import CoachOrchestrator
from backend.schemas.coach import CoachReport
from backend.schemas.conversation import ConversationTurn
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult
from backend.services.coach_service import CoachService


class NoopCache:
    def namespaced(self, namespace, digest):
        return f"test:{namespace}:{digest}"

    async def get_json_async(self, key):
        return None

    async def set_json_async(self, key, value, ttl_seconds):
        return None


class MemoryCache(NoopCache):
    def __init__(self, payload=None):
        self.payload = payload
        self.set_calls = []

    async def get_json_async(self, key):
        return self.payload

    async def set_json_async(self, key, value, ttl_seconds):
        self.set_calls.append((key, value, ttl_seconds))


@pytest.mark.asyncio
async def test_coach_report_allows_empty_kb_chunks_and_records_warning():
    state = SessionState(
        session_id="s1",
        setup_ready=True,
        conversation=[
            ConversationTurn(turn_index=1, speaker="manager", text="我们来复盘绩效差距。"),
            ConversationTurn(turn_index=2, speaker="employee", text="我觉得资源不足。"),
        ],
    )
    saved = {}

    class SessionService:
        def get_session(self, session_id):
            assert session_id == "s1"
            return state

        def save_session(self, next_state):
            saved["state"] = next_state
            return next_state

    class ReportRepo:
        def save_coach(self, report):
            saved["report"] = report

    class Retrieval:
        def retrieve(self, task_id, context):
            return []

    class Orchestrator:
        async def run(self, next_state, retrieved_chunks_by_task):
            assert set(retrieved_chunks_by_task) == {
                "rubric_evaluation",
                "emotion_evaluation",
                "performance_evaluation",
                "redline_check",
                "report_generator",
            }
            assert all(chunks == [] for chunks in retrieved_chunks_by_task.values())
            return CoachReport(session_id=next_state.session_id, summary="ok")

    service = CoachService()
    service.session_service = SessionService()
    service.report_repo = ReportRepo()
    service.retrieval = Retrieval()
    service.orchestrator = Orchestrator()
    service.cache = NoopCache()

    report = await service.generate("s1")

    assert report.session_id == "s1"
    assert state.stage == "report_ready"
    assert state.coach_report_id == "s1"
    assert any("redline_check" in warning for warning in state.warnings)
    assert saved["report"] is report
    assert saved["state"] is state


def test_coach_report_status_is_partial_when_any_task_failed():
    report = CoachReport(session_id="s1", status="completed", summary="报告已生成。")
    task_results = [
        CoachTaskResult(task_id="rubric_evaluation", task_name="Rubric 综合评估", status="success", score=80, summary="ok"),
        CoachTaskResult(task_id="performance_evaluation", task_name="绩效反馈质量评估", status="failed", summary="结构化输出失败"),
    ]

    normalized = CoachOrchestrator._normalize_report_status(report, task_results)

    assert normalized.status == "partial"
    assert "绩效反馈质量评估" in normalized.summary
    assert normalized.task_results == task_results


def test_coach_report_content_cache_key_ignores_runtime_timestamps():
    first_state = SessionState(
        session_id="s-cache-1",
        conversation=[
            ConversationTurn(
                turn_index=1,
                speaker="manager",
                text="我们来复盘绩效差距。",
                created_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
            ),
        ],
    )
    second_state = SessionState(
        session_id="s-cache-2",
        conversation=[
            ConversationTurn(
                turn_index=1,
                speaker="manager",
                text="我们来复盘绩效差距。",
                created_at=datetime(2026, 7, 9, tzinfo=timezone.utc) + timedelta(minutes=3),
            ),
        ],
    )

    service = CoachService()
    service.cache = NoopCache()

    assert service._cache_key(first_state) == service._cache_key(second_state)


@pytest.mark.asyncio
async def test_coach_report_returns_cached_report_when_report_id_exists():
    state = SessionState(
        session_id="s1",
        setup_ready=True,
        coach_report_id="s1",
        conversation=[ConversationTurn(turn_index=1, speaker="manager", text="我们来复盘。")],
    )
    cached = CoachReport(session_id="s1", summary="cached")

    class SessionService:
        def get_session(self, session_id):
            assert session_id == "s1"
            return state

    class ReportRepo:
        def get_coach(self, session_id):
            assert session_id == "s1"
            return cached

    class Retrieval:
        def retrieve(self, task_id, context):
            raise AssertionError("cached report should skip retrieval")

    class Orchestrator:
        async def run(self, next_state, retrieved_chunks_by_task):
            raise AssertionError("cached report should skip orchestration")

    service = CoachService()
    service.session_service = SessionService()
    service.report_repo = ReportRepo()
    service.retrieval = Retrieval()
    service.orchestrator = Orchestrator()
    service.cache = NoopCache()

    report = await service.generate("s1")

    assert report is cached


@pytest.mark.asyncio
async def test_coach_report_returns_content_cache_and_persists_for_session():
    state = SessionState(
        session_id="s2",
        setup_ready=True,
        conversation=[ConversationTurn(turn_index=1, speaker="manager", text="我们来复盘。")],
    )
    cached_payload = CoachReport(session_id="cached-session", summary="cached by content").model_dump(mode="json")
    saved = {}

    class SessionService:
        def get_session(self, session_id):
            assert session_id == "s2"
            return state

        def save_session(self, next_state):
            saved["state"] = next_state
            return next_state

    class ReportRepo:
        def save_coach(self, report):
            saved["report"] = report
            return report

    class Retrieval:
        def retrieve(self, task_id, context):
            raise AssertionError("content cache should skip retrieval")

    class Orchestrator:
        async def run(self, next_state, retrieved_chunks_by_task):
            raise AssertionError("content cache should skip orchestration")

    service = CoachService()
    service.session_service = SessionService()
    service.report_repo = ReportRepo()
    service.retrieval = Retrieval()
    service.orchestrator = Orchestrator()
    service.cache = MemoryCache(cached_payload)

    report = await service.generate("s2")

    assert report.session_id == "s2"
    assert report.summary == "cached by content"
    assert saved["report"] is report
    assert saved["state"].coach_report_id == "s2"
    assert saved["state"].stage == "report_ready"


@pytest.mark.asyncio
async def test_concurrent_coach_report_generation_reuses_inflight_result():
    session_id = "concurrent-s1"
    state = SessionState(
        session_id=session_id,
        setup_ready=True,
        conversation=[ConversationTurn(turn_index=1, speaker="manager", text="我们来复盘绩效差距。")],
    )
    saved = {}
    run_calls = 0

    class SessionService:
        def get_session(self, requested_session_id):
            assert requested_session_id == session_id
            return state

        def save_session(self, next_state):
            saved["state"] = next_state
            return next_state

    class ReportRepo:
        def get_coach(self, requested_session_id):
            assert requested_session_id == session_id
            if "report" not in saved:
                raise KeyError(requested_session_id)
            return saved["report"]

        def save_coach(self, report):
            saved["report"] = report
            return report

    class Retrieval:
        def retrieve(self, task_id, context):
            return []

    class Orchestrator:
        async def run(self, next_state, retrieved_chunks_by_task):
            nonlocal run_calls
            run_calls += 1
            await asyncio.sleep(0.05)
            return CoachReport(session_id=next_state.session_id, summary="ok")

    def make_service():
        service = CoachService()
        service.session_service = SessionService()
        service.report_repo = ReportRepo()
        service.retrieval = Retrieval()
        service.orchestrator = Orchestrator()
        service.cache = NoopCache()
        return service

    first, second = await asyncio.gather(
        make_service().generate(session_id),
        make_service().generate(session_id),
    )

    assert run_calls == 1
    assert first is saved["report"]
    assert second is saved["report"]
    assert state.stage == "report_ready"
    assert state.coach_report_id == session_id

