from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.intent_recognition import IntentRecognitionAgent
from backend.agents.profile_extraction import ProfileExtractionAgent
from backend.schemas.intent import IntentResult
from backend.schemas.profile import EmployeeProfile


class IntentGraphState(TypedDict, total=False):
    """LangGraph state for one intent-recognition run."""

    text: str | None
    profile: EmployeeProfile | None
    intent_id: str | None
    result: IntentResult


class IntentRecognitionWorkflow:
    """LangGraph-backed wrapper around :class:`IntentRecognitionAgent`.

    The single ``recognize_intent`` node calls the existing agent, so the
    explicit-selection shortcut, LLM structured output and validation behaviour
    are unchanged.
    """

    def __init__(self) -> None:
        self.intent_agent = IntentRecognitionAgent()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(IntentGraphState)
        builder.add_node("recognize_intent", self._recognize_intent_node)
        builder.add_edge(START, "recognize_intent")
        builder.add_edge("recognize_intent", END)
        return builder.compile()

    async def recognize(
        self,
        *,
        text: str | None = None,
        profile: EmployeeProfile | None = None,
        intent_id: str | None = None,
    ) -> IntentResult:
        result = await self.graph.ainvoke({"text": text, "profile": profile, "intent_id": intent_id})
        return result["result"]

    async def _recognize_intent_node(self, graph_state: IntentGraphState) -> dict[str, IntentResult]:
        result = await self.intent_agent.recognize(
            text=graph_state.get("text"),
            profile=graph_state.get("profile"),
            intent_id=graph_state.get("intent_id"),
        )
        return {"result": result}


class ProfileGraphState(TypedDict, total=False):
    """LangGraph state for one profile-extraction run."""

    document_text: str
    profile: EmployeeProfile


class ProfileExtractionWorkflow:
    """LangGraph-backed wrapper around :class:`ProfileExtractionAgent`.

    The single ``extract_profile`` node calls the existing agent, so the
    structured-output extraction and validation behaviour are unchanged.
    """

    def __init__(self) -> None:
        self.profile_agent = ProfileExtractionAgent()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(ProfileGraphState)
        builder.add_node("extract_profile", self._extract_profile_node)
        builder.add_edge(START, "extract_profile")
        builder.add_edge("extract_profile", END)
        return builder.compile()

    async def extract(self, document_text: str) -> EmployeeProfile:
        result = await self.graph.ainvoke({"document_text": document_text})
        return result["profile"]

    async def _extract_profile_node(self, graph_state: ProfileGraphState) -> dict[str, EmployeeProfile]:
        profile = await self.profile_agent.extract(graph_state["document_text"])
        return {"profile": profile}
