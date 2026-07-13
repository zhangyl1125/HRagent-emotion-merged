from __future__ import annotations

from backend.agents.coach_agent.generic_agent import GenericCoachAgent
from backend.business_config.loader import get_config_loader
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult


class RubricEvaluator(GenericCoachAgent):
    async def evaluate(self, state: SessionState, retrieved_chunks: list[RetrievedChunk] | None = None) -> CoachTaskResult:
        if not self.manager_turns(state.conversation):
            return CoachTaskResult(task_id="rubric_evaluation", task_name="Rubric 综合评估", status="insufficient_information", score=None, summary="没有 manager 对话证据，不能评分。")
        return await self.run_llm_task(
            task_id="rubric_evaluation",
            task_name="Rubric 综合评估",
            prompt_template="coach/rubric.jinja2",
            task_model_name="coach_evaluator",
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            intent=state.intent.model_dump(exclude_none=True) if state.intent else {},
            conversation=self.conversation_payload(state.conversation),
            rubric=get_config_loader().coach_config("rubric.yaml"),
            retrieved_chunks=self.chunks_payload(retrieved_chunks),
        )
