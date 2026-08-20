"""Deterministic circuit breaker for bot-to-bot auto-reply loops.

The guard runs after the inbound message has been persisted and before any
keyword rule or model call.  It intentionally relies on recent message shape,
not on an LLM classification, so loop prevention remains fast and available
when the configured model is slow or unavailable.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_NORMALIZE_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)
_AUTOMATION_MARKERS = (
    "无人值守",
    "自动回复",
    "自动客服",
    "智能客服",
    "机器人客服",
    "拍下秒发",
    "下单秒发",
    "自助下单",
    "无需回复",
    "请勿回复",
)


@dataclass(frozen=True)
class BotLoopDecision:
    blocked: bool
    reason: str = "allowed"
    rapid_turns: int = 0


def _normalize_content(value: Any) -> str:
    return _NORMALIZE_RE.sub("", str(value or "").casefold())[:2_000]


def _message_direction(message: dict[str, Any]) -> str:
    return str(message.get("direction") or "").strip().upper()


def _message_time(message: dict[str, Any]) -> int:
    try:
        return max(0, int(message.get("message_time") or message.get("messageTime") or 0))
    except (TypeError, ValueError):
        return 0


def _is_automated_outbound(message: dict[str, Any]) -> bool:
    if _message_direction(message) != "OUT":
        return False
    value = message.get("is_automated")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _similar_template(left: str, right: str) -> bool:
    if not left or not right:
        return False
    # Very short buyer replies ("好的", "在吗") are often repeated by humans.
    # Only fuzzy-match content long enough to look like a reusable template.
    if min(len(left), len(right)) < 12:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right, autojunk=False).ratio() >= 0.9


def evaluate_recent_exchange(
    messages: Iterable[dict[str, Any]],
    *,
    max_rapid_turns: int = 3,
    rapid_reply_seconds: int = 20,
) -> BotLoopDecision:
    """Classify a chronological slice ending in the current inbound text."""

    ordered = [dict(item) for item in messages]
    if not ordered or _message_direction(ordered[-1]) != "IN":
        return BotLoopDecision(False)

    current = ordered[-1]
    current_text = _normalize_content(current.get("content") or current.get("msg_content"))
    if not current_text:
        return BotLoopDecision(False)
    rapid_limit_ms = max(1, int(rapid_reply_seconds)) * 1_000

    # Strong signal: the counterpart rapidly repeats (or lightly rewrites) its
    # previous template after one of our automated replies. This catches the
    # screenshot scenario on the second incoming bot message while allowing a
    # human to repeat an unanswered question later.
    for index in range(len(ordered) - 2, -1, -1):
        candidate = ordered[index]
        if _message_direction(candidate) != "IN":
            continue
        candidate_text = _normalize_content(
            candidate.get("content") or candidate.get("msg_content")
        )
        automated_between = [
            item for item in ordered[index + 1 : -1]
            if _is_automated_outbound(item)
        ]
        latest_auto_time = _message_time(automated_between[-1]) if automated_between else 0
        current_time = _message_time(current)
        repeated_rapidly = bool(
            latest_auto_time
            and current_time
            and 0 <= current_time - latest_auto_time <= rapid_limit_ms
        )
        if repeated_rapidly and _similar_template(candidate_text, current_text):
            return BotLoopDecision(True, "repeated_automated_template")
        # The nearest prior inbound is the relevant turn. Older repeated human
        # questions should not trip the guard across an intervening discussion.
        break

    # A pair of different but explicit automation templates is also a strong
    # bot signal. Requiring markers on both messages avoids blocking a human
    # merely asking whether a listing is unattended or instant-delivery.
    current_has_marker = any(marker in current_text for marker in _AUTOMATION_MARKERS)
    if current_has_marker:
        for index in range(len(ordered) - 2, -1, -1):
            candidate = ordered[index]
            if _message_direction(candidate) != "IN":
                continue
            candidate_text = _normalize_content(
                candidate.get("content") or candidate.get("msg_content")
            )
            automated_between = any(
                _is_automated_outbound(item)
                for item in ordered[index + 1 : -1]
            )
            if automated_between and any(marker in candidate_text for marker in _AUTOMATION_MARKERS):
                return BotLoopDecision(True, "automated_template_exchange")
            break

    # Fallback for bots that vary every message: count adjacent, rapid
    # automated-OUT -> IN exchanges from the tail. A non-automated seller
    # message or a slow response breaks the chain.
    rapid_turns = 0
    cursor = len(ordered) - 1
    while cursor > 0 and _message_direction(ordered[cursor]) == "IN":
        outbound = ordered[cursor - 1]
        if not _is_automated_outbound(outbound):
            break
        inbound_time = _message_time(ordered[cursor])
        outbound_time = _message_time(outbound)
        if not inbound_time or not outbound_time or not 0 <= inbound_time - outbound_time <= rapid_limit_ms:
            break
        rapid_turns += 1
        cursor -= 2
        if cursor < 0:
            break
        # The preceding message should be the inbound turn that caused this
        # automated outbound. Continue from it to inspect the previous pair.
        if _message_direction(ordered[cursor]) != "IN":
            break

    bounded_max_turns = max(2, min(int(max_rapid_turns), 10))
    if rapid_turns >= bounded_max_turns:
        return BotLoopDecision(True, "rapid_automated_ping_pong", rapid_turns)
    return BotLoopDecision(False, rapid_turns=rapid_turns)


async def evaluate_bot_loop_guard(
    db: AsyncSession,
    *,
    account_id: int,
    session_id: str,
    window_minutes: int = 10,
    max_rapid_turns: int = 3,
    rapid_reply_seconds: int = 20,
) -> BotLoopDecision:
    """Load a bounded conversation slice and evaluate the circuit breaker."""

    normalized_sid = (
        str(session_id or "").strip().removeprefix("sid:").removesuffix("@goofish")
    )
    if not account_id or not normalized_sid:
        return BotLoopDecision(False)

    bounded_window = max(1, min(int(window_minutes), 60))
    threshold_ms = int(time.time() * 1_000) - bounded_window * 60 * 1_000
    rows = await db.execute(
        text(
            """
            SELECT
                message.id,
                message.direction,
                message.msg_content AS content,
                message.message_time,
                CASE
                    WHEN COALESCE(message.pnm_id, '') LIKE 'ai-auto-reply:%' THEN 1
                    WHEN COALESCE(message.pnm_id, '') LIKE 'kw-%' THEN 1
                    WHEN EXISTS (
                        SELECT 1
                        FROM ai_auto_reply_attempt AS attempt
                        WHERE attempt.local_message_id = message.id
                    ) THEN 1
                    ELSE 0
                END AS is_automated
            FROM xianyu_chat_message AS message
            WHERE message.account_id = :account_id
              AND message.deleted = 0
              AND message.content_type = 1
              AND message.s_id IN (:sid_plain, :sid_goofish)
              AND message.message_time >= :threshold_ms
            ORDER BY message.message_time DESC, message.id DESC
            LIMIT 40
            """
        ),
        {
            "account_id": int(account_id),
            "sid_plain": normalized_sid,
            "sid_goofish": f"{normalized_sid}@goofish",
            "threshold_ms": threshold_ms,
        },
    )
    recent = [dict(row) for row in reversed(rows.mappings().all())]
    return evaluate_recent_exchange(
        recent,
        max_rapid_turns=max_rapid_turns,
        rapid_reply_seconds=rapid_reply_seconds,
    )
