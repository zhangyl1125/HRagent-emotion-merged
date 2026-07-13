from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.coach_agent.coach_orchestrator import CoachOrchestrator
from backend.schemas.coach import CoachReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult


class CoachGraphState(TypedDict, total=False):
    """LangGraph state for one Coach report generation run.

    The four evaluator nodes run in parallel (fan-out from ``START``) and each
    writes its result to a dedicated key, so there is no concurrent write to the
    same key and no reducer is required. ``generate_report`` is the fan-in node:
    LangGraph only runs it once all four evaluator branches finished.
    """

    state: SessionState
    chunks_by_task: dict[str, list[RetrievedChunk]]
    rubric_result: CoachTaskResult
    emotion_result: CoachTaskResult
    performance_result: CoachTaskResult
    redline_result: CoachTaskResult
    report: CoachReport


class CoachWorkflow:
    """LangGraph-backed Coach evaluation + report workflow.

    The public run path delegates to the orchestrator's consolidated LLM report
    generation. The graph nodes remain available for explicit task-level runs,
    and propagate model errors without local report fallbacks.
    """

    def __init__(self) -> None:
        self.orchestrator = CoachOrchestrator()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(CoachGraphState)
        builder.add_node("evaluate_rubric", self._evaluate_rubric_node)
        builder.add_node("evaluate_emotion", self._evaluate_emotion_node)
        builder.add_node("evaluate_performance", self._evaluate_performance_node)
        builder.add_node("evaluate_redline", self._evaluate_redline_node)
        builder.add_node("generate_report", self._generate_report_node)
        for evaluator_node in (
            "evaluate_rubric",
            "evaluate_emotion",
            "evaluate_performance",
            "evaluate_redline",
        ):
            builder.add_edge(START, evaluator_node)
            builder.add_edge(evaluator_node, "generate_report")
        builder.add_edge("generate_report", END)
        return builder.compile()

    async def run(
        self,
        state: SessionState,
        retrieved_chunks_by_task: dict[str, list[RetrievedChunk]] | None = None,
    ) -> CoachReport:
        return await self.orchestrator.run(state, retrieved_chunks_by_task)

    async def _evaluate_rubric_node(self, graph_state: CoachGraphState) -> dict[str, CoachTaskResult]:
        state = graph_state["state"]
        chunks = graph_state.get("chunks_by_task", {})
        result = await self.orchestrator._safe_evaluate(
            "rubric_evaluation",
            "Rubric 综合评估",
            self.orchestrator.rubric.evaluate(state, retrieved_chunks=chunks.get("rubric_evaluation", [])),
            state,
        )
        return {"rubric_result": result}

    async def _evaluate_emotion_node(self, graph_state: CoachGraphState) -> dict[str, CoachTaskResult]:
        state = graph_state["state"]
        chunks = graph_state.get("chunks_by_task", {})
        result = await self.orchestrator._safe_evaluate(
            "emotion_evaluation",
            "情绪承接评估",
            self.orchestrator.emotion.evaluate(state, retrieved_chunks=chunks.get("emotion_evaluation", [])),
            state,
        )
        return {"emotion_result": result}

    async def _evaluate_performance_node(self, graph_state: CoachGraphState) -> dict[str, CoachTaskResult]:
        state = graph_state["state"]
        chunks = graph_state.get("chunks_by_task", {})
        result = await self.orchestrator._safe_evaluate(
            "performance_evaluation",
            "绩效反馈质量评估",
            self.orchestrator.performance.evaluate(state, retrieved_chunks=chunks.get("performance_evaluation", [])),
            state,
        )
        return {"performance_result": result}

    async def _evaluate_redline_node(self, graph_state: CoachGraphState) -> dict[str, CoachTaskResult]:
        state = graph_state["state"]
        chunks = graph_state.get("chunks_by_task", {})
        result = await self.orchestrator._safe_evaluate(
            "redline_check",
            "话术红线检测",
            self.orchestrator.redline.evaluate(state, retrieved_chunks=chunks.get("redline_check", [])),
            state,
        )
        return {"redline_result": result}

    async def _generate_report_node(self, graph_state: CoachGraphState) -> dict[str, CoachReport]:
        state = graph_state["state"]
        chunks = graph_state.get("chunks_by_task", {})
        # Preserve the exact ordering used by CoachOrchestrator.run.
        results: list[CoachTaskResult] = [
            graph_state["rubric_result"],
            graph_state["emotion_result"],
            graph_state["performance_result"],
            graph_state["redline_result"],
        ]
        report = await self.orchestrator.finalize_report(state, results, chunks)
        return {"report": report}
