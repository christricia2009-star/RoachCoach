#!/usr/bin/env python3
"""
Contract test: backend Pydantic response models <-> iOS Swift Codable
structs.

WHY THIS EXISTS
----------------
Two real, live bugs were found by hand while auditing this repo:

  1. SightingOut/TruckOut (backend/main.py) serialized plain Python
     snake_case field names (truck_id, confidence_level, cuisine_type,
     ...). Sighting.swift and (the pre-fix) Truck.swift had no
     CodingKeys and expected camelCase (truckId, confidenceLevel,
     cuisineType, ...) — every GET /api/sightings, GET /api/trucks,
     and POST /api/sightings either failed to decode or 422'd,
     silently, with nothing to catch it.

  2. RadarObservation.SourceKind (a Swift enum, not a struct field
     name — outside what this script checks, but the same root cause)
     was missing a case the backend actually emits, which broke
     decoding for an entire array the moment one matching record
     appeared.

This script only catches bug #1's class (field-NAME contract drift
between a Pydantic model and its Swift struct), run against models
that are actually wired up to real endpoints. It is deliberately
narrow and heuristic (regex/AST over the source, not a real Swift
parser) rather than trying to be a complete cross-language type
checker — narrow-and-run-in-CI beats thorough-and-never-written.

WHAT IT CHECKS
--------------
For every (Pydantic model, Swift struct) pair in CONTRACTS below:

  - FAIL: a non-optional Swift stored property whose wire key (its
    CodingKeys alias, or its property name if the struct has no
    CodingKeys enum) has no matching Pydantic field wire name (its
    Field(alias=...), or its field name if no alias). This is the
    dangerous direction — Swift's synthesized Decodable throws
    keyNotFound for the whole record, not just that field.

  - WARN: an optional Swift property with no backend match (dead
    field, decodes to nil — not breaking, but likely drift), or a
    Pydantic field with no matching Swift property (extra data on the
    wire, harmless, but worth a human glance).

USAGE
-----
    python3 scripts/contract_test.py

Exits 1 (and prints FAIL lines) if any hard contract break is found,
so this is meant to run in CI on every PR touching backend/main.py or
IOS/*.swift. See CONTRACTS below to add a pair when a new response
model / Swift struct is introduced — nothing here discovers new pairs
automatically, on purpose: an explicit map is easier to trust than a
name-guessing heuristic once TruckOut/RadarSightingOut-style naming
mismatches exist.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_MAIN = REPO_ROOT / "backend" / "main.py"
IOS_DIR = REPO_ROOT / "IOS"

# ------------------------------------------------------------------
# Explicit (Pydantic model class name -> Swift struct name, Swift file)
# pairs. Update this when a response_model is added/changed, or when
# the Swift struct it's decoded into is renamed. This is intentionally
# a hand-maintained map, not name-matching — TruckOut/Truck,
# RadarSightingOut/Sighting, RadarObservationOut/RadarObservation,
# RadarScanResultOut/RadarScanResult, RadarSourceOut/RadarSourceResult,
# and RadarCameraOut/RadarCameraResult are none of them a trivial
# strip-the-Out-suffix match.
# ------------------------------------------------------------------
CONTRACTS: list[tuple[str, str, str]] = [
    # (Pydantic model, Swift struct, Swift file relative to IOS/)
    ("TruckOut", "Truck", "Truck.swift"),
    ("SightingOut", "Sighting", "Sighting.swift"),
    ("RadarSourceOut", "RadarSourceResult", "RadarScanService.swift"),
    ("RadarCameraOut", "RadarCameraResult", "RadarScanService.swift"),
    ("RadarSightingOut", "Sighting", "Sighting.swift"),
    ("RadarObservationOut", "RadarObservation", "RadarObservation.swift"),
    ("RadarScanResultOut", "RadarScanResult", "RadarScanService.swift"),
]


@dataclass
class PyField:
    name: str
    wire_name: str
    optional: bool


@dataclass
class SwiftProp:
    name: str
    wire_name: str
    optional: bool


@dataclass
class Report:
    fails: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# PYTHON SIDE
# ------------------------------------------------------------------

def _literal_alias(call: ast.Call) -> str | None:
    """Pulls alias="..." out of a Field(...) call, if present."""
    for kw in call.keywords:
        if kw.arg == "alias" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def parse_pydantic_models(path: Path) -> dict[str, list[PyField]]:
    tree = ast.parse(path.read_text())
    models: dict[str, list[PyField]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(
            (isinstance(b, ast.Name) and b.id == "BaseModel")
            for b in node.bases
        ):
            continue

        fields: list[PyField] = []

        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue

            field_name = stmt.target.id
            optional = False

            # Optional[...] / X | None annotations
            ann = stmt.annotation
            ann_src = ast.dump(ann)
            if "Optional" in ann_src or "None" in ann_src:
                optional = True

            wire_name = field_name

            # model_config lines aren't real fields
            if field_name == "model_config":
                continue

            if isinstance(stmt.value, ast.Call):
                callee = stmt.value.func
                callee_name = (
                    callee.id
                    if isinstance(callee, ast.Name)
                    else getattr(callee, "attr", "")
                )
                if callee_name == "Field":
                    alias = _literal_alias(stmt.value)
                    if alias:
                        wire_name = alias
                    # Field(default=None, ...) / Field(default_factory=...)
                    for kw in stmt.value.keywords:
                        if kw.arg == "default" and isinstance(
                            kw.value, ast.Constant
                        ) and kw.value.value is None:
                            optional = True

            fields.append(
                PyField(
                    name=field_name,
                    wire_name=wire_name,
                    optional=optional,
                )
            )

        if fields:
            models[node.name] = fields

    return models


# ------------------------------------------------------------------
# SWIFT SIDE (heuristic — regex, not a real parser)
# ------------------------------------------------------------------

def _extract_struct_body(src: str, struct_name: str) -> str | None:
    match = re.search(
        r"struct\s+" + re.escape(struct_name) + r"\b[^{]*\{",
        src,
    )
    if not match:
        return None

    depth = 1
    i = match.end()
    start = i
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1

    return src[start:i - 1]


def _extract_coding_keys(body: str) -> dict[str, str] | None:
    ck_match = re.search(
        r"enum\s+CodingKeys[^{]*\{(.*?)\n\s*\}",
        body,
        re.DOTALL,
    )
    if not ck_match:
        return None

    mapping: dict[str, str] = {}
    for case_line in re.finditer(
        r'case\s+(\w+)(?:\s*=\s*"([^"]+)")?',
        ck_match.group(1),
    ):
        prop, alias = case_line.group(1), case_line.group(2)
        mapping[prop] = alias or prop

    return mapping


def _extract_stored_properties(body: str) -> list[tuple[str, bool]]:
    """
    Returns [(property_name, is_optional), ...] for stored (not
    computed) properties: `let/var name: Type` NOT followed by `{`
    (which would make it computed) before the next statement.
    """

    # Strip out computed-property and function bodies so their
    # internal `let x: Y` locals aren't mistaken for stored props.
    # Heuristic: drop everything from the first top-level `{` after a
    # property/func signature that isn't immediately closed.
    cleaned_lines = []
    skip_depth = 0
    for line in body.splitlines():
        if skip_depth > 0:
            skip_depth += line.count("{") - line.count("}")
            continue

        stripped = line.strip()

        is_stored_prop_line = bool(
            re.match(r"(let|var)\s+\w+\s*:", stripped)
        )

        if is_stored_prop_line and "{" in stripped:
            # e.g. `var coordinate: CLLocationCoordinate2D { ... }`
            # single-line computed property — skip entirely.
            if stripped.count("{") == stripped.count("}"):
                continue
            skip_depth = stripped.count("{") - stripped.count("}")
            continue

        if not is_stored_prop_line and re.match(
            r"(init|func|var\s+\w+\s*:.*\{)", stripped
        ):
            skip_depth += stripped.count("{") - stripped.count("}")
            if skip_depth < 0:
                skip_depth = 0
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)

    props = []
    for m in re.finditer(
        r"^\s*(?:let|var)\s+(\w+)\s*:\s*([^\n=]+?)(?:=.*)?$",
        cleaned,
        re.MULTILINE,
    ):
        name, type_str = m.group(1), m.group(2).strip()
        optional = type_str.rstrip(",").endswith("?")
        props.append((name, optional))

    return props


def _extract_decode_if_present_props(body: str) -> set[str]:
    """
    A struct with a hand-written `init(from decoder:)` can decode a
    non-optional stored property via `decodeIfPresent(...) ?? default`
    instead of `decode(...)` — meaning a missing key does NOT throw,
    even though the property itself isn't Optional-typed. Without
    this, the checker would flag Truck.rating/averageWaitMinutes
    (decoded this way on purpose, see Truck.swift) as false-positive
    FAILs forever. Only recognized inside an actual `init(from
    decoder:` block, so this can't accidentally suppress a real
    required-property FAIL elsewhere.
    """

    init_match = re.search(
        r"init\(from\s+decoder\s*:.*?\)\s*throws\s*\{(.*?)\n\s*\}",
        body,
        re.DOTALL,
    )
    if not init_match:
        return set()

    return set(
        re.findall(
            r"decodeIfPresent\([^)]*forKey:\s*\.(\w+)\)",
            init_match.group(1),
        )
    )


def parse_swift_struct(
    swift_path: Path, struct_name: str
) -> list[SwiftProp]:
    src = swift_path.read_text()
    body = _extract_struct_body(src, struct_name)
    if body is None:
        raise ValueError(
            f"struct {struct_name} not found in {swift_path}"
        )

    coding_keys = _extract_coding_keys(body)
    stored = _extract_stored_properties(body)
    soft_optional = _extract_decode_if_present_props(body)

    result = []
    for name, optional in stored:
        if name in soft_optional:
            optional = True
        if coding_keys is not None:
            if name not in coding_keys:
                # Property intentionally excluded from CodingKeys —
                # not part of the wire contract either direction.
                continue
            wire_name = coding_keys[name]
        else:
            wire_name = name
        result.append(SwiftProp(name=name, wire_name=wire_name, optional=optional))

    return result


# ------------------------------------------------------------------
# COMPARE
# ------------------------------------------------------------------

def check_pair(
    py_model: str,
    py_fields: list[PyField],
    swift_struct: str,
    swift_file: str,
    swift_props: list[SwiftProp],
    report: Report,
) -> None:

    py_wire_names = {f.wire_name for f in py_fields}
    swift_wire_names = {p.wire_name for p in swift_props}

    for prop in swift_props:
        if prop.wire_name in py_wire_names:
            continue
        loc = f"{swift_struct} ({swift_file}).{prop.name}"
        if prop.optional:
            report.warns.append(
                f"{loc}: no matching field on {py_model} "
                f"(wire key \"{prop.wire_name}\") — decodes to nil, "
                "check for drift"
            )
        else:
            report.fails.append(
                f"{loc}: REQUIRED, no matching field on {py_model} "
                f"(wire key \"{prop.wire_name}\") — decoding "
                f"{swift_struct} from {py_model}'s JSON will throw "
                "keyNotFound for the whole record"
            )

    for pf in py_fields:
        if pf.wire_name in swift_wire_names:
            continue
        report.warns.append(
            f"{py_model}.{pf.name} (wire key \"{pf.wire_name}\"): "
            f"no matching property on {swift_struct} — extra data "
            "on the wire, not currently read"
        )


def main() -> int:
    py_models = parse_pydantic_models(BACKEND_MAIN)
    report = Report()
    checked = 0

    for model_name, struct_name, swift_file in CONTRACTS:
        if model_name not in py_models:
            report.fails.append(
                f"{model_name}: not found in {BACKEND_MAIN} — "
                "CONTRACTS entry is stale, update or remove it"
            )
            continue

        swift_path = IOS_DIR / swift_file
        if not swift_path.exists():
            report.fails.append(
                f"{swift_file}: not found under {IOS_DIR} — "
                "CONTRACTS entry is stale"
            )
            continue

        try:
            swift_props = parse_swift_struct(swift_path, struct_name)
        except ValueError as exc:
            report.fails.append(str(exc))
            continue

        check_pair(
            model_name,
            py_models[model_name],
            struct_name,
            swift_file,
            swift_props,
            report,
        )
        checked += 1

    print(f"Checked {checked} contract(s).\n")

    if report.warns:
        print(f"WARN ({len(report.warns)}):")
        for w in report.warns:
            print(f"  - {w}")
        print()

    if report.fails:
        print(f"FAIL ({len(report.fails)}):")
        for f_ in report.fails:
            print(f"  - {f_}")
        print()
        print("Contract test FAILED.")
        return 1

    print("Contract test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
