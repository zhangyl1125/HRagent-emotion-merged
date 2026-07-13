from __future__ import annotations

import json
from typing import Any

from backend.config.settings import get_settings
from backend.repositories.postgres_repository import PostgresRepository
from backend.schemas.employee_database import EmployeeDatabaseRecord, EmployeeDatabaseUpsertRequest
from backend.schemas.profile import EmployeeProfile


class EmployeeDatabaseService:
    """PostgreSQL-backed employee information lookup.

    Employee master data is stored in the same PostgreSQL database used for
    sessions, documents, reports, KB chunks, and pgvector embeddings.
    """

    def __init__(self, repository: PostgresRepository | None = None):
        self.settings = get_settings()
        self.repo = repository or PostgresRepository()
        self.database_url = self.settings.database_url

    def search(
        self,
        query: str | None = None,
        limit: int = 20,
        employee_id: str | None = None,
        name: str | None = None,
    ) -> list[EmployeeDatabaseRecord]:
        limit = max(1, min(limit, 100))
        needle = (query or "").strip()
        employee_id = (employee_id or "").strip()
        name = (name or "").strip()

        where: list[str] = []
        params: list[str | int] = []
        if employee_id:
            where.append("employee_id = %s")
            params.append(employee_id)
        if name:
            where.append("(name ILIKE %s OR employee_alias ILIKE %s)")
            name_like = f"%{name}%"
            params.extend([name_like, name_like])
        if needle and not where:
            like = f"%{needle}%"
            where.append(
                "(employee_id ILIKE %s OR employee_alias ILIKE %s OR name ILIKE %s "
                "OR department ILIKE %s OR role ILIKE %s OR manager ILIKE %s OR profile_text ILIKE %s)"
            )
            params.extend([like, like, like, like, like, like, like])

        sql = "SELECT * FROM employees"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, employee_id ASC LIMIT %s"
        params.append(limit)

        with self.repo.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, employee_id: str) -> EmployeeDatabaseRecord:
        with self.repo.connection() as conn:
            row = conn.execute("SELECT * FROM employees WHERE employee_id = %s", (employee_id,)).fetchone()
        if row is None:
            raise KeyError(f"Employee not found: {employee_id}")
        return self._row_to_record(row)

    def upsert(self, payload: EmployeeDatabaseUpsertRequest) -> EmployeeDatabaseRecord:
        profile_json = payload.profile.model_dump(mode="json", exclude_none=True) if payload.profile else None
        with self.repo.connection() as conn:
            conn.execute(
                """
                INSERT INTO employees (
                    employee_id, employee_alias, name, department, role, manager,
                    profile_text, profile_json, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT(employee_id) DO UPDATE SET
                    employee_alias = excluded.employee_alias,
                    name = excluded.name,
                    department = excluded.department,
                    role = excluded.role,
                    manager = excluded.manager,
                    profile_text = excluded.profile_text,
                    profile_json = excluded.profile_json,
                    updated_at = NOW()
                """,
                (
                    payload.employee_id,
                    payload.employee_alias,
                    payload.name,
                    payload.department,
                    payload.role,
                    payload.manager,
                    payload.profile_text,
                    json.dumps(profile_json, ensure_ascii=False) if profile_json is not None else None,
                ),
            )
        return self.get(payload.employee_id)

    def _row_to_record(self, row: dict[str, Any]) -> EmployeeDatabaseRecord:
        profile = self._parse_profile(row.get("profile_json"))
        record = EmployeeDatabaseRecord(
            employee_id=row["employee_id"],
            employee_alias=row.get("employee_alias"),
            name=row.get("name"),
            department=row.get("department"),
            role=row.get("role"),
            manager=row.get("manager"),
            profile_text=row.get("profile_text"),
            profile=profile,
            updated_at=row.get("updated_at").isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
        )
        if not record.profile_text:
            record.profile_text = self._build_profile_text(record)
        return record

    @staticmethod
    def _parse_profile(raw: Any) -> EmployeeProfile | None:
        if not raw:
            return None
        if isinstance(raw, str):
            raw = json.loads(raw)
        return EmployeeProfile.model_validate(raw)

    @staticmethod
    def _build_profile_text(record: EmployeeDatabaseRecord) -> str:
        lines = [
            ("员工ID", record.employee_id),
            ("员工代称", record.employee_alias or record.name),
            ("岗位", record.role),
            ("部门", record.department),
            ("汇报对象", record.manager),
        ]
        if record.profile:
            data: dict[str, Any] = record.profile.model_dump(exclude_none=True)
            for key in [
                "level",
                "reporting_line",
                "performance_rating",
                "review_cycle",
                "conversation_topic",
                "employee_status_summary",
            ]:
                if data.get(key):
                    lines.append((key, data[key]))
            if data.get("key_goals"):
                lines.append(("关键目标", "、".join(map(str, data["key_goals"]))))
            if data.get("facts"):
                facts = [item.get("description") for item in data["facts"] if isinstance(item, dict) and item.get("description")]
                if facts:
                    lines.append(("事实", "；".join(facts)))
        return "\n".join(f"{label}：{value}" for label, value in lines if value)
