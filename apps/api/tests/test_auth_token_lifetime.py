from __future__ import annotations

import asyncio

import jwt

from app.core import security


def test_admin_token_has_no_expiration_claim():
    token = security.create_token(security.settings.admin_username)
    payload = jwt.decode(token, options={"verify_signature": False})

    assert "exp" not in payload
    assert security.decode_token(token)["username"] == security.settings.admin_username


def test_non_expiring_token_can_still_be_revoked(monkeypatch):
    monkeypatch.setattr(security.settings, "app_env", "test")
    token = security.create_token(security.settings.admin_username)
    payload = security.decode_token(token)

    async def exercise_revocation():
        assert await security.authenticate_token(token) is not None
        await security.revoke_token_payload(payload)
        assert await security.authenticate_token(token) is None

    asyncio.run(exercise_revocation())
