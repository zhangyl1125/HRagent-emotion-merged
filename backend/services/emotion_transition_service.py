from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone

from backend.business_config.loader import get_config_loader
from backend.schemas.emotion import EmotionState, EmployeeAttitude
from backend.schemas.simulation import (
    BigFivePersonality,
    EmotionTransitionStructuredOutput,
    VADVector,
)
from backend.schemas.state import SessionState
from backend.services.langchain_llm_service import LangChainLLMService

logger = logging.getLogger(__name__)


class EmotionTransitionService:
    """Update three-axis VAD while preserving HRagent-05 attitude fields."""

    _ATTITUDE_BY_ANCHOR = {
        "calm_receptive": EmployeeAttitude.CALM_NEUTRAL,
        "cautious_neutral": EmployeeAttitude.CALM_NEUTRAL,
        "skeptical_controlled": EmployeeAttitude.GUARDED_HESITANT,
        "disappointed_withdrawn": EmployeeAttitude.SILENT_WITHDRAWN,
        "anxious_defensive": EmployeeAttitude.DEFENSIVE_RESISTANT,
        "defensive_resistant": EmployeeAttitude.DEFENSIVE_RESISTANT,
        "angry_challenging": EmployeeAttitude.FRUSTRATED_PUSHBACK,
        "hopeful_negotiating": EmployeeAttitude.REFLECTIVE_SOFTENING,
        "aligned_ready": EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE,
    }

    def initial_state(
        self,
        intent_id: str | None,
        personality: BigFivePersonality | None = None,
    ) -> EmotionState:
        anchors = get_config_loader().emotion_anchors()
        anchor_id = get_config_loader().default_emotion_anchor_id(intent_id)
        anchor = anchors.get(anchor_id or "") or next(iter(anchors.values()), None)
        base_vad = anchor.vad if anchor else VADVector()
        vad = self._initial_vad_from_personality(base_vad, personality)
        nearest_id = self._nearest_anchor_id(vad) or (anchor.id if anchor else None)
        attitude = self._attitude_for_anchor(nearest_id)
        return EmotionState(
            current_attitude=attitude,
            intensity=self._legacy_intensity(vad),
            transition_reason="initial_vad_state",
            emotion_description=anchor.description if anchor else "",
            current_vad=vad,
            current_anchor_id=nearest_id,
            transition_strategy="expected_value",
            last_reason_summary="初始化情绪基线来自面谈目的，并按大五人格调整三维 VAD。",
            reply_emotion_guidance=self._personality_initial_guidance(personality),
        )

    async def update_after_manager_message(
        self,
        state: SessionState,
        manager_message: str,
        *,
        audio_emotion: str | None = None,
    ) -> SessionState:
        if not state.emotion_state:
            state.emotion_state = self.initial_state(
                state.intent.intent_id if state.intent else None,
                state.personality,
            )
        try:
            output = await LangChainLLMService().ainvoke_structured(
                prompt=self._build_prompt(
                    state,
                    manager_message,
                    audio_emotion=audio_emotion,
                ),
                schema=EmotionTransitionStructuredOutput,
                task_name="employee",
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Emotion transition LLM failed, using fallback: %s", exc)
            output = self._fallback_transition(
                manager_message,
                audio_emotion=audio_emotion,
            )
            warning = f"情绪转移使用规则兜底：{type(exc).__name__}"
            if warning not in state.warnings:
                state.warnings.append(warning)
        state.emotion_state = self._apply_transition(
            state,
            output,
            manager_message,
        )
        return state

    def _build_prompt(
        self,
        state: SessionState,
        manager_message: str,
        *,
        audio_emotion: str | None = None,
    ) -> str:
        context = {
            "intent": state.intent.model_dump(exclude_none=True) if state.intent else {},
            "personality": state.personality.model_dump() if state.personality else {},
            "emotion_state": self._emotion_prompt_payload(state),
            "emotion_anchors": [
                anchor.model_dump(mode="json")
                for anchor in get_config_loader().emotion_anchors().values()
            ],
            "conversation": [
                turn.model_dump(mode="json", exclude_none=True)
                for turn in state.conversation[-8:]
            ],
            "latest_manager_message": manager_message,
            "manager_audio_emotion": audio_emotion,
        }
        return (
            "你只负责三维 VAD 情绪转移，不要读取、推断或修改动机满足度。"
            "基于当前 VAD、大五人格、面谈目的和经理最新话术判断员工下一轮情绪。"
            "使用 valence/arousal/dominance 三维空间，输出 VAD 变化、策略、触发因素、"
            "员工回复的情绪表达指导和简短理由，只返回结构化结果。"
            f"context={json.dumps(context, ensure_ascii=False)}"
        )

    @staticmethod
    def _emotion_prompt_payload(state: SessionState) -> dict:
        if not state.emotion_state:
            return {}
        payload = state.emotion_state.model_dump(mode="json")
        if state.motivation is None:
            return payload
        for legacy_key in (
            "interview_purpose",
            "primary_motivation",
            "secondary_motivation",
            "primary_satisfaction",
            "secondary_satisfaction",
            "total_satisfaction",
            "last_primary_delta",
            "last_secondary_delta",
        ):
            payload.pop(legacy_key, None)
        return payload

    @staticmethod
    def _fallback_transition(
        manager_message: str,
        *,
        audio_emotion: str | None = None,
    ) -> EmotionTransitionStructuredOutput:
        text = manager_message or ""
        audio = str(audio_emotion or "").strip().lower()
        positive = any(token in text for token in ["理解", "支持", "一起", "具体", "资源", "计划", "谢谢", "承认", "可以讨论"])
        negative = any(token in text for token in ["威胁", "必须", "态度不好", "别找理由", "不接受", "公司决定", "就是你的问题"])
        if audio in {"angry", "anger", "frustrated", "hostile", "愤怒", "生气"}:
            negative = True
        elif audio in {"calm", "friendly", "warm", "平静", "友好"}:
            positive = True
        if positive and not negative:
            delta = VADVector(valence=0.18, arousal=-0.12, dominance=0.12)
            triggers = ["support_or_empathy"]
            guidance = "语气可略缓和，但仍保持员工真实顾虑。"
        elif negative:
            delta = VADVector(valence=-0.22, arousal=0.18, dominance=-0.08)
            triggers = ["pressure_or_denial"]
            guidance = "语气更防御，控制感下降或开始质疑。"
        else:
            delta = VADVector(valence=-0.03, arousal=0.04, dominance=0.0)
            triggers = ["unclear_or_neutral"]
            guidance = "保持谨慎，不做大幅情绪跳跃。"
        return EmotionTransitionStructuredOutput(
            vad_delta=delta,
            transition_strategy="expected_value",
            detected_emotion_triggers=triggers,
            reply_emotion_guidance=guidance,
            reason_summary=", ".join(triggers),
        )

    def _apply_transition(
        self,
        state: SessionState,
        output: EmotionTransitionStructuredOutput,
        manager_message: str,
    ) -> EmotionState:
        previous = state.emotion_state or EmotionState()
        current = previous.current_vad
        markov = self._markov_expected_vad(current)
        personality_delta = self._personality_delta(
            state.personality,
            output.vad_delta,
            manager_message,
        )
        next_vad = VADVector(
            valence=self._clamp(
                current.valence * 0.35
                + markov.valence * 0.25
                + (current.valence + output.vad_delta.valence) * 0.4
                + personality_delta.valence
            ),
            arousal=self._clamp(
                current.arousal * 0.35
                + markov.arousal * 0.25
                + (current.arousal + output.vad_delta.arousal) * 0.4
                + personality_delta.arousal
            ),
            dominance=self._clamp(
                current.dominance * 0.35
                + markov.dominance * 0.25
                + (current.dominance + output.vad_delta.dominance) * 0.4
                + personality_delta.dominance
            ),
        )
        anchor_id = self._nearest_anchor_id(next_vad)
        anchors = get_config_loader().emotion_anchors()
        anchor = anchors.get(anchor_id or "")
        attitude = self._attitude_for_anchor(anchor_id)
        return previous.model_copy(
            update={
                "previous_attitude": previous.current_attitude,
                "current_attitude": attitude,
                "intensity": self._legacy_intensity(next_vad),
                "transition_reason": output.reason_summary or "vad_transition",
                "emotion_description": anchor.description if anchor else "",
                "emotion_band": anchor_id or previous.emotion_band,
                "turn_index": previous.turn_index + 1,
                "current_vad": next_vad,
                "current_anchor_id": anchor_id,
                "transition_strategy": output.transition_strategy,
                "last_reason_summary": output.reason_summary,
                "reply_emotion_guidance": output.reply_emotion_guidance,
                "has_manager_response": True,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def _markov_expected_vad(self, current: VADVector) -> VADVector:
        anchors = list(get_config_loader().emotion_anchors().values())
        if not anchors:
            return current
        scores = [-4.0 * self._distance(current, anchor.vad) for anchor in anchors]
        maximum = max(scores)
        weights = [math.exp(score - maximum) for score in scores]
        total = sum(weights) or 1.0
        return VADVector(
            valence=sum(
                anchor.vad.valence * weight
                for anchor, weight in zip(anchors, weights, strict=False)
            ) / total,
            arousal=sum(
                anchor.vad.arousal * weight
                for anchor, weight in zip(anchors, weights, strict=False)
            ) / total,
            dominance=sum(
                anchor.vad.dominance * weight
                for anchor, weight in zip(anchors, weights, strict=False)
            ) / total,
        )

    def _nearest_anchor_id(self, vad: VADVector) -> str | None:
        anchors = list(get_config_loader().emotion_anchors().values())
        if not anchors:
            return None
        return min(anchors, key=lambda anchor: self._distance(vad, anchor.vad)).id

    def _initial_vad_from_personality(
        self,
        base_vad: VADVector,
        personality: BigFivePersonality | None,
    ) -> VADVector:
        p = personality or get_config_loader().default_big_five()
        config = get_config_loader().personality_initial_vad_weights()
        dimension_weights = config.get("dimensions") or {}
        max_axis_delta = min(
            1.0,
            max(0.0, float(config.get("max_axis_delta", 0.35))),
        )
        axes = {"valence": 0.0, "arousal": 0.0, "dominance": 0.0}
        for dimension in [
            "openness",
            "conscientiousness",
            "extraversion",
            "agreeableness",
            "neuroticism",
        ]:
            weights = dimension_weights.get(dimension) or {}
            normalized = (float(getattr(p, dimension, 50)) - 50.0) / 50.0
            for axis in axes:
                axes[axis] += normalized * float(weights.get(axis, 0.0))
        return VADVector(
            valence=self._clamp(
                base_vad.valence
                + self._clamp(axes["valence"], -max_axis_delta, max_axis_delta)
            ),
            arousal=self._clamp(
                base_vad.arousal
                + self._clamp(axes["arousal"], -max_axis_delta, max_axis_delta)
            ),
            dominance=self._clamp(
                base_vad.dominance
                + self._clamp(axes["dominance"], -max_axis_delta, max_axis_delta)
            ),
        )

    @staticmethod
    def _personality_delta(
        personality: BigFivePersonality | None,
        llm_delta: VADVector,
        manager_message: str,
    ) -> VADVector:
        p = personality or BigFivePersonality()
        neuro = (p.neuroticism - 50) / 100
        agree = (p.agreeableness - 50) / 100
        extra = (p.extraversion - 50) / 100
        cons = (p.conscientiousness - 50) / 100
        open_ = (p.openness - 50) / 100
        negative = llm_delta.valence < 0 or any(
            token in manager_message
            for token in ["态度不好", "必须", "别找理由", "不接受"]
        )
        if negative:
            return VADVector(
                valence=-0.05 * max(neuro, 0) + 0.03 * max(agree, 0),
                arousal=0.05 * max(neuro + extra, 0),
                dominance=0.04 * cons - 0.05 * max(neuro, 0),
            )
        return VADVector(
            valence=0.04 * max(agree + open_, 0),
            arousal=-0.03 * max(agree, 0) + 0.02 * max(extra, 0),
            dominance=0.04 * max(cons + open_, 0),
        )

    @classmethod
    def _attitude_for_anchor(cls, anchor_id: str | None) -> EmployeeAttitude:
        return cls._ATTITUDE_BY_ANCHOR.get(
            anchor_id or "",
            EmployeeAttitude.GUARDED_HESITANT,
        )

    @staticmethod
    def _legacy_intensity(vad: VADVector) -> int:
        raw = (abs(vad.arousal) * 0.55 + max(0.0, -vad.valence) * 0.45) * 100
        return max(10, min(100, int(round(raw))))

    @staticmethod
    def _distance(left: VADVector, right: VADVector) -> float:
        return math.sqrt(
            (left.valence - right.valence) ** 2
            + (left.arousal - right.arousal) ** 2
            + (left.dominance - right.dominance) ** 2
        )

    @staticmethod
    def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
        return max(lower, min(upper, float(value)))

    @staticmethod
    def _personality_initial_guidance(
        personality: BigFivePersonality | None,
    ) -> str:
        p = personality or BigFivePersonality()
        return max(
            (p.openness, "开放性高，较愿意讨论新方案"),
            (p.conscientiousness, "尽责性高，重视证据、计划和边界"),
            (p.extraversion, "外向性高，情绪更容易外显"),
            (p.agreeableness, "宜人性高，较容易缓和"),
            (p.neuroticism, "神经质高，对压力和否定更敏感"),
            key=lambda item: item[0],
        )[1]
