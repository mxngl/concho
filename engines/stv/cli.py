"""Command line interface: ``concho-stv`` / ``python -m engines.stv.cli``.

With ``--config project_config.json`` (P3.2) the course team, the building lifetime and the
use-phase inputs come from the config (``stv`` section); ``--team`` overrides the team.
Without ``--config`` the team comes from ``--team`` or the input JSON, as before.

The config use phase is added to single runs. ``--combine-results`` sums the use phase of
all inputs, so per-trade runs that are combined later should use ``--no-use-phase`` (all
but one). ``--architecture-history-dir`` runs stay construction-only, as before.

Revit exports are mapped with the STV mapping table (P3.6): ``--stv-mapping``, else
``files.stv_mapping`` of ``--config``, else the default table ``template/stv_mapping.csv``
(with a warning). The export flags take one or more files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from engines.common.config import validate_config_file

from .central_bim import load_central_bim_model
from .custom_materials import CustomMaterialsError
from .engine import LIFETIME_YEARS, STVEngine
from .mapping import (
    DEFAULT_MAPPING_PATH,
    ScheduleReport,
    StvMapping,
    StvMappingError,
    StvMappingTieError,
    load_stv_mapping,
)
from .models import STVInputs, STVResults
from .project import STVProjectSettings
from .reference import TEMPLATE_ENV_VAR, STVReferenceData, resolve_template_path
from .revit_architecture import load_architecture_schedule
from .revit_mep import load_mep_schedule
from .revit_structural import load_structural_schedule
from .visualization import export_visualizations
from .workbook_inputs import load_stv_workbook_inputs

ARCHITECTURE_HISTORY_TIMESTAMP_RE = re.compile(
    r"_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})(am|pm)_",
    re.IGNORECASE,
)


def _history_entry(
    results: STVResults,
    *,
    timestamp: str,
    source_file: str | None = None,
    source_path: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "timestamp": timestamp,
        "team": results.team,
        "lifetime_years": results.lifetime_years,
        "metric_summary": results.metric_summary(),
        "breakdown": results.breakdown.to_dict(),
    }
    if source_file is not None:
        entry["source_file"] = source_file
    if source_path is not None:
        entry["source_path"] = source_path
    return entry


def append_results_history(
    output_dir: Path,
    results: STVResults,
    *,
    previous_results: STVResults | None = None,
    previous_timestamp: str | None = None,
) -> Path:
    history_path = output_dir / "history.json"
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    else:
        history = []
        if previous_results is not None:
            history.append(_history_entry(
                previous_results,
                timestamp=previous_timestamp or datetime.now(UTC).isoformat(),
            ))

    history.append(_history_entry(results, timestamp=datetime.now(UTC).isoformat()))
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history_path


def _parse_schedule_timestamp(schedule_path: Path) -> datetime:
    match = ARCHITECTURE_HISTORY_TIMESTAMP_RE.search(schedule_path.name)
    if match:
        date_part, hour_text, minute_text, second_text, meridiem = match.groups()
        hour = int(hour_text)
        if meridiem.lower() == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12

        parsed = datetime.fromisoformat(
            f"{date_part}T{hour:02d}:{minute_text}:{second_text}"
        )
        return parsed.replace(tzinfo=UTC)

    return datetime.fromtimestamp(schedule_path.stat().st_mtime, tz=UTC)


def _run_stv(
    payload: dict[str, object],
    *,
    team: str,
    template_path: str,
    lifetime_years: int = LIFETIME_YEARS,
    reference_data: STVReferenceData | None = None,
) -> STVResults:
    payload["team"] = team
    inputs = STVInputs.from_dict(payload)
    reference_data = reference_data or STVReferenceData.from_workbook(template_path)
    engine = STVEngine(reference_data, lifetime_years=lifetime_years)
    return engine.calculate(inputs)


def _item_dicts(items) -> list[dict[str, object]]:
    return [
        {
            "assembly": item.assembly,
            "material_type": item.material_type,
            "amount": item.amount,
            "estimated_amount": item.estimated_amount,
        }
        for item in items
    ]


def _load_mapping(
    parser: argparse.ArgumentParser,
    mapping_arg: str | None,
    settings: STVProjectSettings | None,
    reference_data: STVReferenceData,
) -> StvMapping:
    """--stv-mapping, else files.stv_mapping of --config, else the default table."""
    if mapping_arg:
        path = Path(mapping_arg)
    elif settings is not None and settings.stv_mapping is not None:
        path = settings.stv_mapping
    else:
        path = DEFAULT_MAPPING_PATH
        print(
            f"warning: no STV mapping given (--stv-mapping or files.stv_mapping of "
            f"--config); using the default table {path}.",
            file=sys.stderr,
        )
    if not path.is_file():
        parser.error(f"STV mapping not found: {path}")
    try:
        mapping = load_stv_mapping(path, catalog=reference_data)
    except StvMappingError as exc:
        parser.error(str(exc))
    for warning in mapping.warnings:
        print(f"warning: {path}: {warning}", file=sys.stderr)
    return mapping


def _schedule_report_dict(reports: list[ScheduleReport]) -> dict[str, object]:
    """Per-discipline item report (several exports of one discipline are listed together)."""
    return {
        "discipline": reports[0].discipline,
        "sources": [r.source for r in reports],
        "mapping": reports[0].mapping_source,
        "mapped_rows": sum(r.mapped_rows for r in reports),
        "skipped_rows": [row for r in reports for row in r.skipped_rows],
        "construction_items": [item for r in reports for item in r.to_dict()[
            "construction_items"]],
    }


def _load_settings(
    parser: argparse.ArgumentParser, config_path: str | None
) -> STVProjectSettings | None:
    """Read the STV settings from --config (errors exit, warnings go to stderr)."""
    if not config_path:
        return None
    report = validate_config_file(config_path)
    if not report.ok:
        parser.error(
            f"invalid project_config {config_path}:\n"
            + "\n".join(f"  - {e}" for e in report.errors)
        )
    try:
        settings = STVProjectSettings.from_config(
            report.config, Path(config_path).resolve().parent
        )
    except CustomMaterialsError as exc:
        parser.error(str(exc))
    for warning in settings.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return settings


def _run_architecture_history(
    schedule_dir: Path,
    *,
    team: str,
    output_dir: Path,
    template_path: str,
    mapping: StvMapping,
    reference_data: STVReferenceData,
    lifetime_years: int = LIFETIME_YEARS,
) -> dict[str, object]:
    schedule_paths = sorted(
        schedule_dir.glob("*.csv"),
        key=_parse_schedule_timestamp,
    )
    if not schedule_paths:
        raise ValueError(f"No architecture schedule CSVs found in {schedule_dir}.")

    history: list[dict[str, object]] = []
    latest_report = None
    latest_results = None
    latest_schedule_path = None

    for schedule_path in schedule_paths:
        report = load_architecture_schedule(schedule_path, mapping)
        payload = {"construction_items": _item_dicts(report.construction_items)}
        results = _run_stv(
            payload, team=team, template_path=template_path, lifetime_years=lifetime_years,
            reference_data=reference_data,
        )
        timestamp = _parse_schedule_timestamp(schedule_path).isoformat()
        history.append(
            _history_entry(
                results,
                timestamp=timestamp,
                source_file=schedule_path.name,
                source_path=str(schedule_path),
            )
        )
        latest_report = report
        latest_results = results
        latest_schedule_path = schedule_path

    assert latest_report is not None
    assert latest_results is not None
    assert latest_schedule_path is not None

    results_path = output_dir / "stv_results.json"
    results_path.write_text(
        json.dumps(latest_results.to_dict(), indent=2),
        encoding="utf-8",
    )

    architecture_report_path = output_dir / "architecture_schedule_items.json"
    architecture_report_path.write_text(
        json.dumps(latest_report.to_dict(), indent=2),
        encoding="utf-8",
    )

    history_path = output_dir / "history.json"
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    image_paths = export_visualizations(latest_results, output_dir)
    return {
        "results_json": str(results_path),
        "charts": {key: str(path) for key, path in image_paths.items()},
        "history_json": str(history_path),
        "architecture_schedule_items": str(architecture_report_path),
        "history_source_dir": str(schedule_dir),
        "history_source_files": [str(path) for path in schedule_paths],
        "latest_schedule": str(latest_schedule_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sustainable Target Value calculations.")
    parser.add_argument("--input", help="Path to JSON inputs.")
    parser.add_argument(
        "--template",
        default=None,
        help=(
            "Path to the STV Excel workbook used as the reference dataset "
            f"(default: ${TEMPLATE_ENV_VAR}). The course workbook must be supplied locally."
        ),
    )
    parser.add_argument(
        "--config",
        help=(
            "project_config JSON (docs/config.md): course team, lifetime and use-phase "
            "inputs come from its stv section."
        ),
    )
    parser.add_argument(
        "--no-use-phase",
        action="store_true",
        help=(
            "Construction only: ignore stv.use_phase of --config (e.g. for per-trade runs "
            "that are combined later with --combine-results)."
        ),
    )
    parser.add_argument(
        "--team",
        help="Course team row of the STV workbook (overrides stv.course_team of --config).",
    )
    parser.add_argument(
        "--structural-schedule",
        nargs="+",
        action="extend",
        help="Revit structural schedule CSV(s) to convert into embodied STV inputs.",
    )
    parser.add_argument(
        "--mep-schedule",
        nargs="+",
        action="extend",
        help="Revit MEP takeoff CSV(s) to convert into embodied STV inputs.",
    )
    parser.add_argument(
        "--architecture-schedule",
        nargs="+",
        action="extend",
        help="Revit architecture takeoff CSV(s) to convert into embodied STV inputs.",
    )
    parser.add_argument(
        "--stv-mapping",
        help=(
            "STV mapping table (stv_mapping.csv, docs/engines/stv.md) for the Revit exports "
            "(default: files.stv_mapping of --config, else template/stv_mapping.csv)."
        ),
    )
    parser.add_argument(
        "--architecture-history-dir",
        help="Directory of Revit architecture takeoff CSVs to batch into a time-history STV run.",
    )
    parser.add_argument(
        "--central-bim-model",
        help=(
            "Path to a combined central BIM CSV. Rows are mapped with architecture, "
            "structural, or MEP rules based on their source_schedule filename."
        ),
    )
    parser.add_argument(
        "--stv-workbook-input",
        help=(
            "Path to an STV workbook whose selected Construction and Materials rows "
            "and Use Phase inputs should be added to the calculation."
        ),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for result JSON and generated charts.",
    )
    parser.add_argument(
        "--combine-results",
        nargs="+",
        help="Paths to one or more existing stv_results.json files to merge into a project STV.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = _load_settings(parser, args.config)
    lifetime_years = settings.lifetime_years if settings else LIFETIME_YEARS

    if not args.combine_results:
        try:
            args.template = str(resolve_template_path(args.template))
        except FileNotFoundError as exc:
            parser.error(str(exc))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "stv_results.json"
    previous_results = None
    previous_timestamp = None
    if results_path.exists():
        previous_results = STVResults.from_dict(
            json.loads(results_path.read_text(encoding="utf-8"))
        )
        previous_timestamp = datetime.fromtimestamp(
            results_path.stat().st_mtime,
            tz=UTC,
        ).isoformat()

    if args.combine_results:
        result_paths = [Path(path) for path in args.combine_results]
        loaded_results = [
            STVResults.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in result_paths
        ]
        team = args.team or (settings.team if settings else None)
        with_use_phase = [
            str(path) for path, result in zip(result_paths, loaded_results, strict=True)
            if any(result.breakdown.use_phase.to_dict().values())
        ]
        if len(with_use_phase) > 1:
            print(
                "warning: the use phase is summed over "
                f"{len(with_use_phase)} inputs: {', '.join(with_use_phase)}",
                file=sys.stderr,
            )
        combined_results = STVResults.combine(loaded_results, team=team)

        results_path.write_text(
            json.dumps(combined_results.to_dict(), indent=2),
            encoding="utf-8",
        )
        image_paths = export_visualizations(combined_results, output_dir)
        history_path = append_results_history(
            output_dir,
            combined_results,
            previous_results=previous_results,
            previous_timestamp=previous_timestamp,
        )

        response: dict[str, object] = {
            "results_json": str(results_path),
            "charts": {key: str(path) for key, path in image_paths.items()},
            "combined_from": [str(path) for path in result_paths],
            "history_json": str(history_path),
        }
        print(json.dumps(response, indent=2))
        return

    if args.architecture_history_dir:
        team = args.team or (settings.team if settings else None)
        if not team:
            parser.error(
                "Provide a team with --team or --config when using --architecture-history-dir."
            )
        reference_data = STVReferenceData.from_workbook(args.template)
        response = _run_architecture_history(
            Path(args.architecture_history_dir),
            team=team,
            output_dir=output_dir,
            template_path=args.template,
            mapping=_load_mapping(parser, args.stv_mapping, settings, reference_data),
            reference_data=reference_data,
            lifetime_years=lifetime_years,
        )
        print(json.dumps(response, indent=2))
        return

    payload: dict[str, object] = {}
    if args.input:
        input_path = Path(args.input)
        payload = json.loads(input_path.read_text(encoding="utf-8"))

    workbook_payload = None
    if args.stv_workbook_input:
        workbook_payload = load_stv_workbook_inputs(args.stv_workbook_input)
        existing_items = list(payload.get("construction_items", []))
        workbook_items = list(workbook_payload.get("construction_items", []))
        payload["construction_items"] = existing_items + workbook_items
        payload["use_phase"] = workbook_payload.get("use_phase", {})
        if "team" not in payload and workbook_payload.get("team"):
            payload["team"] = workbook_payload["team"]

    reference_data = STVReferenceData.from_workbook(args.template)
    exports = [
        ("structural", args.structural_schedule or [], load_structural_schedule),
        ("mep", args.mep_schedule or [], load_mep_schedule),
        ("architecture", args.architecture_schedule or [], load_architecture_schedule),
    ]
    mapping = None
    if args.central_bim_model or any(paths for _, paths, _ in exports):
        mapping = _load_mapping(parser, args.stv_mapping, settings, reference_data)
    mapped_reports: list[ScheduleReport] = []
    report_files: dict[str, str] = {}

    try:
        if args.central_bim_model:
            central = load_central_bim_model(args.central_bim_model, mapping)
            mapped_reports.append(central.report)
            payload["construction_items"] = list(payload.get("construction_items", [])) + (
                _item_dicts(central.construction_items)
            )
            central_report_path = output_dir / "central_bim_model_stv_items.json"
            central_report_path.write_text(json.dumps(central.to_dict(), indent=2),
                                           encoding="utf-8")
            report_files["central_bim_model_stv_items"] = str(central_report_path)

        for discipline, paths, loader in exports:
            if not paths:
                continue
            reports = [loader(path, mapping) for path in paths]
            mapped_reports += reports
            payload["construction_items"] = list(payload.get("construction_items", [])) + [
                item for report in reports for item in _item_dicts(report.construction_items)
            ]
            report_path = output_dir / f"{discipline}_schedule_items.json"
            report_path.write_text(json.dumps(_schedule_report_dict(reports), indent=2),
                                   encoding="utf-8")
            report_files[f"{discipline}_schedule_items"] = str(report_path)
    except StvMappingTieError as exc:
        parser.error(str(exc))

    if settings is not None and not args.no_use_phase:
        if payload.get("use_phase"):
            print(
                "warning: the use phase from the inputs is replaced by stv.use_phase of "
                "--config.",
                file=sys.stderr,
            )
        payload["use_phase"] = settings.use_phase
    team = args.team or (settings.team if settings else None) or payload.get("team")
    if not team:
        parser.error("Provide a team with --team, --config or in the input JSON.")
    results = _run_stv(
        payload, team=team, template_path=args.template, lifetime_years=lifetime_years,
        reference_data=reference_data,
    )

    results_path.write_text(
        json.dumps(results.to_dict(), indent=2),
        encoding="utf-8",
    )
    image_paths = export_visualizations(results, output_dir)
    history_path = append_results_history(
        output_dir,
        results,
        previous_results=previous_results,
        previous_timestamp=previous_timestamp,
    )

    response: dict[str, object] = {
        "results_json": str(results_path),
        "charts": {key: str(path) for key, path in image_paths.items()},
        "history_json": str(history_path),
    }
    response.update(report_files)
    if mapping is not None:
        response["stv_mapping"] = mapping.source
    if args.stv_workbook_input:
        response["stv_workbook_input"] = str(args.stv_workbook_input)
        response["stv_workbook_construction_item_count"] = len(
            workbook_payload.get("construction_items", []) if workbook_payload else []
        )
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
