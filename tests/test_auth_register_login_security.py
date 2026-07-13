from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_password_hash_uses_argon2id_random_salt_and_verifies():
    pytest.importorskip("argon2")
    from backend.services.password_service import PasswordService

    service = PasswordService()
    password = "Bosch-HR-Agent-Strong-Password-2026"

    first_hash = service.hash_password(password)
    second_hash = service.hash_password(password)

    assert first_hash.startswith("$argon2id$")
    assert second_hash.startswith("$argon2id$")
    assert first_hash != second_hash
    assert password not in first_hash
    assert service.verify_password(password, first_hash) is True
    assert service.verify_password("wrong-password", first_hash) is False


def test_short_password_is_rejected():
    pytest.importorskip("argon2")
    from backend.services.password_service import PasswordPolicyError, PasswordService

    service = PasswordService()

    with pytest.raises(PasswordPolicyError):
        service.hash_password("short-password")


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None


class _FakeRepo:
    def connection(self):
        return _FakeConnection()


def test_auth_whitelist_allows_only_configured_bosch_accounts():
    from backend.services.whitelist_service import WhitelistService

    settings = SimpleNamespace(
        auth_whitelist_enabled=True,
        auth_allowed_emails="aah5sgh@bosch.com,uay4sgh@bosch.com",
    )
    service = WhitelistService(repo=_FakeRepo(), settings=settings)

    assert service.is_allowed("aah5sgh@bosch.com") is True
    assert service.is_allowed("UAY4SGH@bosch.com") is True
    assert service.is_allowed("someone.else@bosch.com") is False
    assert service.is_allowed("aah5sgh@example.com") is False
