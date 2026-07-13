from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
import re

from backend.exceptions.llm_errors import LLMError
from backend.schemas.state import SessionState
from backend.services.langchain_llm_service import LangChainLLMService
from backend.services.prompt_service import PromptService
from backend.services.dynamic_persona_builder import DynamicPersonaBuilder


logger = logging.getLogger(__name__)


class EmployeeAgent:
    """Employee role-play agent.

    It uses profile, intent, persona, difficulty and runtime rehearsal context held in SessionState.
    It does not retrieve policy/methodology KB and does not write session state.
    """

    _LEADING_REPLY_BUFFER_CHARS = 4
    _STREAM_HOLDBACK_CHARS = 1
    _VISIBLE_CHUNK_CHARS = 4
    _FIRST_DELTA_WARMUP_SECONDS = 0.8
    _STREAM_WARMUP_TEXT = "嗯，"

    async def reply(self, state: SessionState, latest_manager_message: str) -> str:
        try:
            return await asyncio.wait_for(self._reply_with_llm(state, latest_manager_message), timeout=35)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Employee LLM failed for session_id=%s; using local fallback: %s", state.session_id, exc)
            return self._fallback_reply(state, latest_manager_message)

    async def stream_reply(self, state: SessionState, latest_manager_message: str) -> AsyncIterator[tuple[str, str]]:
        """Stream ``(channel, text)`` pairs.

        ``channel`` is ``"reply"`` for the visible employee answer. Chain-of-thought
        deltas are not requested or forwarded.
        """
        try:
            async with asyncio.timeout(60):
                prompt = self._build_reply_prompt(state, latest_manager_message)
                prefixes = self._reply_prefixes(state)
                emitted = False
                started = False
                pending = ""
                model_started = False
                warmup_emitted = False
                stream_queue: asyncio.Queue[tuple[str, tuple[str, str] | Exception | None]] = asyncio.Queue()

                async def produce_model_deltas() -> None:
                    try:
                        async for channel, text in LangChainLLMService().astream_reasoning_text(
                            prompt=prompt, task_name="employee", enable_thinking=False
                        ):
                            await stream_queue.put(("delta", (channel, text)))
                    except Exception as model_exc:  # noqa: BLE001
                        await stream_queue.put(("error", model_exc))
                    finally:
                        await stream_queue.put(("done", None))

                producer = asyncio.create_task(produce_model_deltas())
                try:
                    while True:
                        try:
                            if not model_started and not warmup_emitted:
                                kind, value = await asyncio.wait_for(stream_queue.get(), timeout=self._FIRST_DELTA_WARMUP_SECONDS)
                            else:
                                kind, value = await stream_queue.get()
                        except asyncio.TimeoutError:
                            warmup_emitted = True
                            emitted = True
                            async for piece in self._visible_stream_chunks(self._STREAM_WARMUP_TEXT):
                                yield "reply", piece
                            continue

                        if kind == "done":
                            break
                        if kind == "error":
                            raise value if isinstance(value, Exception) else LLMError("Employee stream failed.")

                        channel, text = value if isinstance(value, tuple) else ("content", "")
                        text = str(text or "")
                        if not text:
                            continue
                        model_started = True
                        if channel == "thinking":
                            continue
                        pending += text
                        if not started:
                            cleaned = self._strip_leading_reply_artifacts(pending, prefixes)
                            if warmup_emitted:
                                cleaned = self._strip_duplicate_warmup(cleaned)
                            if not cleaned:
                                pending = ""
                                continue
                            if cleaned == pending.lstrip() and not self._has_stable_reply_start(cleaned):
                                pending = cleaned
                                continue
                            pending = cleaned
                            started = True
                        if len(pending) <= self._STREAM_HOLDBACK_CHARS:
                            continue
                        emitted = True
                        emit_text, pending = pending[:-self._STREAM_HOLDBACK_CHARS], pending[-self._STREAM_HOLDBACK_CHARS:]
                        async for piece in self._visible_stream_chunks(emit_text):
                            yield "reply", piece
                finally:
                    if not producer.done():
                        producer.cancel()

                if not started:
                    pending = self._strip_leading_reply_artifacts(pending, prefixes)
                    if warmup_emitted:
                        pending = self._strip_duplicate_warmup(pending)
                pending = self._strip_trailing_reply_artifacts(pending)
                if pending:
                    emitted = True
                    async for piece in self._visible_stream_chunks(pending):
                        yield "reply", piece
                if not emitted:
                    raise LLMError("Employee Agent returned empty streamed reply.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Employee stream failed for session_id=%s; using local fallback: %s", state.session_id, exc)
            async for piece in self._visible_stream_chunks(self._fallback_reply(state, latest_manager_message)):
                yield "reply", piece

    @staticmethod
    async def _visible_stream_chunks(text: str) -> AsyncIterator[str]:
        chunk = ""
        for char in text:
            chunk += char
            if char in "，。！？；、\n" or len(chunk) >= EmployeeAgent._VISIBLE_CHUNK_CHARS:
                yield chunk
                chunk = ""
                await asyncio.sleep(0.018)
        if chunk:
            yield chunk


    @classmethod
    def _clean_reply_text(cls, text: str, prefixes: list[str] | None = None) -> str:
        cleaned = cls._strip_leading_reply_artifacts(text, prefixes)
        cleaned = cls._strip_trailing_reply_artifacts(cleaned)
        pairs = [("“", "”"), ('"', '"'), ("'", "'"), ("「", "」"), ("『", "』")]
        changed = True
        while changed and len(cleaned) >= 2:
            changed = False
            for left, right in pairs:
                if cleaned.startswith(left) and cleaned.endswith(right):
                    cleaned = cleaned[1:-1].strip()
                    changed = True
        return cleaned

    @staticmethod
    def _strip_leading_reply_artifacts(text: str, prefixes: list[str] | None = None) -> str:
        cleaned = text.lstrip()
        cleaned = re.sub(r"^(?:员工|employee|assistant|回复|答复)[：:]\s*", "", cleaned, flags=re.IGNORECASE)
        for prefix in prefixes or []:
            safe_prefix = re.escape(prefix.strip())
            if safe_prefix:
                cleaned = re.sub(rf"^{safe_prefix}[：:]\s*", "", cleaned)
        cleaned = re.sub(r"^(?:[\u4e00-\u9fff]{1,3}经理|经理)(?:[，,、：:\s]+|(?=[\u4e00-\u9fff])|$)", "", cleaned)
        return cleaned.lstrip(" \t\r\n\"'“”‘’「」『』")

    @classmethod
    def _has_stable_reply_start(cls, text: str) -> bool:
        stripped = text.lstrip()
        return len(stripped) >= cls._LEADING_REPLY_BUFFER_CHARS or any(char in stripped for char in "，,。！？!?；;：:\n")

    @staticmethod
    def _strip_trailing_reply_artifacts(text: str) -> str:
        return text.rstrip().rstrip("\"'“”‘’「」『』").rstrip()

    @staticmethod
    def _strip_duplicate_warmup(text: str) -> str:
        return re.sub(r"^(?:嗯+[，,。…\.\s]*)+", "", text).lstrip()

    @staticmethod
    def _filter_thinking_chinese(text: str) -> str:
        """Keep only Chinese reasoning content; drop English, digits, markdown and stray symbols."""
        # Remove ASCII letters, digits and markdown/structural symbols entirely.
        cleaned = re.sub(r"[A-Za-z0-9]+", "", text)
        cleaned = re.sub(r"[*#/\\\[\]{}<>|_`~^=+\-()$%&@\"']", "", cleaned)
        # Drop ASCII sentence punctuation, keeping only Chinese punctuation.
        cleaned = re.sub(r"[.,!?;:]", "", cleaned)
        # Collapse runs of Chinese punctuation that became adjacent after removals.
        cleaned = re.sub(r"([，。！？；：、…]){2,}", r"\1", cleaned)
        # Strip leading punctuation/whitespace left behind.
        cleaned = re.sub(r"^[\s，。！？；：、…]+", "", cleaned)
        # Collapse excess whitespace.
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        # If nothing Chinese remains, emit nothing.
        if not re.search(r"[\u4e00-\u9fff]", cleaned):
            return ""
        return cleaned

    async def _reply_with_llm(self, state: SessionState, latest_manager_message: str) -> str:
        prompt = self._build_reply_prompt(state, latest_manager_message)
        reply = await LangChainLLMService().ainvoke_text(
            prompt=prompt,
            task_name="employee",
        )
        cleaned = self._clean_reply_text(reply, self._reply_prefixes(state))
        if not cleaned:
            raise LLMError("Employee Agent returned empty reply.")
        return cleaned


    @staticmethod
    def _fallback_reply(state: SessionState, latest_manager_message: str) -> str:
        profile = state.employee_profile
        intent_name = state.intent.config.name if state.intent and state.intent.config else "这次反馈"
        topic = profile.conversation_topic if profile and profile.conversation_topic else intent_name
        first_fact = ""
        if profile and profile.facts:
            first_fact = profile.facts[0].description
        if not first_fact and profile and profile.key_goals:
            first_fact = profile.key_goals[0]

        attitude = state.emotion_state.current_attitude.value if state.emotion_state else "calm_neutral"
        persona_name = state.persona.name if state.persona else ""

        if attitude == "silent_withdrawn" or "沉默" in persona_name:
            return "嗯……我先消化一下。现在让我马上表态，我其实有点不知道该怎么说。"
        if attitude == "frustrated_pushback":
            return "说实话，这样听起来我会有点委屈。不是说我不接受反馈，但我需要知道到底是哪件事让你这么判断。"
        if attitude == "defensive_resistant" or "防御" in persona_name:
            return "我不太能直接接受这个结论。" + (f"如果是说{first_fact}，那我也想把当时的背景讲清楚。" if first_fact else "能不能先说具体是哪几个点？")
        if attitude == "reflective_softening":
            return "如果是具体案例，我可以一起看。只是我也希望你把当时的背景和资源限制一起放进去考虑。"
        if attitude == "cooperative_constructive" or "谈判" in persona_name:
            return "这样说会清楚一些。那我想确认一下，后面具体看哪些指标、需要什么支持，我们能不能先对齐？"
        if "情绪" in persona_name:
            return "我听到了，但心里还是有点难受。这个反馈是不是意味着你们已经不太认可我后面的机会了？"
        return f"你这个点我听到了，但我想先确认一下具体依据。关于{topic}，我不太希望只凭一个笼统印象来判断。"

    @staticmethod
    def _reply_prefixes(state: SessionState) -> list[str]:
        profile = state.employee_profile
        if not profile:
            return []
        values = [getattr(profile, "employee_alias", None), getattr(profile, "name", None)]
        return [str(value).strip() for value in values if str(value or "").strip()]

    @staticmethod
    def _build_reply_prompt(state: SessionState, latest_manager_message: str) -> str:
        return PromptService().render(
            "employee/reply.jinja2",
            profile=state.employee_profile.model_dump(exclude_none=True) if state.employee_profile else {},
            intent=state.intent.model_dump(exclude_none=True) if state.intent else {},
            persona=state.persona.model_dump(exclude_none=True) if state.persona else {},
            difficulty=state.difficulty.model_dump(exclude_none=True) if state.difficulty else {},
            personality=state.personality.model_dump(exclude_none=True) if state.personality else {},
            motivation=state.motivation.model_dump(mode="json", exclude_none=True) if state.motivation else {},
            emotion_state=state.emotion_state.model_dump(mode="json", exclude_none=True),
            rehearsal_context=state.rehearsal_context.model_dump(mode="json", exclude_none=True),
            emotion_prompt=DynamicPersonaBuilder().build(state.emotion_state),
            conversation=json.dumps(
                [turn.model_dump(mode="json", exclude_none=True) for turn in state.conversation],
                ensure_ascii=False,
                indent=2,
            ),
            latest_manager_message=latest_manager_message,
        )

async def _debug_stream_main() -> None:
    """Manual backend stream test.

    Usage inside the backend container:
      python -m backend.agents.employee_agent
      EMPLOYEE_AGENT_STREAM_TEST=llm python -m backend.agents.employee_agent
    """
    import os
    import time

    from backend.schemas.conversation import ConversationTurn
    from backend.schemas.difficulty import DifficultyConfig
    from backend.schemas.intent import IntentConfig, IntentResult
    from backend.schemas.persona import PersonaConfig
    from backend.schemas.profile import EmployeeProfile, FactItem

    mode = os.getenv("EMPLOYEE_AGENT_STREAM_TEST", "fake").strip().lower()
    latest_message = os.getenv("EMPLOYEE_AGENT_TEST_MESSAGE", "你认为目前的绩效状态怎么样？")
    state = SessionState(
        session_id="employee-agent-stream-debug",
        stage="guidance_ready",
        setup_ready=True,
        guidance_report_id="employee-agent-stream-debug",
        employee_profile=EmployeeProfile(
            employee_alias="Ms. 宁春燕/NING Chunyan",
            role="HSE Senior Manager",
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
        persona=PersonaConfig(
            id="data_challenge",
            name="数据逻辑追问型",
            profile_prompt="员工会追问事实依据、数据口径和判断标准。",
        ),
        difficulty=DifficultyConfig(
            id="high",
            name="高压",
            description="员工会多轮追问依据，但仍保持业务场景真实边界。",
        ),
        conversation=[ConversationTurn(turn_index=1, speaker="manager", text=latest_message)],
    )

    if mode == "fake":
        def fake_init(self):
            self.settings = None

        async def fake_astream_text(self, *, prompt, task_name=None, model=None, temperature=None, max_tokens=None):
            for piece in ["嗯？，", "我想先", "确认一下，", "这个判断", "具体依据", "是什么？"]:
                await asyncio.sleep(0.2)
                yield piece

        async def fake_astream_reasoning_text(self, *, prompt, task_name=None, model=None, temperature=None, max_tokens=None, enable_thinking=True):
            for piece in ["先想清楚", "员工的顾虑，", "再决定", "怎么回应。"]:
                await asyncio.sleep(0.2)
                yield "thinking", piece
            for piece in ["嗯？，", "我想先", "确认一下，", "这个判断", "具体依据", "是什么？"]:
                await asyncio.sleep(0.2)
                yield "content", piece

        LangChainLLMService.__init__ = fake_init
        LangChainLLMService.astream_text = fake_astream_text
        LangChainLLMService.astream_reasoning_text = fake_astream_reasoning_text
        EmployeeAgent._build_reply_prompt = staticmethod(lambda state, latest_manager_message: latest_manager_message)

    print(f"stream_test_mode={mode}")
    start = time.monotonic()
    chunks: list[str] = []
    async for channel, chunk in EmployeeAgent().stream_reply(state, latest_message):
        elapsed = time.monotonic() - start
        if channel == "reply":
            chunks.append(chunk)
        print(f"{elapsed:0.3f}s channel={channel} chunk={chunk!r}", flush=True)
    print(f"done total={time.monotonic() - start:0.3f}s text={''.join(chunks)!r}")


if __name__ == "__main__":
    asyncio.run(_debug_stream_main())

