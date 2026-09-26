"""Fetch the Island 2026 reference fixtures and verify their checksums (roadmap P2.1).

Shallow-clones the three reference repos at the refs pinned in
``tests/fixtures/checksums.json`` into a git-ignored fixture folder, then checks

- that each clone is at the pinned commit, and
- the sha256 of every listed file (``files`` = roadmap §1, ``golden_inputs`` = P2.3).

Any mismatch is fatal (exit code 1). Nothing fetched here may be committed to this repo:
the fixtures contain course workbooks and RSMeans-derived cost data.

The fixture folder is ``--dest``, else ``$CONCHO_FIXTURES_DIR``, else ``.fixtures/`` in the
repo root. Existing clones at the pinned commit are reused (only re-verified).

Usage: ``python scripts/fetch_fixtures.py [--dest DIR] [--verify-only]``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = REPO_ROOT / "tests" / "fixtures" / "checksums.json"
FIXTURES_ENV_VAR = "CONCHO_FIXTURES_DIR"
DEFAULT_DEST = REPO_ROOT / ".fixtures"
FILE_SECTIONS = ("files", "golden_inputs")

# No CRLF conversion (Windows), otherwise the checksums of text files would not match.
GIT = ["git", "-c", "core.autocrlf=false", "-c", "advice.detachedHead=false"]


class FixtureError(RuntimeError):
    pass


def load_manifest(path: Path = CHECKSUMS) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))["repos"]


def resolve_dest(dest: str | None) -> Path:
    value = dest or os.environ.get(FIXTURES_ENV_VAR)
    return Path(value).resolve() if value else DEFAULT_DEST


def _git(args: list[str], cwd: Path, retries: int = 1) -> str:
    for attempt in range(retries):
        proc = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout.strip()
        if attempt + 1 < retries:
            time.sleep(2 ** (attempt + 1))
    raise FixtureError(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}")


def head_commit(target: Path) -> str | None:
    if not (target / ".git").exists():
        return None
    try:
        return _git(["rev-parse", "HEAD"], target)
    except FixtureError:
        return None


def fetch_repo(name: str, spec: dict, dest: Path) -> None:
    """Shallow-fetch ``spec['ref']`` (tag or commit SHA) into ``dest/name``."""
    target = dest / name
    current = head_commit(target)
    if current == spec["commit"]:
        print(f"{name}: present at {current[:7]}, not re-fetched")
        return
    if target.exists():
        raise FixtureError(
            f"{target} exists but is not a clone at {spec['commit'][:7]} "
            f"(HEAD: {current or 'none'}). Delete it and run this script again."
        )

    ref = spec["ref"]
    # A full 40-char SHA is fetched directly; anything else is treated as a tag.
    refspec = ref if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref) else (
        f"refs/tags/{ref}"
    )
    print(f"{name}: fetching {spec['url']} @ {ref}")
    target.mkdir(parents=True)
    _git(["init", "-q"], target)
    _git(["remote", "add", "origin", spec["url"]], target)
    _git(["fetch", "-q", "--depth", "1", "origin", refspec], target, retries=4)
    _git(["checkout", "-q", "FETCH_HEAD"], target)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_repo(name: str, spec: dict, dest: Path) -> list[str]:
    """Return a list of problems (empty if the clone matches the manifest)."""
    target = dest / name
    problems: list[str] = []
    commit = head_commit(target)
    if commit != spec["commit"]:
        problems.append(f"{name}: HEAD is {commit or 'missing'}, expected {spec['commit']}")
    for section in FILE_SECTIONS:
        for rel, expected in spec.get(section, {}).items():
            path = target / rel
            if not path.is_file():
                problems.append(f"{name}/{rel}: missing")
                continue
            actual = sha256(path)
            if actual != expected:
                problems.append(f"{name}/{rel}: sha256 {actual}, expected {expected}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dest", help=f"fixture folder (default: ${FIXTURES_ENV_VAR}, else .fixtures/)"
    )
    parser.add_argument(
        "--verify-only", action="store_true", help="only verify existing clones, fetch nothing"
    )
    args = parser.parse_args(argv)

    dest = resolve_dest(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    problems: list[str] = []
    for name, spec in manifest.items():
        try:
            if not args.verify_only:
                fetch_repo(name, spec, dest)
        except FixtureError as exc:
            problems.append(str(exc))
            continue
        problems.extend(verify_repo(name, spec, dest))

    if problems:
        print("\nFIXTURE VERIFICATION FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    count = sum(len(spec.get(s, {})) for spec in manifest.values() for s in FILE_SECTIONS)
    print(f"OK: {len(manifest)} repos at the pinned commits, {count} checksums verified in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
