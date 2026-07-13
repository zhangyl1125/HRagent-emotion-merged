from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
import logging

from backend.business_config.loader import get_config_loader
from backend.config.settings import get_settings
from backend.exceptions.workflow_errors import MaxTurnsReachedError, WorkflowError
from backend.services.session_service import SessionService
from backend.workflows.graph import RehearsalWorkflow
from backend.workflows.guards import ensure_rehearsal_allowed
from backend.schemas.conversation import ConversationTurn
from backend.schemas.emotion import ConversationEmotionLog, EmotionState
from backend.schemas.state import RehearsalRuntimeContext, SessionState


logger = logging.getLogger(__name__)


class RehearsalService:
    """Business entry for rehearsal."""

    def __init__(self):
        self.session_service = SessionService()
        self.workflow = RehearsalWorkflow()
        self.loader = get_config_loader()

    async def send_manager_message(
        self,
        session_id: str,
        message: str,
        *,
        input_mode: str = "text",
        audio_emotion: str | None = None,
    ) -> SessionState:
        state = await asyncio.to_thread(self.session_service.get_session, session_id)
        ensure_rehearsal_allowed(state)
        if self._max_turns_enabled(state) and state.user_turn_count >= state.max_user_turns:
            raise MaxTurnsReachedError("已达到最大用户回合数，请结束本轮并生成报告。")
        new_state = await self.workflow.invoke(
            state,
            {"manager_message": message, "input_mode": input_mode, "audio_emotion": audio_emotion},
        )
        return await asyncio.to_thread(self.session_service.save_session, new_state)

    async def stream_manager_message(
        self,
        session_id: str,
        message: str,
        *,
        input_mode: str = "text",
        audio_emotion: str | None = None,
    ) -> AsyncIterator[dict]:
        try:
            state = await asyncio.to_thread(self.session_service.get_session, session_id)
            ensure_rehearsal_allowed(state)
            if self._max_turns_enabled(state) and state.user_turn_count >= state.max_user_turns:
                raise MaxTurnsReachedError("已达到最大用户回合数，请结束本轮并生成报告。")

            next_index = len(state.conversation) + 1
            state.conversation.append(
                ConversationTurn(
                    turn_index=next_index,
                    speaker="manager",
                    text=message,
                    metadata={"input_mode": input_mode, "audio_emotion": audio_emotion},
                )
            )
            state.user_turn_count += 1

            previous_emotion = self.workflow.nodes.prepare_emotion_state(state)
            state.emotion_state = previous_emotion
            motivation_before = (
                state.motivation.model_copy(deep=True)
                if state.motivation else None
            )
            signal = await self.workflow.nodes.analyze_emotion(
                user_text=message,
                current_state=previous_emotion,
                history=state.conversation[-5:],
                audio_emotion=audio_emotion,
            )
            await self.workflow.nodes.apply_simulation_transition(
                state,
                message,
                signal=signal,
                turn_index=next_index,
                audio_emotion=audio_emotion,
            )

            yield {"event": "start"}
            yield {
                "event": "manager_echo",
                "turn_index": next_index,
                "speaker": "manager",
                "text": message,
            }
            yield {
                "event": "emotion.updated",
                "emotion_state": state.emotion_state.model_dump(mode="json"),
                "signal": signal.model_dump(mode="json"),
                "motivation": (
                    state.motivation.model_dump(mode="json")
                    if state.motivation else None
                ),
            }
            yield {"event": "employee_start", "turn_index": next_index + 1, "speaker": "employee"}

            chunks: list[str] = []
            async for channel, text in self.workflow.nodes.employee_agent.stream_reply(state, message):
                if channel == "thinking":
                    continue
                chunks.append(text)
                yield {
                    "event": "delta",
                    "turn_index": next_index + 1,
                    "speaker": "employee",
                    "text": text,
                }

            reply = "".join(chunks).strip()
            if not reply:
                raise ValueError("Employee Agent returned empty streamed reply.")
            state.conversation.append(
                ConversationTurn(
                    turn_index=next_index + 1,
                    speaker="employee",
                    text=reply,
                    metadata={"emotion_state": state.emotion_state.model_dump(mode="json")},
                )
            )
            state.emotion_log.append(
                ConversationEmotionLog(
                    turn_index=next_index,
                    hrbp_text=message,
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
            saved = await asyncio.to_thread(self.session_service.save_session, state)
            yield {"event": "done", "state": saved.model_dump(mode="json")}
        except WorkflowError as exc:
            logger.info("Rehearsal stream rejected for session_id=%s: %s", session_id, exc)
            yield {"event": "error", "message": str(exc) or type(exc).__name__}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Rehearsal stream failed for session_id=%s", session_id)
            yield {"event": "error", "message": str(exc) or type(exc).__name__}

    def update_runtime_context(
        self,
        session_id: str,
        *,
        runtime_note: str | None = None,
        runtime_notes: list[str] | str | None = None,
        persona_override: str | None = None,
        persona_id: str | None = None,
        difficulty_id: str | None = None,
        clear_context: bool = False,
    ) -> SessionState:
        state = self.session_service.get_session(session_id)
        ensure_rehearsal_allowed(state)

        notes = self._normalize_runtime_notes(runtime_note, runtime_notes)
        override_was_sent = persona_override is not None
        override = self._clean_optional(persona_override)
        persona_id = self._clean_optional(persona_id)
        difficulty_id = self._clean_optional(difficulty_id)

        if not any([clear_context, notes, override_was_sent, persona_id, difficulty_id]):
            raise ValueError("请先输入要应用到预演的员工信息或模拟提示。")

        previous_context = state.rehearsal_context
        context = previous_context
        lines = ["已更新本轮模拟设定。"]

        if clear_context:
            lines = ["已清空本轮动态模拟设定。"]
            personas = self.loader.personas()
            difficulties = self.loader.difficulties()
            if previous_context.initial_persona_id and previous_context.initial_persona_id in personas:
                state.persona = personas[previous_context.initial_persona_id]
                lines.append(f"基础 Persona 恢复为：{state.persona.name}")
            if previous_context.initial_difficulty_id and previous_context.initial_difficulty_id in difficulties:
                state.difficulty = difficulties[previous_context.initial_difficulty_id]
                state.max_user_turns = get_settings().max_user_turns
                lines.append(f"基础难度恢复为：{state.difficulty.name}")
            context = RehearsalRuntimeContext()
        else:
            if not context.initial_persona_id and state.persona:
                context.initial_persona_id = state.persona.id
            if not context.initial_difficulty_id and state.difficulty:
                context.initial_difficulty_id = state.difficulty.id

        for note in notes:
            if note not in context.runtime_notes:
                context.runtime_notes.append(note)
            lines.append(f"新增信息：{note}")

        if override_was_sent:
            context.persona_override = override
            lines.append(f"Persona 人为调整：{override}" if override else "已清空 Persona 人为调整。")

        if persona_id:
            personas = self.loader.personas()
            if persona_id not in personas:
                raise ValueError(f"Unknown persona_id: {persona_id}")
            state.persona = personas[persona_id]
            context.active_persona_id = persona_id
            lines.append(f"基础 Persona 切换为：{state.persona.name}")

        if difficulty_id:
            difficulties = self.loader.difficulties()
            if difficulty_id not in difficulties:
                raise ValueError(f"Unknown difficulty_id: {difficulty_id}")
            state.difficulty = difficulties[difficulty_id]
            context.active_difficulty_id = difficulty_id
            state.max_user_turns = get_settings().max_user_turns
            lines.append(f"基础难度切换为：{state.difficulty.name}")

        context.touch()
        state.rehearsal_context = context
        state.stage = "rehearsal"
        state.coach_report_id = None

        state.conversation.append(
            ConversationTurn(
                turn_index=len(state.conversation) + 1,
                speaker="system",
                text="\n".join(lines),
                metadata={
                    "type": "rehearsal_context_update",
                    "clear_context": clear_context,
                    "has_runtime_note": bool(notes),
                    "runtime_note_count": len(notes),
                    "has_persona_override": bool(override),
                    "persona_id": persona_id,
                    "difficulty_id": difficulty_id,
                },
            )
        )
        return self.session_service.save_session(state)

    def end_rehearsal(self, session_id: str) -> SessionState:
        state = self.session_service.get_session(session_id)
        state.stage = "rehearsal"
        return self.session_service.save_session(state)

    def retry_rehearsal(self, session_id: str) -> SessionState:
        state = self.session_service.get_session(session_id)
        if state.run_mode == "guidance_only":
            raise ValueError("run_mode=guidance_only，不允许再练一轮。")
        state.conversation = []
        state.rehearsal_context = RehearsalRuntimeContext()
        if state.personality and state.motivation:
            state.emotion_state = self.workflow.nodes.emotion_transition.initial_state(
                state.intent.intent_id if state.intent else None,
                state.personality,
            )
            state.motivation = state.motivation.model_copy(
                update={
                    "primary_score": 50.0,
                    "secondary_scores": {
                        motive_id: 50.0
                        for motive_id in state.motivation.secondary_motive_ids
                    },
                    "total_satisfaction": 50.0,
                    "last_change_reason": None,
                    "has_manager_response": False,
                },
                deep=True,
            )
        else:
            state.emotion_state = EmotionState()
        state.emotion_log = []
        state.user_turn_count = 0
        state.stage = "setup_ready"
        state.coach_report_id = None
        return self.session_service.save_session(state)

    @staticmethod
    def _max_turns_enabled(state: SessionState) -> bool:
        configured_limit = get_settings().max_user_turns
        return configured_limit > 0 and state.max_user_turns > 0

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _normalize_runtime_notes(
        cls,
        runtime_note: str | None,
        runtime_notes: list[str] | str | None,
    ) -> list[str]:
        raw: list[str | None] = [runtime_note]
        if isinstance(runtime_notes, list):
            raw.extend(runtime_notes)
        elif runtime_notes is not None:
            raw.append(runtime_notes)
        return list(
            dict.fromkeys(
                note for note in (cls._clean_optional(item) for item in raw) if note
            )
        )
