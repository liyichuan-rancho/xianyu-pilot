from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.routes.delivery_workflow_compat import sync_external_delivery_source
from app.migrations import discover_migrations, split_sql_script


class _Result:
    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        scalar_value: Any = None,
    ) -> None:
        self._rows = rows or []
        self._scalar_value = scalar_value

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any:
        return self._scalar_value


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.saved_config: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(statement)
        params = params or {}
        if "FROM xianyu_goods g" in sql:
            return _Result(
                rows=[
                    {
                        "id": 42,
                        "account_id": 7,
                        "external_goods_id": "1076474420957",
                        "goods_id": None,
                        "title": "测试资料",
                    }
                ]
            )
        if "WHERE external_system = :external_system" in sql:
            return _Result()
        if "INSERT INTO delivery_text_source" in sql:
            return _Result()
        if "SELECT LAST_INSERT_ID()" in sql:
            return _Result(scalar_value=99)
        if "FROM delivery_goods_config" in sql:
            return _Result()
        if "FROM delivery_rule" in sql:
            return _Result()
        if "INSERT INTO delivery_goods_config" in sql:
            self.saved_config = json.loads(str(params["config_json"]))
            return _Result()
        raise AssertionError(f"unexpected SQL: {sql}")

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def test_external_source_migration_is_discovered_and_parseable() -> None:
    migrations = discover_migrations()

    assert migrations[-1].version == "046"
    assert migrations[-1].path.name == "046_external_delivery_source_sync.sql"
    assert len(split_sql_script(migrations[-1].source)) >= 8


@pytest.mark.asyncio
async def test_sync_endpoint_upserts_source_and_enables_pay_delivery() -> None:
    db = _FakeSession()
    content = "链接：https://example.test/share\n提取码：1234"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    response = await sync_external_delivery_source(
        body={
            "accountId": 7,
            "externalGoodsId": "1076474420957",
            "sourceKey": "xpm-delivery-source-v1:7:1076474420957",
            "title": "测试资料",
            "content": content,
            "contentSha256": digest,
            "enabled": True,
            "autoConfirmShipment": True,
        },
        db=db,
        _={},
    )

    assert response.code == 200
    assert response.data == {
        "sourceId": 99,
        "goodsId": 42,
        "externalGoodsId": "1076474420957",
        "contentSha256": digest,
        "enabled": True,
        "autoConfirmShipment": True,
        "timing": "payDelivery",
    }
    assert db.committed is True
    assert db.rolled_back is False
    assert db.saved_config is not None
    assert db.saved_config["accountId"] == 7
    assert db.saved_config["payDelivery"] == {
        "enabled": 1,
        "mode": "text",
        "sourceId": 99,
        "sourceTitle": "测试资料",
        "content": content,
        "autoConfirmShipment": True,
    }
