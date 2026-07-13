from __future__ import annotations

from datetime import datetime, timezone

from backend.config.settings import get_settings
from backend.schemas.emotion import EmployeeAttitude, EmotionSignal, EmotionState
from backend.schemas.motivation import InterviewPurpose, MvpiMotivation, clamp_score
from backend.services.emotion_state_service import EmotionStateService
from backend.services.motivation_scoring_service import MotivationScoringService


class AttitudeTransitionEngine:
    _ESCALATE_PATH = [
        EmployeeAttitude.CALM_NEUTRAL,
        EmployeeAttitude.GUARDED_HESITANT,
        EmployeeAttitude.DEFENSIVE_RESISTANT,
        EmployeeAttitude.FRUSTRATED_PUSHBACK,
    ]
    _SOFTEN_PATH = [
        EmployeeAttitude.FRUSTRATED_PUSHBACK,
        EmployeeAttitude.DEFENSIVE_RESISTANT,
        EmployeeAttitude.GUARDED_HESITANT,
        EmployeeAttitude.REFLECTIVE_SOFTENING,
        EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE,
    ]

    def __init__(self):
        self.settings = get_settings()
        self.motivation_scoring = MotivationScoringService()
        self.emotion_state_service = EmotionStateService()

    def compute_next_state(self, current: EmotionState, signal: EmotionSignal, *, turn_index: int) -> EmotionState:
        if not self.settings.emotion_engine_enabled:
            return current
        if getattr(self.settings, "motivation_engine_enabled", True):
            return self._compute_motivation_state(current, signal, turn_index=turn_index)
        return self._compute_legacy_state(current, signal, turn_index=turn_index)

    def _compute_motivation_state(self, current: EmotionState, signal: EmotionSignal, *, turn_index: int) -> EmotionState:
        delta = self.motivation_scoring.calculate_delta(
            signal=signal,
            interview_purpose=current.interview_purpose,
            primary_motivation=current.primary_motivation,
            secondary_motivation=current.secondary_motivation,
        )
        primary = clamp_score(current.primary_satisfaction + delta.primary_delta)
        secondary = clamp_score(current.secondary_satisfaction + delta.secondary_delta)
        total = self.motivation_scoring.total_satisfaction(primary, secondary)
        expression = self.emotion_state_service.expression_for(
            total_satisfaction=total,
            interview_purpose=current.interview_purpose,
            signal=signal,
        )

        max_intensity = min(100, max(0, self.settings.emotion_state_max_intensity))
        signal.primary_delta = delta.primary_delta
        signal.secondary_delta = delta.secondary_delta
        return EmotionState(
            current_attitude=expression.attitude,
            previous_attitude=current.current_attitude,
            intensity=min(max_intensity, expression.intensity),
            transition_reason=signal.analysis_reason or self._delta_reason(delta.primary_delta, delta.secondary_delta),
            interview_purpose=current.interview_purpose,
            primary_motivation=current.primary_motivation,
            secondary_motivation=current.secondary_motivation,
            primary_satisfaction=round(primary, 2),
            secondary_satisfaction=round(secondary, 2),
            total_satisfaction=total,
            emotion_band=expression.emotion_band,
            emotion_description=expression.description,
            last_primary_delta=round(delta.primary_delta, 2),
            last_secondary_delta=round(delta.secondary_delta, 2),
            turn_index=turn_index,
            updated_at=datetime.now(timezone.utc),
        )

    def _compute_legacy_state(self, current: EmotionState, signal: EmotionSignal, *, turn_index: int) -> EmotionState:
        attitude = current.current_attitude
        intensity_delta = 0
        reason = "no_significant_change"

        if signal.risk_flags:
            attitude = self._step_escalate(attitude)
            intensity_delta = 10
            reason = "risk_flags_detected"
        elif signal.pressure > 0.75 and signal.empathy < 0.30:
            attitude = self._step_escalate(attitude)
            intensity_delta = 12
            reason = "high_pressure_low_empathy"
        elif signal.respectfulness < 0.45:
            attitude = self._step_escalate(attitude)
            intensity_delta = 10
            reason = "low_respectfulness"
        elif signal.likely_employee_reaction == "withdraw":
            attitude = EmployeeAttitude.SILENT_WITHDRAWN if attitude in {EmployeeAttitude.GUARDED_HESITANT, EmployeeAttitude.DEFENSIVE_RESISTANT, EmployeeAttitude.SILENT_WITHDRAWN} else EmployeeAttitude.GUARDED_HESITANT
            intensity_delta = 6
            reason = "employee_likely_to_withdraw"
        elif signal.support_plan > 0.60:
            attitude = self._step_soften(attitude, allow_cooperation=True)
            intensity_delta = -10
            reason = "concrete_support_plan"
        elif signal.empathy > 0.65 and signal.specificity > 0.55:
            attitude = self._step_soften(attitude, allow_cooperation=False)
            intensity_delta = -8
            reason = "empathy_with_specific_evidence"
        elif signal.likely_employee_reaction == "soften":
            attitude = self._step_soften(attitude, allow_cooperation=False)
            intensity_delta = -5
            reason = "softening_signal"

        max_intensity = min(100, max(0, self.settings.emotion_state_max_intensity))
        next_intensity = max(0, min(max_intensity, current.intensity + intensity_delta))
        if attitude == EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE:
            next_intensity = min(next_intensity, 45)
        elif attitude in {EmployeeAttitude.DEFENSIVE_RESISTANT, EmployeeAttitude.FRUSTRATED_PUSHBACK, EmployeeAttitude.SILENT_WITHDRAWN}:
            next_intensity = max(next_intensity, 35)

        return EmotionState(
            current_attitude=attitude,
            previous_attitude=current.current_attitude,
            intensity=next_intensity,
            transition_reason=reason,
            interview_purpose=current.interview_purpose,
            primary_motivation=current.primary_motivation,
            secondary_motivation=current.secondary_motivation,
            primary_satisfaction=current.primary_satisfaction,
            secondary_satisfaction=current.secondary_satisfaction,
            total_satisfaction=current.total_satisfaction,
            emotion_band=current.emotion_band,
            emotion_description=current.emotion_description,
            last_primary_delta=0.0,
            last_secondary_delta=0.0,
            turn_index=turn_index,
            updated_at=datetime.now(timezone.utc),
        )

    def _step_escalate(self, attitude: EmployeeAttitude) -> EmployeeAttitude:
        if attitude == EmployeeAttitude.SILENT_WITHDRAWN:
            return EmployeeAttitude.SILENT_WITHDRAWN
        if attitude == EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE:
            return EmployeeAttitude.GUARDED_HESITANT
        if attitude == EmployeeAttitude.REFLECTIVE_SOFTENING:
            return EmployeeAttitude.GUARDED_HESITANT
        if attitude in self._ESCALATE_PATH:
            idx = self._ESCALATE_PATH.index(attitude)
            return self._ESCALATE_PATH[min(len(self._ESCALATE_PATH) - 1, idx + 1)]
        return EmployeeAttitude.GUARDED_HESITANT

    def _step_soften(self, attitude: EmployeeAttitude, *, allow_cooperation: bool) -> EmployeeAttitude:
        if attitude == EmployeeAttitude.SILENT_WITHDRAWN:
            return EmployeeAttitude.GUARDED_HESITANT
        if attitude == EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE:
            return EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE
        if attitude == EmployeeAttitude.CALM_NEUTRAL:
            return EmployeeAttitude.REFLECTIVE_SOFTENING
        if attitude in self._SOFTEN_PATH:
            idx = self._SOFTEN_PATH.index(attitude)
            next_attitude = self._SOFTEN_PATH[min(len(self._SOFTEN_PATH) - 1, idx + 1)]
            if next_attitude == EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE and not allow_cooperation:
                return EmployeeAttitude.REFLECTIVE_SOFTENING
            return next_attitude
        return attitude

    @staticmethod
    def _delta_reason(primary_delta: float, secondary_delta: float) -> str:
        total_delta = primary_delta * 0.7 + secondary_delta * 0.3
        if total_delta > 8:
            return "satisfaction_rising"
        if total_delta < -8:
            return "satisfaction_dropping"
        return "no_significant_change"

    @staticmethod
    def normalize_purpose(intent_id: str | None) -> InterviewPurpose:
        mapping = {
            "development": InterviewPurpose.MOTIVATION,
            "promotion_development": InterviewPurpose.MOTIVATION,
            "motivation": InterviewPurpose.MOTIVATION,
            "improvement": InterviewPurpose.IMPROVEMENT,
            "pip_underperformance": InterviewPurpose.IMPROVEMENT,
            "exit": InterviewPurpose.EXIT,
            "termination_or_separation": InterviewPurpose.EXIT,
            "development_improvement": InterviewPurpose.MOTIVATION_IMPROVEMENT,
            "motivation_improvement": InterviewPurpose.MOTIVATION_IMPROVEMENT,
            "improvement_exit": InterviewPurpose.IMPROVEMENT_EXIT,
        }
        return mapping.get(str(intent_id or "").strip(), InterviewPurpose.IMPROVEMENT)

    @staticmethod
    def infer_motivations(persona_id: str | None, intent_id: str | None) -> tuple[MvpiMotivation, MvpiMotivation]:
        persona_map = {
            "emotionally_hurt": (MvpiMotivation.RECOGNITION, MvpiMotivation.SECURITY),
            "outcome_negotiator": (MvpiMotivation.COMMERCE, MvpiMotivation.POWER),
            "data_logic_challenger": (MvpiMotivation.RECOGNITION, MvpiMotivation.SECURITY),
            "silent_avoidant": (MvpiMotivation.SECURITY, MvpiMotivation.AFFILIATION),
        }
        if persona_id in persona_map:
            return persona_map[persona_id]
        purpose = AttitudeTransitionEngine.normalize_purpose(intent_id)
        if purpose == InterviewPurpose.EXIT:
            return MvpiMotivation.SECURITY, MvpiMotivation.RECOGNITION
        if purpose == InterviewPurpose.MOTIVATION:
            return MvpiMotivation.POWER, MvpiMotivation.RECOGNITION
        if purpose == InterviewPurpose.MOTIVATION_IMPROVEMENT:
            return MvpiMotivation.POWER, MvpiMotivation.RECOGNITION
        if purpose == InterviewPurpose.IMPROVEMENT_EXIT:
            return MvpiMotivation.SECURITY, MvpiMotivation.AFFILIATION
        return MvpiMotivation.RECOGNITION, MvpiMotivation.SECURITY
