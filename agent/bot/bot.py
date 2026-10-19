"""Concho Discord bot (roadmap P6.6): forwards chat messages to the n8n webhook.

The bot only POSTs the message and ignores the response body: the n8n workflow posts the reply
to the Discord channel or thread itself ("Send reply"). So the bot needs no reply logic; it
just says "typing" while n8n works and logs the HTTP status.

Which messages are forwarded
- not from a bot (including itself), not empty;
- in a channel listed in ``DISCORD_CHANNEL_ID_ASK`` (comma separated) or in a thread under one
  of them, or any message that mentions the bot (``@Concho``); the mention is stripped.

Payload (``docs/agent.md``, input contract): ``content``, ``author_id``, ``author_name``,
``channel_id``, ``thread_id`` (only in threads), ``guild_id``, ``message_id``, ``source`` =
``discord``, ``attachments`` (URLs). Header ``X-Concho-Token``.

Env: ``DISCORD_BOT_TOKEN``, ``CONCHO_WEBHOOK_URL`` (``http://n8n:5678/webhook/<path>``),
``CONCHO_WEBHOOK_TOKEN``, ``DISCORD_CHANNEL_ID_ASK``. The message-content intent must be
enabled for the bot in the Discord developer portal.

The functions below take any object with the discord.py message attributes, so they are tested
offline without discord.py; ``discord`` is imported in :func:`main` only.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable
from typing import Any

log = logging.getLogger("concho-bot")

TOKEN_HEADER = "X-Concho-Token"
WEBHOOK_TIMEOUT_S = 150  # the workflow answers the webhook after the whole run (max 120 s)


def parse_ids(raw: str | None) -> set[str]:
    """``"123, 456"`` -> ``{"123", "456"}`` (ids stay strings: they exceed JS number range)."""
    return {p.strip() for p in (raw or "").split(",") if p.strip()}


def is_thread(channel: Any) -> bool:
    return getattr(channel, "parent_id", None) is not None


def should_handle(message: Any, bot_user_id: int | str, ask_channels: Iterable[str]) -> bool:
    if getattr(message.author, "bot", False) or str(message.author.id) == str(bot_user_id):
        return False
    if not (message.content or "").strip():
        return False
    mentioned = any(str(u.id) == str(bot_user_id) for u in getattr(message, "mentions", []))
    channel = message.channel
    home = str(channel.parent_id if is_thread(channel) else channel.id)
    return mentioned or home in set(ask_channels)


def clean_content(content: str, bot_user_id: int | str) -> str:
    """Remove the bot's own mention (``<@id>`` / ``<@!id>``) and trim."""
    return re.sub(rf"<@!?{re.escape(str(bot_user_id))}>", "", content or "").strip()


def build_payload(message: Any, bot_user_id: int | str) -> dict[str, Any]:
    channel = message.channel
    payload: dict[str, Any] = {
        "content": clean_content(message.content, bot_user_id),
        "author_id": str(message.author.id),
        "author_name": getattr(message.author, "display_name", None) or str(message.author),
        "channel_id": str(channel.parent_id if is_thread(channel) else channel.id),
        "guild_id": str(message.guild.id) if getattr(message, "guild", None) else "",
        "message_id": str(message.id),
        "source": "discord",
        "attachments": [a.url for a in getattr(message, "attachments", [])],
    }
    if is_thread(channel):
        payload["thread_id"] = str(channel.id)
    return payload


async def post_to_webhook(session: Any, url: str, token: str, payload: dict[str, Any],
                          timeout: Any = None) -> int:
    """POST and return the HTTP status. The response body is read to the end and dropped."""
    async with session.post(url, json=payload, headers={TOKEN_HEADER: token},
                            timeout=timeout) as resp:
        await resp.read()
        return resp.status


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    url = os.environ.get("CONCHO_WEBHOOK_URL", "")
    webhook_token = os.environ.get("CONCHO_WEBHOOK_TOKEN", "")
    ask = parse_ids(os.environ.get("DISCORD_CHANNEL_ID_ASK"))
    missing = [n for n, v in (("DISCORD_BOT_TOKEN", token), ("CONCHO_WEBHOOK_URL", url),
                              ("CONCHO_WEBHOOK_TOKEN", webhook_token)) if not v]
    if missing:
        log.error("missing env: %s", ", ".join(missing))
        return 2

    import aiohttp  # installed with discord.py
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    state: dict[str, Any] = {}

    @client.event
    async def on_ready() -> None:
        state["session"] = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT_S))
        log.info("logged in as %s; ask channels: %s", client.user, sorted(ask) or "(mentions only)")

    @client.event
    async def on_message(message: Any) -> None:
        if not should_handle(message, client.user.id, ask):
            return
        payload = build_payload(message, client.user.id)
        try:
            async with message.channel.typing():
                status = await post_to_webhook(state["session"], url, webhook_token, payload)
            log.info("message %s -> webhook %s", payload["message_id"], status)
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.error("webhook call failed for message %s: %s", payload["message_id"],
                      type(exc).__name__)

    client.run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
