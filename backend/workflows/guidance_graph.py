from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.guidance_agent import GuidanceAgent
from backend.schemas.guidance import GuidanceReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState


class GuidanceGraphState(TypedDict, total=False):
    """LangGraph state for one guidance-report generation run."""

    state: SessionState
    chunks: list[RetrievedChunk]
    report: GuidanceReport


class GuidanceWorkflow:
    """LangGraph-backed guidance workflow.

    The non-streaming path is decomposed into ``validate_intent`` -> ``generate``
    nodes. Both nodes call the existing :class:`GuidanceAgent`, so the LLM call,
    structured-output parsing and local fallback behaviour are unchanged. The
    streaming path is exposed verbatim through :meth:`stream_text` /
    :meth:`report_from_stream_sections` so callers keep identical SSE behaviour.
    """

    def __init__(self) -> None:
        self.agent = GuidanceAgent()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(GuidanceGraphState)
        builder.add_node("validate_intent", self._validate_intent_node)
        builder.add_node("generate", self._generate_node)
        builder.add_edge(START, "validate_intent")
        builder.add_edge("validate_intent", "generate")
        builder.add_edge("generate", END)
        return builder.compile()

    async def run(self, state: SessionState, chunks: list[RetrievedChunk]) -> GuidanceReport:
        result = await self.graph.ainvoke({"state": state, "chunks": chunks})
        return result["report"]

    async def _validate_intent_node(self, graph_state: GuidanceGraphState) -> dict[str, object]:
        state = graph_state["state"]
        if not state.intent or not state.intent.config:
            raise ValueError("intent is required for guidance")
        return {}

    async def _generate_node(self, graph_state: GuidanceGraphState) -> dict[str, GuidanceReport]:
        report = await self.agent.generate(graph_state["state"], graph_state["chunks"])
        return {"report": report}

    # --- Streaming passthrough (behaviour identical to GuidanceAgent) ---------
    def stream_text(self, state: SessionState, chunks: list[RetrievedChunk]) -> AsyncIterator[str]:
        return self.agent.stream_text(state, chunks)

    def report_from_stream_sections(
        self,
        state: SessionState,
        chunks: list[RetrievedChunk],
        sections: dict[str, str],
    ) -> GuidanceReport:
        return self.agent.report_from_stream_sections(state, chunks, sections)
