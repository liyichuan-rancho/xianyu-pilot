from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ai_provider, ollama_runtime
from app.services.open_source_config import normalize_open_source_config


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://localhost:11434/api", "http://localhost:11434"),
        ("http://host.docker.internal:11434/v1/", "http://host.docker.internal:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_normalize_ollama_base_url_accepts_local_runtime_addresses(value, expected):
    assert ollama_runtime.normalize_ollama_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com",
        "http://192.168.1.8:11434",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434/private/path",
        "file:///tmp/ollama.sock",
    ],
)
def test_normalize_ollama_base_url_rejects_nonlocal_or_unsafe_addresses(value):
    with pytest.raises(ValueError):
        ollama_runtime.normalize_ollama_base_url(value)


def test_ollama_config_does_not_require_api_key():
    config = normalize_open_source_config(
        {
            "generalModel": {
                "transport": "ollama",
                "ollamaUrl": "http://127.0.0.1:11434",
                "modelName": "qwen3:8b",
            }
        }
    )

    assert config["generalModel"]["transport"] == "ollama"
    assert config["generalModel"]["ollamaUrl"] == "http://127.0.0.1:11434"
    assert ai_provider.is_ai_configured(config["generalModel"]) is True


@pytest.mark.asyncio
async def test_generate_text_with_ollama_uses_native_non_streaming_chat(monkeypatch):
    captured = {}

    async def fake_request(**kwargs):
        captured.update(kwargs)
        return 200, {
            "message": {"role": "assistant", "content": "本地模型回复"},
            "prompt_eval_count": 12,
            "eval_count": 5,
        }

    monkeypatch.setattr(ollama_runtime, "_request_ollama_json", fake_request)

    result = await ollama_runtime.generate_text_with_ollama(
        base_url="http://localhost:11434/api",
        model="qwen3:8b",
        messages=[{"role": "user", "content": "你好"}],
        temperature=0.3,
        timeout_seconds=30,
    )

    assert captured["path"] == "/api/chat"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["model"] == "qwen3:8b"
    assert captured["payload"]["options"]["temperature"] == 0.3
    assert result["content"] == "本地模型回复"
    assert result["usage"]["total_tokens"] == 17


@pytest.mark.asyncio
async def test_ai_provider_routes_ollama_without_remote_api_credentials(monkeypatch):
    async def fake_resolve():
        return {
            "transport": "ollama",
            "ollama_url": "http://127.0.0.1:11434",
            "base_url": "",
            "api_key": "",
            "model": "qwen3:8b",
            "enabled": True,
            "source": "settings",
            "request_timeout": 60,
        }

    async def fake_generate(**kwargs):
        assert kwargs["base_url"] == "http://127.0.0.1:11434"
        assert kwargs["messages"][-1]["content"] == "介绍一下商品"
        return {"content": "这是本地生成的商品介绍", "usage": {"total_tokens": 9}}

    monkeypatch.setattr(ai_provider, "_resolve_ai_config", fake_resolve)
    monkeypatch.setattr(ai_provider, "generate_text_with_ollama", fake_generate)

    result = await ai_provider.generate_text("goods", "你是商品文案助手", "介绍一下商品")

    assert result["ok"] is True
    assert result["provider"] == "ollama"
    assert result["content"] == "这是本地生成的商品介绍"
    assert result["usage"]["total_tokens"] == 9
