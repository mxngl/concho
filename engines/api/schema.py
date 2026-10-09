"""SQLite schema of ``concho.db`` (P5.3). Documented in docs/data-api.md.

Every table except ``snapshots`` has a ``snapshot_id``: one database holds all snapshots of a
team repo, so the API can list and compare them. Tier 1 only (D13): no schedule tables yet.
"""

from __future__ import annotations

import sqlite3

from . import SCHEMA_VERSION

TABLES = (
    "meta", "snapshots", "elements", "quantity_summary", "tvd_line_items", "tvd_clusters",
    "stv_items", "stv_summary", "data_quality",
)

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE snapshots (
  snapshot_id   TEXT PRIMARY KEY,   -- results/index.json: id (UTC timestamp)
  timestamp     TEXT NOT NULL,
  commit_sha    TEXT,
  label         TEXT,
  label_source  TEXT,
  project_name  TEXT,
  team_name     TEXT,
  gross_sf      REAL,
  tvd_grand_total REAL,
  tvd_target      REAL,
  tvd_status      TEXT,
  stv_present     INTEGER NOT NULL,           -- 0 when the STV step was skipped
  stv_note        TEXT,
  stv_carbon_life_cycle REAL,
  stv_carbon_target     REAL,
  stv_carbon_embodied   REAL,
  stv_use_phase_modeled INTEGER,
  stv_custom_material   INTEGER,
  stv_proxy             INTEGER,
  elements_status TEXT NOT NULL,              -- loaded | stale | no_exports
  elements_note   TEXT,
  summary_json    TEXT NOT NULL,              -- precomputed summary, < 10 KB
  ingested_at     TEXT NOT NULL
);

CREATE TABLE elements (
  snapshot_id TEXT NOT NULL,
  element_id  TEXT,
  export      TEXT NOT NULL,                  -- export file name
  discipline  TEXT NOT NULL,                  -- architecture | structural | mep
  category    TEXT,                           -- Parts count with their Original Category
  family      TEXT,
  type        TEXT,
  level       TEXT,
  mark        TEXT,
  assembly_code TEXT,                         -- '' = none
  material    TEXT,
  is_part     INTEGER NOT NULL,
  dnc         INTEGER NOT NULL,               -- carries the "do not count" marker
  area_sf     REAL NOT NULL,
  length_lf   REAL NOT NULL,
  volume_cf   REAL NOT NULL,
  qty_issues  INTEGER NOT NULL                -- quantity cells the parser could not read
);
CREATE INDEX elements_snapshot ON elements (snapshot_id, category, level, assembly_code);

CREATE TABLE quantity_summary (               -- category x level x Assembly Code (no DNC rows)
  snapshot_id TEXT NOT NULL,
  category    TEXT NOT NULL,
  level       TEXT NOT NULL,                  -- '' = no level
  ac          TEXT NOT NULL,                  -- '' = no Assembly Code
  elements    INTEGER NOT NULL,
  area_sf     REAL NOT NULL,
  length_lf   REAL NOT NULL,
  volume_cf   REAL NOT NULL,
  PRIMARY KEY (snapshot_id, category, level, ac)
);

CREATE TABLE tvd_line_items (
  snapshot_id TEXT NOT NULL,
  line_no     INTEGER NOT NULL,
  cluster     TEXT NOT NULL,
  ac          TEXT NOT NULL,
  grp         TEXT,
  description TEXT,
  unit        TEXT,
  unit_cost   REAL,
  qty         REAL,
  qty_src     TEXT,
  total       REAL NOT NULL,
  notes       TEXT,
  PRIMARY KEY (snapshot_id, line_no)
);

CREATE TABLE tvd_clusters (
  snapshot_id TEXT NOT NULL,
  cluster     TEXT NOT NULL,
  estimate    REAL NOT NULL,
  target      REAL NOT NULL,
  delta       REAL NOT NULL,
  delta_pct   REAL,
  per_sf      REAL,
  share_of_total REAL,
  line_items  INTEGER NOT NULL,
  PRIMARY KEY (snapshot_id, cluster)
);

CREATE TABLE stv_items (
  snapshot_id   TEXT NOT NULL,
  item_no       INTEGER NOT NULL,
  assembly      TEXT NOT NULL,
  material_type TEXT NOT NULL,
  unit          TEXT,                         -- from the "(sf)" suffix of the material type
  amount        REAL NOT NULL,
  carbon        REAL NOT NULL,                -- embodied, kgCO2e
  energy        REAL NOT NULL,                -- MJ
  water         REAL NOT NULL,                -- kg
  ozone         REAL NOT NULL,                -- kg CFC-11e
  carbon_materials    REAL NOT NULL,
  carbon_transport    REAL NOT NULL,
  carbon_construction REAL NOT NULL,
  carbon_per_unit     REAL,                   -- carbon / amount (what_if)
  estimated_amount    REAL NOT NULL,
  proxy_amount        REAL NOT NULL,
  custom_material     INTEGER NOT NULL,
  custom_material_source TEXT,
  origin              TEXT,
  PRIMARY KEY (snapshot_id, item_no)
);

CREATE TABLE stv_summary (                    -- one row per metric: carbon energy water ozone
  snapshot_id   TEXT NOT NULL,
  metric        TEXT NOT NULL,
  target        REAL,
  project       REAL,                         -- life cycle
  percent_of_target REAL,
  embodied      REAL,
  embodied_materials    REAL,
  embodied_transport    REAL,
  embodied_construction REAL,
  use_phase     REAL,
  use_electricity REAL,
  use_heating   REAL,
  use_water     REAL,
  PRIMARY KEY (snapshot_id, metric)
);

CREATE TABLE data_quality (
  snapshot_id TEXT NOT NULL,
  scope       TEXT NOT NULL,                  -- tvd | stv | elements | cost_db
  metric      TEXT NOT NULL,
  value       REAL,
  total       REAL,
  pct         REAL,
  detail      TEXT,                           -- JSON, small
  PRIMARY KEY (snapshot_id, scope, metric)
);
"""


def connect(path: str, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create(conn: sqlite3.Connection) -> None:
    """Create the tables in an empty database; refuse a database of another schema version."""
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "meta" in have:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            raise ValueError(
                f"concho.db has schema version {row[0] if row else '?'}, this concho has "
                f"{SCHEMA_VERSION}: delete the database and ingest again.")
        return
    conn.executescript(DDL)
    conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()
