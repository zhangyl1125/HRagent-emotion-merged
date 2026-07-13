from __future__ import annotations

from backend.agents.coach_agent.generic_agent import GenericCoachAgent
from backend.business_config.loader import get_config_loader
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.schemas.task import CoachTaskResult


class EmotionEvaluator(GenericCoachAgent):
    async def evaluate(self, state: SessionState, retrieved_chunks: list[RetrievedChunk] | None = None) -> CoachTaskResult:
        if not self.manager_turns(state.conversation) or not self.employee_turns(state.conversation):
            return CoachTaskResult(task_id="emotion_evaluation", task_name="情绪承接评估", status="insufficient_information", score=None, summary="缺少双方对话，不能判断情绪承接。")
        return await self.run_llm_task(
            task_id="emotion_evaluation",
            task_name="情绪承接评估",
            prompt_template="coach/emotion.jinja2",
            task_model_name="coach_evaluator",
            conversation=self.conversation_payload(state.conversation),
            emotion_log=[item.model_dump(mode="json", exclude_none=True) for item in state.emotion_log],
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            emotion_config=get_config_loader().coach_config("emotion.yaml"),
            retrieved_chunks=self.chunks_payload(retrieved_chunks),
        )
