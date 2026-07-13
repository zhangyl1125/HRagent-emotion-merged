from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from backend.core.session_context import set_current_auth_user_id
from backend.schemas.auth import AuthUser
from backend.services.auth_session_service import AuthSessionService, MaxActiveSessionsReached
from backend.services.session_service import SessionService


class LoadAuthSessionService(AuthSessionService):
    active_sessions_key = "auth:test:active_sessions:pytest_concurrency"

    @staticmethod
    def _key(session_id: str) -> str:
        return f"auth:test:session:pytest_concurrency:{session_id}"


def _redis_client():
    service = LoadAuthSessionService()
    client = service._client()
    if client is None:
        pytest.skip("Redis is not configured.")
    return client


def _cleanup_auth_test_keys() -> None:
    client = _redis_client()
    client.delete(LoadAuthSessionService.active_sessions_key)
    for key in list(client.scan_iter("auth:test:session:pytest_concurrency:*")):
        client.delete(key)


def test_auth_login_session_concurrency_limit_is_exactly_100():
    _cleanup_auth_test_keys()

    def create_one(index: int) -> bool:
        service = LoadAuthSessionService()
        user = AuthUser(
            id=f"00000000-0000-0000-0000-{index:012d}",
            email=f"load{index}@bosch.com",
            display_name=f"Load {index}",
            role="user",
            auth_provider="local",
        )
        try:
            service.create_session(user)
            return True
        except MaxActiveSessionsReached:
            return False

    with ThreadPoolExecutor(max_workers=120) as pool:
        futures = [pool.submit(create_one, index) for index in range(101)]
        results = [future.result() for future in as_completed(futures)]

    client = _redis_client()
    success_count = sum(1 for item in results if item)
    limited_count = len(results) - success_count
    active_count = client.zcard(LoadAuthSessionService.active_sessions_key)

    _cleanup_auth_test_keys()

    assert success_count == 100
    assert limited_count == 1
    assert active_count == 100


@pytest.mark.parametrize("concurrency", [1, 10, 25, 50, 75, 100])
def test_workflow_session_create_preliminary_concurrency_latency(concurrency: int):
    set_current_auth_user_id("auth-disabled")
    service = SessionService()
    created_session_ids: list[str] = []

    def create_business_session() -> float:
        start = time.perf_counter()
        state = service.create_session()
        created_session_ids.append(state.session_id)
        return time.perf_counter() - start

    try:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(create_business_session) for _ in range(concurrency)]
            durations = [future.result() for future in as_completed(futures)]
        total_seconds = time.perf_counter() - started

        p50 = statistics.median(durations)
        p95 = sorted(durations)[max(0, int(len(durations) * 0.95) - 1)]
        max_seconds = max(durations)

        print(
            {
                "concurrency": concurrency,
                "total_seconds": round(total_seconds, 4),
                "p50_seconds": round(p50, 4),
                "p95_seconds": round(p95, 4),
                "max_seconds": round(max_seconds, 4),
                "created": len(created_session_ids),
                "initial_slow_threshold": "p95>1.5s or total>5s",
                "slow": p95 > 1.5 or total_seconds > 5,
            }
        )

        assert len(created_session_ids) == concurrency
        assert all(duration > 0 for duration in durations)
    finally:
        if created_session_ids:
            with service.repo.repo.connection() as conn:
                conn.execute("DELETE FROM sessions WHERE session_id = ANY(%s)", (created_session_ids,))
