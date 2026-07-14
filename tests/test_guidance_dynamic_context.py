import json

from backend.agents.guidance_agent import GUIDANCE_SECTION_KEYS, GuidanceAgent
from backend.schemas.emotion import ConversationEmotionLog, EmotionState, EmployeeAttitude
from backend.schemas.intent import IntentConfig, IntentResult
from backend.schemas.profile import EmployeeProfile
from backend.schemas.simulation import BigFivePersonality, MotivationState, VADVector
from backend.schemas.state import SessionState


def _dynamic_state() -> SessionState:
    motivation = MotivationState(
        primary_motive_id="security",
        secondary_motive_ids=["recognition", "affiliation"],
        primary_score=38,
        secondary_scores={"recognition": 45, "affiliation": 52},
    )
    return SessionState(
        session_id="dynamic-guidance",
        setup_ready=True,
        personality=BigFivePersonality(
            openness=42,
            conscientiousness=72,
            extraversion=48,
            agreeableness=58,
            neuroticism=69,
        ),
        motivation=motivation,
        emotion_state=EmotionState(
            current_vad=VADVector(valence=-0.42, arousal=0.56, dominance=-0.31),
        ),
        emotion_log=[
            ConversationEmotionLog(
                turn_index=1,
                hrbp_text="我们先对齐事实。",
                employee_attitude_before=EmployeeAttitude.GUARDED_HESITANT,
                employee_attitude_after=EmployeeAttitude.DEFENSIVE_RESISTANT,
                intensity=66,
                transition_reason="压力上升",
                vad_before=VADVector(valence=-0.12, arousal=0.21, dominance=-0.05),
                vad_after=VADVector(valence=-0.42, arousal=0.56, dominance=-0.31),
                motivation_before=motivation,
                motivation_after=motivation.model_copy(update={"primary_score": 38}),
            )
        ],
        intent=IntentResult(
            intent_id="improvement",
            config=IntentConfig(
                id="improvement",
                name="改进型反馈",
                business_goal="对齐绩效差距并形成改进行动。",
                expected_outcome="员工理解事实与下一步行动。",
            ),
        ),
    )


def test_guidance_prompt_includes_dynamic_personality_motivation_and_vad_log():
    prompt = GuidanceAgent._build_section_prompt(_dynamic_state(), [], "purpose")

    assert '"primary_motive_id": "security"' in prompt
    assert '"current_vad"' in prompt
    assert '"vad_before"' in prompt
    assert '"vad_after"' in prompt
    assert '"updated_at"' not in prompt
    assert "不得作为事实定性或心理诊断" in prompt
    assert '"persona":' not in prompt
    assert '"difficulty":' not in prompt


def test_guidance_prompt_uses_existing_profile_text_as_supplemental_info():
    state = _dynamic_state()
    state.employee_profile = EmployeeProfile(
        employee_alias="员工A",
        source_profile_text="上传资料中的补充事实与历史反馈。",
    )

    prompt = GuidanceAgent._build_section_prompt(state, [], "opening_suggestion")

    assert '"supplemental_info": "上传资料中的补充事实与历史反馈。"' in prompt


def _guidance_context(state: SessionState, section_key: str) -> dict:
    prompt = GuidanceAgent._build_section_prompt(state, [], section_key)
    return json.loads(prompt.split("context=", 1)[1])


def test_dynamic_guidance_sections_exclude_legacy_emotion_satisfaction_payload():
    state = _dynamic_state()
    state.emotion_state = EmotionState(
        interview_purpose="retention",
        primary_motivation="commerce",
        secondary_motivation="power",
        primary_satisfaction=17,
        secondary_satisfaction=29,
        total_satisfaction=21,
        last_primary_delta=-3,
        last_secondary_delta=2,
        current_vad=VADVector(valence=-0.2, arousal=0.4, dominance=-0.1),
        current_anchor_id="guarded",
    )
    expected_fields = {
        "current_vad",
        "current_anchor_id",
        "transition_strategy",
        "last_reason_summary",
        "reply_emotion_guidance",
        "has_manager_response",
    }

    for section_key in GUIDANCE_SECTION_KEYS:
        context = _guidance_context(state, section_key)
        assert set(context["emotion_state"]) == expected_fields


def test_legacy_guidance_keeps_complete_emotion_payload():
    state = _dynamic_state()
    state.motivation = None
    state.emotion_state = EmotionState(
        interview_purpose="retention",
        primary_motivation="commerce",
        secondary_motivation="power",
        primary_satisfaction=17,
        secondary_satisfaction=29,
        total_satisfaction=21,
        last_primary_delta=-3,
        last_secondary_delta=2,
        current_vad=VADVector(valence=-0.2, arousal=0.4, dominance=-0.1),
    )

    context = _guidance_context(state, "purpose")
    expected = state.emotion_state.model_dump(mode="json", exclude_none=True)
    expected.pop("updated_at")

    assert context["emotion_state"] == expected
