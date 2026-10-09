"""Concho Discord bot (roadmap P6.6): forwards channel messages to the n8n webhook.

The bot only POSTs. n8n answers in Discord itself (the "Send reply" node), so the response
body of the webhook is ignored; the bot only shows the typing indicator while n8n works and logs
the HTTP status. Everything else (routing, memory, answers) lives in the workflow.

Contract (docs/agent.md, "Input contract"): POST ``$CONCHO_WEBHOOK_URL`` with the header
``X-Concho-Token`` and JSON ``content``, ``author_id``, ``author_name``, ``channel_id``,
optional ``thread_id`` (a message in a Discord thread), ``guild_id``, ``message_id``,
``source`` = ``discord`` and ``attachments`` (names and URLs only).

Env (all from ``agent/.env``, see ``agent/.env.example``):

- ``DISCORD_BOT_TOKEN``: the bot token (needs the *Message Content* intent).
- ``DISCORD_CHANNEL_ID_ASK``: channel(s) to listen in, comma separated. Threads of these
  channels count as well. Messages elsewhere are ignored.
- ``CONCHO_WEBHOOK_URL``: ``http://n8n:5678/webhook/<CONCHO_WEBHOOK_PATH>`` inside compose.
- ``CONCHO_WEBHOOK_TOKEN``: the shared header value.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable, Mapping
from typing import Any

log = logging.getLogger("concho-bot")

TOKEN_HEADER = "X-Concho-Token"
REQUEST_TIMEOUT_S = 130  # the workflow's own execution timeout is 120 s
MAX_CONTENT = 4000


def parse_channel_ids(value: str | None) -> set[str]:
    """``"123, 456"`` -> ``{"123", "456"}``; empty items are dropped."""
    return {p.strip() for p in (value or "").split(",") if p.strip()}


def channel_scope(message: Any) -> tuple[str, str | None]:
    """``(channel_id, thread_id)`` of a message. In a thread the channel is the thread; its
    parent is the channel the thread belongs to. Both are strings (Discord ids exceed 2**53)."""
    channel = message.channel
    parent_id = getattr(channel, "parent_id", None)
    if parent_id is not None:  # a thread
        return str(parent_id), str(channel.id)
    return str(channel.id), None


def should_handle(message: Any, allowed: Iterable[str], bot_user_id: int | str | None) -> bool:
    """Human messages with text in an allowed channel (or a thread of one)."""
    if getattr(message.author, "bot", False):
        return False
    if bot_user_id is not None and str(message.author.id) == str(bot_user_id):
        return False
    if not (message.content or "").strip():
        return False
    channel_id, _ = channel_scope(message)
    return channel_id in set(allowed)


def build_payload(message: Any) -> dict[str, Any]:
    """The JSON the workflow's "Normalize input" node expects."""
    channel_id, thread_id = channel_scope(message)
    guild = getattr(message, "guild", None)
    payload: dict[str, Any] = {
        "content": (message.content or "").strip()[:MAX_CONTENT],
        "author_id": str(message.author.id),
        "author_name": str(getattr(message.author, "display_name", None) or message.author.name),
        "channel_id": channel_id,
        "guild_id": str(guild.id) if guild is not None else "",
        "message_id": str(message.id),
        "source": "discord",
        "attachments": [{"filename": a.filename, "url": a.url,
                         "content_type": getattr(a, "content_type", None)}
                        for a in getattr(message, "attachments", [])],
    }
    if thread_id:
        payload["thread_id"] = thread_id
    return payload


async def post_to_webhook(session: Any, url: str, token: str, payload: Mapping[str, Any]) -> int:
    """POST and return the HTTP status. The body is read and dropped (the reply is n8n's job).

    ``session`` is an ``aiohttp.ClientSession`` (anything with the same ``post`` context
    manager works, the tests use a fake)."""
    async with session.post(url, json=dict(payload), headers={TOKEN_HEADER: token}) as response:
        await response.read()
        return response.status


def settings(env: Mapping[str, str]) -> dict[str, Any]:
    missing = [k for k in ("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID_ASK", "CONCHO_WEBHOOK_URL",
                           "CONCHO_WEBHOOK_TOKEN") if not (env.get(k) or "").strip()]
    if missing:
        raise SystemExit("missing environment variables: " + ", ".join(missing))
    return {"discord_token": env["DISCORD_BOT_TOKEN"].strip(),
            "channels": parse_channel_ids(env["DISCORD_CHANNEL_ID_ASK"]),
            "url": env["CONCHO_WEBHOOK_URL"].strip(),
            "webhook_token": env["CONCHO_WEBHOOK_TOKEN"].strip()}


def run(env: Mapping[str, str] = os.environ) -> None:  # pragma: no cover (needs Discord)
    import aiohttp
    import discord

    cfg = settings(env)
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    http: dict[str, Any] = {}

    @client.event
    async def on_ready() -> None:
        http["session"] = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S))
        log.info("logged in as %s, listening in %d channel(s)", client.user,
                 len(cfg["channels"]))

    @client.event
    async def on_message(message: discord.Message) -> None:
        if not should_handle(message, cfg["channels"], client.user.id if client.user else None):
            return
        payload = build_payload(message)
        try:
            async with message.channel.typing():
                status = await post_to_webhook(http["session"], cfg["url"],
                                               cfg["webhook_token"], payload)
        except (aiohttp.ClientError, TimeoutError):
            log.exception("webhook unreachable (message %s)", payload["message_id"])
            return
        if status >= 400:
            log.error("webhook answered %s for message %s", status, payload["message_id"])
        else:
            log.info("forwarded message %s (HTTP %s)", payload["message_id"], status)

    client.run(cfg["discord_token"], log_handler=None)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    run()
