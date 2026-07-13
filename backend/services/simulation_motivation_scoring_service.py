from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.business_config.loader import get_config_loader
from backend.schemas.simulation import MotivationScoringStructuredOutput, MotivationState
from backend.schemas.state import SessionState
from backend.services.langchain_llm_service import LangChainLLMService

logger = logging.getLogger(__name__)


class SimulationMotivationScoringService:
    """Update motive satisfaction without reading or changing VAD emotion."""

    async def update_after_manager_message(self, state: SessionState, manager_message: str) -> SessionState:
        if not state.motivation:
            return state
        try:
            output = await LangChainLLMService().ainvoke_structured(
                prompt=self._build_prompt(state, manager_message),
                schema=MotivationScoringStructuredOutput,
                task_name="employee",
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Motivation scoring LLM failed, using fallback: %s", exc)
            output = self._fallback_score(state, manager_message)
            warning = f"动机满足度评分使用规则兜底：{type(exc).__name__}"
            if warning not in state.warnings:
                state.warnings.append(warning)
        state.motivation = self._apply_score_change(state.motivation, output)
        return state

    def _build_prompt(self, state: SessionState, manager_message: str) -> str:
        motive = state.motivation
        assert motive is not None
        context = {
            "intent": state.intent.model_dump(exclude_none=True) if state.intent else {},
            "motivation": motive.model_dump(mode="json"),
            "motives": {
                key: value.model_dump()
                for key, value in get_config_loader().motives().items()
            },
            "conversation": [
                turn.model_dump(mode="json", exclude_none=True)
                for turn in state.conversation[-8:]
            ],
            "latest_manager_message": manager_message,
        }
        return (
            "你只负责评估员工主/辅诉求满足度，不要输出或推断情绪 VAD。"
            "分数范围是 -100 到 100；主诉求权重70%，两个辅诉求各15%。"
            "根据经理最新话术是否共情、否定、给出落地路径、触发红线，"
            "输出各诉求分数变化，只返回结构化结果。"
            f"context={json.dumps(context, ensure_ascii=False)}"
        )

    def _fallback_score(
        self,
        state: SessionState,
        manager_message: str,
    ) -> MotivationScoringStructuredOutput:
        text = manager_message or ""
        intent_id = state.intent.intent_id if state.intent else ""
        empathy = any(token in text for token in ["理解", "辛苦", "压力", "感受", "落差", "担心", "确实不容易"])
        plan = any(token in text for token in ["计划", "目标", "路径", "资源", "支持", "安排", "阶段", "时间", "过渡", "补偿", "方案"])
        denial = any(token in text for token in ["别找理由", "不是问题", "没什么可说", "你必须", "公司已经决定", "不接受", "就是你的问题"])
        evidence = any(token in text for token in ["行为", "例子", "事实", "记录", "具体", "数据", "证据"])
        redline = "态度不好" in text and intent_id in {"exit", "improvement_exit"} and not evidence
        primary_delta = 0.0
        secondary_delta = 0.0
        behaviors: list[str] = []
        redlines: list[str] = []
        if empathy:
            primary_delta += 8
            secondary_delta += 5
            behaviors.append("empathy")
        if plan:
            primary_delta += 15
            secondary_delta += 8
            behaviors.append("action_path")
        if denial:
            primary_delta -= 18
            secondary_delta -= 12
            behaviors.append("denial_or_pressure")
        if redline:
            primary_delta -= 35
            secondary_delta -= 20
            redlines.append("attitude_without_behavior_evidence")
        if not behaviors and not redlines:
            behaviors.append("neutral_or_unclear")
        motive = state.motivation
        return MotivationScoringStructuredOutput(
            primary_score_delta=primary_delta,
            secondary_score_deltas={
                motive_id: secondary_delta
                for motive_id in (motive.secondary_motive_ids if motive else [])
            },
            detected_behaviors=behaviors,
            redline_hits=redlines,
            reason_summary=";".join(behaviors + redlines),
        )

    @staticmethod
    def _apply_score_change(
        motivation: MotivationState,
        output: MotivationScoringStructuredOutput,
    ) -> MotivationState:
        updated = motivation.model_copy(deep=True)
        updated.primary_score = max(
            -100.0,
            min(100.0, updated.primary_score + output.primary_score_delta),
        )
        for motive_id in updated.secondary_motive_ids:
            delta = float(output.secondary_score_deltas.get(motive_id, 0.0))
            current = updated.secondary_scores.get(motive_id, 50.0)
            updated.secondary_scores[motive_id] = max(
                -100.0,
                min(100.0, current + delta),
            )
        updated.has_manager_response = True
        updated.last_change_reason = (
            output.reason_summary
            or ", ".join(output.detected_behaviors + output.redline_hits)
        )
        updated.updated_at = datetime.now(timezone.utc)
        return MotivationState.model_validate(updated.model_dump(mode="json"))
