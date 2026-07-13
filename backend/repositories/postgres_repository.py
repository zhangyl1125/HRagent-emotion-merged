from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock
from typing import Any, Iterator

from backend.config.settings import get_settings


_CONNECTION_LIMITS: dict[tuple[str, int], BoundedSemaphore] = {}
_CONNECTION_LIMITS_LOCK = Lock()


def _connection_limit(database_url: str, size: int) -> BoundedSemaphore:
    key = (database_url, max(1, size))
    with _CONNECTION_LIMITS_LOCK:
        limit = _CONNECTION_LIMITS.get(key)
        if limit is None:
            limit = BoundedSemaphore(key[1])
            _CONNECTION_LIMITS[key] = limit
        return limit


class PostgresRepository:
    """Shared PostgreSQL + pgvector access layer.

    All structured runtime data and KB vectors are stored in this single
    PostgreSQL database. The service fails fast when PostgreSQL, pgvector,
    schema creation, or credentials are unavailable.
    """

    def __init__(self, database_url: str | None = None, *, initialize: bool = True):
        self.settings = get_settings()
        self.database_url = (database_url or self.settings.database_url or "").strip()
        if not self.database_url:
            raise RuntimeError("DATABASE_URL 未配置。PostgreSQL + pgvector 模式必须显式配置 DATABASE_URL。")
        self._connection_limit = _connection_limit(self.database_url, self.settings.db_pool_size)
        if initialize:
            self.init_schema()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg 未安装。请安装 backend/requirements.txt 后再连接 PostgreSQL。") from exc
        try:
            return psycopg.connect(self.database_url, row_factory=dict_row)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"无法连接 PostgreSQL：{exc}") from exc

    @contextmanager
    def connection(self):
        with self._connection_limit:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init_schema(self) -> None:
        with self.connection() as conn:
            try:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                conn.execute("CREATE EXTENSION IF NOT EXISTS citext")
                conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("PostgreSQL 未启用必要扩展。请安装 pgvector/citext/pgcrypto 并授权 CREATE EXTENSION。") from exc
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    employee_alias TEXT,
                    name TEXT,
                    department TEXT,
                    role TEXT,
                    manager TEXT,
                    profile_text TEXT,
                    profile_json JSONB,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_alias ON employees(employee_alias)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email CITEXT NOT NULL UNIQUE,
                    display_name VARCHAR(120),
                    password_hash TEXT,
                    auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',
                    provider_subject VARCHAR(255),
                    role VARCHAR(30) NOT NULL DEFAULT 'user',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    is_email_verified BOOLEAN NOT NULL DEFAULT TRUE,
                    last_login_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT app_users_auth_provider_check CHECK (auth_provider IN ('local', 'oidc'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_whitelist (
                    email CITEXT PRIMARY KEY,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                INSERT INTO auth_whitelist (email, enabled, note)
                VALUES ('aah5sgh@bosch.com', TRUE, 'administrator account')
                ON CONFLICT (email) DO UPDATE SET enabled = EXCLUDED.enabled
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    email CITEXT,
                    event_type VARCHAR(40) NOT NULL,
                    success BOOLEAN NOT NULL,
                    reason VARCHAR(120),
                    ip_address INET,
                    user_agent TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_audit_email_created ON auth_audit_log(email, created_at DESC)")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_oidc_subject
                ON app_users(auth_provider, provider_subject)
                WHERE provider_subject IS NOT NULL
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    owner_user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
                    state_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES app_users(id) ON DELETE SET NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated ON sessions(owner_user_id, updated_at DESC)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    filename TEXT,
                    raw_path TEXT,
                    record_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guidance_reports (
                    session_id TEXT PRIMARY KEY,
                    report_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS coach_reports (
                    session_id TEXT PRIMARY KEY,
                    report_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                    doc_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_documents_scope ON kb_documents(scope)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    collection_name TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    embedding VECTOR NOT NULL,
                    index_version TEXT NOT NULL,
                    content_hash TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_collection ON kb_chunks(collection_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_scope ON kb_chunks(scope)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_id ON kb_chunks(doc_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_metadata ON kb_chunks USING GIN(metadata)")
            if self.settings.postgres_create_hnsw_index:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_hnsw "
                    "ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
                )

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def dumps(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def vector_literal(vector: list[float]) -> str:
        if not vector:
            raise ValueError("Embedding vector cannot be empty.")
        return "[" + ",".join(str(float(x)) for x in vector) + "]"

    def load_metadata(self, key: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM app_metadata WHERE key = %s", (key,)).fetchone()
        if not row:
            return {}
        value = row["value"]
        if isinstance(value, str):
            return json.loads(value)
        return dict(value)

    def save_metadata(self, key: str, value: dict) -> dict:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO app_metadata (key, value, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = NOW()
                """,
                (key, self.dumps(value)),
            )
        return value
