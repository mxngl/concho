"""Export the project_config JSON Schema and the generated field reference (P3.1).

Writes
- ``docs/schema/project_config.schema.json`` (from ``engines.common.config``) and
- the field reference in ``docs/config.md`` between the ``BEGIN/END GENERATED`` markers.

Usage:
    python scripts/export_config_schema.py          # regenerate both
    python scripts/export_config_schema.py --check  # exit 1 if either is out of date (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines.common.config import json_schema, json_schema_text  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "project_config.schema.json"
DOC_PATH = REPO_ROOT / "docs" / "config.md"
BEGIN = "<!-- BEGIN GENERATED: field reference (python scripts/export_config_schema.py) -->"
END = "<!-- END GENERATED -->"


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if ref:
        return defs[ref.split("/")[-1]]
    return node


def _type_of(node: dict[str, Any], defs: dict[str, Any]) -> str:
    if "$ref" in node:
        target = _resolve(node, defs)
        return _type_of(target, defs) if "enum" in target else "object"
    if "const" in node:
        return f"`{json.dumps(node['const'])}`"
    if "enum" in node:
        return " \\| ".join(f"`{json.dumps(v)}`" for v in node["enum"])
    for key in ("anyOf", "oneOf"):
        if key in node:
            return " \\| ".join(_type_of(n, defs) for n in node[key])
    t = node.get("type", "any")
    if t == "array":
        return f"list of {_type_of(node.get('items', {}), defs)}"
    if t == "object" and "additionalProperties" in node and node["additionalProperties"]:
        keys = node.get("propertyNames", {})
        key_t = _type_of(_resolve(keys, defs), defs) if keys else "string"
        return f"map {key_t} → {_type_of(node['additionalProperties'], defs)}"
    if t == "object" and "patternProperties" in node:
        (key_pattern, value), = node["patternProperties"].items()
        return f"map `{key_pattern}` → {_type_of(value, defs)}"
    fmt = node.get("format")
    return f"{t} ({fmt})" if fmt else str(t)


def _constraints(node: dict[str, Any]) -> str:
    parts = []
    for key, sym in (("minimum", "≥"), ("exclusiveMinimum", ">"), ("maximum", "≤"),
                     ("exclusiveMaximum", "<")):
        if key in node:
            parts.append(f"{sym} {node[key]}")
    if "pattern" in node:
        parts.append(f"pattern `{node['pattern']}`")
    if "minItems" in node:
        parts.append(f"≥ {node['minItems']} item(s)")
    return ", ".join(parts)


def _children(node: dict[str, Any], defs: dict[str, Any]) -> list[dict[str, Any]]:
    """Object definitions reachable from a property (through anyOf/oneOf/items)."""
    out = []
    if "$ref" in node:
        out.append(_resolve(node, defs))
    for key in ("anyOf", "oneOf"):
        for sub in node.get(key, []):
            out += _children(sub, defs)
    if node.get("type") == "array" and "items" in node:
        out += _children(node["items"], defs)
    return out


def _rows(obj: dict[str, Any], defs: dict[str, Any], prefix: str) -> list[str]:
    rows = []
    required = set(obj.get("required", []))
    for name, prop in obj.get("properties", {}).items():
        path = f"{prefix}{name}"
        target = _resolve(prop, defs)
        desc = (prop.get("description") or target.get("description") or "").replace("\n", " ")
        default = json.dumps(prop["default"]) if "default" in prop else ""
        info = _constraints(prop)
        for sub in prop.get("anyOf", []):
            info = info or _constraints(sub)
        cell_desc = desc + (f" ({info})" if info else "")
        rows.append(
            f"| `{path}` | {_type_of(prop, defs)} | {'yes' if name in required else ''} | "
            f"{f'`{default}`' if default else ''} | {cell_desc} |"
        )
        children = _children(prop, defs)
        is_list = prop.get("type") == "array" or any(
            s.get("type") == "array" for s in prop.get("anyOf", [])
        )
        for child in children:
            label = ""
            if len(children) > 1:
                method = child.get("properties", {}).get("method", {}).get("const")
                label = f"{{{method}}}" if method else ""
            rows += _rows(child, defs, f"{path}{'[]' if is_list else ''}{label}.")
    return rows


def field_reference() -> str:
    schema = json_schema()
    defs = schema.get("$defs", {})
    lines = [
        BEGIN,
        "",
        "Generated from `docs/schema/project_config.schema.json`; do not edit by hand.",
        "`required` = the key must be present. `{method}` marks the variants of",
        "`tvd.cluster_split`; `[]` marks list items.",
        "",
        "| Field | Type | Required | Default | Description |",
        "|---|---|---|---|---|",
        *_rows(schema, defs, ""),
        "",
        END,
    ]
    return "\n".join(lines)


def render_doc(current: str) -> str:
    start, end = current.index(BEGIN), current.index(END) + len(END)
    return current[:start] + field_reference() + current[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if files are out of date")
    args = parser.parse_args(argv)

    schema_text = json_schema_text()
    doc_current = DOC_PATH.read_text(encoding="utf-8")
    doc_text = render_doc(doc_current)
    schema_current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""

    stale = [p for p, new, old in ((SCHEMA_PATH, schema_text, schema_current),
                                   (DOC_PATH, doc_text, doc_current)) if new != old]
    if args.check:
        for p in stale:
            print(f"out of date: {p.relative_to(REPO_ROOT)}")
        if stale:
            print("Run: python scripts/export_config_schema.py", file=sys.stderr)
            return 1
        print("project_config schema and field reference are up to date.")
        return 0

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text, encoding="utf-8")
    DOC_PATH.write_text(doc_text, encoding="utf-8")
    for p in stale:
        print(f"updated: {p.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
