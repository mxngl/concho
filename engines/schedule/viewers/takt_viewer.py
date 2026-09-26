from __future__ import annotations

import json
from pathlib import Path
import re

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
PLANNING_ENGINE_DIR = BASE_DIR.parent
ALICE_BIM_MAPPER_DIR = PLANNING_ENGINE_DIR / "ALICE_BIM_mapper"

MICRO_SCHEDULE_PATH = BASE_DIR / "outputs" / "Micro_Schedule.csv"
VIEWER_PATH = BASE_DIR / "outputs" / "Micro_Schedule_Takt_Viewer.html"
ALICE_WORKBOOK_PATH = ALICE_BIM_MAPPER_DIR / "inputs" / "ALICE_macro.xlsx"


WBS_COLORS = {
    "SITE PREPARATION & DEMOLITION": "#64748b",
    "EARTHWORK & BASEMENT": "#a16207",
    "SUPERSTRUCTURE": "#2563eb",
    "ENVELOPE": "#0891b2",
    "MEP INSTALLATION": "#7c3aed",
    "INTERIOR": "#16a34a",
    "SYSTEMS / COMMISSIONING": "#dc2626",
    "UNASSIGNED": "#6b7280",
}


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def level_sort_key(level: object) -> tuple[float, str]:
    text = clean_text(level)
    match = re.search(r"-?\d+", text)
    if match:
        return (float(match.group(0)), text)
    if text.casefold() == "roof":
        return (9000.0, text)
    return (9500.0, text)


def room_sort_key(lane: str) -> tuple[tuple[float, str], float, str]:
    level_match = re.match(r"^(.*?)(?: Room | Zone |$)", lane)
    level = level_match.group(1).strip() if level_match else lane
    room_match = re.search(r"(?:Room|Zone)\s+(-?\d+(?:\.\d+)?)", lane)
    room_number = float(room_match.group(1)) if room_match else 9999.0
    return (level_sort_key(level), room_number, lane)


def fallback_wbs(task_name: str) -> str:
    normalized = task_name.casefold()
    if any(token in normalized for token in ["fencing", "site", "water", "power", "tree", "bleacher", "crane pad"]):
        return "SITE PREPARATION & DEMOLITION"
    if any(token in normalized for token in ["basement", "excavation", "shoring", "footing", "grade beam", "rocking", "backfill", "waterproofing", "utilities", "subgrade"]):
        return "EARTHWORK & BASEMENT"
    if any(token in normalized for token in ["frame", "floor", "roof", "column"]):
        return "SUPERSTRUCTURE"
    if any(token in normalized for token in ["exterior", "glass", "facade", "mesh"]):
        return "ENVELOPE"
    if any(token in normalized for token in ["mep", "electrical", "mechanical", "tab", "systems"]):
        return "MEP INSTALLATION"
    if any(token in normalized for token in ["interior", "ceiling"]):
        return "INTERIOR"
    if any(token in normalized for token in ["inspection", "contingency", "testing", "start-up"]):
        return "SYSTEMS / COMMISSIONING"
    return "UNASSIGNED"


def load_wbs_by_task_id() -> dict[str, str]:
    if not ALICE_WORKBOOK_PATH.exists():
        return {}

    workbook = pd.ExcelFile(ALICE_WORKBOOK_PATH)
    tasks = workbook.parse("Tasks", dtype=str).fillna("")
    wbs = workbook.parse("WBS", dtype=str).fillna("")

    if not {"Id*", "Alice WBS Id*"}.issubset(tasks.columns):
        return {}
    if not {"Alice WBS Id*", "Name*"}.issubset(wbs.columns):
        return {}

    wbs_by_id = {
        clean_text(row["Alice WBS Id*"]): clean_text(row["Name*"]).upper()
        for _, row in wbs.iterrows()
    }
    return {
        clean_text(row["Id*"]): wbs_by_id.get(clean_text(row["Alice WBS Id*"]), "")
        for _, row in tasks.iterrows()
    }


def build_viewer_data() -> tuple[list[dict[str, object]], list[str], list[str], pd.Timestamp, pd.Timestamp]:
    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    micro["element_start_dt"] = pd.to_datetime(micro["element_start"], format="mixed")
    micro["element_end_dt"] = pd.to_datetime(micro["element_end"], format="mixed")

    wbs_by_task_id = load_wbs_by_task_id()
    micro["wbs"] = micro.apply(
        lambda row: wbs_by_task_id.get(clean_text(row["task_id"])) or fallback_wbs(clean_text(row["task_name"])),
        axis=1,
    )
    micro["lane"] = micro.apply(
        lambda row: clean_text(row.get("room_takt_id"))
        or clean_text(row.get("takt_id"))
        or clean_text(row.get("level"))
        or "Unassigned",
        axis=1,
    )

    group_columns = ["micro_task_id", "micro_task_name", "task_id", "task_name", "wbs", "lane", "level"]
    bars = (
        micro.groupby(group_columns, dropna=False)
        .agg(
            start=("element_start_dt", "min"),
            end=("element_end_dt", "max"),
            elements=("element_id", "nunique"),
            room_takt_id=("room_takt_id", "first"),
            takt_id=("takt_id", "first"),
            room_number=("room_number", "first"),
            room_name=("room_name", "first"),
        )
        .reset_index()
    )
    bars = bars[bars["end"] > bars["start"]].copy()

    project_start = bars["start"].min().floor("h")
    project_end = bars["end"].max().ceil("h")
    bars["start_hour"] = (bars["start"] - project_start).dt.total_seconds() / 3600.0
    bars["duration_hour"] = (bars["end"] - bars["start"]).dt.total_seconds() / 3600.0

    lanes = sorted(bars["lane"].map(clean_text).unique(), key=room_sort_key)
    wbs_names = sorted(bars["wbs"].map(clean_text).unique())

    records: list[dict[str, object]] = []
    for _, row in bars.sort_values(["start", "lane", "micro_task_name"], kind="stable").iterrows():
        wbs = clean_text(row["wbs"]) or "UNASSIGNED"
        records.append(
            {
                "taskId": clean_text(row["task_id"]),
                "taskName": clean_text(row["task_name"]),
                "microTaskId": clean_text(row["micro_task_id"]),
                "microTaskName": clean_text(row["micro_task_name"]),
                "wbs": wbs,
                "lane": clean_text(row["lane"]),
                "level": clean_text(row["level"]),
                "start": row["start"].isoformat(),
                "end": row["end"].isoformat(),
                "startHour": round(float(row["start_hour"]), 4),
                "durationHour": round(float(row["duration_hour"]), 4),
                "elements": int(row["elements"]),
                "color": WBS_COLORS.get(wbs, WBS_COLORS["UNASSIGNED"]),
                "roomNumber": clean_text(row["room_number"]),
                "roomName": clean_text(row["room_name"]),
            }
        )

    return records, lanes, wbs_names, project_start, project_end


def build_html() -> str:
    bars, lanes, wbs_names, project_start, project_end = build_viewer_data()
    total_hours = int((project_end - project_start).total_seconds() // 3600)
    hour_width = 18
    row_height = 34
    label_width = 260
    chart_width = max(total_hours * hour_width, 960)
    chart_height = max(len(lanes) * row_height, 240)

    data_json = json.dumps(
        {
            "bars": bars,
            "lanes": lanes,
            "wbsNames": wbs_names,
            "projectStart": project_start.isoformat(),
            "projectEnd": project_end.isoformat(),
            "totalHours": total_hours,
            "hourWidth": hour_width,
            "rowHeight": row_height,
            "labelWidth": label_width,
            "chartWidth": chart_width,
            "chartHeight": chart_height,
            "colors": WBS_COLORS,
        },
        indent=2,
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Micro Schedule Takt Viewer</title>
  <style>
    :root {{
      --label-width: {label_width}px;
      --hour-width: {hour_width}px;
      --row-height: {row_height}px;
      --border: #d7dce3;
      --text: #111827;
      --muted: #64748b;
      --panel: #f8fafc;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      color: var(--text);
      background: #ffffff;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      gap: 18px;
      min-height: 56px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.96);
    }}
    h1 {{
      margin: 0;
      font-size: 17px;
      font-weight: 650;
      white-space: nowrap;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .legend {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin-left: auto;
      min-width: 0;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      color: #334155;
      white-space: nowrap;
    }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 2px;
      border: 1px solid rgba(15, 23, 42, 0.18);
    }}
    .viewport {{
      height: calc(100vh - 56px);
      overflow: auto;
      background:
        linear-gradient(to right, #fff 0, #fff var(--label-width), transparent var(--label-width)),
        #fff;
    }}
    .canvas {{
      position: relative;
      width: {label_width + chart_width}px;
      height: {52 + chart_height}px;
      min-width: 100%;
    }}
    .corner {{
      position: sticky;
      left: 0;
      top: 0;
      z-index: 15;
      width: var(--label-width);
      height: 52px;
      border-right: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      padding: 18px 12px;
      font-size: 12px;
      font-weight: 650;
      color: #334155;
    }}
    .time-axis {{
      position: sticky;
      top: 0;
      left: var(--label-width);
      z-index: 10;
      height: 52px;
      width: {chart_width}px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }}
    .tick {{
      position: absolute;
      top: 0;
      width: 1px;
      height: {52 + chart_height}px;
      background: #edf1f5;
    }}
    .tick.major {{
      background: #cbd5e1;
    }}
    .tick-label {{
      position: absolute;
      top: 8px;
      transform: translateX(4px);
      font-size: 11px;
      color: #475569;
      white-space: nowrap;
    }}
    .lane-label {{
      position: sticky;
      left: 0;
      z-index: 8;
      height: var(--row-height);
      width: var(--label-width);
      border-right: 1px solid var(--border);
      border-bottom: 1px solid #eef2f7;
      background: #fff;
      padding: 9px 12px;
      font-size: 12px;
      color: #1f2937;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .lane-line {{
      position: absolute;
      left: var(--label-width);
      width: {chart_width}px;
      height: 1px;
      background: #eef2f7;
    }}
    .bar {{
      position: absolute;
      height: 20px;
      border-radius: 4px;
      border: 1px solid rgba(15, 23, 42, 0.18);
      color: #fff;
      font-size: 10px;
      line-height: 18px;
      padding: 0 6px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      cursor: default;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.16);
    }}
    .bar:hover {{
      filter: brightness(0.92);
      z-index: 12;
    }}
    .tooltip {{
      position: fixed;
      z-index: 40;
      display: none;
      max-width: 360px;
      padding: 10px 12px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #fff;
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
      font-size: 12px;
      line-height: 1.45;
      pointer-events: none;
    }}
    .tooltip b {{
      display: block;
      margin-bottom: 3px;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Micro Schedule Takt Viewer</h1>
    <div class="meta" id="meta"></div>
    <div class="legend" id="legend"></div>
  </header>
  <main class="viewport">
    <div class="canvas" id="canvas">
      <div class="corner">Takt / Level</div>
      <div class="time-axis" id="timeAxis"></div>
    </div>
  </main>
  <div class="tooltip" id="tooltip"></div>
  <script id="schedule-data" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('schedule-data').textContent);
    const canvas = document.getElementById('canvas');
    const timeAxis = document.getElementById('timeAxis');
    const legend = document.getElementById('legend');
    const tooltip = document.getElementById('tooltip');
    const startDate = new Date(data.projectStart);
    const laneIndex = new Map(data.lanes.map((lane, index) => [lane, index]));

    document.getElementById('meta').textContent =
      `${{data.lanes.length}} lanes | ${{data.bars.length}} bars | ${{data.totalHours}} hours`;

    for (const wbs of data.wbsNames) {{
      const item = document.createElement('div');
      item.className = 'legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'swatch';
      swatch.style.background = data.colors[wbs] || data.colors.UNASSIGNED;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(wbs));
      legend.appendChild(item);
    }}

    for (let hour = 0; hour <= data.totalHours; hour += 1) {{
      const x = data.labelWidth + hour * data.hourWidth;
      const tick = document.createElement('div');
      tick.className = hour % 24 === 0 ? 'tick major' : 'tick';
      tick.style.left = `${{x}}px`;
      tick.style.top = '52px';
      canvas.appendChild(tick);

      if (hour % 24 === 0 || hour === data.totalHours) {{
        const label = document.createElement('div');
        label.className = 'tick-label';
        label.style.left = `${{hour * data.hourWidth}}px`;
        const date = new Date(startDate.getTime() + hour * 3600000);
        label.textContent = `h${{hour}} | ${{date.toLocaleDateString([], {{month: 'short', day: 'numeric'}})}}`;
        timeAxis.appendChild(label);
      }}
    }}

    data.lanes.forEach((lane, index) => {{
      const y = 52 + index * data.rowHeight;
      const label = document.createElement('div');
      label.className = 'lane-label';
      label.style.top = `${{y}}px`;
      label.style.position = 'absolute';
      label.textContent = lane;
      label.title = lane;
      canvas.appendChild(label);

      const line = document.createElement('div');
      line.className = 'lane-line';
      line.style.top = `${{y + data.rowHeight}}px`;
      canvas.appendChild(line);
    }});

    function formatDateTime(value) {{
      return new Date(value).toLocaleString([], {{
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      }});
    }}

    for (const bar of data.bars) {{
      const lane = laneIndex.get(bar.lane);
      if (lane === undefined) continue;
      const el = document.createElement('div');
      el.className = 'bar';
      el.style.left = `${{data.labelWidth + bar.startHour * data.hourWidth}}px`;
      el.style.top = `${{52 + lane * data.rowHeight + 7}}px`;
      el.style.width = `${{Math.max(bar.durationHour * data.hourWidth, 5)}}px`;
      el.style.background = bar.color;
      el.textContent = bar.microTaskName;
      el.dataset.tooltip = `
        <b>${{bar.microTaskName}}</b>
        WBS: ${{bar.wbs}}<br>
        Lane: ${{bar.lane}}<br>
        Task: ${{bar.taskId}} ${{bar.taskName}}<br>
        Start: ${{formatDateTime(bar.start)}}<br>
        End: ${{formatDateTime(bar.end)}}<br>
        Duration: ${{bar.durationHour.toFixed(2)}} hr<br>
        Elements: ${{bar.elements}}
      `;
      el.addEventListener('mousemove', event => {{
        tooltip.innerHTML = el.dataset.tooltip;
        tooltip.style.display = 'block';
        tooltip.style.left = `${{Math.min(event.clientX + 14, window.innerWidth - 380)}}px`;
        tooltip.style.top = `${{Math.min(event.clientY + 14, window.innerHeight - 170)}}px`;
      }});
      el.addEventListener('mouseleave', () => {{
        tooltip.style.display = 'none';
      }});
      canvas.appendChild(el);
    }}
  </script>
</body>
</html>
"""


def main() -> None:
    VIEWER_PATH.parent.mkdir(parents=True, exist_ok=True)
    VIEWER_PATH.write_text(build_html(), encoding="utf-8")
    print(f"Wrote {VIEWER_PATH}")


if __name__ == "__main__":
    main()
