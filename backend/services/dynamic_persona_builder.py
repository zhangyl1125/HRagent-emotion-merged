from __future__ import annotations

from backend.schemas.emotion import EmployeeAttitude, EmotionState


class DynamicPersonaBuilder:
    _LABELS = {
        EmployeeAttitude.CALM_NEUTRAL: "平静中立",
        EmployeeAttitude.GUARDED_HESITANT: "谨慎犹豫",
        EmployeeAttitude.DEFENSIVE_RESISTANT: "防御抵触",
        EmployeeAttitude.FRUSTRATED_PUSHBACK: "不满反驳",
        EmployeeAttitude.SILENT_WITHDRAWN: "沉默退缩",
        EmployeeAttitude.REFLECTIVE_SOFTENING: "开始反思",
        EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE: "合作建设性",
    }
    _BEHAVIOR = {
        EmployeeAttitude.CALM_NEUTRAL: "正常回应，没有明显防御；可以说明事实和疑问，但不要像汇报工作。",
        EmployeeAttitude.GUARDED_HESITANT: "短句、试探、有保留；先确认经理到底在说什么，不急着接受结论。",
        EmployeeAttitude.DEFENSIVE_RESISTANT: "解释困难，质疑评价依据；可以说自己觉得反馈笼统或片面。",
        EmployeeAttitude.FRUSTRATED_PUSHBACK: "表达委屈或不满，但不能攻击；语气可以更直接，仍保持职场边界。",
        EmployeeAttitude.SILENT_WITHDRAWN: "回答少，回避深入；可以说需要消化、不太知道怎么回应，但不要完全拒绝对话。",
        EmployeeAttitude.REFLECTIVE_SOFTENING: "开始理解，愿意听具体反馈；可以部分承认问题，但仍保留自己的背景说明。",
        EmployeeAttitude.COOPERATIVE_CONSTRUCTIVE: "主动讨论下一步改进；可以谈条件、资源、时间点和支持方式。",
    }

    def build(self, state: EmotionState | None) -> str:
        if not state:
            return ""
        label = self._LABELS.get(state.current_attitude, "平静中立")
        behavior = self._BEHAVIOR.get(state.current_attitude, self._BEHAVIOR[EmployeeAttitude.CALM_NEUTRAL])
        return (
            "[当前员工态度状态]\n"
            f"状态：{state.current_attitude.value}（{label}）\n"
            f"强度：{state.intensity}/100\n"
            f"状态区间：{state.emotion_band}\n"
            f"表现说明：{state.emotion_description}\n"
            f"变化原因：{state.transition_reason}\n\n"
            "[当前员工核心诉求满足度]\n"
            f"面谈目的：{getattr(state.interview_purpose, 'value', state.interview_purpose)}\n"
            f"主诉求：{getattr(state.primary_motivation, 'value', state.primary_motivation)}，满足度：{state.primary_satisfaction}/100，本轮变化：{state.last_primary_delta:+.1f}\n"
            f"辅诉求：{getattr(state.secondary_motivation, 'value', state.secondary_motivation)}，满足度：{state.secondary_satisfaction}/100，本轮变化：{state.last_secondary_delta:+.1f}\n"
            f"总满足度：{state.total_satisfaction}/100\n\n"
            "[回复要求]\n"
            f"你现在的态度表现为：{behavior}\n"
            "回复必须体现当前满足度：低满足度时保留防御、委屈、质疑或焦虑；中等满足度时愿意听但仍保留疑虑；高满足度时才可以进入合作对齐。\n"
            "仍要保持企业绩效反馈场景的职业边界，不允许辱骂、人身攻击、歧视、威胁、过度戏剧化或脱离工作场景。\n"
            "回复长度控制在 1-3 句话。"
        )

    @classmethod
    def label(cls, attitude: EmployeeAttitude) -> str:
        return cls._LABELS.get(attitude, attitude.value)
