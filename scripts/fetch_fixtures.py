"""Fetch the Island 2026 reference fixtures and verify their checksums (roadmap P2.1).

Two sources (``--source``):

- ``private`` (default via ``auto``): the private repo ``mxngl/concho-fixtures``, a snapshot of
  exactly the files the tests read, cloned at the commit pinned under ``private`` in
  ``tests/fixtures/checksums.json``. The fixture folder itself is the clone, so the layout
  (``AutoTVD/...``, ``AutoSTV/...``, ``IPD_Challenge/...``) is the same as for ``public``.
  Authentication: ``$CONCHO_FIXTURES_TOKEN`` (fine-grained PAT, read-only; CI secret) if set,
  otherwise plain git with your own GitHub login. The token is never printed or stored in
  ``.git/config``. Built by ``scripts/build_fixture_snapshot.py``.
- ``public``: the three original repos (AutoTVD, AutoSTV, IPD_Challenge) at the refs pinned
  under ``repos``. Needed to build the snapshot; removed in roadmap P1.6 when those repos go
  private or are archived.

``auto`` means ``private``; it never falls back to ``public``. If the private repo cannot be
fetched (no token, no access, commit not pinned yet) the script exits 1 under
``CONCHO_REQUIRE_FIXTURES`` or when a token is set, otherwise it prints why and exits 0
(tests that need the fixtures are skipped).

Everything fetched is checked: the commit, every ``MANIFEST.json`` entry (private), and the
sha256 of every file in ``checksums.json`` (``files`` = roadmap §1, ``golden_inputs`` = P2.3).
Any mismatch is fatal (exit code 1). Nothing fetched here may be committed to this repo: the
fixtures contain course workbooks and RSMeans-derived cost data.

The fixture folder is ``--dest``, else ``$CONCHO_FIXTURES_DIR``, else ``.fixtures/`` in the
repo root. An existing clone at the pinned commit is reused (only re-verified).

Usage: ``python scripts/fetch_fixtures.py [--source auto|private|public] [--dest DIR]
[--verify-only] [--private-commit SHA]``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = REPO_ROOT / "tests" / "fixtures" / "checksums.json"
FIXTURES_ENV_VAR = "CONCHO_FIXTURES_DIR"
REQUIRE_ENV_VAR = "CONCHO_REQUIRE_FIXTURES"
TOKEN_ENV_VAR = "CONCHO_FIXTURES_TOKEN"
DEFAULT_DEST = REPO_ROOT / ".fixtures"
FILE_SECTIONS = ("files", "golden_inputs")
MANIFEST_NAME = "MANIFEST.json"

# No CRLF conversion (Windows), otherwise the checksums of text files would not match.
GIT = ["git", "-c", "core.autocrlf=false", "-c", "advice.detachedHead=false"]

# git stderr that retrying cannot fix.
_NO_RETRY = ("authentication failed", "not found", "403", "404", "could not read username")


class FixtureError(RuntimeError):
    pass


class FixturesUnavailable(FixtureError):
    """The fixtures could not be fetched (no access, nothing pinned yet): not a checksum error."""


def _load(path: Path | None = None) -> dict:
    return json.loads((path or CHECKSUMS).read_text(encoding="utf-8"))


def load_manifest(path: Path | None = None) -> dict[str, dict]:
    """The ``public`` source: the three original repos."""
    return _load(path)["repos"]


def load_private_spec(path: Path | None = None) -> dict:
    return _load(path)["private"]


def resolve_dest(dest: str | None) -> Path:
    value = dest or os.environ.get(FIXTURES_ENV_VAR)
    return Path(value).resolve() if value else DEFAULT_DEST


def _redact(text: str) -> str:
    token = os.environ.get(TOKEN_ENV_VAR)
    return text.replace(token, "***") if token else text


def _git(args: list[str], cwd: Path, retries: int = 1) -> str:
    env = None
    if os.environ.get(TOKEN_ENV_VAR) or not sys.stdin.isatty():
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # fail instead of hanging on a prompt
    for attempt in range(retries):
        proc = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, env=env)
        if proc.returncode == 0:
            return proc.stdout.strip()
        if any(s in proc.stderr.lower() for s in _NO_RETRY):
            break
        if attempt + 1 < retries:
            time.sleep(2 ** (attempt + 1))
    # args may carry the token (authenticated URL): never put it into a message.
    raise FixtureError(
        _redact(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}")
    )


def head_commit(target: Path) -> str | None:
    if not (target / ".git").exists():
        return None
    try:
        return _git(["rev-parse", "HEAD"], target)
    except FixtureError:
        return None


def _refspec(ref: str) -> str:
    # A full 40-char SHA is fetched directly; anything else is treated as a tag.
    return ref if _is_sha(ref) else f"refs/tags/{ref}"


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def fetch_repo(name: str, spec: dict, dest: Path) -> None:
    """Public source: shallow-fetch ``spec['ref']`` (tag or commit SHA) into ``dest/name``."""
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
    print(f"{name}: fetching {spec['url']} @ {ref}")
    target.mkdir(parents=True)
    _git(["init", "-q"], target)
    _git(["remote", "add", "origin", spec["url"]], target)
    _git(["fetch", "-q", "--depth", "1", "origin", _refspec(ref)], target, retries=4)
    _git(["checkout", "-q", "FETCH_HEAD"], target)


def _authenticated(url: str, token: str) -> str:
    assert url.startswith("https://github.com/"), url
    return url.replace("https://", f"https://x-access-token:{token}@", 1)


def fetch_private(spec: dict, dest: Path) -> None:
    """Private source: the fixture folder ``dest`` is a shallow clone of the snapshot repo."""
    commit = spec["commit"]
    if not _is_sha(commit):
        raise FixturesUnavailable(
            f"the private fixture commit is not pinned yet (private.commit in {CHECKSUMS.name} is "
            f"{commit!r}). Max pins it after pushing the snapshot to the private repo; to test "
            "a push before that, pass --private-commit SHA."
        )
    current = head_commit(dest)
    if current == commit:
        print(f"private fixtures: present at {current[:7]}, not re-fetched")
        return
    if (dest / ".git").exists() or any(dest.iterdir()):
        raise FixtureError(
            f"{dest} is not empty and is not a clone of the private fixtures at {commit[:7]} "
            f"(HEAD: {current or 'none'}), e.g. it holds the public clones. Delete it, or use "
            "--dest for the private fixtures, or --source public to keep the public clones."
        )

    token = os.environ.get(TOKEN_ENV_VAR)
    url = spec["url"]
    how = f"${TOKEN_ENV_VAR}" if token else "your git login"
    print(f"private fixtures: fetching {url} @ {commit[:7]} (auth: {how})")
    try:
        _git(["init", "-q"], dest)
        _git(["remote", "add", "origin", url], dest)  # plain URL, the token is never stored
        remote = _authenticated(url, token) if token else "origin"
        try:
            _git(["fetch", "-q", "--depth", "1", remote, commit], dest, retries=4)
        except FixtureError as exc:
            raise FixturesUnavailable(
                f"cannot fetch {url} at {commit[:7]}: {exc}\nCheck that the commit exists and "
                f"that ${TOKEN_ENV_VAR} (or your GitHub login) has read access to the repo."
            ) from None
        _git(["checkout", "-q", "FETCH_HEAD"], dest)
    except FixtureError:
        shutil.rmtree(dest / ".git", ignore_errors=True)  # leave dest clean for the next try
        raise


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_files(name: str, spec: dict, root: Path) -> list[str]:
    """Check the sha256 of every file in ``spec``'s ``files``/``golden_inputs`` under ``root``."""
    problems: list[str] = []
    for section in FILE_SECTIONS:
        for rel, expected in spec.get(section, {}).items():
            path = root / rel
            if not path.is_file():
                problems.append(f"{name}/{rel}: missing")
                continue
            actual = sha256(path)
            if actual != expected:
                problems.append(f"{name}/{rel}: sha256 {actual}, expected {expected}")
    return problems


def verify_repo(name: str, spec: dict, dest: Path) -> list[str]:
    """Public source: return a list of problems (empty if the clone matches the manifest)."""
    target = dest / name
    problems: list[str] = []
    commit = head_commit(target)
    if commit != spec["commit"]:
        problems.append(f"{name}: HEAD is {commit or 'missing'}, expected {spec['commit']}")
    return problems + verify_files(name, spec, target)


def verify_private(spec: dict, repos: dict[str, dict], dest: Path) -> tuple[list[str], int]:
    """Private source: commit, every MANIFEST.json entry, and the checksums.json files.

    Returns (problems, number of files checked).
    """
    problems: list[str] = []
    commit = head_commit(dest)
    if commit != spec["commit"]:
        problems.append(
            f"private fixtures: HEAD is {commit or 'missing'}, expected {spec['commit']}"
        )
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.is_file():
        return [*problems, f"{MANIFEST_NAME} missing in {dest}"], 0
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    root = dest.resolve()
    for entry in entries:
        rel = entry["file"]
        path = (root / rel).resolve()
        if root not in path.parents:
            problems.append(f"{MANIFEST_NAME}: {rel!r} points outside the fixture folder")
        elif not path.is_file():
            problems.append(f"{rel}: missing")
        elif path.stat().st_size != entry["size"]:
            problems.append(f"{rel}: size {path.stat().st_size}, expected {entry['size']}")
        elif (actual := sha256(path)) != entry["sha256"]:
            problems.append(f"{rel}: sha256 {actual}, expected {entry['sha256']}")
    # The reference checksums pinned in this repo (roadmap §1, P2.3) must hold for the snapshot too.
    checked = len(entries)
    for name, repo in repos.items():
        problems.extend(verify_files(name, repo, dest / name))
        checked += sum(len(repo.get(s, {})) for s in FILE_SECTIONS)
    return problems, checked


def _fail(problems: list[str]) -> int:
    print("\nFIXTURE VERIFICATION FAILED:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def run_public(dest: Path, verify_only: bool) -> int:
    manifest = load_manifest()
    problems: list[str] = []
    for name, spec in manifest.items():
        try:
            if not verify_only:
                fetch_repo(name, spec, dest)
        except FixtureError as exc:
            problems.append(_redact(str(exc)))
            continue
        problems.extend(verify_repo(name, spec, dest))
    if problems:
        return _fail(problems)
    count = sum(len(spec.get(s, {})) for spec in manifest.values() for s in FILE_SECTIONS)
    print(f"OK: {len(manifest)} repos at the pinned commits, {count} checksums verified in {dest}")
    return 0


def run_private(dest: Path, verify_only: bool, commit: str | None, soft: bool) -> int:
    spec = dict(load_private_spec())
    if commit:
        spec["commit"] = commit
    try:
        if not verify_only:
            fetch_private(spec, dest)
    except FixturesUnavailable as exc:
        print(f"\nPRIVATE FIXTURES NOT AVAILABLE: {exc}", file=sys.stderr)
        if soft:
            print("Continuing without fixtures: tests that need them will be skipped.",
                  file=sys.stderr)
            return 0
        return 1
    except FixtureError as exc:
        return _fail([_redact(str(exc))])
    problems, checked = verify_private(spec, load_manifest(), dest)
    if problems:
        return _fail(problems)
    print(f"OK: private fixtures at {spec['commit'][:7]}, {checked} checksums verified in {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", choices=("auto", "private", "public"), default="auto",
        help="auto (default) = private; public = the original repos (removed in P1.6)",
    )
    parser.add_argument(
        "--dest", help=f"fixture folder (default: ${FIXTURES_ENV_VAR}, else .fixtures/)"
    )
    parser.add_argument(
        "--verify-only", action="store_true", help="only verify existing fixtures, fetch nothing"
    )
    parser.add_argument(
        "--private-commit", metavar="SHA",
        help="private source: use this commit instead of the pinned one (to test a fresh push)",
    )
    args = parser.parse_args(argv)

    dest = resolve_dest(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    source = args.source
    if source == "auto":
        # Verifying without fetching: public only if that is what is there.
        public_present = (
            (dest / "AutoTVD" / ".git").exists() and not (dest / MANIFEST_NAME).exists()
        )
        source = "public" if args.verify_only and public_present else "private"
    if source == "public":
        return run_public(dest, args.verify_only)
    # Only the implicit default may skip quietly, and not when a token or CI says "required".
    soft = (
        args.source == "auto"
        and not os.environ.get(TOKEN_ENV_VAR)
        and not os.environ.get(REQUIRE_ENV_VAR)
    )
    return run_private(dest, args.verify_only, args.private_commit, soft)


if __name__ == "__main__":
    sys.exit(main())
