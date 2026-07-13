from __future__ import annotations

import asyncio

from backend.agents.employee_agent import EmployeeAgent
from backend.schemas.conversation import ConversationTurn
from backend.config.settings import get_settings
from backend.schemas.emotion import ConversationEmotionLog, EmotionSignal
from backend.schemas.state import SessionState
from backend.services.attitude_transition_engine import AttitudeTransitionEngine
from backend.services.cache_service import CacheService, cache_digest
from backend.services.emotion_analyzer import EmotionAnalyzer
from backend.services.emotion_transition_service import EmotionTransitionService
from backend.services.simulation_motivation_scoring_service import (
    SimulationMotivationScoringService,
)


class RehearsalNodes:
    def __init__(self):
        self.employee_agent = EmployeeAgent()
        self.emotion_analyzer = EmotionAnalyzer()
        self.attitude_engine = AttitudeTransitionEngine()
        self.emotion_transition = EmotionTransitionService()
        self.motivation_scoring = SimulationMotivationScoringService()
        self.settings = get_settings()
        self.cache = CacheService(self.settings)

    async def employee_reply_node(
        self,
        state: SessionState,
        manager_message: str,
        *,
        input_mode: str = "text",
        audio_emotion: str | None = None,
    ) -> SessionState:
        next_index = len(state.conversation) + 1
        state.conversation.append(ConversationTurn(turn_index=next_index, speaker="manager", text=manager_message))
        state.user_turn_count += 1

        previous_emotion = self.prepare_emotion_state(state)
        state.emotion_state = previous_emotion
        signal = await self.analyze_emotion(
            user_text=manager_message,
            current_state=previous_emotion,
            history=state.conversation[-5:],
            audio_emotion=audio_emotion,
        )
        motivation_before = (
            state.motivation.model_copy(deep=True)
            if state.motivation else None
        )
        await self.apply_simulation_transition(
            state,
            manager_message,
            signal=signal,
            turn_index=next_index,
            audio_emotion=audio_emotion,
        )

        reply = await self.employee_agent.reply(state, manager_message)
        state.conversation.append(ConversationTurn(turn_index=next_index + 1, speaker="employee", text=reply))
        state.emotion_log.append(
            ConversationEmotionLog(
                turn_index=next_index,
                hrbp_text=manager_message,
                input_mode=input_mode,
                audio_emotion=signal.audio_emotion,
                employee_attitude_before=previous_emotion.current_attitude,
                employee_attitude_after=state.emotion_state.current_attitude,
                intensity=state.emotion_state.intensity,
                transition_reason=state.emotion_state.transition_reason,
                employee_reply=reply,
                signal=signal,
                vad_before=previous_emotion.current_vad,
                vad_after=state.emotion_state.current_vad,
                emotion_anchor_before=previous_emotion.current_anchor_id,
                emotion_anchor_after=state.emotion_state.current_anchor_id,
                motivation_before=motivation_before,
                motivation_after=(
                    state.motivation.model_copy(deep=True)
                    if state.motivation else None
                ),
            )
        )
        state.stage = "rehearsal"
        return state

    def prepare_emotion_state(self, state: SessionState):
        current = state.emotion_state
        if self.uses_dynamic_simulation(state):
            if not current.current_anchor_id:
                return self.emotion_transition.initial_state(
                    state.intent.intent_id if state.intent else None,
                    state.personality,
                )
            return current
        intent_id = state.intent.intent_id if state.intent else None
        persona_id = state.persona.id if state.persona else None
        purpose = self.attitude_engine.normalize_purpose(intent_id)
        primary, secondary = self.attitude_engine.infer_motivations(persona_id, intent_id)
        if (
            getattr(current.interview_purpose, "value", current.interview_purpose) == purpose.value
            and getattr(current.primary_motivation, "value", current.primary_motivation) == primary.value
            and getattr(current.secondary_motivation, "value", current.secondary_motivation) == secondary.value
        ):
            return current
        return current.model_copy(
            update={
                "interview_purpose": purpose,
                "primary_motivation": primary,
                "secondary_motivation": secondary,
            }
        )

    @staticmethod
    def uses_dynamic_simulation(state: SessionState) -> bool:
        return state.personality is not None and state.motivation is not None

    async def apply_simulation_transition(
        self,
        state: SessionState,
        manager_message: str,
        *,
        signal: EmotionSignal,
        turn_index: int,
        audio_emotion: str | None = None,
    ) -> SessionState:
        if self.uses_dynamic_simulation(state):
            motivation_input = state.model_copy(deep=True)
            emotion_input = state.model_copy(deep=True)
            motivation_result, emotion_result = await asyncio.gather(
                self.motivation_scoring.update_after_manager_message(
                    motivation_input,
                    manager_message,
                ),
                self.emotion_transition.update_after_manager_message(
                    emotion_input,
                    manager_message,
                    audio_emotion=audio_emotion,
                ),
            )
            state.motivation = motivation_result.motivation
            state.emotion_state = emotion_result.emotion_state
            self._merge_warnings(state, motivation_result)
            self._merge_warnings(state, emotion_result)
        else:
            state.emotion_state = self.attitude_engine.compute_next_state(
                state.emotion_state,
                signal,
                turn_index=turn_index,
            )
        return state

    @staticmethod
    def _merge_warnings(target: SessionState, source: SessionState) -> None:
        for warning in source.warnings:
            if warning not in target.warnings:
                target.warnings.append(warning)

    async def analyze_emotion(
        self,
        *,
        user_text: str,
        current_state,
        history: list[ConversationTurn],
        audio_emotion: str | None = None,
    ) -> EmotionSignal:
        key = self._emotion_cache_key(
            user_text=user_text,
            current_state=current_state,
            history=history,
            audio_emotion=audio_emotion,
        )
        cached = await self.cache.get_json_async(key)
        if cached:
            return EmotionSignal.model_validate(cached)

        signal = await self.emotion_analyzer.analyze(
            user_text=user_text,
            current_state=current_state,
            history=history,
            audio_emotion=audio_emotion,
        )
        await self.cache.set_json_async(key, signal.model_dump(mode="json"), self.settings.rehearsal_aux_cache_ttl_seconds)
        return signal

    def _emotion_cache_key(
        self,
        *,
        user_text: str,
        current_state,
        history: list[ConversationTurn],
        audio_emotion: str | None = None,
    ) -> str:
        digest = cache_digest({
            "task": "emotion_signal",
            "analyzer": "rules_mvpi_v1",
            "user_text": user_text.strip(),
            "audio_emotion": audio_emotion,
            "current_state": {
                "attitude": str(current_state.current_attitude),
                "intensity": current_state.intensity,
                "turn_index": current_state.turn_index,
                "interview_purpose": getattr(current_state.interview_purpose, "value", current_state.interview_purpose),
                "primary_motivation": getattr(current_state.primary_motivation, "value", current_state.primary_motivation),
                "secondary_motivation": getattr(current_state.secondary_motivation, "value", current_state.secondary_motivation),
                "primary_satisfaction": current_state.primary_satisfaction,
                "secondary_satisfaction": current_state.secondary_satisfaction,
                "vad": current_state.current_vad.model_dump(),
                "anchor_id": current_state.current_anchor_id,
            },
            "history": [
                {"speaker": turn.speaker, "text": turn.text}
                for turn in history[-5:]
            ],
        })
        return self.cache.namespaced("rehearsal_aux", digest)
