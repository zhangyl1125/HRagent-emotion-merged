import pytest

from backend.schemas.conversation import ConversationTurn
from backend.schemas.state import SessionState
from backend.workflows.graph import RehearsalWorkflow
from backend.workflows.guards import ensure_rehearsal_allowed
from backend.exceptions.workflow_errors import WorkflowError


def test_guidance_only_blocks_rehearsal():
    state = SessionState(session_id="s1", setup_ready=True, run_mode="guidance_only")
    with pytest.raises(WorkflowError):
        ensure_rehearsal_allowed(state)


def test_guidance_then_rehearsal_requires_guidance_report():
    state = SessionState(session_id="s1", setup_ready=True, run_mode="guidance_then_rehearsal")
    with pytest.raises(WorkflowError):
        ensure_rehearsal_allowed(state)


@pytest.mark.asyncio
async def test_rehearsal_workflow_invokes_compiled_langgraph(monkeypatch):
    workflow = RehearsalWorkflow()
    assert type(workflow.graph).__name__ == "CompiledStateGraph"

    async def fake_employee_reply_node(state: SessionState, manager_message: str) -> SessionState:
        next_index = len(state.conversation) + 1
        state.conversation.append(ConversationTurn(turn_index=next_index, speaker="manager", text=manager_message))
        state.user_turn_count += 1
        state.conversation.append(ConversationTurn(turn_index=next_index + 1, speaker="employee", text="收到"))
        state.stage = "rehearsal"
        return state

    monkeypatch.setattr(workflow.nodes, "employee_reply_node", fake_employee_reply_node)
    state = SessionState(session_id="s1", setup_ready=True, run_mode="rehearsal_report")

    result = await workflow.invoke(state, {"manager_message": "请说一下你的想法"})

    assert result.stage == "rehearsal"
    assert result.user_turn_count == 1
    assert [turn.speaker for turn in result.conversation] == ["manager", "employee"]
    assert result.conversation[0].text == "请说一下你的想法"
    assert result.conversation[1].text == "收到"

