"""History snapshots: named run snapshots stored as JSON files in a history folder.

P3.5 (course sheet ``TVD Tracking``): a snapshot can carry an ``event`` label (e.g. "Winter
presentation") and a free-text ``note``; both keys are only written when set, so snapshots
without them (and all older snapshots) keep their format and still load.
:func:`tracking_table` builds the ``tracking`` block of the results JSON from the snapshots.
"""

import copy
import json
import os
import re
from datetime import datetime


def save_snapshot(history_dir: str, label: str, results: list[dict], summary: list[dict],
                  unmapped_count: int, *, event: str | None = None,
                  note: str | None = None) -> str:
    """Save a named run snapshot to ``history_dir`` as a dated JSON file (with the tracking
    ``event`` and ``note`` if given)."""
    os.makedirs(history_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe     = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    path     = os.path.join(history_dir, f"{ts_str}_{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        snapshot = {
            "label":         label,
            "date":          date_str,
            "results":       results,
            "summary":       summary,
            "unmapped_count": unmapped_count,
        }
        if event:
            snapshot["event"] = event
        if note:
            snapshot["note"] = note
        json.dump(snapshot, f, indent=2)
    return path


def load_history(history_dir: str) -> list[dict]:
    """Load all JSON snapshots from ``history_dir``, sorted by filename (oldest first)."""
    if not os.path.isdir(history_dir):
        return []
    versions = []
    for fname in sorted(os.listdir(history_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(history_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                v = json.load(f)
            if "label" in v and "summary" in v:
                versions.append(v)
        except (json.JSONDecodeError, KeyError):
            print(f"   Warning: skipping unreadable history snapshot: {fname}")
    return versions


def _grand_total(summary: list[dict]) -> float:
    return next((r["total"] for r in summary if r.get("cluster") == "GRAND TOTAL"), 0.0)


def tracking_row(date: str, label: str, estimate: float, target: float, *,
                 event: str | None = None, note: str | None = None,
                 current: bool = False) -> dict:
    """One ``TVD Tracking`` row: date, event, estimate and delta = target - estimate."""
    return {
        "date": date,
        "label": label,
        "event": event or None,
        "note": note or None,
        "estimate": round(estimate, 2),
        "delta": round(target - estimate, 2),
        "current": current,
    }


def tracking_table(history: list[dict], target: float, current: dict | None = None) -> dict:
    """The ``tracking`` block of the results JSON (course sheet ``TVD Tracking``).

    One row per history snapshot (oldest first; estimate = its GRAND TOTAL, delta = the
    current total target - estimate, as the course's ``=$D$5-D``), then ``current`` (a row
    from :func:`tracking_row` for this run) unless it is ``None`` because the run was saved
    as the last snapshot (that row is then marked ``current``)."""
    rows = [
        tracking_row(v.get("date", ""), v.get("label", ""), _grand_total(v["summary"]), target,
                     event=v.get("event"), note=v.get("note"))
        for v in history
    ]
    if current is not None:
        rows.append(current)
    elif rows:
        rows[-1]["current"] = True
    return {"target": round(target, 2), "rows": rows}


def make_demo_snapshot(history_dir: str, results: list[dict], unmapped_count: int) -> None:
    """
    Create a demo 'Test Version' snapshot in ``history_dir`` (only called when no
    snapshots exist yet).  A handful of line-item totals are scaled to simulate a
    different design iteration.
    """
    results2 = copy.deepcopy(results)
    scale = {
        "B1010":    0.70,   # Structural Bamboo cheaper → simulate timber swap
        "B2010.CW": 1.30,   # Curtain Wall grew in area
        "D5010":    1.12,   # Electrical systems +12 %
        "D5090":    0.90,   # HVAC savings from passive design
        "C1010":    1.20,   # More partition SF in this iteration
    }
    for r in results2:
        if r["ac"] in scale:
            r["total"] = round(r["total"] * scale[r["ac"]], 2)

    # Rebuild summary from modified line items
    totals: dict[str, float] = {}
    seen: list[str] = []
    for r in results2:
        totals[r["cluster"]] = totals.get(r["cluster"], 0) + r["total"]
        if r["cluster"] not in seen:
            seen.append(r["cluster"])
    summary2 = [{"cluster": c, "total": totals[c]} for c in seen]
    summary2.append({"cluster": "GRAND TOTAL", "total": sum(totals.values())})

    path = save_snapshot(history_dir, "Test Version – Scheme A", results2, summary2,
                         unmapped_count - 73)
    print(f"   Demo history snapshot created: {path}")
