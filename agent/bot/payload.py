"""What the Discord bot sends to the Concho webhook (no discord.py import: testable offline).

The contract is in ``docs/agent.md`` ("Input contract"): ``content``, ``author_id``,
``author_name``, ``channel_id``, optional ``thread_id`` (a Discord thread is a channel: the
reply goes where the question was asked), ``guild_id``, ``message_id``, ``source`` and
``attachments``. The bot ignores the webhook's response body: n8n posts the reply itself.
"""

from __future__ import annotations

from typing import Any


def parse_ids(value: str | None) -> set[int]:
    """``"123, 456"`` -> ``{123, 456}``; blanks and non-numbers are ignored."""
    out: set[int] = set()
    for part in (value or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def channel_ids(message: Any) -> tuple[int, int | None]:
    """``(channel_id, thread_id)`` of a message: in a thread the parent channel and the thread."""
    channel = message.channel
    parent_id = getattr(channel, "parent_id", None)
    if parent_id:  # discord.Thread
        return int(parent_id), int(channel.id)
    return int(channel.id), None


def should_answer(message: Any, bot_user_id: int | None, guild_id: int | None,
                  ask_channels: set[int]) -> bool:
    """Only humans, only the configured server, only the ask channel(s) (or their threads)."""
    if getattr(message.author, "bot", False) or message.author.id == bot_user_id:
        return False
    if not (message.content or "").strip():
        return False
    if guild_id and (message.guild is None or message.guild.id != guild_id):
        return False
    channel_id, thread_id = channel_ids(message)
    return not ask_channels or channel_id in ask_channels or thread_id in ask_channels


def build_payload(message: Any) -> dict[str, Any]:
    channel_id, thread_id = channel_ids(message)
    payload: dict[str, Any] = {
        "content": message.content.strip(),
        "author_id": str(message.author.id),
        "author_name": getattr(message.author, "display_name", None) or message.author.name,
        "channel_id": str(channel_id),
        "guild_id": str(message.guild.id) if message.guild else "",
        "message_id": str(message.id),
        "source": "discord",
        "attachments": [
            {"url": a.url, "filename": a.filename, "content_type": a.content_type}
            for a in getattr(message, "attachments", [])],
    }
    if thread_id is not None:
        payload["thread_id"] = str(thread_id)
    return payload
