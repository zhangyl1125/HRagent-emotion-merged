from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
import logging
import re
from typing import Any

from backend.agents.guidance_agent import GuidanceAgent
from backend.config.settings import get_settings
from backend.exceptions.workflow_errors import SetupNotReadyError
from backend.repositories.report_repository import ReportRepository
from backend.services.retrieval_service import RetrievalService
from backend.services.cache_service import CacheService, cache_digest
from backend.services.session_service import SessionService
from backend.schemas.guidance import GuidanceReport
from backend.workflows.guidance_graph import GuidanceWorkflow


logger = logging.getLogger(__name__)


_GUIDANCE_SECTION_TITLES = {
    "purpose": "沟通目标",
    "opening_suggestion": "开场建议",
    "risk_preview": "风险提示",
    "response_strategies": "应对策略",
    "safer_phrases": "建议话术",
}
_SECTION_KEYS = tuple(_GUIDANCE_SECTION_TITLES.keys())
_SECTION_MARKER_RE = re.compile(r"\[SECTION:(purpose|opening_suggestion|risk_preview|response_strategies|safer_phrases)\]", re.IGNORECASE)
_MARKER_HOLDBACK_CHARS = 36


def _semantic_payload(value: Any) -> Any:
    """Return cache/prompt content without non-semantic runtime timestamps."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _semantic_payload(item)
            for key, item in value.items()
            if key not in {"created_at", "updated_at"}
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_payload(item) for item in value]
    return value


class GuidanceService:
    def __init__(self):
        self.session_service = SessionService()
        self.report_repo = ReportRepository()
        self.retrieval = RetrievalService()
        self.workflow = GuidanceWorkflow()
        self.agent = self.workflow.agent
        self.settings = get_settings()
        self.cache = CacheService(self.settings)

    async def generate(self, session_id: str) -> GuidanceReport:
        state, chunks = await asyncio.to_thread(self._prepare, session_id)
        cache_key = self._cache_key(state, chunks)
        cached = await asyncio.to_thread(self._cached_report, cache_key, session_id)
        if cached is not None:
            await asyncio.to_thread(self._save_report_state, state, cached)
            return cached

        report = await self.workflow.run(state, chunks)
        await asyncio.to_thread(self._save_report_state, state, report)
        await self.cache.set_json_async(cache_key, report.model_dump(mode="json"), self.settings.guidance_cache_ttl_seconds)
        return report

    async def stream_generate(self, session_id: str) -> AsyncIterator[dict]:
        try:
            state, chunks = await asyncio.to_thread(self._prepare, session_id)
            yield {"event": "start"}

            cache_key = self._cache_key(state, chunks)
            cached = await asyncio.to_thread(self._cached_report, cache_key, session_id)
            if cached is not None:
                saved_state = await asyncio.to_thread(self._save_report_state, state, cached)
                for key, title, text_value in self._stream_sections(cached):
                    yield {"event": "section_start", "key": key, "title": title}
                    for piece in self._visible_chunks(text_value):
                        yield {"event": "delta", "key": key, "text": piece}
                    yield {"event": "section_done", "key": key}
                yield {
                    "event": "done",
                    "report": cached.model_dump(mode="json"),
                    "state": saved_state.model_dump(mode="json"),
                    "cache_hit": True,
                }
                return

            sections = {key: "" for key in _SECTION_KEYS}
            current_key: str | None = None
            finished_keys: set[str] = set()
            buffer = ""

            async for raw_delta in self.agent.stream_text(state, chunks):
                buffer += raw_delta
                while True:
                    marker = _SECTION_MARKER_RE.search(buffer)
                    if current_key is None:
                        if marker is None:
                            buffer = buffer[-_MARKER_HOLDBACK_CHARS:] if len(buffer) > _MARKER_HOLDBACK_CHARS else buffer
                            break
                        current_key = marker.group(1).lower()
                        yield {"event": "section_start", "key": current_key, "title": _GUIDANCE_SECTION_TITLES[current_key]}
                        buffer = buffer[marker.end():].lstrip("\r\n")
                        continue

                    if marker is not None:
                        text = buffer[:marker.start()]
                        for piece in self._visible_chunks(self._clean_stream_fragment(text)):
                            sections[current_key] += piece
                            yield {"event": "delta", "key": current_key, "text": piece}
                        yield {"event": "section_done", "key": current_key}
                        finished_keys.add(current_key)
                        current_key = marker.group(1).lower()
                        yield {"event": "section_start", "key": current_key, "title": _GUIDANCE_SECTION_TITLES[current_key]}
                        buffer = buffer[marker.end():].lstrip("\r\n")
                        continue

                    if len(buffer) > _MARKER_HOLDBACK_CHARS:
                        text = buffer[:-_MARKER_HOLDBACK_CHARS]
                        buffer = buffer[-_MARKER_HOLDBACK_CHARS:]
                        for piece in self._visible_chunks(self._clean_stream_fragment(text)):
                            sections[current_key] += piece
                            yield {"event": "delta", "key": current_key, "text": piece}
                    break

            if current_key is None:
                raise ValueError("谈前指导流式输出未返回可识别的段落。")

            remaining = self._clean_stream_fragment(buffer, final=True)
            for piece in self._visible_chunks(remaining):
                sections[current_key] += piece
                yield {"event": "delta", "key": current_key, "text": piece}
            if current_key not in finished_keys:
                yield {"event": "section_done", "key": current_key}

            for key in _SECTION_KEYS:
                if key not in finished_keys and key != current_key and sections[key].strip():
                    yield {"event": "section_done", "key": key}

            report = self.agent.report_from_stream_sections(state, chunks, sections)
            saved_state = await asyncio.to_thread(self._save_report_state, state, report)
            await self.cache.set_json_async(cache_key, report.model_dump(mode="json"), self.settings.guidance_cache_ttl_seconds)
            yield {
                "event": "done",
                "report": report.model_dump(mode="json"),
                "state": saved_state.model_dump(mode="json"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Guidance stream failed for session_id=%s", session_id)
            yield {"event": "error", "message": str(exc) or type(exc).__name__}

    def _prepare(self, session_id: str):
        state = self.session_service.get_session(session_id)
        if not state.setup_ready:
            raise SetupNotReadyError("请先完成 profile / intent / persona / difficulty 设置。")
        context = {
            "intent": state.intent.config if state.intent else {},
            "profile": state.employee_profile,
            "persona": state.persona,
            "difficulty": state.difficulty,
            "personality": _semantic_payload(state.personality),
            "motivation": _semantic_payload(state.motivation),
            "emotion_state": _semantic_payload(state.emotion_state),
            "emotion_log": _semantic_payload(state.emotion_log),
            "run_mode": state.run_mode,
        }
        try:
            chunks = self.retrieval.retrieve("guidance", context, top_k=8)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Guidance retrieval failed for session_id=%s", session_id)
            chunks = []
            warning = f"谈前指导 KB 检索失败，已基于员工信息和本地配置继续生成：{exc}"
            if warning not in state.warnings:
                state.warnings.append(warning)
        if not chunks:
            warning = "谈前指导 KB 未检索到知识片段，已基于员工信息和本地配置继续生成。"
            if warning not in state.warnings:
                state.warnings.append(warning)
        return state, chunks

    def _save_report_state(self, state, report: GuidanceReport):
        self.report_repo.save_guidance(report)
        state.guidance_report_id = state.session_id
        state.stage = "guidance_ready"
        return self.session_service.save_session(state)

    def _cached_report(self, cache_key: str, session_id: str) -> GuidanceReport | None:
        payload = self.cache.get_json(cache_key)
        if not payload:
            return None
        report = GuidanceReport.model_validate(payload)
        return report.model_copy(update={"session_id": session_id})

    def _cache_key(self, state, chunks) -> str:
        digest = cache_digest({
            "task": "guidance",
            "profile": state.employee_profile.model_dump(mode="json") if state.employee_profile else None,
            "intent": state.intent.model_dump(mode="json") if state.intent else None,
            "persona": state.persona.model_dump(mode="json") if state.persona else None,
            "difficulty": state.difficulty.model_dump(mode="json") if state.difficulty else None,
            "personality": _semantic_payload(state.personality),
            "motivation": _semantic_payload(state.motivation),
            "emotion_state": _semantic_payload(state.emotion_state),
            "emotion_log": _semantic_payload(state.emotion_log),
            "run_mode": state.run_mode,
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "model": self.settings.guidance_model,
            "kb_index_version": self.settings.kb_index_version,
        })
        return self.cache.namespaced("guidance", digest)

    @staticmethod
    def _stream_sections(report: GuidanceReport) -> list[tuple[str, str, str]]:
        return [
            ("purpose", _GUIDANCE_SECTION_TITLES["purpose"], GuidanceService._format_text(report.purpose)),
            ("opening_suggestion", _GUIDANCE_SECTION_TITLES["opening_suggestion"], GuidanceService._format_text(report.opening_suggestion)),
            ("risk_preview", _GUIDANCE_SECTION_TITLES["risk_preview"], GuidanceService._format_list(report.risk_preview)),
            ("response_strategies", _GUIDANCE_SECTION_TITLES["response_strategies"], GuidanceService._format_list(report.response_strategies)),
            ("safer_phrases", _GUIDANCE_SECTION_TITLES["safer_phrases"], GuidanceService._format_list(report.safer_phrases)),
        ]

    @staticmethod
    def _format_text(value: str) -> str:
        text = str(value or "").strip()
        return f"{text or '—'}\n"

    @staticmethod
    def _format_list(values: list[str]) -> str:
        items = [str(item).strip() for item in values if str(item).strip()]
        if not items:
            return "—\n"
        return "".join(f"- {item}\n" for item in items)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 80) -> list[str]:
        if not text:
            return []
        return [text[index:index + chunk_size] for index in range(0, len(text), chunk_size)]

    @staticmethod
    def _clean_stream_fragment(text: str, final: bool = False) -> str:
        cleaned = text.replace("\r", "")
        if final:
            cleaned = cleaned.replace("[END]", "")
            cleaned = cleaned.strip("`\n ")
        return cleaned

    @staticmethod
    def _visible_chunks(text: str) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        current = ""
        for char in text:
            current += char
            if char in "，。！？；、\n" or len(current) >= 24:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
        return chunks

    def get(self, session_id: str) -> GuidanceReport:
        return self.report_repo.get_guidance(session_id)


async def _debug_guidance_service_stream_main() -> None:
    """Manual guidance SSE stream test (no DB required).

    Exercises GuidanceService.stream_generate end-to-end: agent.stream_text +
    [SECTION:*] marker parsing + holdback + SSE event emission, with the DB
    access points (_prepare / _save_report_state) and the LLM stubbed out.

    Usage inside the backend container:
      python -m backend.services.guidance_service
    """
    import asyncio
    import os

    from backend.schemas.intent import IntentConfig, IntentResult
    from backend.schemas.profile import EmployeeProfile, FactItem
    from backend.schemas.state import SessionState
    from backend.services.langchain_llm_service import LangChainLLMService

    mode = os.getenv("GUIDANCE_SERVICE_STREAM_TEST", "fake").strip().lower()
    state = SessionState(
        session_id="guidance-service-stream-debug",
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

    fake_stream = (
        "[SECTION:purpose]\n本次沟通旨在客观对齐绩效事实并明确改进方向。\n"
        "[SECTION:opening_suggestion]\n先说明本次沟通目的与事实范围，再邀请员工补充视角。\n"
        "[SECTION:risk_preview]\n- 避免人格化、绝对化评价\n- 不承诺未经审批的资源\n- 出现情绪先承接再核实\n"
        "[SECTION:response_strategies]\n- 按事实-影响-期望-支持组织表达\n- 给出可观察标准与截止时间\n- 先确认理解再讨论支持\n"
        "[SECTION:safer_phrases]\n- 我们先对齐共同看到的事实。\n- 这是需要一起解决的交付差距。\n[END]"
    )

    if mode == "fake":
        # 故意把 SECTION 标记切成 7 字符碎片，验证 marker holdback 边界处理
        pieces = [fake_stream[i:i + 7] for i in range(0, len(fake_stream), 7)]

        async def fake_astream_text(self, *, prompt, task_name=None, model=None, temperature=None, max_tokens=None):
            for piece in pieces:
                await asyncio.sleep(0.01)
                yield piece

        LangChainLLMService.__init__ = lambda self: None
        LangChainLLMService.astream_text = fake_astream_text
        GuidanceAgent._build_stream_prompt = staticmethod(lambda state, chunks: "")

    # 绕过 DB：构造未初始化实例，仅注入 agent 并桩掉持久化访问点
    service = GuidanceService.__new__(GuidanceService)
    service.agent = GuidanceAgent()
    service._prepare = lambda session_id: (state, [])
    service._save_report_state = lambda st, report: st

    print(f"guidance_service_stream_test_mode={mode}")
    events: list[dict] = []
    async for event in service.stream_generate(state.session_id):
        events.append(event)
        etype = event.get("event")
        if etype in {"start", "section_start", "section_done", "done", "error"}:
            print(f"event={etype} key={event.get('key')} title={event.get('title')}")

    types = [event["event"] for event in events]
    errors = [event for event in events if event["event"] == "error"]
    assert not errors, f"流式输出报错: {errors}"
    starts = [event["key"] for event in events if event["event"] == "section_start"]
    expected = ["purpose", "opening_suggestion", "risk_preview", "response_strategies", "safer_phrases"]
    assert starts == expected, f"段落顺序/数量异常: {starts}"
    assert "done" in types, "缺少 done 事件"

    done_event = next(event for event in events if event["event"] == "done")
    report = done_event["report"]
    for key in ("purpose", "opening_suggestion"):
        assert str(report.get(key) or "").strip(), f"report.{key} 为空"
    for key in ("risk_preview", "response_strategies", "safer_phrases"):
        assert report.get(key), f"report.{key} 列表为空"
    delta_count = sum(1 for event in events if event["event"] == "delta")
    print(f"events={len(types)} deltas={delta_count}")
    print("guidance service stream OK; report sections all non-empty")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_debug_guidance_service_stream_main())
