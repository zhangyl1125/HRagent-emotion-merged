from __future__ import annotations

from backend.schemas.emotion import EmotionSignal
from backend.schemas.motivation import InterviewPurpose, MvpiMotivation, SatisfactionDelta, clamp_score


class MotivationScoringService:
    def calculate_delta(
        self,
        *,
        signal: EmotionSignal,
        interview_purpose: InterviewPurpose | str,
        primary_motivation: MvpiMotivation | str,
        secondary_motivation: MvpiMotivation | str,
    ) -> SatisfactionDelta:
        delta = self._calculate_base_delta(signal)
        delta = self._apply_interview_purpose_weight(delta, signal, self._purpose(interview_purpose))
        delta = self._apply_mvpi_weight(
            delta,
            signal,
            self._motivation(primary_motivation),
            self._motivation(secondary_motivation),
        )
        return SatisfactionDelta(
            primary_delta=round(delta.primary_delta, 2),
            secondary_delta=round(delta.secondary_delta, 2),
        )

    @staticmethod
    def total_satisfaction(primary: float, secondary: float) -> float:
        return round(clamp_score(primary) * 0.7 + clamp_score(secondary) * 0.3, 2)

    @staticmethod
    def _calculate_base_delta(signal: EmotionSignal) -> SatisfactionDelta:
        primary_delta = 0.0
        secondary_delta = 0.0

        if signal.empathy >= 0.75:
            primary_delta += 12
            secondary_delta += 6
        elif signal.empathy >= 0.45:
            primary_delta += 6
            secondary_delta += 3
        elif signal.empathy < 0.2 and signal.pressure > 0.6:
            primary_delta -= 12
            secondary_delta -= 6

        if signal.specificity >= 0.65 and signal.objective_evidence >= 0.6:
            primary_delta += 10
        elif signal.specificity < 0.25 and signal.pressure > 0.5:
            primary_delta -= 8

        if signal.support_plan >= 0.65:
            primary_delta += 12
            secondary_delta += 6

        if signal.respectfulness < 0.35:
            primary_delta -= 15
            secondary_delta -= 8

        if signal.red_line_hit:
            primary_delta -= 25
            secondary_delta -= 15

        return SatisfactionDelta(primary_delta=primary_delta, secondary_delta=secondary_delta)

    def _apply_interview_purpose_weight(
        self,
        delta: SatisfactionDelta,
        signal: EmotionSignal,
        purpose: InterviewPurpose,
    ) -> SatisfactionDelta:
        if purpose == InterviewPurpose.MOTIVATION:
            delta.primary_delta += signal.recognition * 12
            delta.primary_delta += signal.compensation_or_reward * 14
            delta.primary_delta += signal.growth_path * 8
        elif purpose == InterviewPurpose.IMPROVEMENT:
            delta.primary_delta += signal.growth_path * 14
            delta.secondary_delta += signal.support_plan * 8
            delta.secondary_delta += signal.empathy * 5
        elif purpose == InterviewPurpose.EXIT:
            delta.primary_delta += signal.placement_support * 16
            delta.primary_delta += signal.objective_evidence * 10
            delta.secondary_delta += signal.empathy * 8
        elif purpose == InterviewPurpose.MOTIVATION_IMPROVEMENT:
            motivation_score = max(signal.recognition, signal.compensation_or_reward)
            improvement_score = max(signal.growth_path, signal.support_plan)
            combined = min(motivation_score, improvement_score)
            delta.primary_delta += combined * 18
            delta.secondary_delta += combined * 8
        elif purpose == InterviewPurpose.IMPROVEMENT_EXIT:
            improvement_score = max(signal.growth_path, signal.support_plan)
            exit_score = max(signal.placement_support, signal.objective_evidence)
            combined = min(improvement_score, exit_score)
            delta.primary_delta += combined * 18
            delta.secondary_delta += combined * 8
        return delta

    def _apply_mvpi_weight(
        self,
        delta: SatisfactionDelta,
        signal: EmotionSignal,
        primary_motivation: MvpiMotivation,
        secondary_motivation: MvpiMotivation,
    ) -> SatisfactionDelta:
        delta.primary_delta += self._score_for_motivation(primary_motivation, signal) * 15
        delta.secondary_delta += self._score_for_motivation(secondary_motivation, signal) * 8
        return delta

    @staticmethod
    def _score_for_motivation(motivation: MvpiMotivation, signal: EmotionSignal) -> float:
        if motivation == MvpiMotivation.COMMERCE:
            return signal.compensation_or_reward
        if motivation == MvpiMotivation.POWER:
            return signal.growth_path
        if motivation == MvpiMotivation.RECOGNITION:
            return signal.recognition
        if motivation == MvpiMotivation.AFFILIATION:
            return min(1.0, signal.empathy + signal.support_plan * 0.5)
        if motivation == MvpiMotivation.SECURITY:
            return min(1.0, signal.support_plan + signal.placement_support)
        if motivation == MvpiMotivation.HEDONISM:
            return signal.support_plan
        return 0.0

    @staticmethod
    def _purpose(value: InterviewPurpose | str) -> InterviewPurpose:
        try:
            return InterviewPurpose(getattr(value, "value", value))
        except ValueError:
            return InterviewPurpose.IMPROVEMENT

    @staticmethod
    def _motivation(value: MvpiMotivation | str) -> MvpiMotivation:
        try:
            return MvpiMotivation(getattr(value, "value", value))
        except ValueError:
            return MvpiMotivation.RECOGNITION
