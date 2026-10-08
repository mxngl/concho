"""P7.1, P7.2, P7.4: the static dashboards (``dashboards/site/``) built into a team site by
``run_pipeline.py site``. Data: the INVENTED pipeline fixture plus invented STV results
(``site_builder.py``); no Island or RSMeans data, no course workbook.

Render-free checks: the files are there, every JSON path the JS reads (``assets/paths.js``)
exists in the results the engines write, the package ships the files. The Playwright smoke test
(skipped without Playwright / Chromium) loads the pages and fails on console errors.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from pathlib import Path

import pytest
import run_pipeline
from site_builder import (
    REPO_ROOT,
    SNAPSHOTS,
    _add_stv,
    build_demo_site,
    make_team_repo,
    serve,
)
from stv_fixture import build_stv_results

SITE_SRC = REPO_ROOT / "dashboards" / "site"
JS_PAGES = ("index.js", "tvd.js", "stv.js")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    repo, site = build_demo_site(tmp_path_factory.mktemp("demo"))
    index = json.loads((site / "results" / "index.json").read_text(encoding="utf-8"))
    return repo, site, index


def _load_paths() -> dict:
    text = (SITE_SRC / "assets" / "paths.js").read_text(encoding="utf-8")
    body = text.split("export const PATHS = ", 1)[1].strip().rstrip(";")
    return json.loads(body)


def missing(node, path: str) -> list[str]:
    """Parts of ``path`` (paths.js syntax) that ``node`` lacks. A null on the way stops the
    check (the page treats a null block as absent); an empty list or object has nothing to
    check."""
    head, _, rest = path.partition(".")
    each = head.endswith("[]")
    key = head.removesuffix("[]")
    if key == "*":
        if not isinstance(node, dict):
            return [path]
        children = list(node.values())
    else:
        if not isinstance(node, dict) or key not in node:
            return [path]
        children = [node[key]]
    out = []
    for child in children:
        if each:
            if not isinstance(child, list):
                return [path]
            children_each = child
        else:
            children_each = [child]
        for c in children_each:
            if not rest:
                continue
            if c is None:
                continue
            out += missing(c, rest)
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------------------ the site


def test_site_files(demo):
    repo, site, index = demo
    for name in ("index.html", "tvd/index.html", "stv/index.html", "assets/concho.css",
                 "assets/common.js", "assets/paths.js", "assets/index.js", "assets/tvd.js",
                 "assets/stv.js", "tvd/legacy.html", "results/index.json", ".nojekyll"):
        assert (site / name).is_file(), name
    assert len(index["snapshots"]) == len(SNAPSHOTS)
    for snap in index["snapshots"]:
        assert (site / snap["paths"]["tvd_results"]).is_file()
        if snap["paths"]["stv_results"]:
            assert (site / snap["paths"]["stv_results"]).is_file()
    assert not (site / "results" / "tvd_history").exists()
    latest = index["snapshots"][-1]
    assert (site / "tvd" / "legacy.html").read_bytes() == \
        (repo / latest["paths"]["tvd_dashboard"]).read_bytes()
    # the TVD page links to the legacy page from its footer
    assert 'href: "legacy.html"' in (site / "assets" / "tvd.js").read_text(encoding="utf-8")
    # every file of the source folder is in the site, unchanged
    for src in SITE_SRC.rglob("*"):
        if src.is_file() and "__pycache__" not in src.parts:
            assert (site / src.relative_to(SITE_SRC)).read_bytes() == src.read_bytes()


def test_snapshots_without_stv_have_a_note(demo):
    _, _, index = demo
    first, *_, last = index["snapshots"]
    assert first["stv"] is None and first["paths"]["stv_results"] is None
    assert "STV skipped" in first["stv_note"]
    assert last["stv"] is not None and last["stv_note"] is None


def test_static_files_hold_no_project_values_and_no_cdn():
    """P7.4: project and team name come from the results; nothing external at runtime."""
    config = json.loads((REPO_ROOT / "template" / "project_config.json").read_text("utf-8"))
    forbidden = [config["project"]["name"], config["project"]["team_name"], "Island", "RSMeans"]
    for path in SITE_SRC.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in text, f"{path.name} contains project value {word!r}"
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), \
            f"{path.name} references an external URL"
        assert "innerHTML" not in text, f"{path.name} writes HTML strings"


def test_pipeline_does_not_write_html_strings():
    source = (REPO_ROOT / "scripts" / "run_pipeline.py").read_text(encoding="utf-8")
    assert "<html" not in source and "<table" not in source


# ------------------------------------------------------------------------------ JSON paths


def test_index_paths(demo):
    _, _, index = demo
    for path in _load_paths()["index"]["required"] + _load_paths()["index"]["optional"]:
        assert missing(index, path) == [], path


def test_tvd_paths_in_every_snapshot(demo):
    _, site, index = demo
    paths = _load_paths()["tvd"]
    for snap in index["snapshots"]:
        res = json.loads((site / snap["paths"]["tvd_results"]).read_text("utf-8"))
        for path in paths["required"] + paths["optional"]:
            assert missing(res, path) == [], (snap["label"], path)


def test_stv_paths_in_invented_results(demo):
    _, site, index = demo
    paths = _load_paths()["stv"]
    seen = 0
    for snap in index["snapshots"]:
        if not snap["paths"]["stv_results"]:
            continue
        res = json.loads((site / snap["paths"]["stv_results"]).read_text("utf-8"))
        seen += 1
        for path in paths["required"] + paths["optional"]:
            assert missing(res, path) == [], (snap["label"], path)
    assert seen == 2


def test_stv_units_are_the_engines(demo):
    """P7.2 (from P2.3): energy is MJ and water kg, not kWh and L."""
    js = (SITE_SRC / "assets" / "stv.js").read_text(encoding="utf-8")
    assert 'energy: "MJ"' in js and 'water: "kg"' in js
    assert "kWh" not in js and not re.search(r"\bL\b\)", js)


def test_missing_helper():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "m": {"x": {"k": 1}, "y": {}}, "n": None}
    assert missing(data, "a.b[].c") == []
    assert missing(data, "a.b[].d") == ["d"]
    assert missing(data, "m.*.k") == ["k"]
    assert missing(data, "n.z") == []
    assert missing(data, "q") == ["q"]


def test_every_literal_read_is_declared():
    """Top-level reads in the page code (get(res, "…") / get(idx, "…")) are listed in
    paths.js (as a path or the start of one)."""
    declared = {kind: set(p["required"] + p["optional"]) for kind, p in _load_paths().items()}
    pages = {"index.js": ("idx", "index"), "tvd.js": ("res", "tvd"), "stv.js": ("res", "stv")}
    for name, (var, kind) in pages.items():
        text = (SITE_SRC / "assets" / name).read_text(encoding="utf-8")
        reads = set(re.findall(rf'\bget\({var}, "([^"$]+)"', text))
        assert reads, name
        for read in reads:
            ok = any(d == read or d.startswith((read + ".", read + "[]")) for d in declared[kind])
            assert ok, f"{name} reads {read!r}, not declared in paths.js"


def test_add_stv_replaces_an_existing_result(tmp_path: Path):
    """The demo builder works when the pipeline made results/<id>/stv/ already (with the
    course workbook it does): the invented result replaces it."""
    from datetime import UTC, datetime

    saved = os.environ.pop(run_pipeline.STV_WORKBOOK_ENV, None)
    try:
        repo = make_team_repo(tmp_path)
        entry = run_pipeline.run(repo, label="x", commit="abc",
                                 now=datetime(2027, 1, 1, tzinfo=UTC))
    finally:
        if saved is not None:
            os.environ[run_pipeline.STV_WORKBOOK_ENV] = saved
    stv_dir = repo / "results" / entry["id"] / "stv"
    stv_dir.mkdir(parents=True)
    (stv_dir / "stv_results.json").write_text("{}", encoding="utf-8")
    _add_stv(repo, entry["id"], build_stv_results(tmp_path / "stv_exports"))
    written = json.loads((stv_dir / "stv_results.json").read_text(encoding="utf-8"))
    assert written["team"] == "Example Team"
    index = json.loads((repo / "results" / "index.json").read_text(encoding="utf-8"))
    assert index["snapshots"][0]["stv"]["life_cycle_kgco2e"] > 0


@pytest.mark.skipif(not os.environ.get(run_pipeline.STV_WORKBOOK_ENV),
                    reason="needs the course STV workbook ($COURSE_STV_XLSX)")
def test_stv_paths_in_real_results(tmp_path: Path):
    """With the workbook the real STV engine runs: the paths the page needs are in its JSON."""
    repo = make_team_repo(tmp_path)
    entry = run_pipeline.run(repo, label="real", commit="abc")
    assert entry["paths"]["stv_results"]
    res = json.loads((repo / entry["paths"]["stv_results"]).read_text(encoding="utf-8"))
    for path in _load_paths()["stv"]["required"]:
        assert missing(res, path) == [], path


# ------------------------------------------------------------------------------ packaging


def test_package_data_covers_the_site():
    """The wheel must ship the dashboard files (pipeline.md: known gap of the STV mapping
    table, which is not repeated here)."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["dashboards"]
    base = REPO_ROOT / "dashboards"
    shipped = {p for pattern in patterns for p in base.glob(pattern) if p.is_file()}
    needed = {p for p in SITE_SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert needed <= shipped, sorted(str(p) for p in needed - shipped)


@pytest.mark.skipif(not os.environ.get("CONCHO_PIPELINE_INSTALLED"),
                    reason="only in the CI job 'pipeline' (non-editable install)")
def test_site_files_come_from_the_installed_package(tmp_path: Path):
    import subprocess
    import sys

    code = ("import importlib.resources as r, dashboards; "
            "p = r.files('dashboards') / 'site' / 'index.html'; print(p); print(p.is_file())")
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                         text=True, check=True).stdout.split()
    assert not Path(out[0]).is_relative_to(REPO_ROOT)
    assert out[-1] == "True"


# ------------------------------------------------------------------------------ browser smoke


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    chromium = Path("/opt/pw-browsers/chromium")
    kwargs = {"executable_path": str(chromium)} if chromium.exists() else {}
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(**kwargs)
        except Exception as exc:  # no browser installed
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


def assert_no_placeholder_text(page, where: str) -> None:
    """A null / undefined that reached the DOM shows up as the words "null" or "undefined"."""
    body = page.inner_text("body")
    found = re.findall(r"(?<![A-Za-z])(?:null|undefined|NaN)+(?![A-Za-z])|\[object Object\]", body)
    assert found == [], (where, found)


def _visit(browser, base: str, url: str, width: int = 1100):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: errors.append(f"request failed: {r.url}"))
    page.goto(base + url)
    page.wait_for_selector("#content section, #content .note, #content .cards", timeout=10_000)
    page.wait_for_timeout(200)
    return page, errors


def test_pages_load_without_errors(demo, browser):
    _, site, index = demo
    server = serve(site)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        ids = [s["id"] for s in index["snapshots"]]
        urls = ["/index.html", "/tvd/index.html", "/stv/index.html"] + [
            f"/{page}/index.html?snapshot={i}" for i in ids for page in ("tvd", "stv")]
        for url in urls:
            page, errors = _visit(browser, base, url)
            assert errors == [], (url, errors)
            assert_no_placeholder_text(page, url)
            assert "Example community center" in page.inner_text("#site-header h1")
            assert "Example Team" in page.inner_text("#site-header .sub")
            page.close()
        # latest snapshot has STV; the first one shows its note, not a broken page
        page, errors = _visit(browser, base, f"/stv/index.html?snapshot={ids[0]}")
        text = page.inner_text("#content")
        assert "No STV result" in text and "STV skipped" in text
        page.close()
        page, errors = _visit(browser, base, "/stv/index.html")
        text = page.inner_text("#content")
        assert "kgCO₂e" in text and " MJ" in text and "kWh" not in text
        assert "Proxy materials" in text and "Custom materials" in text
        page.close()
        # the snapshot with a not-modeled use phase warns
        page, _ = _visit(browser, base, f"/stv/index.html?snapshot={ids[1]}")
        assert "Use phase not modeled" in page.inner_text("#content")
        page.close()
        # TVD: compare two snapshots shows cluster deltas; no horizontal scroll on a phone
        page, errors = _visit(browser, base, "/tvd/index.html", width=390)
        assert "Compare two snapshots" in page.inner_text("#content")
        assert page.inner_text("#compare table").count("Substructure") == 1
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert errors == []
        page.close()
    finally:
        server.shutdown()


def test_empty_project_renders(tmp_path: Path, browser):
    """AC of phase 7: a new project without snapshots renders without errors."""
    site = tmp_path / "site"
    shutil.copytree(SITE_SRC, site)
    (site / "results").mkdir()
    (site / "results" / "index.json").write_text(
        json.dumps({"schema": 1, "snapshots": []}), encoding="utf-8")
    server = serve(site)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for url in ("/index.html", "/tvd/index.html", "/stv/index.html"):
            page, errors = _visit(browser, base, url)
            assert errors == [] and "No snapshots yet" in page.inner_text("#content"), url
            page.close()
    finally:
        server.shutdown()


def test_missing_results_show_a_message(tmp_path: Path, browser):
    site = tmp_path / "site"
    shutil.copytree(SITE_SRC, site)
    server = serve(site)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        page = browser.new_page()
        page.goto(base + "/tvd/index.html")
        page.wait_for_selector("#content .note")
        assert "Could not" in page.inner_text("#content")
        page.close()
    finally:
        server.shutdown()


def test_one_snapshot_and_within_tolerance(demo, tmp_path: Path, browser):
    """Every team's first run has one snapshot: no history / compare blocks, and no stray
    "null" text. A target gap within tolerance is an info note, not a warning."""
    _, demo_site, index = demo
    site = tmp_path / "site"
    shutil.copytree(demo_site, site)
    last = index["snapshots"][-1]
    (site / "results" / "index.json").write_text(json.dumps(
        {**index, "snapshots": [last], "latest": last["id"]}), encoding="utf-8")
    tvd_path = site / last["paths"]["tvd_results"]
    tvd = json.loads(tvd_path.read_text(encoding="utf-8"))
    tvd["target_consistency"].update(status="within_tolerance", gap=5852.0, gap_pct=0.0316)
    tvd_path.write_text(json.dumps(tvd), encoding="utf-8")
    server = serve(site)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for url in ("/index.html", "/tvd/index.html", "/stv/index.html"):
            page, errors = _visit(browser, base, url)
            assert errors == [], (url, errors)
            assert_no_placeholder_text(page, url)
            page.close()
        page, _ = _visit(browser, base, "/tvd/index.html")
        text = page.inner_text("#content")
        assert "Compare two snapshots" not in text and "History: all snapshots" not in text
        assert "do not add up" not in text
        assert "A–H differ from the total target by $5,852 (0.032 %), within tolerance" in text
        assert page.locator("#content .note.info", has_text="within tolerance").count() >= 1
        page.close()
        # outside the tolerance (accepted by an override) keeps the warning style
        tvd["target_consistency"].update(status="override", override_reason="invented reason")
        tvd_path.write_text(json.dumps(tvd), encoding="utf-8")
        page, _ = _visit(browser, base, "/tvd/index.html")
        assert "do not add up" in page.inner_text("#content")
        assert page.locator("#content .note:not(.info)", has_text="do not add up").count() == 1
        page.close()
    finally:
        server.shutdown()
