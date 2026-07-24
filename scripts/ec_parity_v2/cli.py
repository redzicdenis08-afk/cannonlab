from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .classifiers import classify
from .common import LEGACY_RULES, load_json
from .validation import validate_legacy_file, validate_new_file

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = ROOT / "profiles" / "parity" / "extremecraft-evidence-rules-v1.json"

def evidence_files(path: Path, output_path: Path | None) -> list[Path]:
    if path.is_file():
        return [path]
    excluded = output_path.resolve() if output_path else None
    return [
        candidate for candidate in sorted(path.rglob("*.json"))
        if excluded is None or candidate.resolve() != excluded
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a 16-dimension ExtremeCraft cannon-physics evidence pack"
    )
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--skip-hash-verification", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    rules_payload = load_json(args.rules)
    dimensions = rules_payload.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("rules dimensions must be a non-empty object")
    evidence_root = args.evidence if args.evidence.is_dir() else args.evidence.parent
    evidence_root = evidence_root.resolve()
    files = evidence_files(args.evidence, args.json_out)

    file_reports: list[dict[str, Any]] = []
    dimension_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dimension_files: dict[str, list[str]] = defaultdict(list)
    dimension_claims: dict[str, set[str]] = defaultdict(set)
    valid_legacy: set[str] = set()

    for path in files:
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            file_reports.append({
                "file": str(path),
                "mode": "unknown",
                "dimension": None,
                "probe": None,
                "samples": 0,
                "valid": False,
                "errors": [f"invalid JSON: {exc}"],
            })
            continue

        if "dimension" in payload or payload.get("kind") == "ec-parity-evidence":
            dimension, samples, errors = validate_new_file(
                payload, path, evidence_root, dimensions,
                verify_hashes=not args.skip_hash_verification,
            )
            valid = dimension is not None and not errors
            if valid:
                dimension_samples[dimension].extend(samples)
                dimension_files[dimension].append(str(path))
                claimed = payload.get("claimed_classification")
                if isinstance(claimed, str):
                    dimension_claims[dimension].add(claimed)
            file_reports.append({
                "file": str(path),
                "mode": "v2",
                "dimension": dimension,
                "probe": None,
                "samples": len(samples),
                "valid": valid,
                "errors": errors,
            })
        else:
            probe, errors = validate_legacy_file(payload)
            valid = probe is not None and not errors
            if valid:
                valid_legacy.add(probe)
            file_reports.append({
                "file": str(path),
                "mode": "legacy",
                "dimension": LEGACY_RULES.get(probe or "", {}).get("dimension"),
                "probe": probe,
                "samples": len(payload.get("samples", [])) if isinstance(payload.get("samples"), list) else 0,
                "valid": valid,
                "errors": errors,
            })

    dimension_reports = []
    valid_dimensions: set[str] = set()
    for dimension, rule in dimensions.items():
        samples = dimension_samples.get(dimension, [])
        errors: list[str] = []
        sample_ids = [sample.get("sample_id") for sample in samples]
        duplicate_ids = sorted(
            value for value, count in Counter(sample_ids).items()
            if isinstance(value, str) and count > 1
        )
        if duplicate_ids:
            errors.append("duplicate sample_ids across files: " + ", ".join(duplicate_ids))
        minimum = int(rule.get("minimum_samples", 0))
        if len(samples) < minimum:
            errors.append(f"samples={len(samples)} below required {minimum}")
        required_labels = rule.get("required_labels")
        if isinstance(required_labels, dict):
            field = required_labels.get("field")
            required_values = set(required_labels.get("values", []))
            observed = {
                sample.get(field) for sample in samples
                if isinstance(field, str)
            }
            missing_labels = sorted(required_values - observed)
            if missing_labels:
                errors.append(
                    f"missing {field} labels: {', '.join(str(value) for value in missing_labels)}"
                )
        analysis = classify(str(rule.get("classifier", "none")), samples, dimension) if samples else {
            "classification": "no-evidence",
            "confidence": "none",
            "metrics": {"samples": 0},
        }
        claims = dimension_claims.get(dimension, set())
        if len(claims) > 1:
            errors.append("conflicting claimed_classification values: " + ", ".join(sorted(claims)))
        elif claims and analysis["classification"] not in {
            "not-automatically-classified", "classification-error"
        }:
            claim = next(iter(claims))
            if claim != analysis["classification"]:
                errors.append(
                    f"claimed_classification {claim!r} conflicts with derived "
                    f"{analysis['classification']!r}"
                )
        if analysis["classification"] == "classification-error":
            errors.append(f"automatic classification failed: {analysis.get('error')}")
        valid = not errors
        if valid:
            valid_dimensions.add(dimension)
        dimension_reports.append({
            "dimension": dimension,
            "valid": valid,
            "files": dimension_files.get(dimension, []),
            "samples": len(samples),
            "minimum_samples": minimum,
            "analysis": analysis,
            "errors": errors,
        })

    reverse_legacy = {
        rules["dimension"]: probe for probe, rules in LEGACY_RULES.items()
    }
    compatibility_valid = set(valid_legacy)
    for dimension in valid_dimensions:
        probe = reverse_legacy.get(dimension)
        if probe:
            compatibility_valid.add(probe)

    missing_dimensions = sorted(set(dimensions) - valid_dimensions)
    missing_probes = sorted(set(LEGACY_RULES) - compatibility_valid)
    invalid_files = [report for report in file_reports if not report["valid"]]
    status = "PASS" if not missing_dimensions and not invalid_files else "INCOMPLETE"
    report = {
        "schema_version": 2,
        "status": status,
        "ec_calibrated": status == "PASS",
        "profile": rules_payload.get("profile"),
        "rules": rules_payload.get("id"),
        "hash_verification": not args.skip_hash_verification,
        "required_dimension_count": len(dimensions),
        "valid_dimension_count": len(valid_dimensions),
        "coverage_ratio": len(valid_dimensions) / len(dimensions),
        "valid_dimensions": sorted(valid_dimensions),
        "missing_dimensions": missing_dimensions,
        "dimension_reports": dimension_reports,
        "invalid_file_count": len(invalid_files),
        "files": file_reports,
        "legacy_compatibility": {
            "required_probe_count": len(LEGACY_RULES),
            "valid_probe_count": len(compatibility_valid),
            "valid_probes": sorted(compatibility_valid),
            "missing_probes": missing_probes,
            "legacy_files_do_not_promote_v2_dimensions": True,
        },
        # Kept at top level so older CI and callers fail closed without breaking.
        "required_probe_count": len(LEGACY_RULES),
        "valid_probe_count": len(compatibility_valid),
        "valid_probes": sorted(compatibility_valid),
        "missing_probes": missing_probes,
        "truth_boundary": {
            "pass_validates_completeness_hashes_and_internal_consistency": True,
            "pass_independently_proves_measurement_accuracy": False,
            "legacy_evidence_proves_v2_parity": False,
            "private_server_mechanics_are_still_black_box_observations": True,
            "note": (
                "PASS means all 16 dimensions have structurally valid, hash-backed evidence "
                "meeting the declared sample contracts. It does not prove the operator measured "
                "or interpreted the private server correctly."
            ),
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if status == "PASS" else 2
