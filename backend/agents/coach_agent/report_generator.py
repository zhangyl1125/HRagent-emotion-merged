from __future__ import annotations

import asyncio
import json
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

from backend.business_config.loader import get_config_loader
from backend.rag.citation import chunks_to_citations
from backend.schemas.coach import CoachReport
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.task import BetterPhrase, CoachTaskResult, RiskItem
from backend.services.langchain_llm_service import LangChainLLMService


def _prompt_payload(value: Any) -> Any:
    """Serialize dynamic report context without volatile timestamps."""
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


CoachReportSectionKey = Literal[
    "summary_score",
    "risks",
    "strengths_improvements",
    "better_phrases",
    "next_step",
]
CoachReportSectionValue = BaseModel

COACH_REPORT_SECTION_KEYS: tuple[CoachReportSectionKey, ...] = (
    "summary_score",
    "risks",
    "strengths_improvements",
    "better_phrases",
    "next_step",
)
COACH_REPORT_SECTION_TITLES: dict[CoachReportSectionKey, str] = {
    "summary_score": "综合结论与评分",
    "risks": "风险提示",
    "strengths_improvements": "优势与待改进",
    "better_phrases": "建议话术",
    "next_step": "下一步建议",
}
_CULTURE_NARRATIVE_SECTIONS: frozenset[CoachReportSectionKey] = frozenset(
    {"strengths_improvements", "better_phrases", "next_step"}
)
_SECTION_REQUIREMENTS: dict[CoachReportSectionKey, str] = {
    "summary_score": "生成 overall_score 和 summary。overall_score 为 0-100 的整数或 null；summary 要概括经理本轮表现、主要风险和最重要的改进方向。",
    "risks": "生成 top_risks。每条风险必须来自 task_results 中的风险、证据或 retrieved_chunks，不要编造事实。",
    "strengths_improvements": "生成 key_strengths 与 key_improvements。表现判断只基于 manager/employee 原话证据和 Coach 子任务结果；相关时可用价值观补充具体改进方向，但不要新增栏目。",
    "better_phrases": "生成 better_phrases。每条给出 original、suggestion、reason；original 只能来自 manager 原话或为空；相关时可把价值观转成自然、可执行的表达，不要写口号。",
    "next_step": "生成 next_step。给出管理者下一轮沟通最应该做的一步，简洁、可执行、不过度承诺；相关时可体现价值观要求的具体管理行为。",
}


class CoachSummaryScoreSection(BaseModel):
    overall_score: int | None = Field(default=None, ge=0, le=100)
    summary: str = Field(min_length=1)


class CoachRisksSection(BaseModel):
    top_risks: list[RiskItem] = Field(default_factory=list)


class CoachStrengthsImprovementsSection(BaseModel):
    key_strengths: list[str] = Field(default_factory=list)
    key_improvements: list[str] = Field(default_factory=list)


class CoachBetterPhrasesSection(BaseModel):
    better_phrases: list[BetterPhrase] = Field(default_factory=list)


class CoachNextStepSection(BaseModel):
    next_step: str = Field(min_length=1)


_SECTION_SCHEMAS: dict[CoachReportSectionKey, type[BaseModel]] = {
    "summary_score": CoachSummaryScoreSection,
    "risks": CoachRisksSection,
    "strengths_improvements": CoachStrengthsImprovementsSection,
    "better_phrases": CoachBetterPhrasesSection,
    "next_step": CoachNextStepSection,
}
_SECTION_OUTPUT_HINTS: dict[CoachReportSectionKey, str] = {
    "summary_score": '{"overall_score": 0, "summary": "string"}',
    "risks": '{"top_risks": [{"rule_id": null, "severity": "low", "category": "沟通风险", "matched_text": null, "explanation": "string", "safer_phrase": null}]}',
    "strengths_improvements": '{"key_strengths": ["string"], "key_improvements": ["string"]}',
    "better_phrases": '{"better_phrases": [{"original": "string|null", "suggestion": "string", "reason": "string"}]}',
    "next_step": '{"next_step": "string"}',
}


class ReportGenerator:
    async def generate(
        self,
        session_id: str,
        task_results: list[CoachTaskResult],
        retrieved_chunks: list[RetrievedChunk] | None = None,
        profile: dict | None = None,
        intent: dict | None = None,
        personality: dict | None = None,
        motivation: dict | None = None,
        emotion_state: dict | None = None,
        conversation: list[dict] | None = None,
        emotion_log: list[dict] | None = None,
        **_ignored: Any,
    ) -> CoachReport:
        sections = await self.generate_sections(
            session_id,
            task_results,
            retrieved_chunks=retrieved_chunks,
            profile=profile,
            intent=intent,
            personality=personality,
            motivation=motivation,
            emotion_state=emotion_state,
            conversation=conversation,
            emotion_log=emotion_log,
        )
        return self.report_from_sections(
            session_id,
            task_results,
            sections,
            retrieved_chunks=retrieved_chunks,
        )

    async def generate_sections(
        self,
        session_id: str,
        task_results: list[CoachTaskResult],
        **context: Any,
    ) -> dict[CoachReportSectionKey, BaseModel]:
        values = await asyncio.gather(
            *(self.generate_section(session_id, task_results, key, **context) for key in COACH_REPORT_SECTION_KEYS)
        )
        return dict(zip(COACH_REPORT_SECTION_KEYS, values, strict=True))

    async def generate_section(
        self,
        session_id: str,
        task_results: list[CoachTaskResult],
        section_key: CoachReportSectionKey,
        **context: Any,
    ) -> BaseModel:
        if not task_results:
            raise ValueError("task_results are required for Coach report section generation")
        chunks: list[str] = []
        async for delta in self.stream_section_output(session_id, task_results, section_key, **context):
            chunks.append(delta)
        output = self._parse_section_output(section_key, "".join(chunks).strip())
        self._validate_section(section_key, output)
        return output

    async def stream_section_output(
        self,
        session_id: str,
        task_results: list[CoachTaskResult],
        section_key: CoachReportSectionKey,
        **context: Any,
    ):
        if not task_results:
            raise ValueError("task_results are required for Coach report section generation")
        prompt = self._build_section_prompt(session_id, task_results, section_key, **context)
        async for delta in LangChainLLMService().astream_text(prompt=prompt, task_name="coach_report"):
            if delta:
                yield delta

    @staticmethod
    def _build_section_prompt(
        session_id: str,
        task_results: list[CoachTaskResult],
        section_key: CoachReportSectionKey,
        retrieved_chunks: list[RetrievedChunk] | None = None,
        profile: dict | None = None,
        intent: dict | None = None,
        personality: dict | None = None,
        motivation: dict | None = None,
        emotion_state: dict | None = None,
        conversation: list[dict] | None = None,
        emotion_log: list[dict] | None = None,
        **_ignored: Any,
    ) -> str:
        all_chunks = list(retrieved_chunks or [])
        company_values = get_config_loader().company_values()
        culture_allowed = bool(
            company_values.get("enabled")
            and company_values.get("values")
            and section_key in _CULTURE_NARRATIVE_SECTIONS
        )
        general_chunks = [chunk for chunk in all_chunks if chunk.scope != "culture"]
        culture_chunks = [chunk for chunk in all_chunks if culture_allowed and chunk.scope == "culture"]
        context = {
            "session_id": session_id,
            "profile": profile or {},
            "intent": intent or {},
            "personality": personality or {},
            "motivation": motivation or {},
            "emotion_state": emotion_state or {},
            "emotion_log": emotion_log or [],
            "conversation": conversation or [],
            "task_results": [result.model_dump(exclude_none=True) for result in task_results],
            "retrieved_chunks": [chunk.model_dump(exclude_none=True) for chunk in general_chunks],
            "company_values": company_values if culture_allowed else {},
            "culture_chunks": [chunk.model_dump(exclude_none=True) for chunk in culture_chunks],
        }
        return (
            "你是绩效反馈预演 Coach 的最终复盘报告生成器。\n"
            "这次只生成 CoachReport 的一个 section，不要输出其它 section。\n"
            "评价和风险必须来自 task_results、conversation 或 retrieved_chunks；建议和话术还可使用 company_values 与 culture_chunks；不要编造事实。\n"
            "Coach 评分和 evidence 只能基于 manager/employee 原话，不得把 system 记录作为经理表现证据。\n"
            "overall_score 只能根据 task_results 生成，company_values、文化资料、人格、诉求和情绪状态绝对不能改变评分。\n"
            "人格、诉求、VAD 和情绪日志只可在有日志依据时解释员工反应、变化触发原因和改进建议，不得作心理诊断。\n"
            "company_values 和 culture_chunks 仅可用于优势与待改进、建议话术、下一步建议中的补充建议。\n"
            "价值观资料是规范参考，不是经理表现证据；判断经理体现或违背价值观时必须有 manager 原话支持。\n"
            "仅使用与当前场景直接相关的价值观并转成具体管理行为，不新增价值观栏目，不堆砌口号；资料为空时不得编造。\n"
            "不要输出 Markdown，不要解释 schema，只输出 JSON object。\n"
            f"session_id={session_id}\n"
            f"section_key={section_key}\n"
            f"section_title={COACH_REPORT_SECTION_TITLES[section_key]}\n"
            f"section_requirement={_SECTION_REQUIREMENTS[section_key]}\n"
            f"必须只输出 JSON object，schema={_SECTION_OUTPUT_HINTS[section_key]}\n"
            f"context={json.dumps(context, ensure_ascii=False, default=str)}"
        )

    @staticmethod
    def _parse_section_output(section_key: CoachReportSectionKey, raw_output: str) -> BaseModel:
        return _SECTION_SCHEMAS[section_key].model_validate(ReportGenerator._extract_json_object(raw_output))

    @staticmethod
    def _extract_json_object(raw_output: str) -> dict[str, object]:
        text = raw_output.strip()
        if not text:
            raise ValueError("Coach report section returned empty output.")
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Coach report section did not return a JSON object.") from exc
            data = json.loads(text[start : end + 1])
        if not isinstance(data, dict):
            raise ValueError("Coach report section JSON must be an object.")
        return data

    @staticmethod
    def _validate_section(section_key: CoachReportSectionKey, output: BaseModel) -> None:
        data = output.model_dump(exclude_none=True)
        if section_key == "summary_score" and not str(data.get("summary") or "").strip():
            raise ValueError("summary_score section returned empty summary")
        if section_key == "next_step" and not str(data.get("next_step") or "").strip():
            raise ValueError("next_step section returned empty next_step")

    @staticmethod
    def report_from_sections(
        session_id: str,
        task_results: list[CoachTaskResult],
        sections: Mapping[CoachReportSectionKey, BaseModel],
        retrieved_chunks: list[RetrievedChunk] | None = None,
    ) -> CoachReport:
        summary_score = sections["summary_score"]
        risks = sections["risks"]
        strengths_improvements = sections["strengths_improvements"]
        better_phrases = sections["better_phrases"]
        next_step = sections["next_step"]
        return CoachReport.model_validate(
            {
                "session_id": session_id,
                "culture_version": get_config_loader().culture_version(),
                "status": "success",
                "overall_score": getattr(summary_score, "overall_score", None),
                "summary": getattr(summary_score, "summary", ""),
                "top_risks": getattr(risks, "top_risks", []),
                "key_strengths": getattr(strengths_improvements, "key_strengths", []),
                "key_improvements": getattr(strengths_improvements, "key_improvements", []),
                "better_phrases": getattr(better_phrases, "better_phrases", []),
                "task_results": task_results,
                "citations": [
                    citation.model_dump(exclude_none=True)
                    for citation in chunks_to_citations(retrieved_chunks or [])
                ],
                "next_step": getattr(next_step, "next_step", None),
            }
        )

    @staticmethod
    def section_display_text(section_key: CoachReportSectionKey, value: BaseModel) -> str:
        data = value.model_dump(exclude_none=True)
        if section_key == "summary_score":
            score = data.get("overall_score")
            prefix = f"评分：{score}/100\n" if isinstance(score, int) else "评分：暂无\n"
            return f"{prefix}{str(data.get('summary') or '').strip()}\n"
        if section_key == "risks":
            return ReportGenerator._format_risks(data.get("top_risks") or [])
        if section_key == "strengths_improvements":
            return ReportGenerator._format_list("优势", data.get("key_strengths") or []) + ReportGenerator._format_list("待改进", data.get("key_improvements") or [])
        if section_key == "better_phrases":
            return ReportGenerator._format_phrases(data.get("better_phrases") or [])
        if section_key == "next_step":
            return f"{str(data.get('next_step') or '').strip()}\n"
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _format_list(title: str, values: list[object]) -> str:
        items = [str(item).strip() for item in values if str(item).strip()]
        return f"{title}：\n" + "".join(f"- {item}\n" for item in items) if items else f"{title}：暂无\n"

    @staticmethod
    def _format_risks(values: list[object]) -> str:
        if not values:
            return "暂无明显风险\n"
        lines: list[str] = []
        for item in values:
            data = item if isinstance(item, dict) else item.model_dump(exclude_none=True)
            category = str(data.get("category") or "沟通风险").strip()
            explanation = str(data.get("explanation") or data).strip()
            safer_phrase = str(data.get("safer_phrase") or "").strip()
            lines.append(f"- {category}：{explanation}{f' 建议：{safer_phrase}' if safer_phrase else ''}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_phrases(values: list[object]) -> str:
        if not values:
            return "暂无建议话术\n"
        lines: list[str] = []
        for item in values:
            data = item if isinstance(item, dict) else item.model_dump(exclude_none=True)
            original = str(data.get("original") or "").strip()
            suggestion = str(data.get("suggestion") or data).strip()
            reason = str(data.get("reason") or "").strip()
            lines.append(f"- {f'原表达：{original}；' if original else ''}建议：{suggestion}{f'；原因：{reason}' if reason else ''}")
        return "\n".join(lines) + "\n"
