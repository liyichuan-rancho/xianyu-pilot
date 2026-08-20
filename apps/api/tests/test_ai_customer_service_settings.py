from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.business_settings import (
    AI_CS_SETTING_KEY,
    BusinessSettingValidationError,
    build_default_business_setting,
    validate_ai_customer_service_config,
)


def test_ai_customer_service_defaults_are_latency_optimized():
    config = build_default_business_setting(AI_CS_SETTING_KEY)

    assert config["replyDelaySeconds"] == 3
    assert config["reasoningEffort"] == "none"
    assert config["botLoopProtection"] is True
    assert config["botLoopMaxTurns"] == 3
    assert config["botLoopWindowMinutes"] == 10


def test_ai_customer_service_accepts_supported_reasoning_and_delay():
    config = validate_ai_customer_service_config(
        {
            "replyDelaySeconds": 2,
            "reasoningEffort": "LOW",
            "botLoopMaxTurns": 4,
            "botLoopWindowMinutes": 15,
        }
    )

    assert config["replyDelaySeconds"] == 2
    assert config["reasoningEffort"] == "low"
    assert config["botLoopMaxTurns"] == 4
    assert config["botLoopWindowMinutes"] == 15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("replyDelaySeconds", 1),
        ("replyDelaySeconds", 121),
        ("reasoningEffort", "turbo"),
        ("botLoopMaxTurns", 1),
        ("botLoopMaxTurns", 11),
        ("botLoopWindowMinutes", 0),
        ("botLoopWindowMinutes", 61),
        ("botLoopProtection", "true"),
    ],
)
def test_ai_customer_service_rejects_invalid_latency_policy(field, value):
    with pytest.raises(BusinessSettingValidationError):
        validate_ai_customer_service_config({field: value})
