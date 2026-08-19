from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx


OLLAMA_TRANSPORT = "ollama"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DOCKER_OLLAMA_BASE_URL = "http://host.docker.internal:11434"

_ALLOWED_HOSTNAMES = {"localhost", "host.docker.internal"}
_MAX_REQUEST_BYTES = 512 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024


class OllamaRuntimeError(RuntimeError):
    """A safe, operator-facing Ollama failure."""


def normalize_ollama_base_url(value: Any) -> str:
    raw = str(value or "").strip() or DEFAULT_OLLAMA_BASE_URL
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ollama 服务地址端口无效") from exc

    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("Ollama 服务地址仅支持 HTTP 或 HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Ollama 服务地址不得包含凭据")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("Ollama 服务地址不得包含查询参数或片段")
    if parsed.path.rstrip("/") not in {"", "/api", "/v1"}:
        raise ValueError("Ollama 服务地址应填写根地址，例如 http://127.0.0.1:11434")

    hostname = parsed.hostname.rstrip(".").casefold()
    allowed_host = hostname in _ALLOWED_HOSTNAMES
    if not allowed_host:
        try:
            allowed_host = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            allowed_host = False
    if not allowed_host:
        raise ValueError("Ollama 服务地址仅允许本机回环地址或 host.docker.internal")

    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Ollama 服务地址端口无效")

    normalized = urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc,
            "",
            "",
            "",
            "",
        )
    )
    return normalized.rstrip("/")


def is_ollama_configured(config: dict[str, Any] | None) -> bool:
    if not config:
        return False
    enabled = config.get("enabled")
    if enabled is None:
        enabled = True
    model = str(config.get("model") or config.get("modelName") or "").strip()
    try:
        normalize_ollama_base_url(
            config.get("ollama_url")
            or config.get("ollamaUrl")
            or config.get("base_url")
            or config.get("baseUrl")
        )
        endpoint_valid = True
    except ValueError:
        endpoint_valid = False
    return bool(enabled and model and endpoint_valid)


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().casefold()
        if role not in {"system", "user", "assistant"}:
            role = "user"
        content = item.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        normalized.append({"role": role, "content": content})
    return normalized


async def _request_ollama_json(
    *,
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float,
    max_response_bytes: int = _MAX_RESPONSE_BYTES,
) -> tuple[int, dict[str, Any]]:
    endpoint = f"{normalize_ollama_base_url(base_url)}{path}"
    request_content = None
    if payload is not None:
        request_content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(request_content) > _MAX_REQUEST_BYTES:
            raise OllamaRuntimeError("发送给 Ollama 的上下文过长")

    timeout = max(1.0, min(float(timeout_seconds or 30), 300.0))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 3.0)),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                method,
                endpoint,
                content=request_content,
                headers={"Content-Type": "application/json"},
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_response_bytes:
                        raise OllamaRuntimeError("Ollama 返回内容过大")
                status_code = response.status_code
    except OllamaRuntimeError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
        raise OllamaRuntimeError("无法连接 Ollama，请确认服务已启动且地址可从后端访问") from exc

    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OllamaRuntimeError("Ollama 返回了无法解析的响应") from exc
    if not isinstance(data, dict):
        raise OllamaRuntimeError("Ollama 返回了无效响应")
    return status_code, data


async def generate_text_with_ollama(
    *,
    base_url: Any,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = {
        "model": str(model or "").strip(),
        "messages": _normalize_messages(messages),
        "stream": False,
        "options": {"temperature": float(temperature)},
    }
    status_code, data = await _request_ollama_json(
        base_url=normalize_ollama_base_url(base_url),
        method="POST",
        path="/api/chat",
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    if status_code < 200 or status_code >= 300:
        if status_code == 404:
            raise OllamaRuntimeError("Ollama 未找到该模型，请先执行 ollama pull 下载模型")
        raise OllamaRuntimeError(f"Ollama 调用失败（HTTP {status_code}）")

    message = data.get("message") or {}
    content = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
    if not content:
        raise OllamaRuntimeError("Ollama 未返回有效文本")

    prompt_tokens = int(data.get("prompt_eval_count") or 0)
    completion_tokens = int(data.get("eval_count") or 0)
    return {
        "content": content,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def probe_ollama(base_url: Any, timeout_seconds: float = 1.5) -> dict[str, Any]:
    try:
        status_code, data = await _request_ollama_json(
            base_url=normalize_ollama_base_url(base_url),
            method="GET",
            path="/api/version",
            timeout_seconds=timeout_seconds,
            max_response_bytes=64 * 1024,
        )
        return {
            "available": 200 <= status_code < 300,
            "version": str(data.get("version") or "") if status_code == 200 else "",
        }
    except (ValueError, OllamaRuntimeError):
        return {"available": False, "version": ""}
