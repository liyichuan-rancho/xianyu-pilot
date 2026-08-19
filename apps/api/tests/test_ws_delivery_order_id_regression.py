from __future__ import annotations

import json
import os
import sys
from pathlib import Path


os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ws_delivery_handler import extract_order_id_from_message
from app.services.ws_protocol import (
    extract_order_id_from_payload,
    parse_numbered_fields,
)


ORDER_ID = "5127000000000013940"
ITEM_ID = "1076000000957"


def _paid_trade_card_payload() -> dict:
    card_content = {
        "contentType": 26,
        "dxCard": {
            "item": {
                "main": {
                    "exContent": {
                        "button": {
                            "targetUrl": (
                                "https://h5.m.goofish.com/wow/moyu/moyu-project/"
                                f"idle-logistics/pages/idleDeliver?orderId={ORDER_ID}"
                            )
                        }
                    },
                    "targetUrl": f"fleamarket://order_detail?id={ORDER_ID}&role=Seller",
                }
            }
        },
    }
    return {
        "1": {
            "1": {
                "1": {"1": "1760000001@goofish"},
                "2": "65500000068@goofish",
                "3": "4262000000127.PNM",
                "5": 1786980510425,
                "6": {
                    "1": 101,
                    "3": {
                        "1": "",
                        "2": "[我已付款，等待你发货]",
                        "4": 26,
                        "5": json.dumps(card_content, ensure_ascii=False),
                    },
                },
                "10": {
                    "extJson": json.dumps(
                        {"updateKey": f"65500000068:{ORDER_ID}:63:TRADE_PAID_DONE_SELLER"},
                        ensure_ascii=False,
                    ),
                    "reminderUrl": (
                        f"fleamarket://message_chat?itemId={ITEM_ID}"
                        "&peerUserId=1760000001&sid=65500000068&adv=no"
                    ),
                    "reminderContent": "[我已付款，等待你发货]",
                    "senderUserId": "1760000001",
                },
            },
            "7": 1,
        },
        "3": {"needPush": "true"},
    }


def test_paid_trade_card_parser_surfaces_nested_order_id() -> None:
    payload = _paid_trade_card_payload()

    parsed = parse_numbered_fields(payload)

    assert parsed is not None
    assert parsed["xyGoodsId"] == ITEM_ID
    assert parsed["orderId"] == ORDER_ID
    assert "orderId=" not in parsed["reminderUrl"]


def test_delivery_handler_falls_back_to_raw_trade_card() -> None:
    payload = _paid_trade_card_payload()
    parsed = parse_numbered_fields(payload)
    assert parsed is not None
    parsed.pop("orderId", None)  # Simulate an older normalized-message shape.
    parsed["rawPayload"] = payload

    assert extract_order_id_from_message(parsed) == ORDER_ID


def test_order_detail_generic_id_is_supported_but_item_detail_id_is_rejected() -> None:
    assert (
        extract_order_id_from_payload(
            {"targetUrl": f"fleamarket://order_detail?id={ORDER_ID}&role=Seller"}
        )
        == ORDER_ID
    )
    assert (
        extract_order_id_from_payload(
            {"targetUrl": f"fleamarket://item_detail?id={ITEM_ID}"}
        )
        == ""
    )
    assert (
        extract_order_id_from_payload(
            {"reminderUrl": f"fleamarket://message_chat?itemId={ITEM_ID}"}
        )
        == ""
    )


def test_ext_json_update_key_is_a_bounded_fallback() -> None:
    payload = {
        "extJson": json.dumps(
            {"updateKey": f"65500000068:{ORDER_ID}:63:TRADE_PAID_DONE_SELLER"}
        )
    }

    assert extract_order_id_from_payload(payload) == ORDER_ID
    assert (
        extract_order_id_from_payload(
            {"extJson": json.dumps({"updateKey": "655000000680:63:SESSION_ONLY"})}
        )
        == ""
    )
