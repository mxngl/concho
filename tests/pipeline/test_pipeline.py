"""P5.1/P5.2/P5.5: the Tier-1 team pipeline (``scripts/run_pipeline.py``) on a temporary team
repo made from ``template/`` plus the INVENTED data in ``tests/fixtures/pipeline_team/``.

No Island data, no RSMeans data, no course workbook is committed. STV runs only when
``$COURSE_STV_XLSX`` points to the course STV workbook; without it the pipeline skips STV
with a note, and the tests check that note instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pipeline_team"
SCRIPT = REPO_ROOT / "scripts" / "run_pipeline.py"
WORKBOOK = os.environ.get("COURSE_STV_XLSX")
# 27 CF × 2 × 20 + 1,000 SF × 15 + 720 SF × 40 + 600 SF × 10 + 1,000 (fixture README)
GRAND_TOTAL = 51_880.00


@pytest.fixture
def team(tmp_path: Path) -> Path:
    """A team repo: the template with the invented exports and cost DB on top."""
    repo = tmp_path / "team"
    shutil.copytree(TEMPLATE, repo)
    shutil.copytree(FIXTURE / "exports", repo / "exports", dirs_exist_ok=True)
    shutil.copy2(FIXTURE / "cost_db.csv", repo / "cost_db.csv")
    return repo


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    env.update(extra)
    return env


def pipeline(repo: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", str(repo)],
                          cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          env=env or _env())


def _index(repo: Path) -> dict:
    return json.loads((repo / "results" / "index.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ end to end


def test_full_run(team: Path):
    proc = pipeline(team, "all", "--commit", "0123456789abcdef",
                    "--commit-message", "Update exports [snapshot: Design review 1]\n\nbody")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Validation passed" in proc.stdout

    index = _index(team)
    assert index["schema"] == 1
    [snap] = index["snapshots"]
    assert index["latest"] == snap["id"]
    assert snap["label"] == "Design review 1"
    assert snap["label_source"] == "snapshot_tag"
    assert snap["commit"] == "0123456789abcdef"
    assert snap["tvd"]["grand_total"] == pytest.approx(GRAND_TOTAL)
    assert snap["tvd"]["tvd_target"] == 18_500_000
    assert snap["tvd"]["status"] == "under_target"
    assert snap["exports"] == [
        "exports/Demo_ARCH_Architecture_TakeOff.csv",
        "exports/Demo_STR_Structural_Schedule.csv",
        "exports/Demo_MEP_MEP_TakeOff.csv",
    ]

    run_dir = team / "results" / snap["id"]
    tvd = json.loads((run_dir / "tvd" / "tvd_results.json").read_text(encoding="utf-8"))
    assert tvd["financials"]["grand_total"] == pytest.approx(GRAND_TOTAL)
    assert tvd["meta"]["duplicates_removed"] == 1  # floor 5004 is in both exports
    assert tvd["meta"]["dnc_count"] == 1
    assert "/tmp" not in json.dumps(tvd) and str(team) not in json.dumps(tvd)
    assert (run_dir / "tvd" / "dashboard.html").is_file()
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8")) == snap
    # results/latest/ is a copy of the run folder
    assert (team / "results" / "latest" / "tvd" / "tvd_results.json").read_bytes() == \
        (run_dir / "tvd" / "tvd_results.json").read_bytes()
    # TVD snapshot for the dashboard history
    assert len(list((team / "results" / "tvd_history").glob("*.json"))) == 1
    assert not (team / ".concho-work").exists()

    if WORKBOOK:
        stv = json.loads((run_dir / "stv" / "stv_results.json").read_text(encoding="utf-8"))
        assert snap["stv"]["life_cycle_kgco2e"] == pytest.approx(
            stv["metric_summary"]["carbon"]["project"])
        assert snap["stv"]["embodied_kgco2e"] > 0
        assert snap["paths"]["stv_results"] == f"results/{snap['id']}/stv/stv_results.json"
        assert snap["stv_note"] is None
    else:
        assert snap["stv"] is None
        assert snap["paths"]["stv_results"] is None
        assert "STV skipped" in snap["stv_note"]
        assert "no course STV workbook" in proc.stdout

    site = team / "site"
    page = (site / "index.html").read_text(encoding="utf-8")
    assert "Design review 1" in page and "$51,880" in page and "0123456" in page
    assert f'href="results/{snap["id"]}/tvd/dashboard.html"' in page
    assert (site / "tvd" / "index.html").read_bytes() == (run_dir / "tvd" /
                                                          "dashboard.html").read_bytes()
    assert (site / "results" / snap["id"] / "tvd" / "tvd_results.json").is_file()
    assert (site / "results" / "index.json").is_file()
    assert not (site / "results" / "tvd_history").exists()
    assert (site / ".nojekyll").is_file()


def test_snapshots_append(team: Path, monkeypatch):
    """P5.5: every run adds a snapshot; the index page lists all of them."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    t1 = datetime(2027, 1, 10, 9, 0, 0, tzinfo=UTC)
    t2 = datetime(2027, 1, 17, 9, 30, 0, tzinfo=UTC)
    first = run_pipeline.run(team, commit="aaa1111", commit_message="First exports", now=t1)
    # Second run: one partition wall more (+100 SF × 10)
    arch = team / "exports" / "Demo_ARCH_Architecture_TakeOff.csv"
    arch.write_text(arch.read_text(encoding="utf-8") +
                    "5006,Walls,,Partition,L2,,C1010,Partitions,10,0.5,10,100,50,Gypsum,,\n",
                    encoding="utf-8")
    second = run_pipeline.run(team, commit="bbb2222",
                              commit_message="Week 3 model\n[snapshot: Week 3]", now=t2)
    assert first["id"] == "20270110T090000Z" and second["id"] == "20270117T093000Z"
    assert second["timestamp"] == "2027-01-17T09:30:00Z"

    index = _index(team)
    assert [s["label"] for s in index["snapshots"]] == ["First exports", "Week 3"]
    assert [s["tvd"]["grand_total"] for s in index["snapshots"]] == pytest.approx(
        [GRAND_TOTAL, GRAND_TOTAL + 1_000])
    assert index["latest"] == second["id"]
    assert (team / "results" / first["id"] / "tvd" / "tvd_results.json").is_file()
    latest = json.loads((team / "results" / "latest" / "run.json").read_text(encoding="utf-8"))
    assert latest["id"] == second["id"]
    assert len(list((team / "results" / "tvd_history").glob("*.json"))) == 2

    run_pipeline.build_site(team)
    page = (team / "site" / "index.html").read_text(encoding="utf-8")
    assert "Snapshots (2)" in page
    assert page.index("Week 3") < page.index("First exports")  # newest first
    assert "$52,880" in page


def test_label_from_git(team: Path):
    """Without --commit/--label the pipeline reads HEAD and its message from git."""
    git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    subprocess.run([*git, "init", "-q"], cwd=team, check=True)
    subprocess.run([*git, "add", "-A"], cwd=team, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "New ARCH export\n\nmore text"], cwd=team,
                   check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=team, capture_output=True,
                         text=True, check=True).stdout.strip()
    proc = pipeline(team, "run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    [snap] = _index(team)["snapshots"]
    assert snap["commit"] == sha
    assert snap["label"] == "New ARCH export"
    assert snap["label_source"] == "commit_message"


def test_several_exports_per_discipline(team: Path):
    """TVD takes one file per discipline: two architecture exports are joined by column
    name (STV reads each file)."""
    arch = team / "exports" / "Demo_ARCH_Architecture_TakeOff.csv"
    extra = team / "exports" / "Demo_ARCH2_Architecture_TakeOff.csv"
    extra.write_text("ElementId,Category,Assembly Code,Area\n"
                     "8001,Walls,C1010,50\n", encoding="utf-8")
    assert arch.is_file()
    proc = pipeline(team, "all", "--commit", "c", "--label", "two arch")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 architecture exports" in proc.stdout
    [snap] = _index(team)["snapshots"]
    assert snap["tvd"]["grand_total"] == pytest.approx(GRAND_TOTAL + 500)
    assert "exports/Demo_ARCH2_Architecture_TakeOff.csv" in snap["exports"]


def test_only_architecture_export(team: Path):
    (team / "exports" / "Demo_STR_Structural_Schedule.csv").unlink()
    proc = pipeline(team, "all", "--commit", "c")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no structural export" in proc.stdout
    [snap] = _index(team)["snapshots"]
    # footings gone; floor 5004 still counted from the architecture export
    assert snap["tvd"]["grand_total"] == pytest.approx(GRAND_TOTAL - 1_080)


def test_github_annotations(team: Path):
    (team / "exports" / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    proc = pipeline(team, "validate", env=_env(GITHUB_ACTIONS="true"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "::group::Validate the exports" in proc.stdout
    assert "::warning title=Concho pipeline::exports/notes.csv is not used" in proc.stdout


# ------------------------------------------------------------------------------ validation


def _fails_with(repo: Path, *needles: str, args: tuple[str, ...] = ()):
    proc = pipeline(repo, "validate", *args)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Validation failed" in proc.stdout
    for needle in needles:
        assert needle in proc.stdout, proc.stdout
    assert "Traceback" not in proc.stdout + proc.stderr
    return proc


def test_validate_missing_column(team: Path):
    path = team / "exports" / "Demo_STR_Structural_Schedule.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("Assembly Code,", "Code,")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _fails_with(team, "exports/Demo_STR_Structural_Schedule.csv: column(s) Assembly Code "
                      "missing")


def test_validate_not_utf8(team: Path):
    path = team / "exports" / "Demo_ARCH_Architecture_TakeOff.csv"
    path.write_bytes(path.read_bytes().replace(b"Gypsum", b"Gyps\xfcm"))
    _fails_with(team, "Demo_ARCH_Architecture_TakeOff.csv is not UTF-8")


def test_validate_no_exports(team: Path):
    for path in (team / "exports").glob("*.csv"):
        path.unlink()
    _fails_with(team, "no architecture or structural export")


def test_validate_bad_cost_db(team: Path):
    path = team / "cost_db.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("Substructure,A1010",
                                                             "Nonsense,A1010"),
                    encoding="utf-8")
    _fails_with(team, "cost DB cost_db.csv is invalid")


def test_validate_invalid_config(team: Path):
    path = team / "project_config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["tvd"]
    path.write_text(json.dumps(data), encoding="utf-8")
    _fails_with(team, "project_config.json is invalid")


def test_validate_files_unset(team: Path):
    path = team / "project_config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["files"]["cost_db"] = None
    path.write_text(json.dumps(data), encoding="utf-8")
    _fails_with(team, "files.cost_db is not set")


def test_validate_public_repo_with_cost_data(team: Path):
    _fails_with(team, "this repository is PUBLIC", args=("--repo-visibility", "public"))
    proc = pipeline(team, "validate", "--repo-visibility", "private")
    assert proc.returncode == 0, proc.stdout


def test_validate_public_repo_with_workbook(team: Path, monkeypatch):
    (team / "cost_db.csv").write_text(
        (TEMPLATE / "cost_db.csv").read_text(encoding="utf-8"), encoding="utf-8")
    (team / "course" / "Course_STV_placeholder.xlsx").write_bytes(b"not a real workbook")
    env = {k: v for k, v in _env().items() if k != "COURSE_STV_XLSX"}
    proc = pipeline(team, "validate", "--repo-visibility", "public", env=env)
    assert proc.returncode == 1
    assert "contains the course workbook course/Course_STV_placeholder.xlsx" in proc.stdout


def test_template_as_is_validates(tmp_path: Path):
    """The template itself (empty cost DB, no exports) fails only because there are no
    exports, and warns about the empty cost DB."""
    repo = tmp_path / "team"
    shutil.copytree(TEMPLATE, repo)
    proc = _fails_with(repo, "no architecture or structural export")
    assert "has no rows" in proc.stdout
    assert proc.stdout.count("ERROR:") == 1


def test_run_without_workbook_env_skips_stv(team: Path):
    env = {k: v for k, v in _env().items() if k != "COURSE_STV_XLSX"}
    proc = pipeline(team, "run", "--commit", "c", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    [snap] = _index(team)["snapshots"]
    assert snap["stv"] is None and "STV skipped" in snap["stv_note"]


def test_site_needs_a_run(team: Path):
    proc = pipeline(team, "site")
    assert proc.returncode == 1
    assert "no snapshots yet" in proc.stdout


# ------------------------------------------------------------------------------ units


@pytest.mark.parametrize(("message", "explicit", "expected"), [
    ("Update [snapshot: Scheme A – Week 12]", None, ("Scheme A – Week 12", "snapshot_tag")),
    ("Title line\n\n[Snapshot:  Final ]", None, ("Final", "snapshot_tag")),
    ("Title line\nsecond line", None, ("Title line", "commit_message")),
    ("Title [snapshot: A]", "Manual", ("Manual", "manual")),
    ("", None, ("Run 20270101T000000Z", "default")),
    (None, "  ", ("Run 20270101T000000Z", "default")),
    ("[snapshot: ] Only a title", None, ("[snapshot: ] Only a title", "commit_message")),
])
def test_snapshot_label(message, explicit, expected):
    assert run_pipeline.snapshot_label(message, explicit, "20270101T000000Z") == expected


def test_stv_summary():
    payload = {"metric_summary": {"carbon": {"project": 1234.5, "target": 2000.0}},
               "breakdown": {"embodied": {"carbon": 1000.0}}}
    assert run_pipeline.stv_summary(payload) == {
        "life_cycle_kgco2e": 1234.5, "target_kgco2e": 2000.0, "embodied_kgco2e": 1000.0}


def test_stv_workbook_discovery(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("COURSE_STV_XLSX", raising=False)
    assert run_pipeline.find_stv_workbook(tmp_path) is None
    course = tmp_path / "course"
    course.mkdir()
    (course / "TVD_tool.xlsx").write_bytes(b"")
    assert run_pipeline.find_stv_workbook(tmp_path) is None
    (course / "Course_STV_V1.xlsx").write_bytes(b"")
    assert run_pipeline.find_stv_workbook(tmp_path) == course / "Course_STV_V1.xlsx"
    (course / "old_stv.xlsx").write_bytes(b"")
    with pytest.raises(run_pipeline.PipelineError, match="several STV workbooks"):
        run_pipeline.find_stv_workbook(tmp_path)
    monkeypatch.setenv("COURSE_STV_XLSX", str(course / "missing.xlsx"))
    with pytest.raises(run_pipeline.PipelineError, match="does not exist"):
        run_pipeline.find_stv_workbook(tmp_path)


# ------------------------------------------------------------------------------ template


def test_project_config_matches_example():
    """template/project_config.json is the annotated example with only $schema and the file
    paths changed (so the two cannot drift apart)."""
    config = json.loads((TEMPLATE / "project_config.json").read_text(encoding="utf-8"))
    example = json.loads((TEMPLATE / "project_config.example.json").read_text(encoding="utf-8"))
    assert config["$schema"].startswith("https://raw.githubusercontent.com/mxngl/concho/")
    assert config["$schema"].endswith("/docs/schema/project_config.schema.json")
    assert config["files"] == {**example["files"], "cost_db": "cost_db.csv",
                               "stv_mapping": "stv_mapping.csv",
                               "custom_materials": "custom_materials.csv"}
    for data in (config, example):
        data.pop("$schema")
        data.pop("files")
    assert config == example


def test_template_ships_no_data():
    """P5.1: empty cost DB and custom materials, no exports, no workbooks, no results."""
    for name in ("cost_db.csv", "custom_materials.csv"):
        rows = [line for line in (TEMPLATE / name).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
        assert len(rows) == 1, name  # header only
    assert sorted(p.name for p in (TEMPLATE / "exports").iterdir()) == ["README.md"]
    assert sorted(p.name for p in (TEMPLATE / "course").iterdir()) == [".gitignore",
                                                                      "README.md"]
    assert "*.xlsx" in (TEMPLATE / "course" / ".gitignore").read_text(encoding="utf-8")
    assert not (TEMPLATE / "results").exists()


def test_workflow():
    yaml = pytest.importorskip("yaml")
    text = (TEMPLATE / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert set(triggers["push"]["paths"]) == {
        "exports/**", "project_config.json", "cost_db.csv", "stv_mapping.csv",
        "custom_materials.csv"}
    assert "workflow_dispatch" in triggers
    assert workflow["env"]["CONCHO_VERSION"].startswith("v")
    assert ('pip install "concho[stv] @ git+https://github.com/mxngl/concho@${CONCHO_VERSION}"'
            in text)
    steps = workflow["jobs"]["pipeline"]["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)
    for step in ("run_pipeline.py validate", "run_pipeline.py \"${args[@]}\"",
                 "run_pipeline.py site", "git add results"):
        assert step in runs
    artifact = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
    assert "if" not in artifact  # the dashboard artifact is always uploaded
    assert workflow["jobs"]["deploy"]["if"] == "vars.CONCHO_PAGES != 'off'"
    assert "TODO (P5.2 step 9)" in text


@pytest.mark.skipif(not os.environ.get("CONCHO_PIPELINE_INSTALLED"),
                    reason="only in the CI job 'pipeline' (non-editable install)")
def test_engines_come_from_the_installed_package(tmp_path: Path):
    """The CI job installs concho like a team pipeline does (not editable): the engines and
    their data files must come from site-packages, not from this checkout."""
    code = ("import engines.common.uniformat as u; print(u.UNIFORMAT_CSV); "
            "print(u.UNIFORMAT_CSV.is_file())")
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                         text=True, check=True).stdout.split()
    assert not Path(out[0]).is_relative_to(REPO_ROOT)
    assert out[1] == "True"
