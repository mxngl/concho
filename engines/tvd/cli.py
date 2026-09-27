"""Command line interface: ``python -m engines.tvd`` / ``concho-tvd``.

Project values (targets, GSF, project/team name) come from ``--config``
(``project_config`` JSON, see ``docs/config.md``). ``--cost`` defaults to ``files.cost_db``
of the config; it is a ``cost_db.csv`` (P3.4, ``docs/engines/tvd.md``) and is validated before
the run (errors stop it; old AutoTVD ``cost_data.csv`` files are converted with
``scripts/migrate_cost_data.py``).

Output layout under ``--out DIR`` (mirrors the AutoTVD repo layout):

- ``DIR/results/<YYYYMMDD_HHMMSS>.json`` and ``DIR/results/latest.json``
- ``DIR/history/`` snapshots (override with ``--history DIR``); ``--event`` / ``--note`` add
  a tracking event and note to the run (snapshot and the results JSON ``tracking`` table)
- ``DIR/TVD_Dashboard.html``, or ``DIR/docs/index.html`` with ``--ci``
"""

import argparse
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from engines.common.config import validate_config_file
from engines.tvd.alert import fire_budget_webhook
from engines.tvd.cost_db import CostDbError
from engines.tvd.engine import run_files
from engines.tvd.history import (
    load_history,
    make_demo_snapshot,
    save_snapshot,
    tracking_row,
    tracking_table,
)
from engines.tvd.results_writer import save_results_json
from engines.tvd.summary import fmt_usd, grand_total_of
from engines.tvd.targets import ProjectTargets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="concho-tvd",
        description="Concho TVD cost analysis (migrated from AutoTVD)",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: write the dashboard to OUT/docs/index.html, skip browser "
             "and demo snapshot",
    )
    parser.add_argument(
        "--snapshot",
        metavar="LABEL",
        help='Save a named snapshot of this run to the history folder before generating '
             'the dashboard. Example: --snapshot "Scheme A – Week 12"',
    )
    parser.add_argument("--event", metavar="LABEL",
                        help='Tracking event of this run (course "TVD Tracking" column EVENT), '
                             'e.g. "Winter presentation"; stored in the snapshot and the '
                             "results JSON tracking table")
    parser.add_argument("--note", metavar="TEXT",
                        help="Free-text note for this run (stored like --event)")
    parser.add_argument("--config", metavar="FILE", required=True,
                        help="project_config JSON with the project values (targets, GSF, "
                             "names); see docs/config.md")
    parser.add_argument("--arch", metavar="FILE", required=True,
                        help="Architecture take-off CSV (e.g. Architecture_TakeOff.csv)")
    parser.add_argument("--struct", metavar="FILE", required=True,
                        help="Structural take-off CSV (e.g. Structural_Schedule.csv)")
    parser.add_argument("--cost", metavar="FILE",
                        help="Cost DB CSV (cost_db.csv format, docs/engines/tvd.md); "
                             "default: files.cost_db of the config")
    parser.add_argument("--out", metavar="DIR", required=True,
                        help="Output folder for results/ and the dashboard")
    parser.add_argument("--history", metavar="DIR",
                        help="History snapshot folder (default: OUT/history)")
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    ci_mode = args.ci
    out_dir = args.out
    history_dir = args.history or os.path.join(out_dir, "history")

    report = validate_config_file(args.config)
    if not report.ok:
        parser.error(f"invalid project_config {args.config}:\n"
                     + "\n".join(f"  - {e}" for e in report.errors))
    config = report.config
    cost_path = args.cost
    if cost_path is None:
        if config.files.cost_db is None:
            parser.error("no cost DB: pass --cost or set files.cost_db in the config")
        cost_path = str(Path(args.config).resolve().parent / config.files.cost_db)

    print("AutoTVD Cost Analysis" + (" [CI mode]" if ci_mode else ""))
    print(f"   Project: {config.project.name} ({config.project.team_name})")
    for warning in report.warnings:
        print(f"   Config warning: {warning}")

    try:
        project = ProjectTargets.from_config(config)
        project.check()
    except (NotImplementedError, ValueError) as exc:
        parser.error(str(exc))
    budget = project.derivation.budget_amount if project.derivation else None
    if budget is not None:
        print(f"   Budget (course formula): {budget:,.2f}; total target "
              f"{project.total_target:,.2f}"
              + (" (above the budget!)" if project.total_target > budget else ""))
    tc = project.target_consistency()
    print(f"   Target consistency: {tc['status']} (A-H + carved-out vs. total "
          f"{tc['gap']:+,.2f}, {tc['gap_pct']:+.4f} %; incl. on-top {tc['gap_incl_on_top']:+,.2f})")

    # 1–6. Load data, compute line items and cluster summary
    # (run.notes repeat the target warnings of the config validation printed above.)
    try:
        run = run_files(args.arch, args.struct, cost_path, project)
    except CostDbError as exc:
        parser.error(f"{exc}\nCheck the file with: concho costdb validate {cost_path}")
    for warning in run.cost_db_validation["warnings"]:
        print(f"   Cost DB warning: {warning}")
    results, summary, unmapped_count = run.results, run.summary, run.unmapped_count

    # 6b. Save an explicit snapshot if requested, then load the history (tracking table)
    if args.snapshot:
        snap_path = save_snapshot(history_dir, args.snapshot, results, summary, unmapped_count,
                                  event=args.event, note=args.note)
        print(f"   Snapshot saved: {snap_path}")
    history = load_history(history_dir)
    grand_total = grand_total_of(summary)
    ts = datetime.now()
    current = None if args.snapshot else tracking_row(
        ts.strftime("%Y-%m-%d"), f"Run {ts:%Y-%m-%d}", grand_total, run.total_target,
        event=args.event, note=args.note, current=True)
    tracking = tracking_table(history, run.total_target, current)

    # 6c. Save structured results JSON (timestamped + latest.json)
    payload = run.results_payload(ts=ts, tracking=tracking)
    results_path = save_results_json(os.path.join(out_dir, "results"), payload)
    print(f"   Results JSON: {results_path}")

    # 6d. Fire the budget alert webhook if grand total exceeds target
    if grand_total > run.total_target:
        fire_budget_webhook(summary, grand_total, run.total_target)

    # 7. Print summary to console
    print()
    print(f"  {'Cluster':<35} {'Total':>14}")
    print("  " + "─" * 51)
    for r in summary:
        marker = " ◄" if r["cluster"] == "GRAND TOTAL" else ""
        print(f"  {r['cluster']:<35} {fmt_usd(r['total']):>14}{marker}")
    print(f"\n  Unmapped elements: {unmapped_count} (no Assembly Code)")
    overall = run.reliability["totals"]["overall"]
    print("  Reliability (overall): " + ", ".join(
        f"{level.replace('_', ' ')} {fmt_usd(amount)}" for level, amount in overall.items()))
    print(f"  Tracking: {len(tracking['rows'])} row(s); this run "
          f"{fmt_usd(grand_total)}, delta (target − estimate) "
          f"{run.total_target - grand_total:+,.2f}")

    # 8. Demo snapshot for the dashboard (local mode, empty history only)
    if not history and not ci_mode:
        print("\n   No history snapshots found — creating demo snapshot...")
        make_demo_snapshot(history_dir, results, unmapped_count)
        history = load_history(history_dir)

    # 9. Generate HTML dashboard (legacy renderer, replaced in P7.1)
    from dashboards.tvd.legacy_render import generate_html

    if ci_mode:
        html_dir = os.path.join(out_dir, "docs")
        out_path = os.path.join(html_dir, "index.html")
    else:
        html_dir = out_dir
        out_path = os.path.join(out_dir, "TVD_Dashboard.html")
    os.makedirs(html_dir, exist_ok=True)

    html = generate_html(results, summary, unmapped_count, run.source,
                         run.targets, run.total_target, run.gross_sf, run.unmapped_rows,
                         history, team_name=run.project.team_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard saved: {out_path}")
    print(f"History snapshots loaded: {len(history)}")

    # 10. Open in browser (local mode only)
    if not ci_mode:
        webbrowser.open(f"file:///{os.path.abspath(out_path).replace(os.sep, '/')}")
    return 0
