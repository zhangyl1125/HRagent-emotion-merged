from __future__ import annotations

from datetime import datetime, timezone

from backend.repositories.session_repository import SessionRepository
from backend.schemas.state import SessionState


class SessionService:
    def __init__(self, repo: SessionRepository | None = None):
        self.repo = repo or SessionRepository()

    def create_session(self, max_user_turns: int | None = None) -> SessionState:
        return self.repo.create(max_user_turns=max_user_turns)

    def get_session(self, session_id: str) -> SessionState:
        return self.repo.get(session_id)

    def list_sessions(self) -> list[SessionState]:
        return self.repo.list()

    def save_session(self, state: SessionState) -> SessionState:
        return self.repo.save(state)

    def delete_session(self, session_id: str) -> SessionState:
        return self.repo.delete(session_id)

    def end_session(self, session_id: str) -> SessionState:
        state = self.repo.get(session_id)
        state.stage = "ended"
        state.ended_at = datetime.now(timezone.utc)
        return self.repo.save(state)
