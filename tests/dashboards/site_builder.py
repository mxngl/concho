"""Builds a demo team site from INVENTED data (P7): the pipeline fixture of
``tests/fixtures/pipeline_team/`` through ``scripts/run_pipeline.py``, three snapshots, and
invented STV results (``stv_fixture.py``) added to two of them, because the course workbook
the STV engine needs is never in the repo.

Used by ``test_site.py`` and by ``make_screenshots.py``.
"""

from __future__ import annotations

import csv
import functools
import http.server
import io
import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

import run_pipeline
from stv_fixture import build_stv_results

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pipeline_team"

# (label, UTC time, cost factor, STV): the cost factor scales the invented unit costs so the
# demo totals come near the target of the template config; STV: None = skipped (as without a
# course workbook), "no_use_phase" / "use_phase" = invented results.
SNAPSHOTS = [
    ("Week 1", datetime(2027, 1, 10, 9, 0, 0, tzinfo=UTC), 60, None),
    ("Design review 1", datetime(2027, 1, 17, 9, 30, 0, tzinfo=UTC), 90, "no_use_phase"),
    ("Week 3", datetime(2027, 1, 24, 10, 15, 0, tzinfo=UTC), 105, "use_phase"),
]


def _scaled_cost_db(factor: int) -> str:
    text = (FIXTURE / "cost_db.csv").read_text(encoding="utf-8")
    comments = [ln for ln in text.splitlines() if ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(
        ln for ln in text.splitlines() if not ln.startswith("#")))))
    for row in rows:
        row["unit_cost"] = f"{float(row['unit_cost']) * factor:.2f}"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "\n".join(comments) + "\n" + out.getvalue()


def _add_stv(repo: Path, snap_id: str, results: dict) -> None:
    """What `run_pipeline.py run` does when the course workbook is there, with `results`."""
    results_root = repo / "results"
    stv_dir = results_root / snap_id / "stv"
    stv_dir.mkdir(parents=True)
    (stv_dir / "stv_results.json").write_text(json.dumps(results, indent=2) + "\n",
                                              encoding="utf-8")
    entry = {"stv": run_pipeline.stv_summary(results), "stv_note": None}
    paths = {"stv_results": f"results/{snap_id}/stv/stv_results.json"}
    run_json = results_root / snap_id / "run.json"
    index_json = results_root / "index.json"
    index = json.loads(index_json.read_text(encoding="utf-8"))
    for snap in index["snapshots"]:
        if snap["id"] == snap_id:
            snap.update(entry)
            snap["paths"].update(paths)
            run_json.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    index_json.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    if index["latest"] == snap_id:
        shutil.rmtree(results_root / "latest")
        shutil.copytree(results_root / snap_id, results_root / "latest")


def build_demo_site(work: Path) -> tuple[Path, Path]:
    """Returns (team repo, site folder)."""
    repo = work / "team"
    shutil.copytree(TEMPLATE, repo)
    shutil.copytree(FIXTURE / "exports", repo / "exports", dirs_exist_ok=True)
    for i, (label, when, factor, stv) in enumerate(SNAPSHOTS):
        (repo / "cost_db.csv").write_text(_scaled_cost_db(factor), encoding="utf-8")
        if i == 1:  # one more partition wall: a second kind of change between snapshots
            arch = repo / "exports" / "Demo_ARCH_Architecture_TakeOff.csv"
            arch.write_text(arch.read_text(encoding="utf-8") +
                            "5006,Walls,,Partition,L2,,C1010,Partitions,10,0.5,10,100,50,"
                            "Gypsum,,\n", encoding="utf-8")
        entry = run_pipeline.run(repo, label=label, commit=f"{i + 1:07d}abcdef", now=when)
        if stv:
            results = build_stv_results(work / f"stv_exports_{i}", use_phase=stv == "use_phase",
                                        scale=1.0 + 0.1 * i)
            _add_stv(repo, entry["id"], results)
    site = run_pipeline.build_site(repo)
    return repo, site


def serve(site: Path) -> http.server.ThreadingHTTPServer:
    """Serve ``site`` on a free local port (what ``python -m http.server`` does)."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):  # keep test output quiet
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
