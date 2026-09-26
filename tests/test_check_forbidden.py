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
