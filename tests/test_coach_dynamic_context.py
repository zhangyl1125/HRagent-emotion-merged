from datetime import datetime, timedelta, timezone

from backend.agents.coach_agent.report_generator import _prompt_payload
from backend.schemas.conversation import ConversationTurn
from backend.schemas.emotion import ConversationEmotionLog, EmotionState, EmployeeAttitude
from backend.schemas.simulation import BigFivePersonality, MotivationState, VADVector
from backend.schemas.state import SessionState
from backend.services.coach_service import CoachService


class _Settings:
    kb_index_version = "test"

    @staticmethod
    def model_for_task(task_name: str) -> str:
        return f"model:{task_name}"

    @staticmethod
    def max_tokens_for_task(task_name: str) -> int:
        return 1000


class _Cache:
    @staticmethod
    def namespaced(namespace: str, digest: str) -> str:
        return f"{namespace}:{digest}"


def _state(*, valence: float = -0.2, primary_score: float = 45) -> SessionState:
    motivation = MotivationState(
        primary_motive_id="security",
        secondary_motive_ids=["recognition", "affiliation"],
        primary_score=primary_score,
        secondary_scores={"recognition": 51, "affiliation": 47},
    )
    emotion_state = EmotionState(
        current_vad=VADVector(valence=valence, arousal=0.48, dominance=-0.18),
    )
    return SessionState(
        session_id="coach-dynamic",
        personality=BigFivePersonality(
            openness=44,
            conscientiousness=73,
            extraversion=46,
            agreeableness=61,
            neuroticism=67,
        ),
        motivation=motivation,
        emotion_state=emotion_state,
        conversation=[
            ConversationTurn(turn_index=1, speaker="manager", text="我们先对齐事实。"),
            ConversationTurn(turn_index=2, speaker="employee", text="我担心后续安排。"),
        ],
        emotion_log=[
            ConversationEmotionLog(
                turn_index=1,
                hrbp_text="我们先对齐事实。",
                employee_attitude_before=EmployeeAttitude.GUARDED_HESITANT,
                employee_attitude_after=EmployeeAttitude.DEFENSIVE_RESISTANT,
                intensity=62,
                transition_reason="安全感诉求未被充分回应",
                vad_before=VADVector(valence=-0.1, arousal=0.2, dominance=-0.05),
                vad_after=VADVector(valence=valence, arousal=0.48, dominance=-0.18),
                motivation_before=motivation,
                motivation_after=motivation,
            )
        ],
    )


def _service() -> CoachService:
    service = CoachService.__new__(CoachService)
    service.settings = _Settings()
    service.cache = _Cache()
    return service


def test_coach_cache_key_tracks_dynamic_state_but_ignores_runtime_timestamps():
    first = _state()
    second = _state()
    second.emotion_state.updated_at = first.emotion_state.updated_at + timedelta(minutes=5)
    second.motivation.updated_at = first.motivation.updated_at + timedelta(minutes=5)
    second.emotion_log[0].created_at = first.emotion_log[0].created_at + timedelta(minutes=5)

    assert _service()._cache_key(first) == _service()._cache_key(second)
    assert _service()._cache_key(first) != _service()._cache_key(_state(valence=-0.55))
    assert _service()._cache_key(first) != _service()._cache_key(_state(primary_score=18))


def test_report_prompt_payload_preserves_emotion_trajectory_fields():
    payload = _prompt_payload(
        {
            "vad_before": {"valence": -0.1},
            "vad_after": {"valence": -0.5},
            "updated_at": datetime.now(timezone.utc),
        }
    )

    assert payload == {
        "vad_before": {"valence": -0.1},
        "vad_after": {"valence": -0.5},
    }
