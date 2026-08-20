from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai_bot_loop_guard import evaluate_recent_exchange


def _message(direction: str, content: str, at_ms: int, *, automated: bool = False) -> dict:
    return {
        "direction": direction,
        "content": content,
        "message_time": at_ms,
        "is_automated": automated,
    }


def test_repeated_counterparty_template_is_blocked_after_one_auto_reply():
    template = "无人值守，2人小刀免拼（1人直接拼成），拍下秒发～"
    decision = evaluate_recent_exchange([
        _message("IN", template, 1_000),
        _message("OUT", "您好，这款支持直接拼成，拍下秒发。", 3_000, automated=True),
        _message("IN", template, 4_000),
    ])

    assert decision.blocked is True
    assert decision.reason == "repeated_automated_template"


def test_two_different_automation_templates_are_blocked():
    decision = evaluate_recent_exchange([
        _message("IN", "本店无人值守，拍下后系统秒发。", 1_000),
        _message("OUT", "好的，请直接下单。", 3_000, automated=True),
        _message("IN", "这里是智能客服，商品支持自助下单。", 4_000),
    ])

    assert decision.blocked is True
    assert decision.reason == "automated_template_exchange"


def test_short_human_repetition_is_not_treated_as_a_template_loop():
    decision = evaluate_recent_exchange([
        _message("IN", "在吗", 1_000),
        _message("OUT", "在的，请问需要了解什么？", 5_000, automated=True),
        _message("IN", "在吗", 40_000),
    ])

    assert decision.blocked is False


def test_slow_human_repetition_is_not_treated_as_a_template_loop():
    question = "请问这个商品具体应该怎么使用呢"
    decision = evaluate_recent_exchange([
        _message("IN", question, 1_000),
        _message("OUT", "请参考商品详情页。", 5_000, automated=True),
        _message("IN", question, 40_000),
    ])

    assert decision.blocked is False


def test_changed_messages_trip_the_rapid_ping_pong_cap():
    decision = evaluate_recent_exchange([
        _message("IN", "问题一", 1_000),
        _message("OUT", "回答一", 2_000, automated=True),
        _message("IN", "问题二", 3_000),
        _message("OUT", "回答二", 4_000, automated=True),
        _message("IN", "问题三", 5_000),
        _message("OUT", "回答三", 6_000, automated=True),
        _message("IN", "问题四", 7_000),
    ], max_rapid_turns=3)

    assert decision.blocked is True
    assert decision.reason == "rapid_automated_ping_pong"
    assert decision.rapid_turns == 3


def test_manual_outbound_breaks_the_rapid_automation_chain():
    decision = evaluate_recent_exchange([
        _message("IN", "问题一", 1_000),
        _message("OUT", "人工回答", 2_000, automated=False),
        _message("IN", "问题二", 3_000),
    ], max_rapid_turns=2)

    assert decision.blocked is False
