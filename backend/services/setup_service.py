from __future__ import annotations

from backend.config.settings import get_settings
from backend.business_config.loader import get_config_loader
from backend.schemas.profile import EmployeeProfile, FactItem
from backend.schemas.simulation import BigFivePersonality, MotivationState
from backend.schemas.state import SessionState
from backend.services.emotion_transition_service import EmotionTransitionService
from backend.services.session_service import SessionService
from backend.workflows.setup_graph import IntentRecognitionWorkflow


class SetupService:
    def __init__(self):
        self.session_service = SessionService()
        self.intent_workflow = IntentRecognitionWorkflow()
        self.loader = get_config_loader()
        self.emotion_transition = EmotionTransitionService()

    def confirm_profile(self, session_id: str, profile: EmployeeProfile) -> SessionState:
        state = self.session_service.get_session(session_id)
        state.employee_profile = profile
        self._backfill_profile_setup_fields(state)
        if profile.is_ready_for_setup():
            state.stage = "profile_ready"
        else:
            state.warnings.append(f"缺少必填字段: {', '.join(profile.missing_required_fields())}")
        return self.session_service.save_session(state)

    async def confirm_intent(self, session_id: str, intent_id: str | None = None, free_text: str | None = None) -> SessionState:
        state = self.session_service.get_session(session_id)
        result = await self.intent_workflow.recognize(text=free_text, profile=state.employee_profile, intent_id=intent_id)
        state.intent = result
        self._backfill_profile_setup_fields(state)
        return self.session_service.save_session(state)

    def confirm_persona(self, session_id: str, persona_id: str, difficulty_id: str = "medium", run_mode: str = "guidance_then_rehearsal") -> SessionState:
        state = self.session_service.get_session(session_id)
        personas = self.loader.personas()
        difficulties = self.loader.difficulties()
        if persona_id not in personas:
            raise ValueError(f"Unknown persona_id: {persona_id}")
        if difficulty_id not in difficulties:
            raise ValueError(f"Unknown difficulty_id: {difficulty_id}")
        state.persona = personas[persona_id]
        state.difficulty = difficulties[difficulty_id]
        state.run_mode = run_mode  # validated by SessionState on save/read
        state.max_user_turns = get_settings().max_user_turns
        return self.session_service.save_session(state)

    def confirm_simulation(
        self,
        session_id: str,
        *,
        personality: BigFivePersonality,
        primary_motive_id: str,
        secondary_motive_ids: list[str],
        run_mode: str = "guidance_then_rehearsal",
    ) -> SessionState:
        state = self.session_service.get_session(session_id)
        self._validate_motives(primary_motive_id, secondary_motive_ids)
        state.personality = personality
        state.motivation = MotivationState(
            primary_motive_id=primary_motive_id,
            secondary_motive_ids=secondary_motive_ids,
            primary_score=50.0,
            secondary_scores={
                motive_id: 50.0 for motive_id in secondary_motive_ids
            },
        )
        state.emotion_state = self.emotion_transition.initial_state(
            intent_id=state.intent.intent_id if state.intent else None,
            personality=personality,
        )
        state.run_mode = run_mode
        state.max_user_turns = get_settings().max_user_turns
        state.setup_ready = False
        state.guidance_report_id = None
        state.coach_report_id = None
        return self.session_service.save_session(state)

    def complete_setup(self, session_id: str) -> SessionState:
        state = self.session_service.get_session(session_id)
        self._backfill_profile_setup_fields(state)
        missing = []
        if not state.employee_profile or not state.employee_profile.is_ready_for_setup():
            missing.append("employee_profile_required_fields")
        if not state.intent:
            missing.append("intent")
        legacy_simulation_ready = bool(state.persona and state.difficulty)
        dynamic_simulation_ready = bool(state.personality and state.motivation)
        if not legacy_simulation_ready and not dynamic_simulation_ready:
            missing.append("persona/difficulty_or_personality/motivation")
        if missing:
            state.warnings.append(f"setup 未完成: {', '.join(missing)}")
            self.session_service.save_session(state)
            raise ValueError(f"setup 未完成: {', '.join(missing)}")
        state.setup_ready = True
        state.stage = "setup_ready"
        return self.session_service.save_session(state)

    def _validate_motives(
        self,
        primary_motive_id: str,
        secondary_motive_ids: list[str],
    ) -> None:
        motives = self.loader.motives()
        if primary_motive_id not in motives:
            raise ValueError(f"Unknown primary_motive_id: {primary_motive_id}")
        if len(secondary_motive_ids) != 2:
            raise ValueError("secondary_motive_ids must contain exactly two motives")
        if len(set(secondary_motive_ids)) != 2:
            raise ValueError("secondary_motive_ids must not contain duplicates")
        if primary_motive_id in secondary_motive_ids:
            raise ValueError("primary motive and secondary motives must be different")
        unknown = [
            motive_id
            for motive_id in secondary_motive_ids
            if motive_id not in motives
        ]
        if unknown:
            raise ValueError(
                f"Unknown secondary_motive_ids: {', '.join(unknown)}"
            )

    def _backfill_profile_setup_fields(self, state: SessionState) -> None:
        profile = state.employee_profile
        if not profile:
            return
        if not profile.employee_alias:
            profile.employee_alias = profile.role or "该员工"
        if not profile.review_cycle:
            profile.review_cycle = "当前绩效周期"
        if not profile.conversation_topic and state.intent:
            profile.conversation_topic = self._intent_display_name(state)
        if not profile.conversation_topic:
            profile.conversation_topic = "绩效沟通"
        if not profile.performance_rating:
            profile.performance_rating = "待确认"
        if not profile.key_goals and not profile.facts:
            fallback_fact = self._fallback_profile_fact(profile)
            if fallback_fact:
                profile.facts.append(FactItem(description=fallback_fact, evidence_source="employee_profile"))

    @staticmethod
    def _fallback_profile_fact(profile: EmployeeProfile) -> str | None:
        for value in [
            profile.employee_status_summary,
            profile.source_profile_text,
            profile.role,
            profile.department,
        ]:
            text = str(value or "").strip()
            if text:
                return text[:240]
        return None

    @staticmethod
    def _intent_display_name(state: SessionState) -> str | None:
        if not state.intent:
            return None
        if state.intent.config and state.intent.config.name:
            return state.intent.config.name
        return state.intent.intent_id

    def list_options(self) -> dict:
        intents = [cfg.model_dump() for cfg in self.loader.intents().values()]
        return {
            "intents": intents,
            "default_intent": self.loader.default_intent_id(),
            "personas": [cfg.model_dump() for cfg in self.loader.personas().values()],
            "difficulties": [cfg.model_dump() for cfg in self.loader.difficulties().values()],
            "default_difficulty": self.loader.default_difficulty_id(),
            "motives": [
                cfg.model_dump() for cfg in self.loader.motives().values()
            ],
            "emotion_anchors": [
                cfg.model_dump()
                for cfg in self.loader.emotion_anchors().values()
            ],
            "default_big_five": self.loader.default_big_five().model_dump(),
            "motive_recommendations": {
                item["id"]: self.loader.motive_recommendation(item["id"])
                for item in intents
                if item.get("id")
            },
            "default_motive_recommendation": (
                self.loader.motive_recommendation(None)
            ),
        }
