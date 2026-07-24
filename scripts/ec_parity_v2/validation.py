from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    LEGACY_RULES,
    SECRET_KEYS,
    find_secret_keys,
    resolve_inside,
    validate_date,
    validate_hash_ref,
    validate_origin,
    validate_timestamp,
)

def validate_new_file(
    payload: dict[str, Any],
    path: Path,
    root: Path,
    dimensions: dict[str, Any],
    verify_hashes: bool,
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    dimension = payload.get("dimension")
    if not isinstance(dimension, str) or not dimension:
        errors.append("dimension is required")
        dimension = None
    elif dimension not in dimensions:
        errors.append(f"unknown dimension {dimension!r}")

    if payload.get("kind") != "ec-parity-evidence":
        errors.append("kind must be exactly 'ec-parity-evidence'")
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("server") != "ExtremeCraft Cannoning":
        errors.append("server must be exactly 'ExtremeCraft Cannoning'")
    if not validate_timestamp(payload.get("captured_at")):
        errors.append("captured_at must be an ISO-8601 timestamp with timezone")
    if not validate_date(payload.get("server_date")):
        errors.append("server_date must be YYYY-MM-DD")
    if not isinstance(payload.get("client_version"), str) or not payload["client_version"].strip():
        errors.append("client_version is required")
    if not validate_origin(payload.get("paste_origin")):
        errors.append("paste_origin must contain integer x, y and z")
    if payload.get("chunk_origin_confirmed") is not True:
        errors.append("chunk_origin_confirmed must be true")

    errors.extend(validate_hash_ref(
        payload.get("fixture"), root, "fixture", verify_hashes, require_id=True
    ))
    raw_artifacts = payload.get("raw_artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        errors.append("raw_artifacts must be a non-empty array")
    else:
        for index, artifact in enumerate(raw_artifacts, 1):
            errors.extend(validate_hash_ref(
                artifact, root, f"raw_artifacts[{index}]", verify_hashes
            ))

    secret_paths = find_secret_keys(payload)
    if secret_paths:
        errors.append("forbidden credential-like keys: " + ", ".join(sorted(secret_paths)))

    samples = payload.get("samples")
    if not isinstance(samples, list):
        errors.append("samples must be an array")
        samples = []
    required_fields: list[str] = []
    if dimension in dimensions:
        required_fields = list(dimensions[dimension].get("sample_fields", []))
    seen_ids: set[str] = set()
    valid_samples: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict):
            errors.append(f"sample {index} must be an object")
            continue
        missing = [field for field in required_fields if field not in sample]
        if missing:
            errors.append(f"sample {index} missing {', '.join(missing)}")
            continue
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            errors.append(f"sample {index} sample_id must be a non-empty string")
            continue
        if sample_id in seen_ids:
            errors.append(f"duplicate sample_id {sample_id!r} within file")
            continue
        seen_ids.add(sample_id)
        valid_samples.append(sample)

    claimed = payload.get("claimed_classification")
    if claimed is not None and (not isinstance(claimed, str) or not claimed.strip()):
        errors.append("claimed_classification must be a non-empty string when present")
    return dimension, valid_samples, errors


def validate_legacy_file(payload: dict[str, Any]) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    probe = payload.get("probe")
    if not isinstance(probe, str) or not probe:
        return None, ["probe is required"]
    if probe not in LEGACY_RULES:
        return probe, [f"unknown probe {probe!r}"]
    for field in (
        "server", "captured_at", "client_version", "paste_origin",
        "chunk_origin_confirmed", "samples",
    ):
        if field not in payload:
            errors.append(f"missing {field}")
    if payload.get("server") != "ExtremeCraft Cannoning":
        errors.append("server must be exactly 'ExtremeCraft Cannoning'")
    if payload.get("chunk_origin_confirmed") is not True:
        errors.append("chunk_origin_confirmed must be true")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        errors.append("samples must be an array")
        samples = []
    rules = LEGACY_RULES[probe]
    if len(samples) < int(rules["minimum_samples"]):
        errors.append(
            f"samples={len(samples)} below required {rules['minimum_samples']}"
        )
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict):
            errors.append(f"sample {index} must be an object")
            continue
        missing = [field for field in rules["sample_fields"] if field not in sample]
        if missing:
            errors.append(f"sample {index} missing {', '.join(missing)}")
    return probe, errors
