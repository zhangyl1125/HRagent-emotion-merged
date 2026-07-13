from __future__ import annotations

from backend.repositories.postgres_repository import PostgresRepository
from backend.schemas.coach import CoachReport
from backend.schemas.guidance import GuidanceReport


class ReportRepository:
    """PostgreSQL-backed GuidanceReport / CoachReport repository."""

    def __init__(self, repository: PostgresRepository | None = None):
        self.repo = repository or PostgresRepository()

    def save_guidance(self, report: GuidanceReport) -> GuidanceReport:
        with self.repo.connection() as conn:
            conn.execute(
                """
                INSERT INTO guidance_reports (session_id, report_json, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    report_json = excluded.report_json,
                    updated_at = NOW()
                """,
                (report.session_id, self.repo.dumps(report.model_dump(mode="json"))),
            )
        return report

    def get_guidance(self, session_id: str) -> GuidanceReport:
        with self.repo.connection() as conn:
            row = conn.execute("SELECT report_json FROM guidance_reports WHERE session_id = %s", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"Guidance report not found: {session_id}")
        return GuidanceReport.model_validate(row["report_json"])

    def save_coach(self, report: CoachReport) -> CoachReport:
        with self.repo.connection() as conn:
            conn.execute(
                """
                INSERT INTO coach_reports (session_id, report_json, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    report_json = excluded.report_json,
                    updated_at = NOW()
                """,
                (report.session_id, self.repo.dumps(report.model_dump(mode="json"))),
            )
        return report

    def get_coach(self, session_id: str) -> CoachReport:
        with self.repo.connection() as conn:
            row = conn.execute("SELECT report_json FROM coach_reports WHERE session_id = %s", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"Coach report not found: {session_id}")
        return CoachReport.model_validate(row["report_json"])
