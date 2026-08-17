from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.routes import misc
from app.services import captcha_solver


@pytest.mark.asyncio
async def test_websocket_start_auth_failure_uses_shared_captcha_dedup(monkeypatch):
    account_id = 787307105
    captcha_solver._AUTO_SOLVE_LAST_TS.pop(account_id, None)
    spawned = []

    monkeypatch.setattr(misc.ws_manager, "get_client", lambda _account_id: None)

    async def fake_restart(_db, _account_id):
        assert _account_id == account_id
        return object(), None

    async def fake_wait(_account_id, timeout_seconds):
        assert _account_id == account_id
        assert timeout_seconds == 12.0
        return "auth_failed", {"lastError": "captcha"}

    def fake_spawn(coroutine, *, name):
        spawned.append(name)
        coroutine.close()

    monkeypatch.setattr(misc, "_restart_ws_client_from_db", fake_restart)
    monkeypatch.setattr(misc, "_wait_ws_connect_result", fake_wait)
    monkeypatch.setattr(misc, "spawn_background_task", fake_spawn)

    try:
        result = await misc.websocket_start(
            data={"accountId": account_id},
            db=object(),
            current_user={"id": 1},
        )

        assert result.code == 200
        assert result.data["connected"] is False
        assert result.data["status"] == "recovering"
        assert spawned == ["misc.ws-captcha-recover"]
        assert captcha_solver.should_auto_solve(account_id) is False

        spawned.clear()
        repeated = await misc.websocket_start(
            data={"accountId": account_id},
            db=object(),
            current_user={"id": 1},
        )

        assert repeated.code == 200
        assert repeated.data["status"] == "recovering"
        assert spawned == []
    finally:
        captcha_solver._AUTO_SOLVE_LAST_TS.pop(account_id, None)
