from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.schemas.state import SessionState
from backend.workflows.guards import ensure_can_add_user_turn, ensure_setup_ready
from backend.workflows.nodes import RehearsalNodes


class RehearsalGraphState(TypedDict):
    """LangGraph state for one manager-message rehearsal turn."""

    state: SessionState
    manager_message: str
    input_mode: str
    audio_emotion: str | None


class RehearsalWorkflow:
    """LangGraph-backed workflow for one rehearsal turn."""

    def __init__(self):
        self.nodes = RehearsalNodes()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(RehearsalGraphState)
        builder.add_node("validate_turn", self._validate_turn_node)
        builder.add_node("employee_reply", self._employee_reply_node)
        builder.add_edge(START, "validate_turn")
        builder.add_edge("validate_turn", "employee_reply")
        builder.add_edge("employee_reply", END)
        return builder.compile()

    async def invoke(self, state: SessionState, inputs: dict[str, Any]) -> SessionState:
        message = str(inputs.get("manager_message") or "").strip()
        if not message:
            raise ValueError("manager_message is required")
        result = await self.graph.ainvoke({
            "state": state,
            "manager_message": message,
            "input_mode": str(inputs.get("input_mode") or "text"),
            "audio_emotion": inputs.get("audio_emotion"),
        })
        return result["state"]

    async def _validate_turn_node(self, graph_state: RehearsalGraphState) -> dict[str, SessionState]:
        state = graph_state["state"]
        ensure_setup_ready(state)
        ensure_can_add_user_turn(state)
        return {"state": state}

    async def _employee_reply_node(self, graph_state: RehearsalGraphState) -> dict[str, SessionState]:
        input_mode = graph_state.get("input_mode", "text")
        audio_emotion = graph_state.get("audio_emotion")
        node_kwargs: dict[str, Any] = {}
        if input_mode != "text" or audio_emotion is not None:
            node_kwargs = {
                "input_mode": input_mode,
                "audio_emotion": audio_emotion,
            }
        state = await self.nodes.employee_reply_node(
            graph_state["state"],
            graph_state["manager_message"],
            **node_kwargs,
        )
        return {"state": state}
