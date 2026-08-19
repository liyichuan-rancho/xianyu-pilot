from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .ollama_runtime import OLLAMA_TRANSPORT


API_TRANSPORT = "openai-compatible"
CODEX_CLI_TRANSPORT = "codex-cli"
CURSOR_CLI_TRANSPORT = "cursor-cli"
LOCAL_CLI_TRANSPORTS = {CODEX_CLI_TRANSPORT, CURSOR_CLI_TRANSPORT}

_DEFAULT_EXECUTABLES = {
    CODEX_CLI_TRANSPORT: "codex",
    CURSOR_CLI_TRANSPORT: "cursor-agent",
}
_EXECUTABLE_CANDIDATES = {
    CODEX_CLI_TRANSPORT: ("codex",),
    CURSOR_CLI_TRANSPORT: ("cursor-agent", "agent", "cursor"),
}
_ALLOWED_EXECUTABLE_NAMES = {
    CODEX_CLI_TRANSPORT: {"codex", "codex.exe", "codex.cmd"},
    CURSOR_CLI_TRANSPORT: {
        "agent",
        "agent.exe",
        "agent.cmd",
        "cursor",
        "cursor.exe",
        "cursor.cmd",
        "cursor-agent",
        "cursor-agent.exe",
        "cursor-agent.cmd",
    },
}
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Cursor receives its prompt as one argv value. Keep comfortably below macOS'
# process argument limit while still allowing substantial chat context.
_MAX_PROMPT_BYTES = 128 * 1024
_MAX_OUTPUT_CHARS = 1024 * 1024


class LocalAICLIError(RuntimeError):
    """A safe, operator-facing local CLI failure."""


def normalize_model_transport(value: Any, provider: Any = "") -> str:
    raw = str(value or "").strip().casefold().replace("_", "-")
    provider_name = str(provider or "").strip().casefold().replace("_", "-")
    aliases = {
        "": API_TRANSPORT,
        "api": API_TRANSPORT,
        "openai": API_TRANSPORT,
        "openai-compatible": API_TRANSPORT,
        "ollama": OLLAMA_TRANSPORT,
        "ollama-local": OLLAMA_TRANSPORT,
        "codex": CODEX_CLI_TRANSPORT,
        "codex-cli": CODEX_CLI_TRANSPORT,
        "cursor": CURSOR_CLI_TRANSPORT,
        "cursor-agent": CURSOR_CLI_TRANSPORT,
        "cursor-cli": CURSOR_CLI_TRANSPORT,
    }
    if raw:
        return aliases.get(raw, API_TRANSPORT)
    return aliases.get(provider_name, API_TRANSPORT)


def is_local_cli_transport(value: Any) -> bool:
    return normalize_model_transport(value) in LOCAL_CLI_TRANSPORTS


def default_cli_executable(transport: Any) -> str:
    return _DEFAULT_EXECUTABLES.get(normalize_model_transport(transport), "")


def validate_cli_executable_config(transport: Any, configured_path: Any = "") -> str:
    normalized_transport = normalize_model_transport(transport)
    if normalized_transport not in LOCAL_CLI_TRANSPORTS:
        raise ValueError("不支持的本机 CLI 调用方式")

    candidate = str(configured_path or "").strip() or default_cli_executable(normalized_transport)
    if not candidate or "\x00" in candidate:
        raise ValueError("CLI 命令路径无效")

    has_separator = any(separator and separator in candidate for separator in (os.sep, os.altsep))
    if has_separator and not os.path.isabs(candidate):
        raise ValueError("CLI 命令只能填写命令名或绝对路径")

    executable_name = Path(candidate).name.casefold()
    if executable_name not in _ALLOWED_EXECUTABLE_NAMES[normalized_transport]:
        expected = "codex" if normalized_transport == CODEX_CLI_TRANSPORT else "cursor-agent（或 cursor / agent）"
        raise ValueError(f"所选调用方式仅允许使用 {expected} 可执行文件")
    return candidate


def resolve_cli_executable(transport: Any, configured_path: Any = "") -> str:
    normalized_transport = normalize_model_transport(transport)
    try:
        candidate = validate_cli_executable_config(normalized_transport, configured_path)
    except ValueError:
        return ""

    if os.path.isabs(candidate):
        path = Path(candidate)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else ""
    if str(configured_path or "").strip():
        return shutil.which(candidate) or ""
    for default_candidate in _EXECUTABLE_CANDIDATES.get(normalized_transport, (candidate,)):
        resolved = shutil.which(default_candidate)
        if resolved:
            return resolved
    return ""


def cli_runtime_status(transport: Any, configured_path: Any = "") -> dict[str, Any]:
    normalized_transport = normalize_model_transport(transport)
    selected_executable = (
        resolve_cli_executable(normalized_transport, configured_path)
        if normalized_transport in LOCAL_CLI_TRANSPORTS
        else ""
    )
    return {
        "generalModelTransport": normalized_transport,
        "generalModelCliAvailable": bool(selected_executable),
        "codexCliAvailable": bool(resolve_cli_executable(CODEX_CLI_TRANSPORT)),
        "cursorCliAvailable": bool(resolve_cli_executable(CURSOR_CLI_TRANSPORT)),
    }


def build_cli_prompt(
    *,
    scene: str,
    messages: list[dict[str, Any]],
    temperature: float,
) -> str:
    serialized_messages = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    prompt = (
        "你正在作为业务系统的纯文本大模型后端运行。"
        "不要浏览网络，不要运行命令，不要检查或修改任何文件，也不要描述你的工作过程。"
        "严格遵循下面的系统指令和对话，只输出最终回复正文。\n\n"
        f"场景：{scene or 'general'}\n"
        f"建议温度：{temperature}\n"
        f"对话（JSON）：{serialized_messages}"
    )
    if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
        raise LocalAICLIError("发送给本机 CLI 的上下文过长")
    return prompt


def _cursor_command_prefix(executable: str) -> list[str]:
    name = Path(executable).name.casefold()
    if name in {"cursor", "cursor.exe", "cursor.cmd"}:
        return [executable, "agent"]
    return [executable]


def build_cli_command(
    *,
    transport: Any,
    executable: str,
    model: str,
    working_directory: str,
    output_file: str = "",
    cursor_prompt: str = "",
) -> list[str]:
    normalized_transport = normalize_model_transport(transport)
    if normalized_transport == CODEX_CLI_TRANSPORT:
        if not output_file:
            raise ValueError("Codex CLI 需要输出文件")
        return [
            executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-last-message",
            output_file,
            "--model",
            model,
            "-",
        ]
    if normalized_transport == CURSOR_CLI_TRANSPORT:
        return _cursor_command_prefix(executable) + [
            "--print",
            "--output-format",
            "text",
            "--mode",
            "ask",
            "--model",
            model,
            "--workspace",
            working_directory,
            "--trust",
            cursor_prompt,
        ]
    raise ValueError("不支持的本机 CLI 调用方式")


def _clean_cli_output(value: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", value or "").strip()[:_MAX_OUTPUT_CHARS]


async def generate_text_with_local_cli(
    *,
    transport: Any,
    cli_path: Any,
    model: str,
    scene: str,
    messages: list[dict[str, Any]],
    temperature: float,
    timeout_seconds: int,
) -> str:
    normalized_transport = normalize_model_transport(transport)
    executable = resolve_cli_executable(normalized_transport, cli_path)
    cli_label = "Codex CLI" if normalized_transport == CODEX_CLI_TRANSPORT else "Cursor CLI"
    if not executable:
        raise LocalAICLIError(f"未找到 {cli_label}，请检查命令路径以及后端进程的 PATH")

    prompt = build_cli_prompt(scene=scene, messages=messages, temperature=temperature)
    with tempfile.TemporaryDirectory(prefix="xianyu-ai-cli-") as temp_dir:
        output_path = str(Path(temp_dir) / "last-message.txt")
        command = build_cli_command(
            transport=normalized_transport,
            executable=executable,
            model=model,
            working_directory=temp_dir,
            output_file=output_path,
            cursor_prompt=prompt,
        )
        stdin_payload = prompt.encode("utf-8") if normalized_transport == CODEX_CLI_TRANSPORT else None

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=temp_dir,
                stdin=asyncio.subprocess.PIPE if stdin_payload is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise LocalAICLIError(f"无法启动 {cli_label}，请检查命令路径和执行权限") from exc

        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(input=stdin_payload),
                timeout=max(5, min(int(timeout_seconds or 30), 300)),
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise LocalAICLIError(f"{cli_label} 调用超时") from exc

        if process.returncode != 0:
            raise LocalAICLIError(f"{cli_label} 调用失败，请确认 CLI 已登录且模型名称可用")

        if normalized_transport == CODEX_CLI_TRANSPORT and Path(output_path).is_file():
            content = Path(output_path).read_text(encoding="utf-8", errors="replace")
        else:
            content = stdout.decode("utf-8", errors="replace")
        content = _clean_cli_output(content)
        if not content:
            raise LocalAICLIError(f"{cli_label} 未返回有效文本")
        return content
