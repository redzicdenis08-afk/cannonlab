from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_KEYS = {
    "password", "token", "session", "cookie", "authorization",
    "access_token", "refresh_token", "minecraft_session",
}

LEGACY_RULES: dict[str, dict[str, Any]] = {
    "single-dispenser-fuse": {
        "dimension": "tnt.fuse.distribution",
        "minimum_samples": 10,
        "sample_fields": ["activation_tick", "first_entity_tick", "first_fuse", "explosion_tick"],
    },
    "dispenser-launch-spread": {
        "dimension": "tnt.spawn.horizontal_kick",
        "minimum_samples": 20,
        "sample_fields": ["spawn", "velocity"],
    },
    "water-flow": {
        "dimension": "tnt.water_motion",
        "minimum_samples": 8,
        "sample_fields": ["flow_state", "positions"],
    },
    "falling-block-parity": {
        "dimension": "falling_block.tick_and_collision",
        "minimum_samples": 10,
        "sample_fields": ["spawn_tick", "block_state", "positions", "outcome"],
    },
    "high-speed-survival": {
        "dimension": "tnt.velocity_and_despawn_limits",
        "minimum_samples": 10,
        "sample_fields": ["requested_velocity", "observed_velocity", "outcome"],
    },
    "durable-blocks-regen": {
        "dimension": "durability.material_hit_contract",
        "minimum_samples": 10,
        "sample_fields": ["material", "explosion_tick", "damage", "replacement_tick"],
    },
    "redstone-timing": {
        "dimension": "redstone.dispenser.activation_order",
        "minimum_samples": 10,
        "sample_fields": ["configured_delay", "activation_tick"],
    },
    "chunk-paste-limits": {
        "dimension": "limits.dispensers_per_chunk",
        "minimum_samples": 6,
        "sample_fields": ["dispensers", "block_entities", "offset_x", "offset_z", "paste_result"],
    },
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("root must be an object")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_inside(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path must be a non-empty string")
    candidate = (root / raw).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes evidence root: {raw}")
    return candidate


def validate_hash_ref(
    value: Any,
    root: Path,
    label: str,
    verify_hashes: bool,
    require_id: bool = False,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    if require_id and (not isinstance(value.get("id"), str) or not value["id"].strip()):
        errors.append(f"{label}.id is required")
    raw_path = value.get("path")
    expected = value.get("sha256")
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected.lower()):
        errors.append(f"{label}.sha256 must be 64 lowercase hex characters")
    try:
        path = resolve_inside(root, raw_path)
    except ValueError as exc:
        errors.append(f"{label}.{exc}")
        return errors
    if verify_hashes:
        if not path.is_file():
            errors.append(f"{label}.path does not exist: {raw_path}")
        elif isinstance(expected, str) and SHA256_RE.fullmatch(expected.lower()):
            observed = sha256_file(path)
            if observed != expected.lower():
                errors.append(
                    f"{label}.sha256 mismatch: expected {expected.lower()} observed {observed}"
                )
    return errors


def find_secret_keys(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in SECRET_KEYS:
                found.append(path)
            found.extend(find_secret_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_secret_keys(child, f"{prefix}[{index}]"))
    return found


def validate_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_origin(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(("x", "y", "z")) <= set(value)
        and all(isinstance(value[key], int) and not isinstance(value[key], bool) for key in ("x", "y", "z"))
    )
