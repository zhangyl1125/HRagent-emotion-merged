from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.guidance_agent import (
    GuidanceAgent,
    GuidanceSectionKey,
    GuidanceSectionValue,
)
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
    nodes. ``GuidanceAgent.generate`` runs the five guidance sections in parallel.
    Streaming callers use the same per-section prompt through ``stream_section``.
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

    def stream_section(
        self,
        state: SessionState,
        chunks: list[RetrievedChunk],
        key: GuidanceSectionKey,
    ) -> AsyncIterator[str]:
        return self.agent.stream_section(state, chunks, key)

    def report_from_sections(
        self,
        state: SessionState,
        chunks: list[RetrievedChunk],
        sections: Mapping[GuidanceSectionKey, GuidanceSectionValue],
    ) -> GuidanceReport:
        return self.agent.report_from_sections(state, chunks, sections)
