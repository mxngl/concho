"""Top-level ``concho`` command (P3.1).

Subcommands:

- ``concho config validate FILE``: validate a project_config file; prints errors and
  warnings. Exit code 0 when valid (warnings allowed), 1 on any error.
- ``concho config schema``: print the project_config JSON Schema.

The engine CLIs stay separate for now (``concho-tvd``, ``concho-stv``, ``concho-schedule``).
"""

from __future__ import annotations

import argparse
import sys

from engines.common.config import json_schema_text, validate_config_file


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
    return parser


def _validate(path: str) -> int:
    report = validate_config_file(path)
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "config":
        if args.config_command == "validate":
            return _validate(args.file)
        if args.config_command == "schema":
            sys.stdout.write(json_schema_text())
            return 0
    return 1  # pragma: no cover (argparse enforces the subcommands)


if __name__ == "__main__":
    sys.exit(main())
