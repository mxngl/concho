"""Fail if tracked files contain forbidden content (roadmap §0, hard rules 1, 2 and 5).

Checks every file listed by ``git ls-files`` for:
- forbidden file names: course workbooks (``*.xlsx``) and meeting transcripts
  (``*Transcript*``, ``*.vtt``, ``*.vtt.*``);
- forbidden content: GitHub raw tokens, n8n webhook URLs with a UUID path,
  the Hostinger VPS domain and local Windows user paths.

Usage: ``python scripts/check_forbidden.py`` (exit code 1 on any finding).
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

# (name, regex). A bare mention of "GHSAT" in prose is allowed; a token is
# GHSAT immediately followed by token characters.
CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GitHub raw token (GHSAT)", re.compile(r"GHSAT[0-9A-Za-z_]")),
    ("webhook URL with UUID", re.compile(r"webhook(?:-test)?/" + UUID)),
    ("Hostinger VPS domain", re.compile(r"hstgr\.cloud", re.IGNORECASE)),
    ("local Windows user path", re.compile(r"C:\\Users\\", re.IGNORECASE)),
]

# (name, glob), matched case-insensitively against the file name.
PATH_PATTERNS: list[tuple[str, str]] = [
    ("Excel workbook", "*.xlsx"),
    ("transcript", "*transcript*"),
    ("VTT subtitle/transcript", "*.vtt"),
    ("VTT subtitle/transcript", "*.vtt.*"),
]


def check_path(path: str) -> list[str]:
    """Return the names of all path patterns the file name matches."""
    name = Path(path).name.lower()
    return [label for label, glob in PATH_PATTERNS if fnmatch.fnmatchcase(name, glob)]


def check_text(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, pattern_name)`` for every forbidden match in ``text``."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in CONTENT_PATTERNS:
            if pattern.search(line):
                hits.append((lineno, label))
    return hits


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def main(root: Path | None = None) -> int:
    root = root or Path.cwd()
    findings = []
    for path in tracked_files(root):
        for label in check_path(path):
            findings.append(f"{path}: forbidden file ({label})")
        full = root / path
        if not full.is_file():
            continue
        text = full.read_bytes().decode("utf-8", errors="ignore")
        for lineno, label in check_text(text):
            findings.append(f"{path}:{lineno}: forbidden content ({label})")

    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} forbidden item(s) found.", file=sys.stderr)
        return 1
    print("No forbidden content found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
