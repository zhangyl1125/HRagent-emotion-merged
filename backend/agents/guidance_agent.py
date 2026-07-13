from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from pydantic import BaseModel, Field

from backend.rag.citation import chunks_to_citations
from backend.schemas.guidance import GuidanceReport
from backend.schemas.state import SessionState
from backend.schemas.retrieval import RetrievedChunk
from backend.services.langchain_llm_service import LangChainLLMService
from backend.services.prompt_service import PromptService


def _prompt_payload(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _prompt_payload(item)
            for key, item in value.items()
            if key not in {"created_at", "updated_at"}
        }
    if isinstance(value, (list, tuple)):
        return [_prompt_payload(item) for item in value]
    return value


logger = logging.getLogger(__name__)

_MOTIVE_LABELS = {
    "commerce": "物质回报",
    "power": "影响力与自主权",
    "recognition": "认可与可见度",
    "affiliation": "团队归属与关系",
    "security": "稳定与确定性",
    "hedonism": "体验与工作愉悦度",
}


class GuidanceStructuredOutput(BaseModel):
    purpose: str = Field(min_length=1)
    opening_suggestion: str = Field(min_length=1)
    risk_preview: list[str]
    response_strategies: list[str]
    safer_phrases: list[str]


class GuidanceAgent:
    async def generate(self, state: SessionState, retrieved_chunks: list[RetrievedChunk]) -> GuidanceReport:
        if not state.intent or not state.intent.config:
            raise ValueError("intent is required for guidance")
        try:
            return await self._generate_with_llm(state, retrieved_chunks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Guidance LLM failed for session_id=%s; using local fallback: %s", state.session_id, exc)
            return self._fallback_report(state, retrieved_chunks)

    async def stream_text(self, state: SessionState, retrieved_chunks: list[RetrievedChunk]) -> AsyncIterator[str]:
        if not state.intent or not state.intent.config:
            raise ValueError("intent is required for guidance")
        emitted = False
        try:
            prompt = self._build_stream_prompt(state, retrieved_chunks)
            async for delta in LangChainLLMService().astream_text(prompt=prompt, task_name="guidance"):
                if delta:
                    emitted = True
                    yield delta
            if not emitted:
                raise ValueError("Guidance stream returned empty content.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Guidance streaming LLM failed for session_id=%s; using local fallback: %s", state.session_id, exc)
            fallback = self._fallback_report(state, retrieved_chunks)
            yield self.stream_text_from_report(fallback)

    async def _generate_with_llm(self, state: SessionState, retrieved_chunks: list[RetrievedChunk]) -> GuidanceReport:
        prompt = self._build_prompt(state, retrieved_chunks)
        output = await LangChainLLMService().ainvoke_structured(
            prompt=prompt,
            schema=GuidanceStructuredOutput,
            task_name="guidance",
            timeout_seconds=45,
        )
        return self._report_from_output(state, retrieved_chunks, output)

    @staticmethod
    def _build_prompt(state: SessionState, retrieved_chunks: list[RetrievedChunk]) -> str:
        base_prompt = PromptService().render(
            "guidance/guidance.jinja2",
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            intent=state.intent.model_dump(exclude_none=True) if state.intent else {},
            persona=state.persona.model_dump(exclude_none=True) if state.persona else {},
            difficulty=state.difficulty.model_dump(exclude_none=True) if state.difficulty else {},
            retrieved_chunks=[chunk.model_dump(exclude_none=True) for chunk in retrieved_chunks],
        )
        dynamic_context = {
            "personality": _prompt_payload(state.personality),
            "motivation": _prompt_payload(state.motivation),
            "emotion_state": _prompt_payload(state.emotion_state),
            "emotion_log": _prompt_payload(state.emotion_log[-12:]),
        }
        return (
            f"{base_prompt}\n\n补充动态人格、诉求与情绪上下文如下。"
            "这些参数只用于形成需要在沟通中验证的假设、识别触发点并调整表达，不得作为事实定性或心理诊断。"
            "涉及情绪变化时，优先依据 emotion_log 的 VAD 前后值、诉求满足度变化和 transition_reason。"
            "不得用人格或诉求参数替代 manager/employee 的事实证据。"
            f"\ndynamic_context={json.dumps(dynamic_context, ensure_ascii=False)}"
        )

    @staticmethod
    def _build_stream_prompt(state: SessionState, retrieved_chunks: list[RetrievedChunk]) -> str:
        base_prompt = GuidanceAgent._build_prompt(state, retrieved_chunks)
        return f"""{base_prompt}

上面的 JSON 字段要求仍然代表内容范围，但本次必须用于前端流式展示。
请不要输出 JSON、Markdown 标题、代码块或额外解释。
请严格按下面 5 个段落标记顺序输出，段落标记必须原样保留：

[SECTION:purpose]
用 1 段话说明本次沟通目标，必须覆盖业务目标、事实范围、预期后续行动。

[SECTION:opening_suggestion]
用 1 段话给出可直接照着说的开场结构，必须包含目的、事实范围、邀请员工补充视角。

[SECTION:risk_preview]
- 合规或流程边界风险
- 员工人格、主辅诉求或当前 VAD 触发点
- 证据不足或表达过度风险
- 后续承诺、资源或时间点风险

[SECTION:response_strategies]
- 事实呈现策略
- 情绪承接策略
- 员工追问或反驳时的应对策略
- 支持方案和检查节点策略
- 结束时沉淀行动和责任边界策略

[SECTION:safer_phrases]
- 可直接说出口的开场话术
- 可直接说出口的事实对齐话术
- 可直接说出口的情绪承接话术
- 可直接说出口的支持方案话术
- 可直接说出口的收尾确认话术

约束：
- 每个段落必须有内容。
- 列表段落每条单独一行，以 "- " 开头。
- 每条要结合当前员工、意图、人格、主辅诉求、当前 VAD、emotion_log 以及兼容保留的 persona/难度，避免通用空话。
- 不要评价用户表现，不要打分，不引用用户对话原话。
- 不要输出 [END] 以外的结束语；如果需要结束，只输出 [END]。
"""

    @staticmethod
    def _report_from_output(state: SessionState, retrieved_chunks: list[RetrievedChunk], output: GuidanceStructuredOutput) -> GuidanceReport:
        payload = {
            **output.model_dump(),
            "session_id": state.session_id,
            "intent_id": state.intent.intent_id,
            "persona_id": state.persona.id if state.persona else None,
            "difficulty_id": state.difficulty.id if state.difficulty else None,
            "citations": [citation.model_dump(exclude_none=True) for citation in chunks_to_citations(retrieved_chunks)],
        }
        return GuidanceReport.model_validate(payload)

    @staticmethod
    def report_from_stream_sections(state: SessionState, retrieved_chunks: list[RetrievedChunk], sections: dict[str, str]) -> GuidanceReport:
        payload = {
            "session_id": state.session_id,
            "intent_id": state.intent.intent_id if state.intent else "unknown",
            "persona_id": state.persona.id if state.persona else None,
            "difficulty_id": state.difficulty.id if state.difficulty else None,
            "purpose": GuidanceAgent._clean_stream_text(sections.get("purpose")) or "围绕当前绩效事实完成一次清晰、合规、可执行的反馈沟通。",
            "opening_suggestion": GuidanceAgent._clean_stream_text(sections.get("opening_suggestion")) or "先说明本次沟通目的和事实范围，再邀请员工补充视角。",
            "risk_preview": GuidanceAgent._stream_list(sections.get("risk_preview")),
            "response_strategies": GuidanceAgent._stream_list(sections.get("response_strategies")),
            "safer_phrases": GuidanceAgent._stream_list(sections.get("safer_phrases")),
            "citations": [citation.model_dump(exclude_none=True) for citation in chunks_to_citations(retrieved_chunks)],
        }
        return GuidanceReport.model_validate(payload)

    @staticmethod
    def stream_text_from_report(report: GuidanceReport) -> str:
        return "\n".join(
            [
                "[SECTION:purpose]",
                report.purpose,
                "[SECTION:opening_suggestion]",
                report.opening_suggestion,
                "[SECTION:risk_preview]",
                *[f"- {item}" for item in report.risk_preview],
                "[SECTION:response_strategies]",
                *[f"- {item}" for item in report.response_strategies],
                "[SECTION:safer_phrases]",
                *[f"- {item}" for item in report.safer_phrases],
                "[END]",
            ]
        )

    @staticmethod
    def _clean_stream_text(value: str | None) -> str:
        text = str(value or "").strip()
        text = text.replace("[END]", "").strip()
        text = text.strip("`")
        return text.strip()

    @staticmethod
    def _stream_list(value: str | None) -> list[str]:
        text = GuidanceAgent._clean_stream_text(value)
        items: list[str] = []
        for line in text.splitlines():
            cleaned = line.strip()
            cleaned = cleaned.removeprefix("-").removeprefix("•").strip()
            if cleaned:
                items.append(cleaned)
        if not items and text:
            items = [text]
        return items

    @staticmethod
    def _unique_items(items: list[str], limit: int | None = None) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            cleaned = str(item or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
            if limit and len(result) >= limit:
                break
        return result

    @staticmethod
    def _fallback_report(state: SessionState, retrieved_chunks: list[RetrievedChunk]) -> GuidanceReport:
        intent = state.intent.config if state.intent else None
        profile = state.employee_profile
        employee = (profile.employee_alias or profile.role or "该员工") if profile else "该员工"
        intent_name = intent.name if intent else "绩效反馈"
        business_goal = intent.business_goal if intent else "围绕当前绩效事实完成一次清晰、合规、可执行的反馈沟通。"
        red_lines = intent.red_lines if intent else []
        coach_focus = intent.coach_focus if intent else []
        expected_outcome = intent.expected_outcome if intent else "员工理解反馈依据，并明确后续行动。"
        difficulty = state.difficulty.name if state.difficulty else "当前难度"
        motivation = state.motivation
        motive_id = motivation.primary_motive_id if motivation else None
        motive_label = _MOTIVE_LABELS.get(str(motive_id or ""), str(motive_id or "")) or None
        dynamic_risks: list[str] = []
        dynamic_strategies: list[str] = []
        dynamic_phrases: list[str] = []
        if motive_label:
            dynamic_risks.append(f"员工当前主诉求为“{motive_label}”；需在对话中验证，不能据此替员工下结论。")
            dynamic_strategies.append(f"围绕“{motive_label}”确认员工真正关切，并把支持边界、可行条件和检查节点说清楚。")
            dynamic_phrases.append(f"我也想确认一下，你对“{motive_label}”最关注的具体部分是什么，哪些条件对你最重要？")
        if state.personality:
            trait_values = {
                "开放性": state.personality.openness,
                "尽责性": state.personality.conscientiousness,
                "外向性": state.personality.extraversion,
                "宜人性": state.personality.agreeableness,
                "情绪敏感度": state.personality.neuroticism,
            }
            strongest_trait, strongest_score = max(trait_values.items(), key=lambda item: item[1])
            if strongest_score >= 65:
                dynamic_risks.append(f"当前 Big Five 设置中{strongest_trait}较突出；这只是演练假设，需通过开放式提问验证实际反应。")
                dynamic_strategies.append(f"围绕{strongest_trait}可能影响的表达偏好先观察、再调整，不把人格参数当作绩效事实。")
        vad = state.emotion_state.current_vad if state.emotion_state else None
        if vad and (vad.valence <= -0.25 or vad.arousal >= 0.35 or vad.dominance <= -0.25):
            dynamic_risks.append(f"当前情绪基线 VAD 为 V={vad.valence:.2f} / A={vad.arousal:.2f} / D={vad.dominance:.2f}，需预留承接和澄清空间。")
            dynamic_strategies.append("先用短句确认感受与事实，在唤醒度下降后再推进目标、期限和责任边界。")
        if state.emotion_log:
            latest_emotion = state.emotion_log[-1]
            if latest_emotion.vad_before and latest_emotion.vad_after:
                dynamic_strategies.append(f"参考最近情绪轨迹从 V={latest_emotion.vad_before.valence:.2f}/A={latest_emotion.vad_before.arousal:.2f}/D={latest_emotion.vad_before.dominance:.2f} 到 V={latest_emotion.vad_after.valence:.2f}/A={latest_emotion.vad_after.arousal:.2f}/D={latest_emotion.vad_after.dominance:.2f} 的变化，避免重复触发上一轮压力点。")

        return GuidanceReport(
            session_id=state.session_id,
            intent_id=state.intent.intent_id if state.intent else "unknown",
            persona_id=state.persona.id if state.persona else None,
            difficulty_id=state.difficulty.id if state.difficulty else None,
            purpose=f"围绕{employee}的{intent_name}开展沟通：{business_goal}",
            opening_suggestion=(
                f"先说明本次沟通目的和事实范围，再邀请{employee}补充视角。"
                "建议使用中性事实开场，避免直接下结论。"
            ),
            risk_preview=GuidanceAgent._unique_items((red_lines or []) + dynamic_risks + [
                "避免使用人格化、绝对化评价，所有反馈需回到事实、岗位要求和可观察行为。",
                "避免承诺未经审批的资源、调薪、晋升、PIP 结果、离职补偿或流程结论。",
                f"员工可能以{difficulty}强度追问依据、背景或公平性，先承接再核实，不要急于压服。",
                "如果证据不完整，明确哪些信息需要会后核实，避免现场做最终定性。",
            ], limit=6),
            response_strategies=[
                f"按“事实 - 影响 - 期望 - 支持”组织表达，并匹配{difficulty}的回应强度。",
                *dynamic_strategies,
                "每个改进点都给出可观察标准、截止时间和检查节点，避免只说态度或能力。",
                "员工防御或沉默时，先确认其压力和顾虑，再回到事实范围。",
                "员工追问公平性时，说明评价口径、样本范围和还需要补充核实的信息。",
                "结尾沉淀双方下一步行动、支持方式、复盘时间，不承诺未经确认的结果。",
                *(coach_focus[:2] if coach_focus else []),
            ],
            safer_phrases=GuidanceAgent._unique_items([
                "今天我想先对齐几个具体事实，也想听听你对背景和限制的补充。",
                *dynamic_phrases,
                "这不是对你个人价值的否定，而是我们需要一起看清楚哪些交付差距影响了结果。",
                "如果你觉得这个判断不完整，我们可以把依据逐项摊开，看哪些需要补充核实。",
                "我会把支持方式和检查节点说清楚，避免只提出要求却没有后续帮助。",
                "我们先确认下一步可执行的动作和时间点，其他需要审批或核实的部分我不会现场承诺。",
                f"本次期望结果是：{expected_outcome}",
            ], limit=6),
            citations=[citation.model_dump(exclude_none=True) for citation in chunks_to_citations(retrieved_chunks)],
            disclaimer="当前为本地兜底生成的谈前指导；模型服务恢复后可重新生成更完整版本。本建议不替代 HR/Legal 或 Manager 的最终判断。",
        )


def _build_debug_state() -> SessionState:
    from backend.schemas.intent import IntentConfig, IntentResult
    from backend.schemas.profile import EmployeeProfile, FactItem

    return SessionState(
        session_id="guidance-agent-stream-debug",
        stage="setup_ready",
        setup_ready=True,
        employee_profile=EmployeeProfile(
            employee_alias="Ms. 测试/TEST",
            role="Engineer",
            department="C/SEB-CN",
            performance_rating="待确认",
            review_cycle="当前绩效周期",
            conversation_topic="改进型反馈",
            facts=[FactItem(description="近期交付节奏和目标线存在差距。")],
        ),
        intent=IntentResult(
            intent_id="improvement",
            config=IntentConfig(
                id="improvement",
                name="改进型反馈",
                business_goal="客观指出绩效差距，明确可量化的改善标准与期限。",
                expected_outcome="员工理解反馈依据，并明确下一步行动。",
                red_lines=["不进行人身攻击或主观定性。"],
            ),
        ),
    )


_FAKE_GUIDANCE_STREAM = (
    "[SECTION:purpose]\n本次沟通旨在客观对齐绩效事实并明确改进方向。\n"
    "[SECTION:opening_suggestion]\n先说明本次沟通目的与事实范围，再邀请员工补充视角。\n"
    "[SECTION:risk_preview]\n- 避免人格化、绝对化评价\n- 不承诺未经审批的资源\n- 出现情绪先承接再核实\n"
    "[SECTION:response_strategies]\n- 按事实-影响-期望-支持组织表达\n- 给出可观察标准与截止时间\n- 先确认理解再讨论支持\n"
    "[SECTION:safer_phrases]\n- 我们先对齐共同看到的事实。\n- 这是需要一起解决的交付差距。\n[END]"
)


async def _debug_guidance_stream_main() -> None:
    """Manual guidance agent stream test.

    Usage inside the backend container:
      python -m backend.agents.guidance_agent
      GUIDANCE_AGENT_STREAM_TEST=llm python -m backend.agents.guidance_agent
    """
    import asyncio
    import os
    import re
    import time

    mode = os.getenv("GUIDANCE_AGENT_STREAM_TEST", "fake").strip().lower()
    state = _build_debug_state()

    if mode == "fake":
        # 故意把 SECTION 标记切成 7 字符碎片，验证下游对被截断标记的处理
        pieces = [_FAKE_GUIDANCE_STREAM[i:i + 7] for i in range(0, len(_FAKE_GUIDANCE_STREAM), 7)]

        async def fake_astream_text(self, *, prompt, task_name=None, model=None, temperature=None, max_tokens=None):
            for piece in pieces:
                await asyncio.sleep(0.01)
                yield piece

        LangChainLLMService.__init__ = lambda self: None
        LangChainLLMService.astream_text = fake_astream_text
        GuidanceAgent._build_stream_prompt = staticmethod(lambda state, chunks: "")

    print(f"guidance_agent_stream_test_mode={mode}")
    start = time.monotonic()
    full = ""
    async for delta in GuidanceAgent().stream_text(state, []):
        full += delta
    markers = re.findall(r"\[SECTION:(\w+)\]", full)
    elapsed = time.monotonic() - start
    print(f"emitted_len={len(full)} sections={markers} elapsed={elapsed:0.3f}s")
    assert full, "stream_text 没有产出任何内容"
    expected = ["purpose", "opening_suggestion", "risk_preview", "response_strategies", "safer_phrases"]
    assert markers == expected, f"段落标记缺失或顺序错误: {markers}"
    print("guidance agent stream OK")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_debug_guidance_stream_main())
