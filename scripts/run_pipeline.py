"""Tier-1 team pipeline (P5.2 steps 1-4, 6, 7; P5.5 snapshots): validate → TVD → STV →
``results/`` + ``results/index.json`` → static site.

Runs in a **team data repo** made from ``template/`` (``docs/pipeline.md``). The team's
``.github/workflows/pipeline.yml`` calls it, and so do the tests (``tests/pipeline/``), so the
logic can be checked without GitHub Actions. The engines are called through their CLIs
(``python -m engines.cli`` / ``engines.tvd`` / ``engines.stv.cli``) of the installed ``concho``
package; nothing here changes engine results.

Subcommands (each takes ``--repo DIR``, default: the current folder):

- ``validate``: config, cost DB, STV mapping, custom materials, exports, course workbook.
  Prints every problem at once; exit code 1 on any error.
- ``run``: TVD (one run with all architecture + structural exports), STV (one run with all
  exports, so the D15 deduplication of the engines applies; skipped with a note when no course
  STV workbook is found), then ``results/<UTC timestamp>/``, ``results/latest/`` and one new
  entry in ``results/index.json``.
- ``site``: ``site/`` = the static dashboards of ``dashboards/site/`` (overview, TVD, STV; they
  read the JSON files in the browser) + a copy of ``results/`` + the legacy TVD page as
  ``tvd/legacy.html``.
- ``all``: the three in a row (what the tests run).

The course STV workbook comes from ``$COURSE_STV_XLSX``, else from ``course/`` in the team
repo (exactly one ``*.xlsx`` whose name contains ``STV``). A team repo that holds a course
workbook or cost data must be private (``--repo-visibility public`` makes that an error).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

CONFIG_NAME = "project_config.json"
RESULTS_DIR = "results"
SITE_DIR = "site"
WORK_DIR = ".concho-work"
COURSE_DIR = "course"
TVD_HISTORY = "tvd_history"
INDEX_NAME = "index.json"
INDEX_SCHEMA = 1
STV_WORKBOOK_ENV = "COURSE_STV_XLSX"

# Revit add-in export names (docs/model-requirements.md): <model>_<suffix>.
EXPORT_KINDS = {
    "architecture": "_Architecture_TakeOff.csv",
    "structural": "_Structural_Schedule.csv",
    "mep": "_MEP_TakeOff.csv",
    "rooms": "_Room_Boundaries.csv",
}
# Columns the engines cannot do without (a missing column reads as empty in the engines).
REQUIRED_COLUMNS = {
    "architecture": ("ElementId", "Category", "Assembly Code"),
    "structural": ("ElementId", "Category", "Assembly Code"),
    "mep": ("ElementId", "Category"),
    "rooms": (),
}
SNAPSHOT_RE = re.compile(r"\[snapshot:\s*([^\]]+)\]", re.IGNORECASE)


# --------------------------------------------------------------------------- messages


class PipelineError(Exception):
    """A problem that stops the pipeline; the message is shown to the team as is."""


def _in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _escape_annotation(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def error(msg: str) -> None:
    if _in_actions():
        print(f"::error title=Concho pipeline::{_escape_annotation(msg)}")
    else:
        print(f"ERROR: {msg}")


def warning(msg: str) -> None:
    if _in_actions():
        print(f"::warning title=Concho pipeline::{_escape_annotation(msg)}")
    else:
        print(f"warning: {msg}")


def info(msg: str) -> None:
    print(msg, flush=True)


def _group(title: str) -> None:
    print(f"::group::{title}" if _in_actions() else f"\n== {title} ==", flush=True)


def _endgroup() -> None:
    if _in_actions():
        print("::endgroup::", flush=True)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run an engine CLI, echo its output, return the completed process."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    for stream in (proc.stdout, proc.stderr):
        if stream.strip():
            print(stream.rstrip(), flush=True)
    return proc


def _concho(*args: str) -> list[str]:
    return [sys.executable, "-m", "engines.cli", *args]


# --------------------------------------------------------------------------- team repo


@dataclass
class TeamRepo:
    root: Path
    config_path: Path
    config: object  # engines.common.config.ProjectConfig
    config_warnings: list[str]
    cost_db: Path | None
    stv_mapping: Path | None
    custom_materials: Path | None
    exports_dir: Path
    exports: dict[str, list[Path]] = field(default_factory=dict)
    unknown_exports: list[Path] = field(default_factory=list)

    def rel(self, path: Path) -> str:
        """Repo-relative path with forward slashes (for logs, results and the CLIs)."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.name


def load_repo(root: Path) -> TeamRepo:
    """Read ``project_config.json`` and find the team's files (raises PipelineError)."""
    from engines.common.config import validate_config_file

    root = root.resolve()
    config_path = root / CONFIG_NAME
    if not config_path.is_file():
        raise PipelineError(f"{CONFIG_NAME} not found in the repo root ({root.name}/). Copy it "
                            "from the Concho template.")
    report = validate_config_file(str(config_path))
    if not report.ok:
        raise PipelineError(
            f"{CONFIG_NAME} is invalid:\n" + "\n".join(f"  - {e}" for e in report.errors)
            + f"\nCheck it locally with: concho config validate {CONFIG_NAME}")
    config = report.config
    files = config.files

    def _path(value: str | None, default: str | None = None) -> Path | None:
        value = value or default
        return (root / value) if value else None

    stv_mapping = _path(files.stv_mapping)
    if stv_mapping is None and (root / "stv_mapping.csv").is_file():
        stv_mapping = root / "stv_mapping.csv"
    custom = _path(files.custom_materials or config.stv.custom_materials_file)
    repo = TeamRepo(
        root=root,
        config_path=config_path,
        config=config,
        config_warnings=list(report.warnings),
        cost_db=_path(files.cost_db),
        stv_mapping=stv_mapping,
        custom_materials=custom,
        exports_dir=_path(files.exports, "exports"),
    )
    _find_exports(repo)
    return repo


def _find_exports(repo: TeamRepo) -> None:
    repo.exports = {kind: [] for kind in EXPORT_KINDS}
    if not repo.exports_dir.is_dir():
        return
    for path in sorted(repo.exports_dir.rglob("*.csv")):
        if "raw" in path.relative_to(repo.exports_dir).parts[:-1]:
            continue
        for kind, suffix in EXPORT_KINDS.items():
            if path.name.lower().endswith(suffix.lower()):
                repo.exports[kind].append(path)
                break
        else:
            repo.unknown_exports.append(path)


def find_stv_workbook(root: Path) -> Path | None:
    """``$COURSE_STV_XLSX``, else the one ``course/*STV*.xlsx`` of the repo, else None."""
    value = os.environ.get(STV_WORKBOOK_ENV)
    if value:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise PipelineError(f"${STV_WORKBOOK_ENV} points to {value}, which does not exist.")
        return path
    course = root / COURSE_DIR
    if not course.is_dir():
        return None
    found = sorted(p for p in course.glob("*.xlsx") if "stv" in p.name.lower())
    if len(found) > 1:
        raise PipelineError(
            f"several STV workbooks in {COURSE_DIR}/ ({', '.join(p.name for p in found)}); "
            f"keep one, or set ${STV_WORKBOOK_ENV}.")
    return found[0] if found else None


def _cost_db_rows(path: Path) -> int:
    rows = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        lines = (line for line in fh if not line.lstrip().startswith("#"))
        for row in csv.DictReader(lines):
            if any((v or "").strip() for v in row.values() if isinstance(v, str)):
                rows += 1
    return rows


def _read_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh), [])
    return [h.strip() for h in header]


def _count_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return max(sum(1 for _ in csv.reader(fh)) - 1, 0)


# --------------------------------------------------------------------------- validate


def validate(root: Path, visibility: str = "unknown") -> tuple[list[str], list[str]]:
    """Step 1: check everything the run needs. Returns (errors, warnings); prints both."""
    errors: list[str] = []
    warnings: list[str] = []

    _group(f"Validate {CONFIG_NAME}")
    proc = _run(_concho("config", "validate", CONFIG_NAME), cwd=root) \
        if (root / CONFIG_NAME).is_file() else None
    _endgroup()
    try:
        repo = load_repo(root)
    except PipelineError as exc:
        errors.append(str(exc))
        return _report(errors, warnings)
    if proc is not None and proc.returncode != 0:
        errors.append(f"{CONFIG_NAME} is invalid (see the messages above).")

    # Cost DB (TVD)
    _group("Validate the cost DB")
    if repo.cost_db is None:
        errors.append("files.cost_db is not set in project_config.json (TVD needs a cost DB; "
                      'the template uses "cost_db.csv").')
    elif not repo.cost_db.is_file():
        errors.append(f"cost DB {repo.rel(repo.cost_db)} not found (files.cost_db).")
    else:
        proc = _run(_concho("costdb", "validate", repo.rel(repo.cost_db), "--config",
                            CONFIG_NAME), cwd=root)
        if proc.returncode != 0:
            errors.append(f"cost DB {repo.rel(repo.cost_db)} is invalid (see the messages above;"
                          f" format: docs/engines/tvd.md).")
        n_rows = _cost_db_rows(repo.cost_db)
        if n_rows == 0:
            warnings.append(f"cost DB {repo.rel(repo.cost_db)} has no rows: every TVD estimate "
                            "will be $0 until you add your cost data.")
        elif visibility == "public":
            errors.append(f"this repository is PUBLIC and {repo.rel(repo.cost_db)} has "
                          f"{n_rows} row(s) of cost data (RSMeans-based data must not be "
                          "published). Make the repository private (docs/pipeline.md).")
    _endgroup()

    # Course STV workbook
    try:
        workbook = find_stv_workbook(root)
    except PipelineError as exc:
        errors.append(str(exc))
        workbook = None
    if workbook is None:
        warnings.append(f"no course STV workbook (course/*STV*.xlsx or ${STV_WORKBOOK_ENV}): "
                        "STV will be skipped, TVD still runs.")
    elif visibility == "public" and repo.rel(workbook).startswith(f"{COURSE_DIR}/"):
        errors.append(f"this repository is PUBLIC and contains the course workbook "
                      f"{repo.rel(workbook)}. Course workbooks may only be in a private repo.")

    # Exports
    _group("Validate the exports")
    if not repo.exports_dir.is_dir():
        errors.append(f"exports folder {repo.rel(repo.exports_dir)}/ not found "
                      "(files.exports).")
    for path in repo.unknown_exports:
        suffixes = ", ".join(s for k, s in EXPORT_KINDS.items() if k != "rooms")
        warnings.append(f"{repo.rel(path)} is not used: export file names end in {suffixes} "
                        "(the Revit add-in names them so; exports/README.md).")
    readable: dict[str, list[Path]] = {kind: [] for kind in EXPORT_KINDS}
    for kind, paths in repo.exports.items():
        for path in paths:
            try:
                header = _read_header(path)
                rows = _count_rows(path)
            except UnicodeDecodeError:
                errors.append(f"{repo.rel(path)} is not UTF-8 text. Export it again with the "
                              "Concho Revit add-in (do not re-save it in Excel).")
                continue
            missing = [c for c in REQUIRED_COLUMNS[kind] if c not in header]
            if missing:
                errors.append(f"{repo.rel(path)}: column(s) {', '.join(missing)} missing. "
                              "Export it again with the current Concho Revit add-in.")
            if rows == 0:
                warnings.append(f"{repo.rel(path)} has no element rows.")
            readable[kind].append(path)
            info(f"  {repo.rel(path)}: {kind}, {rows} row(s)")
    arch, struct = repo.exports.get("architecture", []), repo.exports.get("structural", [])
    if repo.exports_dir.is_dir() and not arch and not struct:
        errors.append(f"no architecture or structural export in {repo.rel(repo.exports_dir)}/ "
                      "(*_Architecture_TakeOff.csv / *_Structural_Schedule.csv): TVD has "
                      "nothing to price.")
    elif not arch or not struct:
        which = "architecture" if not arch else "structural"
        warnings.append(f"no {which} export: TVD runs with the other one only.")
    for kind in ("architecture", "structural"):
        if len(repo.exports[kind]) > 1:
            warnings.append(f"{len(repo.exports[kind])} {kind} exports: TVD takes one file per "
                            "discipline, so the pipeline joins them into one (STV reads each "
                            "file).")
    _endgroup()

    # STV mapping (with the exports: ties are errors) and custom materials
    _group("Validate the STV mapping and custom materials")
    if repo.stv_mapping is None:
        errors.append("no STV mapping: set files.stv_mapping in project_config.json (the "
                      'template uses "stv_mapping.csv").')
    elif not repo.stv_mapping.is_file():
        errors.append(f"STV mapping {repo.rel(repo.stv_mapping)} not found "
                      "(files.stv_mapping).")
    else:
        cmd = _concho("stvmap", "validate", repo.rel(repo.stv_mapping))
        if workbook is not None:
            cmd += ["--template", str(workbook)]
        for kind in ("architecture", "structural", "mep"):
            if readable[kind]:
                cmd += [f"--{kind}", *(repo.rel(p) for p in readable[kind])]
        if _run(cmd, cwd=root).returncode != 0:
            errors.append(f"STV mapping {repo.rel(repo.stv_mapping)} is invalid or has ties on "
                          "your exports (see the messages above; format: docs/engines/stv.md).")
    if repo.custom_materials is not None:
        if not repo.custom_materials.is_file():
            errors.append(f"custom materials {repo.rel(repo.custom_materials)} not found "
                          "(files.custom_materials).")
        else:
            cmd = _concho("custmat", "validate", repo.rel(repo.custom_materials))
            if workbook is not None:
                cmd += ["--template", str(workbook)]
            if _run(cmd, cwd=root).returncode != 0:
                errors.append(f"custom materials {repo.rel(repo.custom_materials)} are invalid "
                              "(see the messages above).")
    _endgroup()
    return _report(errors, warnings)


def _report(errors: list[str], warnings: list[str]) -> tuple[list[str], list[str]]:
    _group("Validation summary")
    for msg in warnings:
        warning(msg)
    for msg in errors:
        error(msg)
    if errors:
        info(f"\nValidation failed: {len(errors)} error(s), {len(warnings)} warning(s). "
             "Fix the errors above and push again.")
    else:
        info(f"\nValidation passed ({len(warnings)} warning(s)).")
    _endgroup()
    return errors, warnings


# --------------------------------------------------------------------------- run


def snapshot_label(message: str | None, explicit: str | None, ts: str) -> tuple[str, str]:
    """Label of the run and where it came from (P5.5): ``--label``, else ``[snapshot: …]``
    in the commit message, else its first line, else ``Run <timestamp>``."""
    if explicit and explicit.strip():
        return explicit.strip(), "manual"
    if message:
        match = SNAPSHOT_RE.search(message)
        if match and match.group(1).strip():
            return match.group(1).strip(), "snapshot_tag"
        first = message.strip().splitlines()[0].strip() if message.strip() else ""
        if first:
            return first, "commit_message"
    return f"Run {ts}", "default"


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _joined_export(repo: TeamRepo, kind: str, work: Path) -> Path:
    """One TVD input per discipline: the export itself, all exports joined by column name,
    or a header-only file when the discipline has no export."""
    paths = repo.exports[kind]
    if len(paths) == 1:
        return paths[0]
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"joined{EXPORT_KINDS[kind]}"
    columns: list[str] = []
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for name in reader.fieldnames or []:
                if name not in columns:
                    columns.append(name)
            rows.extend(reader)
    if not columns:
        columns = list(REQUIRED_COLUMNS[kind])
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return out


def _run_tvd(repo: TeamRepo, run_dir: Path, work: Path, label: str,
             results_root: Path) -> dict:
    """TVD in CI mode: results JSON + legacy dashboard into ``run_dir/tvd/``."""
    _group("TVD")
    arch = _joined_export(repo, "architecture", work / "tvd_inputs")
    struct = _joined_export(repo, "structural", work / "tvd_inputs")
    out = work / "tvd"
    if out.exists():
        shutil.rmtree(out)
    # The TVD snapshots (history / compare in the TVD dashboard) live in results/tvd_history/;
    # TVD writes into a copy that goes back only after the whole run succeeded (run()).
    history = work / TVD_HISTORY
    if (results_root / TVD_HISTORY).is_dir():
        shutil.copytree(results_root / TVD_HISTORY, history)
    cmd = [sys.executable, "-m", "engines.tvd", "--ci", "--config", CONFIG_NAME,
           "--arch", repo.rel(arch), "--struct", repo.rel(struct), "--out", repo.rel(out),
           "--history", repo.rel(history), f"--snapshot={label}"]
    proc = _run(cmd, cwd=repo.root)
    _endgroup()
    if proc.returncode != 0:
        raise PipelineError("TVD failed (see the TVD output above). Nothing was written to "
                            "results/.")
    tvd_dir = run_dir / "tvd"
    tvd_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out / "results" / "latest.json", tvd_dir / "tvd_results.json")
    shutil.copy2(out / "docs" / "index.html", tvd_dir / "dashboard.html")
    payload = json.loads((tvd_dir / "tvd_results.json").read_text(encoding="utf-8"))
    fin = payload.get("financials", {})
    return {
        "grand_total": fin.get("grand_total"),
        "tvd_target": fin.get("tvd_target"),
        "status": fin.get("status"),
        "unmapped_count": payload.get("meta", {}).get("unmapped_count"),
    }


def _run_stv(repo: TeamRepo, run_dir: Path, workbook: Path | None) -> tuple[dict | None, str]:
    if workbook is None:
        note = (f"STV skipped: no course STV workbook (course/*STV*.xlsx or "
                f"${STV_WORKBOOK_ENV}).")
        warning(note)
        return None, note
    stv_exports = {k: repo.exports[k] for k in ("architecture", "structural", "mep")}
    if not any(stv_exports.values()):
        note = "STV skipped: no architecture, structural or MEP export."
        warning(note)
        return None, note
    _group("STV")
    out = run_dir / "stv"
    cmd = [sys.executable, "-m", "engines.stv.cli", "--config", CONFIG_NAME,
           "--template", repo.rel(workbook) if workbook.is_relative_to(repo.root) else
           str(workbook), "--output-dir", repo.rel(out)]
    if repo.stv_mapping is not None:
        cmd += ["--stv-mapping", repo.rel(repo.stv_mapping)]
    flags = {"architecture": "--architecture-schedule", "structural": "--structural-schedule",
             "mep": "--mep-schedule"}
    for kind, paths in stv_exports.items():
        if paths:
            cmd += [flags[kind], *(repo.rel(p) for p in paths)]
    proc = _run(cmd, cwd=repo.root)
    _endgroup()
    if proc.returncode != 0:
        raise PipelineError("STV failed (see the STV output above).")
    return stv_summary(json.loads((out / "stv_results.json").read_text(encoding="utf-8"))), ""


def stv_summary(payload: dict) -> dict:
    """Totals of an STV results JSON for the snapshot index (life cycle and embodied)."""
    carbon = payload.get("metric_summary", {}).get("carbon", {})
    embodied = payload.get("breakdown", {}).get("embodied", {})
    return {
        "life_cycle_kgco2e": carbon.get("project"),
        "target_kgco2e": carbon.get("target"),
        "embodied_kgco2e": embodied.get("carbon"),
    }


def load_index(results_root: Path) -> dict:
    path = results_root / INDEX_NAME
    if path.is_file():
        index = json.loads(path.read_text(encoding="utf-8"))
        index.setdefault("snapshots", [])
        return index
    return {"schema": INDEX_SCHEMA, "snapshots": []}


def run(root: Path, *, label: str | None = None, commit: str | None = None,
        commit_message: str | None = None, now: datetime | None = None) -> dict:
    """Steps 2-4: TVD, STV, results/<ts>/, results/latest/, results/index.json.

    Returns the new index entry."""
    repo = load_repo(root)
    now = now or datetime.now(UTC)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    results_root = repo.root / RESULTS_DIR
    run_dir = results_root / ts
    if run_dir.exists():
        raise PipelineError(f"results/{ts}/ exists already.")
    work = repo.root / WORK_DIR
    if commit is None:
        commit = _git(repo.root, "rev-parse", "HEAD")
    if commit_message is None and commit:
        commit_message = _git(repo.root, "log", "-1", "--format=%B")
    label, label_source = snapshot_label(commit_message, label, ts)
    workbook = find_stv_workbook(repo.root)

    try:
        run_dir.mkdir(parents=True)
        tvd = _run_tvd(repo, run_dir, work, label, results_root)
        stv, stv_note = _run_stv(repo, run_dir, workbook)
        if (results_root / TVD_HISTORY).exists():
            shutil.rmtree(results_root / TVD_HISTORY)
        shutil.copytree(work / TVD_HISTORY, results_root / TVD_HISTORY)
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

    prefix = f"{RESULTS_DIR}/{ts}"
    entry = {
        "id": ts,
        "timestamp": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "commit": commit,
        "label": label,
        "label_source": label_source,
        "exports": [repo.rel(p) for kind in ("architecture", "structural", "mep")
                    for p in repo.exports[kind]],
        "paths": {
            "tvd_results": f"{prefix}/tvd/tvd_results.json",
            "tvd_dashboard": f"{prefix}/tvd/dashboard.html",
            "stv_results": f"{prefix}/stv/stv_results.json" if stv else None,
        },
        "tvd": tvd,
        "stv": stv,
        "stv_note": stv_note or None,
    }
    (run_dir / "run.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")

    latest = results_root / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(run_dir, latest)

    index = load_index(results_root)
    index["schema"] = INDEX_SCHEMA
    index["snapshots"].append(entry)
    index["latest"] = ts
    (results_root / INDEX_NAME).write_text(json.dumps(index, indent=2) + "\n",
                                           encoding="utf-8")
    info(f"\nResults: {prefix}/ (and results/latest/); snapshot '{label}' added to "
         f"results/{INDEX_NAME} ({len(index['snapshots'])} snapshot(s)).")
    info(f"TVD grand total {_money(tvd['grand_total'])} vs target {_money(tvd['tvd_target'])}"
         + (f"; STV life cycle {_num(stv['life_cycle_kgco2e'])} kgCO2e" if stv else
            f"; {stv_note}"))
    return entry


# --------------------------------------------------------------------------- site


def _money(value) -> str:
    return "–" if value is None else f"${value:,.0f}"


def _num(value) -> str:
    return "–" if value is None else f"{value:,.0f}"


SITE_PACKAGE = "dashboards"
SITE_SUBDIR = "site"


def _copy_site_files(dest: Path) -> None:
    """Copy the static dashboard (``dashboards/site/``, P7) into ``dest``.

    Read through ``importlib.resources`` so it works from an installed (non-editable)
    package as well as from the source tree; ``pyproject.toml`` ships the files as package
    data of ``dashboards``."""
    from importlib import resources

    try:
        source = resources.files(SITE_PACKAGE) / SITE_SUBDIR
    except ModuleNotFoundError as exc:
        raise PipelineError("The 'dashboards' package of Concho is not installed; install "
                            "concho (pip install \"concho[stv] @ git+…@<tag>\").") from exc
    with resources.as_file(source) as folder:
        if not (folder / "index.html").is_file():
            raise PipelineError(f"The installed Concho package has no dashboard files "
                                f"({SITE_PACKAGE}/{SITE_SUBDIR}/index.html is missing).")
        shutil.copytree(folder, dest, ignore=shutil.ignore_patterns("__pycache__"),
                        dirs_exist_ok=True)


def build_site(root: Path, site: Path | None = None) -> Path:
    """Step 6 (P7.1, P7.2, P7.4): ``site/`` = the static dashboard of ``dashboards/site/``
    (index, ``tvd/``, ``stv/``, shared ``assets/``) + ``results/`` (the JSON files the pages
    fetch) + the legacy TVD page as ``tvd/legacy.html``. Nothing in it is generated from the
    results here: project and team name, numbers and snapshot list are read by the pages."""
    repo = load_repo(root)
    results_root = repo.root / RESULTS_DIR
    index = load_index(results_root)
    snapshots = index.get("snapshots", [])
    if not snapshots:
        raise PipelineError("results/index.json has no snapshots yet: run the pipeline first.")
    site = site or (repo.root / SITE_DIR)
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    _copy_site_files(site)
    shutil.copytree(results_root, site / RESULTS_DIR,
                    ignore=shutil.ignore_patterns(TVD_HISTORY))
    # The previous TVD page, kept for one release (linked from the footer of tvd/).
    legacy = repo.root / snapshots[-1]["paths"]["tvd_dashboard"]
    shutil.copy2(legacy, site / "tvd" / "legacy.html")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    info(f"Site built: {repo.rel(site)}/ ({len(snapshots)} snapshot(s)).")
    return site


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="Concho Tier-1 team pipeline: validate, TVD, STV, results, site.")
    sub = parser.add_subparsers(dest="step", required=True)
    for name, text in (("validate", "check config, DBs, exports and the course workbook"),
                       ("run", "TVD + STV, write results/ and results/index.json"),
                       ("site", "build site/ from results/"),
                       ("all", "validate, run and site")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--repo", default=".", help="team data repo (default: current folder)")
        if name in ("validate", "all"):
            p.add_argument("--repo-visibility", choices=("public", "private", "unknown"),
                           default="unknown",
                           help="public: cost data or a course workbook is an error")
        if name in ("run", "all"):
            p.add_argument("--label", help="snapshot label (default: [snapshot: …] in the "
                                           "commit message, else its first line)")
            p.add_argument("--commit", help="commit SHA (default: git HEAD)")
            p.add_argument("--commit-message", help="commit message (default: git log -1)")
        if name in ("site", "all"):
            p.add_argument("--site", help="output folder (default: REPO/site)")
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    root = Path(args.repo).resolve()
    try:
        if args.step in ("validate", "all"):
            errors, _ = validate(root, args.repo_visibility)
            if errors:
                return 1
        if args.step in ("run", "all"):
            run(root, label=args.label, commit=args.commit,
                commit_message=args.commit_message)
        if args.step in ("site", "all"):
            build_site(root, Path(args.site).resolve() if args.site else None)
    except PipelineError as exc:
        error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
