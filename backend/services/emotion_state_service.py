from __future__ import annotations

from dataclasses import dataclass

from backend.schemas.emotion import EmployeeAttitude, EmotionSignal
from backend.schemas.motivation import InterviewPurpose, get_satisfaction_band


@dataclass(frozen=True)
class EmotionExpression:
    emotion_band: str
    attitude: EmployeeAttitude
    description: str
    intensity: int


class EmotionStateService:
    def expression_for(
        self,
        *,
        total_satisfaction: float,
        interview_purpose: InterviewPurpose | str,
        signal: EmotionSignal,
    ) -> EmotionExpression:
        band = get_satisfaction_band(total_satisfaction)
        purpose = self._purpose(interview_purpose)

        if signal.likely_employee_reaction == "withdraw" and total_satisfaction < 60:
            return EmotionExpression(
                emotion_band=band,
                attitude=EmployeeAttitude.SILENT_WITHDRAWN,
                description="压力下转为收缩回应，需要低压力追问和确认空间。",
                intensity=max(55, self._band_intensity(band)),
            )

        if band == "extreme_resistance":
            if purpose == InterviewPurpose.MOTIVATION:
                return EmotionExpression(band, EmployeeAttitude.FRUSTRATED_PUSHBACK, "反复强调贡献和公平性，质疑公司是否真正认可自己。", 85)
            if purpose == InterviewPurpose.IMPROVEMENT:
                return EmotionExpression(band, EmployeeAttitude.DEFENSIVE_RESISTANT, "持续委屈，认为评价标准苛刻或事实不完整。", 80)
            if purpose == InterviewPurpose.EXIT:
                return EmotionExpression(band, EmployeeAttitude.FRUSTRATED_PUSHBACK, "直接担心被优化或被针对，强烈要求解释依据和流程。", 88)
            if purpose == InterviewPurpose.MOTIVATION_IMPROVEMENT:
                return EmotionExpression(band, EmployeeAttitude.FRUSTRATED_PUSHBACK, "一边需要认可，一边抵触短板批评，情绪来回波动。", 82)
            return EmotionExpression(band, EmployeeAttitude.DEFENSIVE_RESISTANT, "焦虑防御，害怕进入退出流程，对后果非常敏感。", 90)

        if band == "negative_defensive":
            return EmotionExpression(band, EmployeeAttitude.GUARDED_HESITANT, "抵触有所降低，但仍有明显顾虑和防备。", 62)

        if band == "rational_softening":
            return EmotionExpression(band, EmployeeAttitude.REFLECTIVE_SOFTENING, "火气下降，愿意沟通，但仍会保留疑虑。", 45)

        if band == "active_engagement":
            return EmotionExpression(band, EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE, "开始参与讨论改进路径、支持资源和后续安排。", 32)

        return EmotionExpression(band, EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE, "负面情绪基本消解，能够接纳反馈并对齐行动。", 20)

    @staticmethod
    def _band_intensity(band: str) -> int:
        return {
            "extreme_resistance": 82,
            "negative_defensive": 62,
            "rational_softening": 45,
            "active_engagement": 32,
            "emotion_resolved": 20,
        }.get(band, 50)

    @staticmethod
    def _purpose(value: InterviewPurpose | str) -> InterviewPurpose:
        try:
            return InterviewPurpose(getattr(value, "value", value))
        except ValueError:
            return InterviewPurpose.IMPROVEMENT
