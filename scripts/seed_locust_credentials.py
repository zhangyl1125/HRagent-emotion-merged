from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.password_service import PasswordService  # noqa: E402


def default_database_url() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("HRAGENT_TEST_DATABASE_URL") or "postgresql://hr_agent:hr_agent@localhost:5432/hr_agent"


def password_secret() -> str:
    return os.getenv("HRAGENT_TEST_PASSWORD_SECRET") or "hragent05-locust-test-secret"


def derive_password(email: str, nonce: str) -> str:
    digest = hmac.new(
        password_secret().encode("utf-8"),
        f"{email}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:32]


def fixed_email(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}@bosch.com"


def fixed_nonce(email: str) -> str:
    return hmac.new(
        password_secret().encode("utf-8"),
        f"nonce:{email}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Locust-only Bosch whitelist login credentials.")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--database-url", default=default_database_url())
    parser.add_argument("--email-prefix", default="hragent05-load")
    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be positive")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required. Install backend requirements or run inside the backend container.") from exc

    password_service = PasswordService()
    created = 0
    synced = 0

    with psycopg.connect(args.database_url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS citext")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS locust_test_credentials (
                id BIGSERIAL PRIMARY KEY,
                email CITEXT NOT NULL UNIQUE,
                password_nonce TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_locust_test_credentials_enabled ON locust_test_credentials(enabled, id)")

        fixed_accounts = [fixed_email(args.email_prefix, index) for index in range(1, args.count + 1)]
        conn.execute("UPDATE locust_test_credentials SET enabled = FALSE, updated_at = NOW()")
        conn.execute("UPDATE auth_whitelist SET enabled = FALSE WHERE note = 'locust load test whitelist'")

        for email in fixed_accounts:
            nonce = fixed_nonce(email)
            conn.execute(
                """
                INSERT INTO locust_test_credentials (email, password_nonce, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (email) DO UPDATE SET
                    password_nonce = EXCLUDED.password_nonce,
                    enabled = TRUE,
                    updated_at = NOW()
                """,
                (email, nonce),
            )
            created += 1

        rows = conn.execute(
            """
            SELECT email::text AS email, password_nonce
            FROM locust_test_credentials
            WHERE enabled = TRUE
            ORDER BY id
            LIMIT %s
            """,
            (args.count,),
        ).fetchall()

        for email, nonce in rows:
            plain_password = derive_password(str(email).strip().lower(), str(nonce))
            password_hash = password_service.hash_password(plain_password)
            conn.execute(
                """
                INSERT INTO auth_whitelist (email, enabled, note)
                VALUES (%s, TRUE, 'authorized fixed locust test account')
                ON CONFLICT (email) DO UPDATE SET enabled = TRUE, note = EXCLUDED.note
                """,
                (email,),
            )
            conn.execute(
                """
                INSERT INTO app_users (email, display_name, password_hash, auth_provider, role, is_active, is_email_verified)
                VALUES (%s, %s, %s, 'local', 'user', TRUE, TRUE)
                ON CONFLICT (email) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    is_active = TRUE,
                    is_email_verified = TRUE,
                    updated_at = NOW()
                """,
                (email, "Locust Load User", password_hash),
            )
            synced += 1

        conn.commit()

    print({"ok": True, "requested": args.count, "created": created, "synced": synced})


if __name__ == "__main__":
    main()
