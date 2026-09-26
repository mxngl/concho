"""Command line interface: ``python -m engines.tvd`` / ``concho-tvd``.

Output layout under ``--out DIR`` (mirrors the AutoTVD repo layout):

- ``DIR/results/<YYYYMMDD_HHMMSS>.json`` and ``DIR/results/latest.json``
- ``DIR/history/`` snapshots (override with ``--history DIR``)
- ``DIR/TVD_Dashboard.html``, or ``DIR/docs/index.html`` with ``--ci``
"""

import argparse
import os
import sys
import webbrowser

from engines.tvd.alert import fire_budget_webhook
from engines.tvd.engine import run_files
from engines.tvd.history import load_history, make_demo_snapshot, save_snapshot
from engines.tvd.results_writer import save_results_json
from engines.tvd.summary import fmt_usd, grand_total_of


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
    parser.add_argument("--arch", metavar="FILE", required=True,
                        help="Architecture take-off CSV (e.g. Architecture_TakeOff.csv)")
    parser.add_argument("--struct", metavar="FILE", required=True,
                        help="Structural take-off CSV (e.g. Structural_Schedule.csv)")
    parser.add_argument("--cost", metavar="FILE", required=True,
                        help="Cost database CSV (AutoTVD cost_data.csv format)")
    parser.add_argument("--out", metavar="DIR", required=True,
                        help="Output folder for results/ and the dashboard")
    parser.add_argument("--history", metavar="DIR",
                        help="History snapshot folder (default: OUT/history)")
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    ci_mode = args.ci
    out_dir = args.out
    history_dir = args.history or os.path.join(out_dir, "history")

    print("AutoTVD Cost Analysis" + (" [CI mode]" if ci_mode else ""))

    # 1–6. Load data, compute line items and cluster summary
    run = run_files(args.arch, args.struct, args.cost)
    results, summary, unmapped_count = run.results, run.summary, run.unmapped_count

    # 6b. Save structured results JSON (timestamped + latest.json)
    results_path = save_results_json(os.path.join(out_dir, "results"), run.results_payload())
    print(f"   Results JSON: {results_path}")

    # 6c. Fire the budget alert webhook if grand total exceeds target
    grand_total = grand_total_of(summary)
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

    # 8. Save explicit snapshot if requested, then load history
    if args.snapshot:
        snap_path = save_snapshot(history_dir, args.snapshot, results, summary, unmapped_count)
        print(f"\n   Snapshot saved: {snap_path}")

    history = load_history(history_dir)
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
                         history)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard saved: {out_path}")
    print(f"History snapshots loaded: {len(history)}")

    # 10. Open in browser (local mode only)
    if not ci_mode:
        webbrowser.open(f"file:///{os.path.abspath(out_path).replace(os.sep, '/')}")
    return 0
