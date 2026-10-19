"""Concho Discord bot (roadmap P6.6): forwards questions to the n8n webhook, nothing else.

It listens in the ask channel(s) of one server, POSTs each human message to the Concho webhook
and **ignores the response body**: the n8n workflow posts the reply into the channel or thread
itself (docs/agent.md). While n8n works the bot shows "typing". Configuration is the env only:

    DISCORD_BOT_TOKEN        bot token (secret)
    DISCORD_GUILD_ID         the server (optional; messages from other servers are ignored)
    DISCORD_CHANNEL_ID_ASK   ask channel id(s), comma separated (empty: every channel the bot sees)
    CONCHO_WEBHOOK_URL       http://n8n:5678/webhook/<CONCHO_WEBHOOK_PATH>
    CONCHO_WEBHOOK_TOKEN     value of the header X-Concho-Token (secret)

The bot needs the "Message Content" privileged intent (Discord developer portal -> Bot).
"""

from __future__ import annotations

import logging
import os
import sys

import aiohttp
import discord
from payload import build_payload, parse_ids, should_answer

log = logging.getLogger("concho-bot")
REQUEST_TIMEOUT_S = 150  # n8n answers the webhook when the agent is done (execution timeout 120 s)


def env(name: str, required: bool = False) -> str:
    value = (os.environ.get(name) or "").strip()
    if required and not value:
        sys.exit(f"error: {name} is not set (see agent/.env.example)")
    return value


class ConchoBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.webhook_url = env("CONCHO_WEBHOOK_URL", required=True)
        self.webhook_token = env("CONCHO_WEBHOOK_TOKEN", required=True)
        guild = env("DISCORD_GUILD_ID")
        self.guild_id = int(guild) if guild.isdigit() else None
        self.ask_channels = parse_ids(env("DISCORD_CHANNEL_ID_ASK"))
        self.http: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S))

    async def close(self) -> None:
        if self.http:
            await self.http.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("logged in as %s; ask channels: %s", self.user,
                 sorted(self.ask_channels) or "all")

    async def on_message(self, message: discord.Message) -> None:
        if not should_answer(message, self.user.id if self.user else None, self.guild_id,
                             self.ask_channels):
            return
        assert self.http is not None
        payload = build_payload(message)
        try:
            async with message.channel.typing():
                async with self.http.post(
                        self.webhook_url, json=payload,
                        headers={"X-Concho-Token": self.webhook_token}) as response:
                    await response.read()  # wait for n8n; the body is not used
                    if response.status >= 300:
                        log.error("webhook answered HTTP %s for message %s", response.status,
                                  message.id)
                        await message.reply("Sorry, Concho could not take that question "
                                            "right now.", mention_author=False)
        except (TimeoutError, aiohttp.ClientError):
            log.exception("webhook not reachable for message %s", message.id)
            await message.reply("Sorry, Concho is not reachable right now.", mention_author=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ConchoBot().run(env("DISCORD_BOT_TOKEN", required=True), log_handler=None)


if __name__ == "__main__":
    main()
