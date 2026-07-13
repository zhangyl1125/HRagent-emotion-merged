from __future__ import annotations

import uuid

from backend.config.settings import get_settings
from backend.core.session_context import get_current_auth_user_id
from backend.repositories.postgres_repository import PostgresRepository
from backend.schemas.state import SessionState


class SessionRepository:
    """PostgreSQL-backed SessionState repository."""

    def __init__(self, repository: PostgresRepository | None = None):
        self.repo = repository or PostgresRepository()

    def create(self, max_user_turns: int | None = None) -> SessionState:
        state = SessionState(
            session_id=str(uuid.uuid4()),
            max_user_turns=get_settings().max_user_turns if max_user_turns is None else max_user_turns,
        )
        self.save(state)
        return state

    def get(self, session_id: str) -> SessionState:
        owner_user_id = get_current_auth_user_id()
        with self.repo.connection() as conn:
            row = conn.execute("SELECT owner_user_id::text, state_json FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
            if row is None:
                raise KeyError(f"Session not found: {session_id}")
            if owner_user_id and owner_user_id != "auth-disabled":
                row_owner = row.get("owner_user_id")
                if row_owner != owner_user_id:
                    raise KeyError(f"Session not found: {session_id}")
        return SessionState.model_validate(row["state_json"])

    def save(self, state: SessionState) -> SessionState:
        state.touch()
        payload = state.model_dump(mode="json")
        owner_user_id = get_current_auth_user_id()
        if owner_user_id == "auth-disabled":
            owner_user_id = None
        with self.repo.connection() as conn:
            if owner_user_id:
                row = conn.execute("SELECT owner_user_id::text FROM sessions WHERE session_id = %s", (state.session_id,)).fetchone()
                if row and row.get("owner_user_id") and row["owner_user_id"] != owner_user_id:
                    raise KeyError(f"Session not found: {state.session_id}")
            conn.execute(
                """
                INSERT INTO sessions (session_id, owner_user_id, state_json, updated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    owner_user_id = COALESCE(sessions.owner_user_id, excluded.owner_user_id),
                    state_json = excluded.state_json,
                    updated_at = NOW()
                """,
                (state.session_id, owner_user_id, self.repo.dumps(payload)),
            )
        return state

    def delete(self, session_id: str) -> SessionState:
        owner_user_id = get_current_auth_user_id()
        with self.repo.connection() as conn:
            row = conn.execute(
                "SELECT owner_user_id::text, state_json FROM sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Session not found: {session_id}")
            if owner_user_id and owner_user_id != "auth-disabled" and row.get("owner_user_id") != owner_user_id:
                raise KeyError(f"Session not found: {session_id}")
            conn.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
        return SessionState.model_validate(row["state_json"])

    def list(self) -> list[SessionState]:
        owner_user_id = get_current_auth_user_id()
        with self.repo.connection() as conn:
            if owner_user_id and owner_user_id != "auth-disabled":
                rows = conn.execute(
                    """
                    SELECT state_json FROM sessions
                    WHERE owner_user_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """,
                    (owner_user_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT state_json FROM sessions ORDER BY updated_at DESC LIMIT 100").fetchall()
        return [SessionState.model_validate(row["state_json"]) for row in rows]
