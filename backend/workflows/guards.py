from __future__ import annotations

from backend.config.settings import get_settings
from backend.exceptions.workflow_errors import MaxTurnsReachedError, SetupNotReadyError, WorkflowError
from backend.schemas.state import SessionState


def ensure_setup_ready(state: SessionState) -> None:
    if not state.setup_ready:
        raise SetupNotReadyError("setup_ready=false，不能进入预演。")


def ensure_rehearsal_allowed(state: SessionState) -> None:
    ensure_setup_ready(state)
    if state.run_mode == "guidance_only":
        raise WorkflowError("run_mode=guidance_only，不允许进入多轮预演。")
    if state.run_mode == "guidance_then_rehearsal" and not state.guidance_report_id:
        raise WorkflowError("run_mode=guidance_then_rehearsal，必须先生成谈前指导。")


def ensure_can_add_user_turn(state: SessionState) -> None:
    if get_settings().max_user_turns > 0 and state.max_user_turns > 0 and state.user_turn_count >= state.max_user_turns:
        raise MaxTurnsReachedError("已达到最大用户回合数。")
