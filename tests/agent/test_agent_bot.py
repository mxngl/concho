"""P6.6: the Discord bot's message handling (``agent/bot/payload.py``, no discord.py needed)."""

from __future__ import annotations

import ast
import sys
from types import SimpleNamespace as NS

import agent_helpers as h
import pytest

sys.path.insert(0, str(h.AGENT / "bot"))
import payload  # noqa: E402

GUILD, ASK, THREAD = 1111, 2222, 3333


def msg(content="How much is the roof?", *, channel=ASK, parent=None, bot=False, guild=GUILD,
        author=42, attachments=()):
    return NS(content=content, id=9001, author=NS(id=author, bot=bot, display_name="Max",
                                                  name="max"),
              channel=NS(id=channel, parent_id=parent), guild=NS(id=guild) if guild else None,
              attachments=list(attachments))


def test_payload_follows_the_input_contract_of_the_workflow():
    body = payload.build_payload(msg())
    assert body == {"content": "How much is the roof?", "author_id": "42", "author_name": "Max",
                    "channel_id": str(ASK), "guild_id": str(GUILD), "message_id": "9001",
                    "source": "discord", "attachments": []}
    wf = h.load("concho.json")
    norm = next(n for n in wf["nodes"] if n["name"] == "Normalize input")
    reads = " ".join(a["value"] for a in norm["parameters"]["assignments"]["assignments"])
    for field in body:
        assert f"body.{field}" in reads or field in ("source",), field


def test_a_message_in_a_thread_sends_thread_and_parent_channel():
    body = payload.build_payload(msg(channel=THREAD, parent=ASK))
    assert body["channel_id"] == str(ASK) and body["thread_id"] == str(THREAD)
    assert "thread_id" not in payload.build_payload(msg())


def test_attachments_are_forwarded_as_metadata_only():
    att = NS(url="https://cdn.example/file.png", filename="file.png", content_type="image/png")
    assert payload.build_payload(msg(attachments=[att]))["attachments"] == [
        {"url": "https://cdn.example/file.png", "filename": "file.png",
         "content_type": "image/png"}]


@pytest.mark.parametrize("kwargs, answers", [
    ({}, True),
    ({"bot": True}, False),
    ({"author": 777}, False),                       # the bot itself
    ({"content": "   "}, False),
    ({"guild": 9999}, False),
    ({"guild": None}, False),
    ({"channel": 5555}, False),                     # not an ask channel
    ({"channel": THREAD, "parent": ASK}, True),     # thread of the ask channel
    ({"channel": THREAD, "parent": 5555}, False),
])
def test_which_messages_are_answered(kwargs, answers):
    assert payload.should_answer(msg(**kwargs), 777, GUILD, {ASK}) is answers


def test_without_an_ask_channel_every_channel_of_the_server_counts():
    assert payload.should_answer(msg(channel=5555), 777, GUILD, set())
    assert not payload.should_answer(msg(channel=5555, guild=1), 777, GUILD, set())


def test_id_list_parsing():
    assert payload.parse_ids("123, 456;789,abc,") == {123, 456, 789}
    assert payload.parse_ids(None) == set() and payload.parse_ids("") == set()


def test_the_bot_ignores_the_response_body_and_holds_no_secret():
    source = (h.AGENT / "bot" / "bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    awaited = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Await)]
    assert any("response.read" in call for call in awaited)
    assert ".json()" not in source and ".text()" not in source, "the reply body is not used"
    assert "message.reply(" in source and "X-Concho-Token" in source
    for name in ("DISCORD_BOT_TOKEN", "CONCHO_WEBHOOK_URL", "CONCHO_WEBHOOK_TOKEN",
                 "DISCORD_GUILD_ID", "DISCORD_CHANNEL_ID_ASK"):
        assert name in source and name in h.env_vars_in_example() | {"CONCHO_WEBHOOK_URL"}
    compile(source, "bot.py", "exec")
    assert (h.AGENT / "bot" / "requirements.txt").read_text().startswith("discord.py==")
