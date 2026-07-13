from __future__ import annotations

from backend.agents.coach_agent.generic_agent import GenericCoachAgent
from backend.business_config.loader import get_config_loader
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult


class RedlineEvaluator(GenericCoachAgent):
    async def evaluate(self, state: SessionState, retrieved_chunks: list[RetrievedChunk] | None = None) -> CoachTaskResult:
        if not self.manager_turns(state.conversation):
            return CoachTaskResult(task_id="redline_check", task_name="话术红线检测", status="insufficient_information", score=None, summary="没有 manager 原话，不能检测红线。")
        return await self.run_llm_task(
            task_id="redline_check",
            task_name="话术红线检测",
            prompt_template="coach/redline.jinja2",
            task_model_name="coach_redline",
            conversation=self.conversation_payload(state.conversation),
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            redline=get_config_loader().coach_config("redline.yaml"),
            retrieved_chunks=self.chunks_payload(retrieved_chunks),
        )
