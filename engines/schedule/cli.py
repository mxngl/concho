"""``concho-schedule <step> [options]``: one sub-command per pipeline step.

Each step is a module with its own ``main(argv)``; this dispatcher only picks the module, so
``concho-schedule micro-schedule --help`` is the same as
``python -m engines.schedule.core.micro_schedule --help``. Steps are imported lazily.
The order below is the pipeline order (see ``engines/schedule/README.md``).
"""

from __future__ import annotations

import importlib
import sys

# step name -> (module, one-line description)
STEPS: dict[str, tuple[str, str]] = {
    "takt-zones": (
        "engines.schedule.core.takt_zones",
        "Revit schedules -> central BIM model (+ takt zone per element)",
    ),
    "llm-context": (
        "engines.schedule.core.llm_context",
        "central BIM model -> compact LLM context CSV",
    ),
    "alice-inputs": (
        "engines.schedule.adapters.alice.macro_inputs",
        "[ALICE] export workbook -> Macro_Schedule / Tasks / Crew / Equipment CSVs",
    ),
    "prefab-walls": (
        "engines.schedule.adapters.manufacton.prefab_wall_mapping",
        "[Manufacton] exterior walls + curtain panels -> prefab wall groups",
    ),
    "micro-schedule": (
        "engines.schedule.core.micro_schedule",
        "macro schedule x BIM elements -> Micro_Schedule.csv",
    ),
    "alice-p6-xml": (
        "engines.schedule.adapters.alice.p6_xml",
        "[ALICE] micro schedule -> P6 XML task schedule",
    ),
    "fuzor-xml": (
        "engines.schedule.adapters.fuzor.p6_xml",
        "[Fuzor] micro schedule -> 4D P6 XML + Revit build-code map",
    ),
    "manufacton-parts": (
        "engines.schedule.adapters.manufacton.parts_import",
        "[Manufacton] parts import workbook + parts summary",
    ),
    "manufacton-assemblies": (
        "engines.schedule.adapters.manufacton.assembly_import",
        "[Manufacton] assembly import workbook",
    ),
    "manufacton-orders": (
        "engines.schedule.adapters.manufacton.kit_import",
        "[Manufacton] production orders/items + Revit push maps",
    ),
    "delivery-windows": (
        "engines.schedule.core.delivery_windows",
        "daily vs. 3-day vs. weekly delivery analysis",
    ),
    "takt-plan": (
        "engines.schedule.core.takt_planner",
        "room-zone takt plan for one level (CSV, report, HTML)",
    ),
    "takt-viewer": (
        "engines.schedule.viewers.takt_viewer",
        "micro schedule -> takt viewer HTML",
    ),
    "spatial-viewer": (
        "engines.schedule.viewers.spatial_visualizer",
        "micro schedule -> spatial playback HTML",
    ),
}


def usage() -> str:
    width = max(len(name) for name in STEPS)
    lines = [
        "usage: concho-schedule <step> [options]   (concho-schedule <step> --help for options)",
        "",
        "steps (in pipeline order):",
    ]
    lines += [f"  {name:<{width}}  {description}" for name, (_, description) in STEPS.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print(usage())
        return 0
    step, rest = argv[0], argv[1:]
    if step not in STEPS:
        print(f"concho-schedule: unknown step {step!r}\n\n{usage()}", file=sys.stderr)
        return 2
    module = importlib.import_module(STEPS[step][0])
    module.main(rest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
