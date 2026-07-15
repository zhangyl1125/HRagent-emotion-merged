#!/usr/bin/env python3
"""Retention cleanup for admin analytics. Defaults to dry-run and never removes admin audit records."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config.settings import get_settings
from backend.repositories.postgres_repository import PostgresRepository

BATCH_SIZE = 10_000


def delete_in_batches(repo: PostgresRepository, table: str, cutoff: datetime, *, dry_run: bool) -> int:
    with repo.connection() as conn:
        count = conn.execute(f"SELECT count(*) AS count FROM {table} WHERE created_at < %s", (cutoff,)).fetchone()["count"]
    if dry_run or not count:
        return int(count)
    deleted = 0
    while True:
        with repo.connection() as conn:
            rows = conn.execute(
                f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} WHERE created_at < %s ORDER BY id LIMIT %s) RETURNING id",
                (cutoff, BATCH_SIZE),
            ).fetchall()
        deleted += len(rows)
        if len(rows) < BATCH_SIZE:
            return deleted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only report rows eligible for deletion.")
    parser.add_argument("--include-admin-audit", action="store_true", help="Delete expired admin audit rows only when explicitly requested.")
    args = parser.parse_args()
    settings = get_settings()
    repo = PostgresRepository()
    now = datetime.now(timezone.utc)
    targets = [
        ("llm_usage_events", now - timedelta(days=settings.admin_usage_retention_days)),
        ("api_request_events", now - timedelta(days=settings.admin_api_audit_retention_days)),
    ]
    if args.include_admin_audit:
        targets.append(("admin_action_audit_log", now - timedelta(days=settings.admin_usage_retention_days)))
    for table, cutoff in targets:
        count = delete_in_batches(repo, table, cutoff, dry_run=args.dry_run)
        print(f"{table}: {'would delete' if args.dry_run else 'deleted'} {count} rows older than {cutoff.date()}")


if __name__ == "__main__":
    main()
