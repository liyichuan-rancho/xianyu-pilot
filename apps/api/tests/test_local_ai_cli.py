from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ai_provider
from app.services import open_source_config
from app.services.local_ai_cli import (
    CODEX_CLI_TRANSPORT,
    CURSOR_CLI_TRANSPORT,
    DEFAULT_CODEX_CLI_MODEL,
    build_cli_command,
    normalize_model_transport,
    validate_cli_executable_config,
)
from app.services.open_source_config import default_open_source_config, normalize_open_source_config


def test_fresh_config_defaults_to_codex_luna(monkeypatch):
    monkeypatch.setattr(open_source_config.settings, "ai_provider_enabled", False)
    monkeypatch.setattr(open_source_config.settings, "ai_provider_base_url", "")
    monkeypatch.setattr(open_source_config.settings, "ai_provider_api_key", "")

    config = default_open_source_config()

    assert config["generalModel"]["transport"] == CODEX_CLI_TRANSPORT
    assert config["generalModel"]["modelName"] == DEFAULT_CODEX_CLI_MODEL


def test_complete_legacy_api_environment_keeps_api_default(monkeypatch):
    monkeypatch.setattr(open_source_config.settings, "ai_provider_enabled", True)
    monkeypatch.setattr(open_source_config.settings, "ai_provider_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(open_source_config.settings, "ai_provider_api_key", "sk-live")
    monkeypatch.setattr(open_source_config.settings, "ai_provider_model", "legacy-model")

    config = default_open_source_config()

    assert config["generalModel"]["transport"] == "openai-compatible"
    assert config["generalModel"]["modelName"] == "legacy-model"


def test_normalize_open_source_config_keeps_local_cli_fields():
    config = normalize_open_source_config(
        {
            "generalModel": {
                "transport": "codex-cli",
                "modelName": "gpt-5.3-codex",
                "cliPath": "/opt/homebrew/bin/codex",
            }
        }
    )

    assert config["generalModel"]["transport"] == CODEX_CLI_TRANSPORT
    assert config["generalModel"]["modelName"] == "gpt-5.3-codex"
    assert config["generalModel"]["cliPath"] == "/opt/homebrew/bin/codex"
    assert ai_provider.is_ai_configured(config["generalModel"]) is True


def test_legacy_cli_provider_is_migrated_to_transport():
    assert normalize_model_transport("", "cursor-agent") == CURSOR_CLI_TRANSPORT


def test_cli_path_rejects_shell_or_unrelated_executables():
    with pytest.raises(ValueError):
        validate_cli_executable_config(CODEX_CLI_TRANSPORT, "codex --model gpt-5")
    with pytest.raises(ValueError):
        validate_cli_executable_config(CURSOR_CLI_TRANSPORT, "/bin/sh")
    with pytest.raises(ValueError):
        validate_cli_executable_config(CODEX_CLI_TRANSPORT, "../codex")


def test_codex_command_uses_stdin_read_only_and_ephemeral_session(tmp_path):
    output_file = tmp_path / "answer.txt"
    command = build_cli_command(
        transport=CODEX_CLI_TRANSPORT,
        executable="/opt/homebrew/bin/codex",
        model="gpt-5",
        working_directory=str(tmp_path),
        output_file=str(output_file),
        reasoning_effort="none",
    )

    assert command[-1] == "-"
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5"
    assert command[command.index("-c") + 1] == 'model_reasoning_effort="none"'


def test_cursor_command_uses_ask_mode_and_configured_model(tmp_path):
    command = build_cli_command(
        transport=CURSOR_CLI_TRANSPORT,
        executable="/usr/local/bin/cursor",
        model="sonnet-4-thinking",
        working_directory=str(tmp_path),
        cursor_prompt="只回复正文",
    )

    assert command[:2] == ["/usr/local/bin/cursor", "agent"]
    assert command[command.index("--mode") + 1] == "ask"
    assert command[command.index("--model") + 1] == "sonnet-4-thinking"
    assert command[-1] == "只回复正文"


@pytest.mark.asyncio
async def test_generate_text_routes_local_cli_without_api_key(monkeypatch):
    async def fake_resolve():
        return {
            "transport": CODEX_CLI_TRANSPORT,
            "cli_path": "codex",
            "base_url": "",
            "api_key": "",
            "model": "gpt-5",
            "enabled": True,
            "source": "settings",
            "request_timeout": 45,
        }

    async def fake_generate(**kwargs):
        assert kwargs["model"] == "gpt-5"
        assert kwargs["messages"][-1]["content"] == "你好"
        assert kwargs["reasoning_effort"] == "none"
        return "你好，有什么可以帮你？"

    monkeypatch.setattr(ai_provider, "_resolve_ai_config", fake_resolve)
    monkeypatch.setattr(ai_provider, "generate_text_with_local_cli", fake_generate)

    result = await ai_provider.generate_text(
        "chat", "你是客服", "你好", reasoning_effort="none"
    )

    assert result["ok"] is True
    assert result["provider"] == CODEX_CLI_TRANSPORT
    assert result["content"] == "你好，有什么可以帮你？"
