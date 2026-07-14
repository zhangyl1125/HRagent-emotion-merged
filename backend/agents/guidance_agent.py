from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Literal, Mapping

from backend.business_config.loader import get_config_loader
from backend.rag.citation import chunks_to_citations
from backend.schemas.guidance import GuidanceReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.services.langchain_llm_service import LangChainLLMService


GuidanceSectionKey = Literal[
    "purpose",
    "opening_suggestion",
    "risk_preview",
    "response_strategies",
    "safer_phrases",
]
GuidanceSectionValue = str | list[str]

GUIDANCE_SECTION_KEYS: tuple[GuidanceSectionKey, ...] = (
    "purpose",
    "opening_suggestion",
    "risk_preview",
    "response_strategies",
    "safer_phrases",
)
GUIDANCE_SECTION_TITLES: dict[GuidanceSectionKey, str] = {
    "purpose": "沟通目标",
    "opening_suggestion": "开场建议",
    "risk_preview": "风险提示",
    "response_strategies": "应对策略",
    "safer_phrases": "建议话术",
}
_SECTION_REQUIREMENTS: dict[GuidanceSectionKey, str] = {
    "purpose": "生成本次谈前指导的沟通目标。说明本次沟通要达成什么、管理者应对齐什么；如有相关价值观，应转成可执行的管理行为，不要写话术清单。",
    "opening_suggestion": "生成可直接用于开场的建议。聚焦开场顺序、语气和第一轮表达；如有相关价值观，应自然体现在表达方式中，不要展开完整策略。",
    "risk_preview": "生成 3-5 条风险提示。聚焦员工可能质疑、情绪风险、合规边界、价值观反面行为和管理者容易踩的坑。",
    "response_strategies": "生成 3-5 条应对策略。聚焦事实呈现、承接质疑、推进改进动作和后续跟进，并在相关时体现价值观要求的具体行为。",
    "safer_phrases": "生成 3-5 条建议话术。话术要安全、可直接说出口，可自然体现相关价值观，但不要堆砌口号，也不替 HR/Legal 或公司下最终结论。",
}


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


def _supplemental_info_excerpt(state: SessionState, max_chars: int = 8000) -> str:
    """Return existing supplemental/profile text without changing the session schema."""
    text = str(getattr(state, "supplemental_info", None) or "").strip()
    if not text and state.employee_profile:
        text = str(state.employee_profile.source_profile_text or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[补充资料较长，以上为前 {max_chars} 字。]"


def _emotion_state_prompt_payload(state: SessionState) -> dict:
    payload = _prompt_payload(state.emotion_state)
    if state.motivation is None:
        return payload

    dynamic_fields = {
        "current_vad",
        "current_anchor_id",
        "transition_strategy",
        "last_reason_summary",
        "reply_emotion_guidance",
        "has_manager_response",
    }
    return {key: value for key, value in payload.items() if key in dynamic_fields}


class GuidanceAgent:
    async def generate(
        self,
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk],
    ) -> GuidanceReport:
        sections = await self.generate_sections(state, retrieved_chunks)
        return self.report_from_sections(state, retrieved_chunks, sections)

    async def generate_sections(
        self,
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk],
    ) -> dict[GuidanceSectionKey, GuidanceSectionValue]:
        values = await asyncio.gather(
            *(self.generate_section(state, retrieved_chunks, key) for key in GUIDANCE_SECTION_KEYS)
        )
        return dict(zip(GUIDANCE_SECTION_KEYS, values, strict=True))

    async def generate_section(
        self,
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk],
        section_key: GuidanceSectionKey,
    ) -> GuidanceSectionValue:
        if not state.intent or not state.intent.config:
            raise ValueError("intent is required for guidance")
        text = await LangChainLLMService().ainvoke_text(
            prompt=self._build_section_prompt(state, retrieved_chunks, section_key),
            task_name="guidance",
        )
        text = text.strip()
        if not text:
            raise ValueError(f"Guidance section {section_key} returned empty text.")
        return self.clean_section_text(text)

    async def stream_section(
        self,
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk],
        section_key: GuidanceSectionKey,
    ) -> AsyncIterator[str]:
        if not state.intent or not state.intent.config:
            raise ValueError("intent is required for guidance")
        prompt = self._build_section_prompt(state, retrieved_chunks, section_key)
        async for delta in LangChainLLMService().astream_text(
            prompt=prompt,
            task_name="guidance",
        ):
            if delta:
                yield self.clean_section_text(delta, trim=False)

    @staticmethod
    def _build_section_prompt(
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk],
        section_key: GuidanceSectionKey,
    ) -> str:
        config_loader = get_config_loader()
        company_values = config_loader.company_values()
        culture_enabled = bool(company_values.get("enabled") and company_values.get("values"))
        general_chunks = [chunk for chunk in retrieved_chunks if chunk.scope != "culture"]
        culture_chunks = [
            chunk for chunk in retrieved_chunks if culture_enabled and chunk.scope == "culture"
        ]
        context = {
            "profile": _prompt_payload(state.employee_profile),
            "supplemental_info": _supplemental_info_excerpt(state),
            "intent": _prompt_payload(state.intent),
            "personality": _prompt_payload(state.personality),
            "motivation": _prompt_payload(state.motivation),
            "emotion_state": _emotion_state_prompt_payload(state),
            "emotion_log": _prompt_payload(state.emotion_log[-12:]),
            "retrieved_chunks": [_prompt_payload(chunk) for chunk in general_chunks],
            "company_values": company_values if culture_enabled else {},
            "culture_chunks": [_prompt_payload(chunk) for chunk in culture_chunks],
        }
        return (
            "基于 profile / supplemental_info / intent / personality / motivation / emotion_state / emotion_log 和检索材料，"
            "只生成谈前指导的一个 section。不要评价用户表现，不要打分，不引用用户对话原话。"
            "人格、诉求和情绪参数仅用于形成待验证的沟通假设，不得作为事实定性或心理诊断。"
            "company_values 和 culture_chunks 仅是补充指导知识，不是评分标准。"
            "仅使用与当前场景直接相关的价值观，把它转成具体管理行为并自然融入当前栏目；"
            "不要新增价值观栏目，不要堆砌口号。如果 company_values 或 culture_chunks 为空，不得自行编造公司的价值观。"
            "只输出当前 section 的正文内容，不要输出 JSON，不要输出当前 section 之外的内容。"
            "使用纯中文正文，不要使用 Markdown：不得输出 #、*、**、```，也不要用 - 或 * 作为列表前缀。"
            f"section_key={section_key}"
            f"section_title={GUIDANCE_SECTION_TITLES[section_key]}"
            f"section_requirement={_SECTION_REQUIREMENTS[section_key]}"
            f"context={json.dumps(context, ensure_ascii=False)}"
        )

    @staticmethod
    def report_from_sections(
        state: SessionState,
        retrieved_chunks: list[RetrievedChunk],
        sections: Mapping[GuidanceSectionKey, GuidanceSectionValue],
    ) -> GuidanceReport:
        payload = {
            "purpose": GuidanceAgent._as_text(sections["purpose"]),
            "opening_suggestion": GuidanceAgent._as_text(sections["opening_suggestion"]),
            "risk_preview": GuidanceAgent._as_list(sections["risk_preview"]),
            "response_strategies": GuidanceAgent._as_list(sections["response_strategies"]),
            "safer_phrases": GuidanceAgent._as_list(sections["safer_phrases"]),
            "session_id": state.session_id,
            "intent_id": state.intent.intent_id if state.intent else "unknown",
            "persona_id": state.persona.id if state.persona else None,
            "difficulty_id": state.difficulty.id if state.difficulty else None,
            "primary_motive_id": state.motivation.primary_motive_id if state.motivation else None,
            "secondary_motive_ids": state.motivation.secondary_motive_ids if state.motivation else [],
            "culture_version": get_config_loader().culture_version(),
            "citations": [
                citation.model_dump(exclude_none=True)
                for citation in chunks_to_citations(retrieved_chunks)
            ],
        }
        return GuidanceReport.model_validate(payload)

    @staticmethod
    def _as_text(value: GuidanceSectionValue) -> str:
        if isinstance(value, list):
            return "".join(GuidanceAgent.clean_section_text(item) for item in value if item.strip())
        return GuidanceAgent.clean_section_text(value)

    @staticmethod
    def _as_list(value: GuidanceSectionValue) -> list[str]:
        if isinstance(value, list):
            return [GuidanceAgent.clean_section_text(item) for item in value if item.strip()]
        text = GuidanceAgent.clean_section_text(value)
        return [text] if text else []

    @staticmethod
    def clean_section_text(value: str, *, trim: bool = True) -> str:
        """Keep guidance as plain text because the UI already supplies headings and lists."""
        text = str(value or "")
        text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*", "", text)
        text = re.sub(r"(?m)^[ \t]*[-+][ \t]+", "", text)
        text = text.replace("**", "").replace("__", "").replace("`", "").replace("*", "")
        return text.strip() if trim else text
