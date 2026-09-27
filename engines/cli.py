"""Top-level ``concho`` command (P3.1).

Subcommands:

- ``concho config validate FILE``: validate a project_config file; prints errors and
  warnings. Exit code 0 when valid (warnings allowed), 1 on any error.
- ``concho config schema``: print the project_config JSON Schema.
- ``concho costdb validate FILE [--config CONFIG]`` (P3.4): validate a TVD ``cost_db.csv``;
  with ``--config``, clusters must be course clusters or ``tvd.custom_clusters`` of that
  config. Exit code 0 when valid (warnings allowed), 1 on any error.
- ``concho costdb schema``: print the JSON Schema of one cost DB row.
- ``concho stvmap validate FILE [--template XLSX] [--architecture CSV ...] [--structural
  CSV ...] [--mep CSV ...]`` (P3.6): validate an STV mapping table (``stv_mapping.csv``).
  ``stv_assembly`` / ``stv_material_type`` are checked against the course LCA catalog of the
  course workbook (``--template`` or ``$COURSE_STV_XLSX``; without it: warning, not checked).
  With Revit exports, every element is matched and ties are reported as errors. Exit code 0
  when valid (warnings allowed), 1 on any error.
- ``concho stvmap schema``: print the JSON Schema of one mapping row.
- ``concho custmat validate FILE [--template XLSX]`` (P3.7): validate a custom materials file
  (``custom_materials.csv``); with the course workbook, names are checked against the course
  catalog (a custom material may not reuse a course name).
- ``concho custmat schema``: print the JSON Schema of one custom material row.

The engine CLIs stay separate for now (``concho-tvd``, ``concho-stv``, ``concho-schedule``).
"""

from __future__ import annotations

import argparse
import os
import sys

from engines.common.config import json_schema_text, validate_config_file
from engines.stv import custom_materials
from engines.stv import mapping as stv_mapping
from engines.tvd import cost_db


class _Parser(argparse.ArgumentParser):
    """Usage errors exit with 1 (like validation errors), not argparse's default 2."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="concho", description="Concho command line tools.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    config = sub.add_parser("config", help="project_config tools")
    config_sub = config.add_subparsers(dest="config_command", required=True, parser_class=_Parser)

    validate = config_sub.add_parser("validate", help="validate a project_config JSON file")
    validate.add_argument("file", help="path to the project_config JSON file")

    config_sub.add_parser("schema", help="print the project_config JSON Schema")

    costdb = sub.add_parser("costdb", help="TVD cost DB tools")
    costdb_sub = costdb.add_subparsers(dest="costdb_command", required=True,
                                       parser_class=_Parser)
    cvalidate = costdb_sub.add_parser("validate", help="validate a cost_db.csv file")
    cvalidate.add_argument("file", help="path to the cost_db.csv file")
    cvalidate.add_argument("--config", metavar="FILE",
                           help="project_config JSON: its tvd.custom_clusters are the only "
                                "allowed non-course clusters")
    costdb_sub.add_parser("schema", help="print the JSON Schema of one cost DB row")

    stvmap = sub.add_parser("stvmap", help="STV mapping table tools")
    stvmap_sub = stvmap.add_subparsers(dest="stvmap_command", required=True,
                                       parser_class=_Parser)
    svalidate = stvmap_sub.add_parser("validate", help="validate an stv_mapping.csv file")
    svalidate.add_argument("file", help="path to the stv_mapping.csv file")
    svalidate.add_argument("--template", metavar="XLSX",
                           help="course STV workbook for the LCA catalog check "
                                "(default: $COURSE_STV_XLSX)")
    for discipline in stv_mapping.DISCIPLINES:
        svalidate.add_argument(f"--{discipline}", metavar="CSV", nargs="+", action="extend",
                               default=[],
                               help=f"Revit {discipline} export(s): report ties on their "
                                    "elements")
    stvmap_sub.add_parser("schema", help="print the JSON Schema of one mapping row")

    custmat = sub.add_parser("custmat", help="STV custom materials tools")
    custmat_sub = custmat.add_subparsers(dest="custmat_command", required=True,
                                         parser_class=_Parser)
    mvalidate = custmat_sub.add_parser("validate",
                                       help="validate a custom_materials.csv file")
    mvalidate.add_argument("file", help="path to the custom_materials.csv file")
    mvalidate.add_argument("--template", metavar="XLSX",
                           help="course STV workbook for the catalog name check "
                                "(default: $COURSE_STV_XLSX)")
    custmat_sub.add_parser("schema", help="print the JSON Schema of one custom material row")
    return parser


def _print_report(path: str, report) -> int:
    for msg in report.errors:
        print(f"error: {msg}")
    for msg in report.warnings:
        print(f"warning: {msg}")
    n_warn = len(report.warnings)
    if report.ok:
        print(f"OK: {path} is valid ({n_warn} warning{'s' if n_warn != 1 else ''}).")
        return 0
    n_err = len(report.errors)
    print(f"INVALID: {path} has {n_err} error{'s' if n_err != 1 else ''}.")
    return 1


def _validate(path: str) -> int:
    return _print_report(path, validate_config_file(path))


def _validate_costdb(path: str, config_path: str | None) -> int:
    custom = None
    if config_path is not None:
        config = validate_config_file(config_path)
        if not config.ok:
            print(f"error: {config_path}: invalid project_config (run concho config validate).")
            return 1
        custom = [c.name for c in config.config.tvd.custom_clusters]
    return _print_report(path, cost_db.validate_cost_db_file(path, custom_clusters=custom))


class _CatalogError(Exception):
    pass


def _course_catalog(template: str | None):
    """Course LCA catalog of --template / $COURSE_STV_XLSX; None if neither is given."""
    from engines.stv.reference import TEMPLATE_ENV_VAR, STVReferenceData, resolve_template_path

    try:
        return STVReferenceData.from_workbook(resolve_template_path(template))
    except FileNotFoundError as exc:
        if template or os.environ.get(TEMPLATE_ENV_VAR):
            print(f"error: {exc}")
            raise _CatalogError from exc
    return None


def _validate_custmat(args) -> int:
    try:
        catalog = _course_catalog(args.template)
    except _CatalogError:
        return 1
    report = custom_materials.validate_custom_materials_file(args.file, catalog=catalog)
    return _print_report(args.file, report)


def _validate_stvmap(args) -> int:
    try:
        catalog = _course_catalog(args.template)
    except _CatalogError:
        return 1
    report = stv_mapping.validate_stv_mapping_file(args.file, catalog=catalog)
    exports = [(d, path) for d in stv_mapping.DISCIPLINES for path in getattr(args, d)]
    if report.ok and exports:
        try:
            report.errors += stv_mapping.check_exports(report.mapping, exports)
        except OSError as exc:
            report.errors.append(f"cannot read export: {exc}")
    return _print_report(args.file, report)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "config":
        if args.config_command == "validate":
            return _validate(args.file)
        if args.config_command == "schema":
            sys.stdout.write(json_schema_text())
            return 0
    if args.command == "costdb":
        if args.costdb_command == "validate":
            return _validate_costdb(args.file, args.config)
        if args.costdb_command == "schema":
            sys.stdout.write(cost_db.json_schema_text())
            return 0
    if args.command == "stvmap":
        if args.stvmap_command == "validate":
            return _validate_stvmap(args)
        if args.stvmap_command == "schema":
            sys.stdout.write(stv_mapping.json_schema_text())
            return 0
    if args.command == "custmat":
        if args.custmat_command == "validate":
            return _validate_custmat(args)
        if args.custmat_command == "schema":
            sys.stdout.write(custom_materials.json_schema_text())
            return 0
    return 1  # pragma: no cover (argparse enforces the subcommands)


if __name__ == "__main__":
    sys.exit(main())
