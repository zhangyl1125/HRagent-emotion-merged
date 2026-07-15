from __future__ import annotations

from backend.config.settings import get_settings
from backend.repositories.postgres_repository import PostgresRepository


class WhitelistService:
    def __init__(self, repo: PostgresRepository | None = None, settings=None) -> None:
        self.settings = settings or get_settings()
        self.repo = repo or PostgresRepository()

    def is_allowed(self, email: str) -> bool:
        normalized = email.strip().lower()
        if not self.settings.auth_whitelist_enabled:
            return True
        env_allowed = {
            item.strip().lower()
            for item in self.settings.auth_allowed_emails.split(",")
            if item.strip()
        }
        if normalized in env_allowed:
            return True
        with self.repo.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM auth_whitelist WHERE lower(email::text) = %s AND enabled = TRUE",
                (normalized,),
            ).fetchone()
        return bool(row)

    def list_accounts(self) -> list[dict]:
        with self.repo.connection() as conn:
            rows = conn.execute(
                """
                SELECT whitelist.email::text AS email, whitelist.enabled AS whitelist_enabled,
                       users.display_name, COALESCE(users.role, 'user') AS role,
                       users.id IS NOT NULL AS registered, COALESCE(users.is_active, FALSE) AS is_active
                FROM auth_whitelist AS whitelist
                LEFT JOIN app_users AS users ON lower(users.email::text) = lower(whitelist.email::text)
                WHERE whitelist.enabled = TRUE
                   OR COALESCE(whitelist.note, '') NOT IN ('locust load test whitelist', 'authorized fixed locust test account', 'disabled random load-test whitelist')
                ORDER BY lower(whitelist.email::text)
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def set_allowed(
        self,
        email: str,
        enabled: bool,
        note: str = "managed by administrator",
        *,
        actor_email: str | None = None,
    ) -> None:
        normalized = email.strip().lower()
        with self.repo.connection() as conn:
            conn.execute(
                """
                INSERT INTO auth_whitelist (email, enabled, note, created_by, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (email) DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    note = EXCLUDED.note,
                    updated_by = COALESCE(EXCLUDED.updated_by, auth_whitelist.updated_by),
                    updated_at = NOW()
                """,
                (normalized, enabled, note, actor_email, actor_email),
            )
