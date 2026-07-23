#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if lower in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [part.strip() for part in inner.split(",")]
    return value


def strip_comment(line: str) -> str:
    quote: str | None = None
    output: list[str] = []
    for char in line:
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        if char == "#" and quote is None:
            break
        output.append(char)
    return "".join(output).rstrip()


def minimal_yaml_paths(text: str) -> tuple[dict[str, Any], set[str]]:
    """Read the simple mapping/list subset used by CannonLab scenario files."""
    values: dict[str, Any] = {}
    nonempty_sequences: set[str] = set()
    stack: list[tuple[int, str]] = []

    for original in text.splitlines():
        clean = strip_comment(original)
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        stripped = clean.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()

        if stripped.startswith("-"):
            if stack:
                nonempty_sequences.add(".".join(part for _level, part in stack))
            continue

        match = re.match(r"([^:]+):(.*)$", stripped)
        if not match:
            continue
        key = match.group(1).strip()
        raw_value = match.group(2).strip()
        prefix = ".".join(part for _level, part in stack)
        path = f"{prefix}.{key}" if prefix else key
        if raw_value:
            values[path] = parse_scalar(raw_value)
        else:
            stack.append((indent, key))
    return values, nonempty_sequences


def load_scenario(path: Path) -> tuple[dict[str, Any], set[str], bytes]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        values, sequences = minimal_yaml_paths(text)
        return values, sequences, raw

    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("scenario root must be a mapping")

    values: dict[str, Any] = {}
    sequences: set[str] = set()

    def walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                path_key = f"{prefix}.{key}" if prefix else str(key)
                walk(nested, path_key)
        elif isinstance(value, list):
            if value:
                sequences.add(prefix)
            values[prefix] = value
        else:
            values[prefix] = value

    walk(loaded, "")
    return values, sequences, raw


def get(values: dict[str, Any], path: str, default: Any = None) -> Any:
    value = values.get(path, default)
    return default if value is None and default is not None else value


def audit_scenario(
    values: dict[str, Any],
    sequences: set[str],
    raw: bytes,
    path: Path,
) -> dict[str, Any]:
    assists: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    blockers: list[dict[str, str]] = []

    def sequence_present(name: str) -> bool:
        value = values.get(name)
        return name in sequences or isinstance(value, list) and bool(value)

    if sequence_present("tracking.collision-guides"):
        assists.append({
            "code": "external-collision-guides",
            "reason": "The runtime adds collision geometry that is not present in the cannon schematic.",
        })
    if sequence_present("cannon.tnt-spawn-velocity-rules") or sequence_present(
        "cannon.tnt-source-velocity-rules"
    ):
        assists.append({
            "code": "forced-tnt-velocity",
            "reason": "The runtime overrides natural TNT velocity for selected cohorts.",
        })
    if "cannon.tnt-spawn-y-velocity" in values:
        assists.append({
            "code": "global-forced-tnt-y-velocity",
            "reason": "The runtime overrides natural TNT vertical velocity.",
        })
    if int(get(values, "cannon.clear-tnt-after-fire-ticks", 0) or 0) > 0:
        assists.append({
            "code": "magazine-cutoff",
            "reason": "The runtime deletes live TNT after firing, changing the natural shot lifecycle.",
        })
    if bool(get(values, "cannon.force-redstone-block-inputs", False)):
        assists.append({
            "code": "forced-redstone-block-input",
            "reason": "The runtime may replace a native input with a redstone block.",
        })
    if bool(get(values, "cannon.suppress-paste-side-effects", False)):
        assists.append({
            "code": "suppressed-paste-side-effects",
            "reason": (
                "The lab suppresses paste-time updates; useful for diagnosis, but not proof of "
                "the exact live WorldEdit or FAWE paste sequence."
            ),
        })

    fire_mode = str(get(values, "cannon.fire-mode", "redstone")).lower()
    if fire_mode in {"direct", "direct-dispense", "direct_dispense", "dispenser", "tnt-probe", "tnt_probe"}:
        assists.append({
            "code": f"non-native-fire-mode:{fire_mode}",
            "reason": "The shot bypasses the cannon's native button or lever circuit.",
        })

    durability_mode = str(get(values, "target.durability.mode", "disabled")).lower()
    if durability_mode == "simulate":
        assists.append({
            "code": "simulated-durability",
            "reason": "The target uses CannonLab's simulated hit-count durability model.",
        })

    if not bool(get(values, "limits.enforce-dispenser-limit", True)):
        blockers.append({
            "code": "dispenser-limit-disabled",
            "reason": "The run does not enforce the configured per-chunk dispenser limit.",
        })

    require_payload = bool(get(values, "acceptance.require-payload", False))
    min_target = int(get(values, "acceptance.min-target-destroyed", 0) or 0)
    min_forward = float(get(values, "acceptance.min-forward-distance", 0.0) or 0.0)
    min_remaining = float(
        get(values, "acceptance.min-remaining-dispenser-ratio", 0.0) or 0.0
    )
    max_missing = int(
        get(values, "acceptance.max-cannon-missing-blocks", 2**31 - 1) or 0
    )
    max_replaced = int(
        get(values, "acceptance.max-cannon-replaced-type-blocks", 2**31 - 1) or 0
    )
    max_self = int(get(values, "acceptance.max-self-damage-blocks", 2**31 - 1) or 0)

    required_acceptance_paths = {
        "acceptance.require-payload",
        "acceptance.min-target-destroyed",
        "acceptance.min-forward-distance",
        "acceptance.min-remaining-dispenser-ratio",
        "acceptance.max-cannon-missing-blocks",
        "acceptance.max-cannon-replaced-type-blocks",
        "acceptance.max-self-damage-blocks",
    }
    missing_acceptance_paths = sorted(required_acceptance_paths - values.keys())
    if missing_acceptance_paths:
        warnings.append({
            "code": "acceptance-gates-incomplete",
            "reason": (
                "Field promotion requires explicit runtime acceptance gates; missing: "
                + ", ".join(missing_acceptance_paths)
            ),
        })

    if not require_payload:
        warnings.append({
            "code": "payload-not-required",
            "reason": "The run can pass without a measured payload.",
        })
    if min_target <= 0:
        warnings.append({
            "code": "target-damage-not-required",
            "reason": "The run can pass without damaging the target.",
        })
    if min_forward <= 0:
        warnings.append({
            "code": "range-not-required",
            "reason": "The run can pass without forward travel.",
        })
    if min_remaining < 0.95:
        warnings.append({
            "code": "weak-dispenser-survival",
            "reason": "The run allows substantial dispenser loss.",
        })
    if max_missing > 100:
        warnings.append({
            "code": "weak-missing-block-gate",
            "reason": "The run allows broad cannon destruction.",
        })
    if max_replaced > 25:
        warnings.append({
            "code": "weak-replaced-block-gate",
            "reason": "The run allows broad block-type replacement.",
        })
    if max_self > 100:
        warnings.append({
            "code": "weak-self-damage-gate",
            "reason": "The run allows severe self-damage.",
        })

    target_distance = int(get(values, "target.distance", 0) or 0)
    target_layers = int(get(values, "target.layers", 1) or 1)
    target_type = str(get(values, "target.type", "dry")).lower()
    target_file = str(get(values, "target.file", "") or "").strip()
    if target_distance < 16:
        warnings.append({
            "code": "near-target",
            "reason": "Target distance is too short to establish raid range.",
        })
    if target_layers <= 1 and target_type == "dry":
        warnings.append({
            "code": "single-dry-layer",
            "reason": "A single dry layer does not establish modern defense capability.",
        })
    if not target_file and target_type not in {"dry", "watered"}:
        warnings.append({
            "code": "synthetic-defense-model",
            "reason": (
                "The defense is generated by CannonLab rather than pasted from an exact captured "
                "target schematic."
            ),
        })

    field_gate_warning_codes = {
        "acceptance-gates-incomplete",
        "payload-not-required",
        "target-damage-not-required",
        "range-not-required",
        "weak-dispenser-survival",
        "weak-missing-block-gate",
        "weak-replaced-block-gate",
        "weak-self-damage-gate",
    }
    field_candidate_eligible = (
        not assists
        and not blockers
        and not any(item["code"] in field_gate_warning_codes for item in warnings)
    )
    readiness_eligible = field_candidate_eligible and not warnings
    if blockers:
        status = "FAIL"
        evidence_class = "invalid-for-field-evidence"
    elif assists:
        status = "DIAGNOSTIC"
        evidence_class = "lab-assisted-diagnostic"
    elif not field_candidate_eligible:
        status = "INCOMPLETE"
        evidence_class = "insufficient-evidence-gates"
    else:
        status = "PASS"
        evidence_class = "standalone-candidate"

    return {
        "status": status,
        "schema": "cannonlab-scenario-integrity-v2",
        "scenario": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "name": values.get("name"),
        "cannon_file": values.get("cannon.file"),
        "fire_mode": fire_mode,
        "evidence_class": evidence_class,
        "field_candidate_eligible": field_candidate_eligible,
        "readiness_eligible": readiness_eligible,
        "assists": assists,
        "blockers": blockers,
        "warnings": warnings,
        "truth_boundary": (
            "A clean scenario can still prove only local runtime behavior. Live ExtremeCraft "
            "readiness requires an exact live canary under the intended range, height, payload, "
            "defense, alignment and repeated-shot configuration."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify CannonLab scenarios before their results are promoted as cannon evidence."
    )
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--require-field-candidate", action="store_true")
    parser.add_argument("--require-readiness", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    values, sequences, raw = load_scenario(args.scenario)
    report = audit_scenario(values, sequences, raw, args.scenario)
    text = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.require_readiness and not report["readiness_eligible"]:
        return 2
    if args.require_field_candidate and not report["field_candidate_eligible"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
