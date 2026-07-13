from __future__ import annotations

import re

from backend.schemas.conversation import ConversationTurn
from backend.schemas.emotion import EmotionSignal, EmotionState


class EmotionAnalyzer:
    """Analyze how the manager's latest wording may affect the virtual employee.

    This deterministic analyzer keeps HR training behavior stable and auditable. The
    service boundary is intentionally separate so it can be swapped to a Bosch LLM
    structured-output analyzer later without changing the workflow.
    """

    _EMPATHY_WORDS = ("理解", "知道", "辛苦", "压力", "不容易", "一起", "先听", "感受", "困难")
    _SUPPORT_WORDS = ("支持", "资源", "协调", "下一步", "计划", "一起明确", "帮助", "机制", "优先级", "时间点")
    _OBJECTIVE_WORDS = ("事实", "数据", "记录", "案例", "目标", "标准", "证据", "交付", "延期", "质量", "节点", "结果")
    _PLACEMENT_WORDS = ("过渡", "内部机会", "转岗", "选择", "缓冲", "安排", "交接", "流程", "申诉", "HR", "Legal")
    _RECOGNITION_WORDS = ("认可", "看到", "贡献", "努力", "亮点", "价值", "成绩", "优势", "做得好")
    _GROWTH_WORDS = ("成长", "发展", "提升", "改进", "复盘", "辅导", "阶段目标", "路径", "每两周", "检查点")
    _REWARD_WORDS = ("奖金", "薪酬", "调薪", "晋升", "评级", "收益", "回报", "机会", "权限")
    _PRESSURE_WORDS = ("必须", "马上", "立刻", "完全不行", "很差", "失败", "不能接受", "不符合预期", "不太适合", "继续留下", "淘汰", "退出", "就是你的问题", "你总是", "你从来")
    _DISRESPECT_WORDS = ("没用", "废", "差劲", "离谱", "借口", "推卸", "态度问题", "能力不行")
    _WITHDRAW_WORDS = ("不想听", "别解释", "不用说", "没什么好谈", "就这样")

    async def analyze(
        self,
        *,
        user_text: str,
        current_state: EmotionState,
        history: list[ConversationTurn],
        audio_emotion: str | None = None,
    ) -> EmotionSignal:
        text = user_text.strip()
        lowered = text.lower()

        empathy = self._score_keywords(text, self._EMPATHY_WORDS, base=0.18, step=0.22)
        support_plan = self._score_keywords(text, self._SUPPORT_WORDS, base=0.05, step=0.24)
        pressure = self._score_keywords(text, self._PRESSURE_WORDS, base=0.12, step=0.24)
        disrespect_hits = self._hits(text, self._DISRESPECT_WORDS)
        if "?" in text or "？" in text:
            pressure = max(0.0, pressure - 0.08)

        specificity = self._specificity_score(text)
        objective_evidence = self._score_keywords(text, self._OBJECTIVE_WORDS, base=0.08, step=0.18)
        placement_support = self._score_keywords(text, self._PLACEMENT_WORDS, base=0.0, step=0.22)
        recognition = self._score_keywords(text, self._RECOGNITION_WORDS, base=0.0, step=0.22)
        growth_path = self._score_keywords(text, self._GROWTH_WORDS, base=0.0, step=0.20)
        compensation_or_reward = self._score_keywords(text, self._REWARD_WORDS, base=0.0, step=0.20)
        clarity = min(1.0, 0.35 + len(text) / 80 + specificity * 0.25)
        respectfulness = max(0.0, 0.92 - disrespect_hits * 0.28 - max(0.0, pressure - 0.55) * 0.45)

        risk_flags: list[str] = []
        if disrespect_hits:
            risk_flags.append("low_respectfulness")
        if any(word in lowered for word in ("滚", "傻", "蠢", "威胁", "开除你")):
            risk_flags.append("unsafe_escalation")
        red_line_hit = bool(disrespect_hits or "unsafe_escalation" in risk_flags)

        if self._hits(text, self._WITHDRAW_WORDS) and empathy < 0.35:
            reaction = "withdraw"
        elif pressure > 0.65 or respectfulness < 0.5:
            reaction = "escalate"
        elif empathy > 0.6 and (specificity > 0.45 or support_plan > 0.45):
            reaction = "soften"
        else:
            reaction = "stay"

        user_text_emotion = "calm"
        if pressure > 0.7:
            user_text_emotion = "angry"
        elif empathy > 0.6:
            user_text_emotion = "calm"
        elif clarity < 0.45:
            user_text_emotion = "unclear"

        return EmotionSignal(
            user_text_emotion=user_text_emotion,
            audio_emotion=audio_emotion,
            empathy=round(empathy, 2),
            clarity=round(clarity, 2),
            specificity=round(specificity, 2),
            respectfulness=round(respectfulness, 2),
            pressure=round(pressure, 2),
            support_plan=round(support_plan, 2),
            objective_evidence=round(objective_evidence, 2),
            placement_support=round(placement_support, 2),
            recognition=round(recognition, 2),
            growth_path=round(growth_path, 2),
            compensation_or_reward=round(compensation_or_reward, 2),
            red_line_hit=red_line_hit,
            analysis_reason=self._analysis_reason(
                empathy=empathy,
                specificity=specificity,
                support_plan=support_plan,
                pressure=pressure,
                respectfulness=respectfulness,
                objective_evidence=objective_evidence,
                placement_support=placement_support,
            ),
            likely_employee_reaction=reaction,
            risk_flags=risk_flags,
        )

    @classmethod
    def _hits(cls, text: str, words: tuple[str, ...]) -> int:
        return sum(1 for word in words if word and word in text)

    @classmethod
    def _score_keywords(cls, text: str, words: tuple[str, ...], *, base: float, step: float) -> float:
        return min(1.0, base + cls._hits(text, words) * step)

    @staticmethod
    def _specificity_score(text: str) -> float:
        score = 0.12
        if re.search(r"\d+|一|二|三|四|五|六|七|八|九|十|两", text):
            score += 0.22
        if any(word in text for word in ("案例", "事实", "数据", "节点", "延期", "质量", "交付", "目标", "记录", "反馈")):
            score += 0.28
        if any(word in text for word in ("比如", "例如", "具体", "尤其", "这次", "这个季度", "上周", "项目")):
            score += 0.24
        return min(1.0, score)

    @staticmethod
    def _analysis_reason(
        *,
        empathy: float,
        specificity: float,
        support_plan: float,
        pressure: float,
        respectfulness: float,
        objective_evidence: float,
        placement_support: float,
    ) -> str:
        if respectfulness < 0.45:
            return "表达中出现低尊重或标签化风险，员工更容易防御。"
        if pressure > 0.65 and empathy < 0.35:
            return "压力较高且缺少情绪承接，员工会更关注威胁感。"
        if placement_support > 0.55:
            return "话术补充了过渡或流程安排，能提升员工安全感。"
        if support_plan > 0.6:
            return "话术给出具体支持和下一步，员工更容易进入理性讨论。"
        if empathy > 0.6 and (specificity > 0.45 or objective_evidence > 0.45):
            return "话术同时承接情绪并回到事实，能降低对抗。"
        if empathy > 0.6:
            return "话术有情绪承接，但还需要补充具体事实或行动。"
        if specificity > 0.55:
            return "话术提供了事实线索，但情绪承接还可以更充分。"
        return "本轮话术影响有限，员工态度主要保持原状态。"
