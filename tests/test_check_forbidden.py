from pathlib import Path

import pytest

import check_forbidden as cf

# Forbidden strings are assembled at runtime so this file doesn't trip the check itself.
TOKEN = "GHS" + "AT0AAAAAAAAAAAAAAAAAAAAAAA"
UUID = "ce8a4a9c-1234-4abc-9def-0123456789ab"
VPS = "srv123." + "hstgr" + ".cloud"
WIN_PATH = "C:" + "\\Users\\" + "someone\\repo"


@pytest.mark.parametrize(
    "text",
    [
        f"https://raw.githubusercontent.com/x/y/main/f.json?token={TOKEN}",
        f"https://n8n.example.org/webhook/{UUID}",
        f"https://n8n.example.org/webhook-test/{UUID}",
        f"https://{VPS}/",
        f'"data_source": "{WIN_PATH}"',
    ],
)
def test_forbidden_content_is_detected(text):
    assert cf.check_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "Remove the `?token=" + "GHS" + "AT...` query",
        "the " + "GHS" + "AT token",
        "https://n8n.example.org/webhook/concho",
        "no `C:" + "\\Users` paths in tracked files",
        "C:\\Ashmitha\\QTO.dll",
    ],
)
def test_harmless_mentions_pass(text):
    assert cf.check_text(text) == []


@pytest.mark.parametrize(
    "path",
    [
        "data/CEE_222_STV_V12.xlsx",
        "data/Report.XLSX",
        "Dryrun1-Transcript.txt",
        "meetings/notes_transcript.md",
        "GMT20260419-160103_Recording.transcript.vtt.txt",
        "rec.vtt",
    ],
)
def test_forbidden_paths_are_detected(path):
    assert cf.check_path(path)


@pytest.mark.parametrize(
    "path", ["engines/stv/cli.py", "docs/ROADMAP.md", "data/cost_db.csv"]
)
def test_allowed_paths_pass(path):
    assert cf.check_path(path) == []


def test_repository_is_clean():
    assert cf.main(Path(__file__).resolve().parents[1]) == 0


# Discord snowflake (fake), assembled at runtime so this file doesn't trip the check.
SNOWFLAKE = "1234567890" + "12345678"
AGENT_FILE = "agent/workflows/legacy/island-ai-agent.json"


@pytest.mark.parametrize(
    "text",
    [
        f'"value": "{SNOWFLAKE}",',
        f'"guildId": {SNOWFLAKE}',
        f"https://discord.com/channels/{SNOWFLAKE}/{SNOWFLAKE}",
        "id " + "1" * 17,
        "id " + "9" * 20,
    ],
)
def test_snowflake_detected_under_agent(text):
    assert cf.check_text(text, AGENT_FILE) == [(1, "Discord snowflake ID")]


@pytest.mark.parametrize(
    "text",
    [
        '"value": "={{ $env.DISCORD_GUILD_ID }}",',
        f'"value": "{SNOWFLAKE}", // $env.DISCORD_GUILD_ID',
        '"id": "018e5838-5e9c-4c47-9331-c9fb90103233",',
        '"typeVersion": 1.3,',
        '"position": [1056, 304],',
        "id " + "1" * 16,
        "id " + "1" * 21,
        "abc" + SNOWFLAKE,
        "0." + SNOWFLAKE,
    ],
)
def test_snowflake_harmless_under_agent(text):
    assert cf.check_text(text, AGENT_FILE) == []


def test_snowflake_only_checked_under_agent():
    text = f'"value": "{SNOWFLAKE}"'
    assert cf.check_text(text) == []
    assert cf.check_text(text, "docs/ROADMAP.md") == []
    assert cf.check_text(text, "engines/agent/x.json") == []
    assert cf.check_text(text, "agent/bot.py")
