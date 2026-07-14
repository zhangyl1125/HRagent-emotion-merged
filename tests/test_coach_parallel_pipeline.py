import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.coach_agent.coach_orchestrator import CoachOrchestrator
from backend.schemas.coach import CoachReport
from backend.schemas.conversation import ConversationTurn
from backend.schemas.emotion import ConversationEmotionLog, EmotionState, EmployeeAttitude
from backend.schemas.simulation import BigFivePersonality, MotivationState, VADVector
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult
from backend.services.coach_service import CoachService
from backend.workflows.coach_graph import CoachWorkflow


_TASK_SPECS = (
    ("rubric_evaluation", "Rubric 综合评估"),
    ("emotion_evaluation", "情绪承接评估"),
    ("performance_evaluation", "绩效反馈质量评估"),
    ("redline_check", "话术红线检测"),
)


def _state() -> SessionState:
    motivation = MotivationState(
        primary_motive_id="security",
        secondary_motive_ids=["recognition", "affiliation"],
        primary_score=38,
        secondary_scores={"recognition": 46, "affiliation": 42},
    )
    return SessionState(
        session_id="coach-parallel",
        personality=BigFivePersonality(openness=44, conscientiousness=73),
        motivation=motivation,
        emotion_state=EmotionState(
            interview_purpose="exit_warning",
            primary_motivation="commerce",
            secondary_motivation="power",
            primary_satisfaction=91,
            secondary_satisfaction=87,
            total_satisfaction=89,
            last_primary_delta=9,
            last_secondary_delta=7,
            current_vad=VADVector(valence=-0.35, arousal=0.48, dominance=-0.18),
            current_anchor_id="guarded",
            transition_strategy="maximum_probability",
            last_reason_summary="manager response increased pressure",
        ),
        conversation=[
            ConversationTurn(turn_index=1, speaker="manager", text="我们先对齐事实。"),
            ConversationTurn(turn_index=2, speaker="employee", text="我担心后续安排。"),
        ],
        emotion_log=[
            ConversationEmotionLog(
                turn_index=1,
                hrbp_text="我们先对齐事实。",
                employee_attitude_before=EmployeeAttitude.GUARDED_HESITANT,
                employee_attitude_after=EmployeeAttitude.DEFENSIVE_RESISTANT,
                intensity=62,
                transition_reason="安全感诉求未被充分回应",
                vad_before=VADVector(valence=-0.1, arousal=0.2, dominance=-0.05),
                vad_after=VADVector(valence=-0.35, arousal=0.48, dominance=-0.18),
                motivation_before=motivation,
                motivation_after=motivation,
            )
        ],
    )


@pytest.mark.asyncio
async def test_coach_workflow_fans_out_evaluators_before_dynamic_report():
    state = _state()
    workflow = CoachWorkflow()
    started: set[str] = set()
    all_started = asyncio.Event()
    release = asyncio.Event()
    report_calls: list[dict] = []

    class Evaluator:
        def __init__(self, task_id: str, task_name: str):
            self.task_id = task_id
            self.task_name = task_name

        async def evaluate(self, next_state, retrieved_chunks=None):
            assert next_state is state
            assert retrieved_chunks == []
            started.add(self.task_id)
            if len(started) == len(_TASK_SPECS):
                all_started.set()
            await release.wait()
            return CoachTaskResult(
                task_id=self.task_id,
                task_name=self.task_name,
                summary="ok",
            )

    class ReportGenerator:
        async def generate(self, session_id, task_results, **kwargs):
            report_calls.append({"task_results": task_results, **kwargs})
            return CoachReport(session_id=session_id, summary="ok")

    (
        workflow.orchestrator.rubric,
        workflow.orchestrator.emotion,
        workflow.orchestrator.performance,
        workflow.orchestrator.redline,
    ) = tuple(Evaluator(task_id, task_name) for task_id, task_name in _TASK_SPECS)
    workflow.orchestrator.report_generator = ReportGenerator()

    run_task = asyncio.create_task(
        workflow.run(
            state,
            retrieved_chunks_by_task={task_id: [] for task_id, _task_name in _TASK_SPECS},
        )
    )
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1)
        assert not run_task.done()
    finally:
        release.set()

    report = await asyncio.wait_for(run_task, timeout=1)

    assert [result.task_id for result in report.task_results] == [
        task_id for task_id, _task_name in _TASK_SPECS
    ]
    assert len(report_calls) == 1
    report_context = report_calls[0]
    assert report_context["personality"]["conscientiousness"] == 73
    assert report_context["motivation"]["primary_motive_id"] == "security"
    assert report_context["emotion_state"]["current_vad"]["valence"] == -0.35
    assert report_context["emotion_state"]["current_anchor_id"] == "guarded"
    assert report_context["emotion_state"]["transition_strategy"] == "maximum_probability"
    assert {
        "interview_purpose",
        "primary_motivation",
        "secondary_motivation",
        "primary_satisfaction",
        "secondary_satisfaction",
        "total_satisfaction",
        "last_primary_delta",
        "last_secondary_delta",
    }.isdisjoint(report_context["emotion_state"])
    assert report_context["emotion_log"][0]["vad_after"]["valence"] == -0.35


@pytest.mark.asyncio
async def test_coach_service_retrieves_for_all_evaluators_and_report_generator():
    state = _state()
    retrieval_calls: list[tuple[str, dict]] = []
    saved: dict[str, object] = {}

    class Retrieval:
        def retrieve(self, task_id, context):
            retrieval_calls.append((task_id, context))
            return []

    class Workflow:
        async def run(self, next_state, retrieved_chunks_by_task):
            assert next_state is state
            assert set(retrieved_chunks_by_task) == {
                *(task_id for task_id, _task_name in _TASK_SPECS),
                "report_generator",
            }
            return CoachReport(session_id=next_state.session_id, summary="ok")

    class ReportRepository:
        def save_coach(self, report):
            saved["report"] = report

    class SessionService:
        def save_session(self, next_state):
            saved["state"] = next_state
            return next_state

    service = CoachService.__new__(CoachService)
    service.retrieval = Retrieval()
    service.orchestrator = Workflow()
    service.report_repo = ReportRepository()
    service.session_service = SessionService()
    service.settings = SimpleNamespace(coach_report_max_concurrency_per_worker=2)

    report = await service._generate_uncached(state.session_id, state)

    assert {task_id for task_id, _context in retrieval_calls} == {
        *(task_id for task_id, _task_name in _TASK_SPECS),
        "report_generator",
    }
    assert all(context["personality"]["conscientiousness"] == 73 for _task_id, context in retrieval_calls)
    assert all(context["motivation"]["primary_motive_id"] == "security" for _task_id, context in retrieval_calls)
    assert all(context["emotion_state"]["current_vad"]["valence"] == -0.35 for _task_id, context in retrieval_calls)
    assert all(context["emotion_log"][0]["vad_after"]["valence"] == -0.35 for _task_id, context in retrieval_calls)
    assert len(state.warnings) == len(_TASK_SPECS) + 1
    assert saved == {"report": report, "state": state}


@pytest.mark.asyncio
async def test_legacy_report_keeps_complete_emotion_state_payload():
    state = SessionState(
        session_id="coach-legacy",
        emotion_state=EmotionState(
            interview_purpose="retention",
            primary_motivation="commerce",
            secondary_motivation="power",
            primary_satisfaction=64,
            secondary_satisfaction=58,
            total_satisfaction=61,
            last_primary_delta=4,
            last_secondary_delta=2,
            current_vad=VADVector(valence=0.1, arousal=0.2, dominance=0.3),
        ),
    )
    orchestrator = CoachOrchestrator()
    report_context: dict = {}

    class ReportGenerator:
        async def generate(self, session_id, task_results, **kwargs):
            report_context.update(kwargs)
            return CoachReport(session_id=session_id, summary="ok")

    orchestrator.report_generator = ReportGenerator()
    task_results = [
        CoachTaskResult(task_id=task_id, task_name=task_name, summary="ok")
        for task_id, task_name in _TASK_SPECS
    ]

    await orchestrator.finalize_report(state, task_results)

    assert report_context["motivation"] == {}
    assert report_context["emotion_state"]["interview_purpose"] == "retention"
    assert report_context["emotion_state"]["primary_motivation"] == "commerce"
    assert report_context["emotion_state"]["secondary_motivation"] == "power"
    assert report_context["emotion_state"]["primary_satisfaction"] == 64
    assert report_context["emotion_state"]["secondary_satisfaction"] == 58
    assert report_context["emotion_state"]["total_satisfaction"] == 61
    assert report_context["emotion_state"]["last_primary_delta"] == 4
    assert report_context["emotion_state"]["last_secondary_delta"] == 2
