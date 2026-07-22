"""Generate a de-identified Token baseline from llm_usage_events.

The output contains only aggregate technical fields. It never emits account
addresses, business session identifiers, prompts, responses, or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def build_evidence(
    *,
    label: str,
    started_at: datetime,
    ended_at: datetime,
    flow_count: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    known_input_tokens = sum(
        int(row["input_tokens"]) for row in rows if row.get("input_tokens") is not None
    )
    known_output_tokens = sum(
        int(row["output_tokens"]) for row in rows if row.get("output_tokens") is not None
    )
    input_unavailable_calls = sum(int(row.get("input_unavailable_calls") or 0) for row in rows)
    output_unavailable_calls = sum(int(row.get("output_unavailable_calls") or 0) for row in rows)
    return {
        "schema_version": 1,
        "baseline_label": label,
        "window": {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        "flow_count": flow_count,
        "known_totals": {
            "input_tokens": known_input_tokens,
            "output_tokens": known_output_tokens,
            "calls": sum(int(row.get("calls") or 0) for row in rows),
        },
        "unavailable_usage": {
            "input_token_calls": input_unavailable_calls,
            "output_token_calls": output_unavailable_calls,
        },
        "by_task": rows,
    }


def query_usage(
    database_url: str,
    started_at: datetime,
    ended_at: datetime,
) -> tuple[int, list[dict[str, Any]]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required to aggregate the Token baseline") from exc

    authorized_users_sql = """
        SELECT DISTINCT users.id
        FROM locust_test_credentials AS credentials
        JOIN auth_whitelist AS whitelist
          ON lower(whitelist.email::text) = lower(credentials.email::text)
         AND whitelist.enabled = TRUE
        JOIN app_users AS users
          ON lower(users.email::text) = lower(credentials.email::text)
         AND users.is_active = TRUE
        WHERE credentials.enabled = TRUE
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        flow_count = conn.execute(
            f"""
            WITH authorized_test_users AS ({authorized_users_sql})
            SELECT count(DISTINCT events.business_session_id) AS flow_count
            FROM llm_usage_events AS events
            JOIN authorized_test_users AS users ON users.id = events.user_id
            WHERE events.created_at >= %s
              AND events.created_at < %s
              AND events.business_session_id IS NOT NULL
            """,
            (started_at, ended_at),
        ).fetchone()["flow_count"]
        rows = conn.execute(
            f"""
            WITH authorized_test_users AS ({authorized_users_sql})
            SELECT
                COALESCE(events.task_name, 'unknown') AS task_name,
                events.provider,
                events.model,
                events.usage_source,
                events.status,
                count(*) AS calls,
                sum(events.input_tokens) AS input_tokens,
                sum(events.output_tokens) AS output_tokens,
                count(*) FILTER (WHERE events.input_tokens IS NULL) AS input_unavailable_calls,
                count(*) FILTER (WHERE events.output_tokens IS NULL) AS output_unavailable_calls,
                sum(events.retry_count) AS retries,
                round(avg(events.duration_ms))::bigint AS average_duration_ms
            FROM llm_usage_events AS events
            JOIN authorized_test_users AS users ON users.id = events.user_id
            WHERE events.created_at >= %s
              AND events.created_at < %s
              AND events.business_session_id IS NOT NULL
            GROUP BY
                COALESCE(events.task_name, 'unknown'),
                events.provider,
                events.model,
                events.usage_source,
                events.status
            ORDER BY 1, 2, 3, 4, 5
            """,
            (started_at, ended_at),
        ).fetchall()
    return int(flow_count or 0), [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ended-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not LABEL_PATTERN.fullmatch(args.label):
        parser.error("--label must contain 1-64 ASCII letters, digits, '.', '_' or '-'")
    started_at = parse_timestamp(args.started_at)
    ended_at = parse_timestamp(args.ended_at)
    if ended_at <= started_at:
        parser.error("--ended-at must be later than --started-at")

    database_url = (
        os.getenv("HRAGENT_TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://hr_agent:hr_agent@localhost:5432/hr_agent"
    )
    flow_count, rows = query_usage(database_url, started_at, ended_at)
    if flow_count < 1 or not rows:
        raise SystemExit("No complete test-flow usage was found in the requested window")

    evidence = build_evidence(
        label=args.label,
        started_at=started_at,
        ended_at=ended_at,
        flow_count=flow_count,
        rows=rows,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
