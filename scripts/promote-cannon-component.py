#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
EVIDENCE_RANK = {
    "unknown": 0,
    "inference": 1,
    "static": 2,
    "local-runtime": 3,
    "field-reported": 4,
    "field-verified": 5,
}
FACE_VECTORS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
DIRECTIONAL_TYPES = {
    "minecraft:observer",
    "minecraft:repeater",
    "minecraft:comparator",
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:dispenser",
    "minecraft:dropper",
}
SUPPORT_REQUIRED = {
    "minecraft:redstone_wire",
    "minecraft:repeater",
    "minecraft:comparator",
}
MOTION_TYPES = {
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:piston_head",
    "minecraft:moving_piston",
    "minecraft:slime_block",
    "minecraft:honey_block",
}
SAFE_REWRITABLE_BLOCK_ENTITIES = {
    "minecraft:dispenser",
    "minecraft:dropper",
}


class PromotionError(ValueError):
    pass


def load_script(repo_root: Path, name: str, filename: str) -> ModuleType:
    path = repo_root / "scripts" / filename
    if not path.is_file():
        raise PromotionError(f"missing CannonLab dependency: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PromotionError(f"cannot import CannonLab dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PromotionError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_state(state: str) -> str:
    return state.split("[", 1)[0]


def as_triplet(value: Any, label: str, *, allow_negative: bool = True) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise PromotionError(f"{label} must be a three-integer list")
    try:
        result = tuple(int(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise PromotionError(f"{label} must be a three-integer list") from exc
    if not allow_negative and min(result) < 0:
        raise PromotionError(f"{label} cannot contain negative values")
    return result  # type: ignore[return-value]


def add(left: tuple[int, int, int], right: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(left[index] + right[index] for index in range(3))  # type: ignore[return-value]


def subtract(left: tuple[int, int, int], right: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def inside_box(
    point: tuple[int, int, int],
    minimum: tuple[int, int, int],
    maximum: tuple[int, int, int],
) -> bool:
    return all(minimum[index] <= point[index] <= maximum[index] for index in range(3))


def normalize_model(model: dict[str, Any]) -> tuple[
    dict[tuple[int, int, int], str],
    tuple[dict[str, Any], ...],
    tuple[int, int, int],
    int,
]:
    raw_blocks = model.get("blocks")
    dimensions = model.get("source_dimensions") or {}
    if not isinstance(raw_blocks, dict):
        raise PromotionError("decoded schematic has no block map")
    blocks = {
        tuple(int(part) for part in pos): str(state)
        for pos, state in raw_blocks.items()
        if isinstance(pos, tuple) and len(pos) == 3
    }
    try:
        dims = (
            int(dimensions["width"]),
            int(dimensions["height"]),
            int(dimensions["length"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PromotionError("decoded source dimensions are invalid") from exc
    entities: list[dict[str, Any]] = []
    for raw in model.get("block_entities", ()) or ():
        if not isinstance(raw, dict):
            continue
        pos = raw.get("pos")
        if not isinstance(pos, tuple) or len(pos) != 3:
            continue
        entities.append(
            {
                "pos": tuple(int(part) for part in pos),
                "id": str(raw.get("id", "unknown")),
                "raw": dict(raw.get("raw") or {}) if isinstance(raw.get("raw") or {}, dict) else {},
            }
        )
    return blocks, tuple(entities), dims, int(model.get("data_version", 0))


def validate_manifest(manifest: dict[str, Any]) -> None:
    if int(manifest.get("schema_version", 0)) != 1:
        raise PromotionError("promotion manifest schema_version must equal 1")
    component = manifest.get("component")
    source = manifest.get("source")
    selection = manifest.get("selection")
    evidence = manifest.get("evidence")
    capabilities = manifest.get("capabilities")
    ports = manifest.get("ports")
    if not isinstance(component, dict):
        raise PromotionError("manifest.component must be an object")
    if not str(component.get("id", "")).strip() or not str(component.get("version", "")).strip():
        raise PromotionError("manifest.component requires id and version")
    if not isinstance(source, dict) or len(str(source.get("sha256", ""))) != 64:
        raise PromotionError("manifest.source.sha256 must be an exact 64-character SHA-256")
    if not isinstance(selection, dict):
        raise PromotionError("manifest.selection must be an object")
    if not str(selection.get("module_id", "")).strip():
        raise PromotionError("manifest.selection.module_id is required")
    if len(str(selection.get("expected_signature", ""))) != 64:
        raise PromotionError("manifest.selection.expected_signature is required")
    if not isinstance(evidence, dict):
        raise PromotionError("manifest.evidence must be an object")
    level = str(evidence.get("level", ""))
    if level not in EVIDENCE_RANK or EVIDENCE_RANK[level] < EVIDENCE_RANK["static"]:
        raise PromotionError("manifest.evidence.level must be static or stronger")
    sources = evidence.get("sources")
    if not isinstance(sources, list) or not sources or not all(str(item).strip() for item in sources):
        raise PromotionError("manifest.evidence.sources must contain concrete evidence references")
    if not isinstance(capabilities, list) or not capabilities:
        raise PromotionError("manifest.capabilities must be a non-empty list")
    if not isinstance(ports, list) or not ports:
        raise PromotionError("manifest.ports must be a non-empty list")


def select_module(module_report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    selection = manifest["selection"]
    module_id = str(selection["module_id"])
    matches = [
        module for module in module_report.get("modules") or []
        if str(module.get("module_id")) == module_id
    ]
    if len(matches) != 1:
        raise PromotionError(f"selected module {module_id!r} was not found exactly once")
    module = matches[0]
    expected_signature = str(selection["expected_signature"]).lower()
    actual_signature = str(module.get("signature", "")).lower()
    if actual_signature != expected_signature:
        raise PromotionError(
            f"module signature drift for {module_id}: expected={expected_signature} actual={actual_signature}"
        )
    if not module.get("bounds"):
        raise PromotionError(f"selected module {module_id} has no bounds")
    return module


def crop_bounds(module: dict[str, Any], manifest: dict[str, Any], source_dims: tuple[int, int, int]) -> tuple[
    tuple[int, int, int], tuple[int, int, int]
]:
    raw_bounds = module["bounds"]
    minimum = as_triplet(raw_bounds.get("min"), "selected module bounds.min")
    maximum = as_triplet(raw_bounds.get("max"), "selected module bounds.max")
    padding = as_triplet(
        manifest.get("selection", {}).get("padding", [0, 0, 0]),
        "selection.padding",
        allow_negative=False,
    )
    minimum = tuple(max(0, minimum[index] - padding[index]) for index in range(3))
    maximum = tuple(
        min(source_dims[index] - 1, maximum[index] + padding[index])
        for index in range(3)
    )
    if any(maximum[index] < minimum[index] for index in range(3)):
        raise PromotionError("computed crop bounds are empty")
    return minimum, maximum


def parse_facing(auditor: ModuleType, state: str) -> tuple[int, int, int] | None:
    facing = auditor.properties(state).get("facing")
    return {
        "east": (1, 0, 0),
        "west": (-1, 0, 0),
        "up": (0, 1, 0),
        "down": (0, -1, 0),
        "south": (0, 0, 1),
        "north": (0, 0, -1),
    }.get(facing or "")


def crossing_key(row: dict[str, Any]) -> tuple[str, tuple[int, int, int], tuple[int, int, int]]:
    return (
        str(row["kind"]),
        tuple(int(part) for part in row["inside"]),
        tuple(int(part) for part in row["outside"]),
    )


def manifest_allowed_crossings(manifest: dict[str, Any]) -> dict[
    tuple[str, tuple[int, int, int], tuple[int, int, int]], str
]:
    boundary = manifest.get("boundary") or {}
    if not isinstance(boundary, dict):
        raise PromotionError("manifest.boundary must be an object")
    output: dict[tuple[str, tuple[int, int, int], tuple[int, int, int]], str] = {}
    for raw in boundary.get("allowed_crossings", ()) or ():
        if not isinstance(raw, dict):
            raise PromotionError("each allowed crossing must be an object")
        kind = str(raw.get("kind", "")).strip()
        inside = as_triplet(raw.get("inside"), "allowed crossing inside")
        outside = as_triplet(raw.get("outside"), "allowed crossing outside")
        reason = str(raw.get("reason", "")).strip()
        if not kind or not reason:
            raise PromotionError("allowed crossing requires kind and a review reason")
        output[(kind, inside, outside)] = reason
    return output


def declared_port_crossings(manifest: dict[str, Any]) -> set[
    tuple[tuple[int, int, int], tuple[int, int, int]]
]:
    pairs = set()
    for raw in manifest.get("ports") or []:
        if not isinstance(raw, dict):
            continue
        position = as_triplet(raw.get("source_position"), "port source_position")
        direction = as_triplet(raw.get("direction"), "port direction")
        if direction not in FACE_VECTORS:
            raise PromotionError("port direction must be one axis-aligned unit vector")
        pairs.add((position, add(position, direction)))
    return pairs


def boundary_crossings(
    blocks: dict[tuple[int, int, int], str],
    minimum: tuple[int, int, int],
    maximum: tuple[int, int, int],
    module_map: ModuleType,
    auditor: ModuleType,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    rows: dict[tuple[str, tuple[int, int, int], tuple[int, int, int]], dict[str, Any]] = {}
    port_pairs = declared_port_crossings(manifest)

    def record(kind: str, inside: tuple[int, int, int], outside: tuple[int, int, int]) -> None:
        inside_state = blocks.get(inside, "minecraft:air")
        outside_state = blocks.get(outside, "minecraft:air")
        if base_state(outside_state) in AIR:
            return
        key = (kind, inside, outside)
        rows[key] = {
            "kind": kind,
            "inside": list(inside),
            "outside": list(outside),
            "inside_state": inside_state,
            "outside_state": outside_state,
            "declared_port": (inside, outside) in port_pairs,
        }

    for point, state in blocks.items():
        if not inside_box(point, minimum, maximum) or base_state(state) in AIR:
            continue
        block_type = base_state(state)
        functional = module_map.is_functional_type(block_type)
        for vector in FACE_VECTORS:
            neighbour = add(point, vector)
            if inside_box(neighbour, minimum, maximum):
                continue
            neighbour_state = blocks.get(neighbour, "minecraft:air")
            neighbour_type = base_state(neighbour_state)
            if functional and module_map.is_functional_type(neighbour_type):
                record("functional-face-link", point, neighbour)
            if block_type in MOTION_TYPES or neighbour_type in MOTION_TYPES:
                if block_type in MOTION_TYPES and neighbour_type in MOTION_TYPES:
                    record("motion-cluster-link", point, neighbour)
            if block_type in {"minecraft:water", "minecraft:lava"} and neighbour_type == block_type:
                record("fluid-continuity", point, neighbour)
        if block_type in DIRECTIONAL_TYPES:
            facing = parse_facing(auditor, state)
            if facing:
                for vector in (facing, tuple(-part for part in facing)):
                    neighbour = add(point, vector)
                    if not inside_box(neighbour, minimum, maximum):
                        record("directional-endpoint", point, neighbour)
        if block_type in SUPPORT_REQUIRED:
            below = add(point, (0, -1, 0))
            if not inside_box(below, minimum, maximum):
                record("support-dependency", point, below)

    allowed_manifest = manifest_allowed_crossings(manifest)
    reviewed: list[dict[str, Any]] = []
    unreviewed: list[dict[str, Any]] = []
    for row in sorted(rows.values(), key=lambda item: crossing_key(item)):
        key = crossing_key(row)
        if row["declared_port"]:
            row["review"] = "declared port"
            reviewed.append(row)
        elif key in allowed_manifest:
            row["review"] = allowed_manifest[key]
            reviewed.append(row)
        else:
            unreviewed.append(row)
    unused_allowances = [
        {
            "kind": key[0],
            "inside": list(key[1]),
            "outside": list(key[2]),
            "reason": reason,
        }
        for key, reason in sorted(allowed_manifest.items())
        if key not in rows
    ]
    if unused_allowances:
        raise PromotionError(
            f"manifest contains {len(unused_allowances)} boundary allowances that do not match current source geometry"
        )
    return {
        "crossing_count": len(rows),
        "reviewed_crossings": reviewed,
        "unreviewed_crossings": unreviewed,
    }


def safe_block_entity(entity: dict[str, Any]) -> tuple[bool, str | None]:
    entity_id = str(entity.get("id", ""))
    if entity_id not in SAFE_REWRITABLE_BLOCK_ENTITIES:
        return False, f"block entity {entity_id!r} cannot be losslessly rewritten by the minimal Sponge writer"
    raw = entity.get("raw") or {}
    if not isinstance(raw, dict):
        return False, f"block entity {entity_id!r} has invalid raw NBT"
    items = raw.get("Items", raw.get("items"))
    if items not in (None, [], ()):
        return False, f"block entity {entity_id!r} contains inventory items"
    return True, None


def crop_model(
    blocks: dict[tuple[int, int, int], str],
    block_entities: Iterable[dict[str, Any]],
    minimum: tuple[int, int, int],
    maximum: tuple[int, int, int],
    data_version: int,
) -> dict[str, Any]:
    dimensions = tuple(maximum[index] - minimum[index] + 1 for index in range(3))
    cropped = {
        subtract(pos, minimum): state
        for pos, state in blocks.items()
        if inside_box(pos, minimum, maximum)
    }
    entities = []
    for entity in block_entities:
        pos = tuple(int(part) for part in entity["pos"])
        if not inside_box(pos, minimum, maximum):
            continue
        safe, reason = safe_block_entity(entity)
        if not safe:
            raise PromotionError(reason or "unsafe block entity")
        entities.append(
            {
                "pos": subtract(pos, minimum),
                "id": str(entity.get("id", "unknown")),
                "raw": dict(entity.get("raw") or {}),
            }
        )
    return {
        "format": "sponge-v2",
        "version": 2,
        "data_version": data_version,
        "blocks": cropped,
        "block_entities": entities,
        "source_dimensions": {
            "width": dimensions[0],
            "height": dimensions[1],
            "length": dimensions[2],
        },
    }


def runtime_module_row(
    trace_report: dict[str, Any], module_id: str, source_sha256: str
) -> dict[str, Any]:
    if str(trace_report.get("schematic_sha256", "")).lower() != source_sha256.lower():
        raise PromotionError("runtime trace report source hash does not match the promoted source")
    rows = [
        row for row in trace_report.get("modules") or []
        if str(row.get("module_id")) == module_id
    ]
    if len(rows) != 1:
        raise PromotionError(f"runtime trace does not contain exactly one row for {module_id}")
    return rows[0]


def evaluate_runtime_evidence(
    row: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    requirements = manifest.get("evidence", {}).get("runtime_requirements") or {}
    if not isinstance(requirements, dict):
        raise PromotionError("evidence.runtime_requirements must be an object")
    exclusive_counts = row.get("exclusive_event_counts") or {}
    exclusive_events = sum(int(value) for value in exclusive_counts.values())
    correlated = len(row.get("correlated_entity_uuids") or [])
    coverage = float(row.get("entity_profile_coverage", 0.0))
    failures = []
    if bool(requirements.get("require_active", True)) and not bool(row.get("active")):
        failures.append("module is not active in the supplied trace")
    minimum_exclusive = int(requirements.get("min_exclusive_component_events", 1))
    if exclusive_events < minimum_exclusive:
        failures.append(
            f"exclusive component events {exclusive_events} below required {minimum_exclusive}"
        )
    minimum_correlated = int(requirements.get("min_correlated_entities", 0))
    if correlated < minimum_correlated:
        failures.append(f"correlated entities {correlated} below required {minimum_correlated}")
    minimum_coverage = float(requirements.get("min_entity_profile_coverage", 0.0))
    if coverage < minimum_coverage:
        failures.append(f"entity profile coverage {coverage} below required {minimum_coverage}")
    if failures:
        raise PromotionError("runtime promotion gate failed: " + "; ".join(failures))
    return {
        "active": bool(row.get("active")),
        "first_tick": row.get("first_tick"),
        "last_tick": row.get("last_tick"),
        "event_counts": row.get("event_counts") or {},
        "exclusive_event_counts": exclusive_counts,
        "exclusive_component_events": exclusive_events,
        "correlated_entities": correlated,
        "entity_profile_coverage": coverage,
        "correlated_entity_types": row.get("correlated_entity_types") or {},
        "runtime_role_candidates_for_review_only": row.get("runtime_role_candidates") or [],
    }


def validate_field_record(
    manifest: dict[str, Any], source_sha256: str, module_id: str
) -> dict[str, Any] | None:
    level = str(manifest["evidence"]["level"])
    if EVIDENCE_RANK[level] < EVIDENCE_RANK["field-reported"]:
        return None
    record = manifest["evidence"].get("field_record")
    if not isinstance(record, dict):
        raise PromotionError(f"{level} promotion requires evidence.field_record")
    required = ("server", "date", "observation", "source")
    missing = [key for key in required if not str(record.get(key, "")).strip()]
    if missing:
        raise PromotionError(f"field_record is missing: {', '.join(missing)}")
    if str(record.get("source_sha256", "")).lower() != source_sha256.lower():
        raise PromotionError("field_record.source_sha256 does not match source")
    if str(record.get("module_id", "")) != module_id:
        raise PromotionError("field_record.module_id does not match selected module")
    return dict(record)


def validate_capabilities(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    component_level = str(manifest["evidence"]["level"])
    output = []
    seen = set()
    for raw in manifest["capabilities"]:
        if not isinstance(raw, dict):
            raise PromotionError("each capability must be an object")
        capability_id = str(raw.get("id", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()
        justification = str(raw.get("justification", "")).strip()
        if not capability_id or capability_id in seen:
            raise PromotionError(f"capability id is missing or duplicated: {capability_id!r}")
        if evidence not in EVIDENCE_RANK:
            raise PromotionError(f"capability {capability_id}: invalid evidence {evidence!r}")
        if EVIDENCE_RANK[evidence] > EVIDENCE_RANK[component_level]:
            raise PromotionError(
                f"capability {capability_id}: evidence exceeds component promotion evidence"
            )
        if EVIDENCE_RANK[evidence] >= EVIDENCE_RANK["static"] and not justification:
            raise PromotionError(f"capability {capability_id}: justification is required")
        seen.add(capability_id)
        output.append(
            {
                "id": capability_id,
                "evidence": evidence,
                "justification": justification,
            }
        )
    return output


def validate_ports(
    manifest: dict[str, Any],
    minimum: tuple[int, int, int],
    maximum: tuple[int, int, int],
    blocks: dict[tuple[int, int, int], str],
) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for raw in manifest["ports"]:
        if not isinstance(raw, dict):
            raise PromotionError("each port must be an object")
        port_id = str(raw.get("id", "")).strip()
        kind = str(raw.get("kind", "")).strip()
        medium = str(raw.get("medium", "")).strip()
        source_position = as_triplet(raw.get("source_position"), f"port {port_id} source_position")
        direction = as_triplet(raw.get("direction"), f"port {port_id} direction")
        contract = raw.get("contract") or {}
        if not port_id or port_id in seen:
            raise PromotionError(f"port id is missing or duplicated: {port_id!r}")
        if kind not in {"input", "output"}:
            raise PromotionError(f"port {port_id}: kind must be input/output")
        if not medium:
            raise PromotionError(f"port {port_id}: medium is required")
        if direction not in FACE_VECTORS:
            raise PromotionError(f"port {port_id}: direction must be axis-aligned")
        if not isinstance(contract, dict):
            raise PromotionError(f"port {port_id}: contract must be an object")
        if not inside_box(source_position, minimum, maximum):
            raise PromotionError(f"port {port_id}: source position is outside the crop")
        if base_state(blocks.get(source_position, "minecraft:air")) in AIR:
            raise PromotionError(f"port {port_id}: source position points to air")
        seen.add(port_id)
        output.append(
            {
                "id": port_id,
                "kind": kind,
                "medium": medium,
                "position": list(subtract(source_position, minimum)),
                "direction": list(direction),
                "contract": dict(contract),
            }
        )
    return output


def verify_output(
    output_path: Path,
    expected: dict[str, Any],
    auditor: ModuleType,
    data_version: int,
) -> dict[str, Any]:
    root_name, root, trailing, _size, diagnostics = auditor.load(output_path)
    if trailing:
        raise PromotionError("promoted schematic has trailing NBT bytes")
    decoded = auditor.decode_any(root_name, root)
    blocks, entities, dimensions, actual_data_version = normalize_model(decoded)
    expected_occupied = {
        pos: state for pos, state in expected["blocks"].items() if base_state(state) not in AIR
    }
    actual_occupied = {
        pos: state for pos, state in blocks.items() if base_state(state) not in AIR
    }
    if actual_occupied != expected_occupied:
        raise PromotionError("promoted schematic occupied geometry does not round-trip exactly")
    expected_entities = sorted(tuple(entity["pos"]) for entity in expected["block_entities"])
    actual_entities = sorted(tuple(entity["pos"]) for entity in entities)
    if actual_entities != expected_entities:
        raise PromotionError("promoted schematic block-entity positions do not round-trip exactly")
    if actual_data_version != data_version:
        raise PromotionError("promoted schematic DataVersion does not round-trip")
    return {
        "path": str(output_path),
        "sha256": sha256_file(output_path),
        "bytes": output_path.stat().st_size,
        "data_version": actual_data_version,
        "dimensions": list(dimensions),
        "occupied_blocks": len(actual_occupied),
        "block_entities": len(actual_entities),
        "geometry_verified": True,
        "container_diagnostics": diagnostics,
    }


def registry_document(
    manifest: dict[str, Any],
    output_schematic: Path,
    registry_path: Path,
    output_verification: dict[str, Any],
    capabilities: list[dict[str, Any]],
    ports: list[dict[str, Any]],
    source_sha256: str,
    module: dict[str, Any],
) -> dict[str, Any]:
    component = manifest["component"]
    relative_path = os.path.relpath(output_schematic, registry_path.parent)
    entry = {
        "id": str(component["id"]),
        "version": str(component["version"]),
        "evidence": {
            "level": str(manifest["evidence"]["level"]),
            "sources": [str(item) for item in manifest["evidence"]["sources"]],
        },
        "capabilities": [
            {"id": row["id"], "evidence": row["evidence"]}
            for row in capabilities
        ],
        "schematic": {
            "path": relative_path.replace("\\", "/"),
            "sha256": output_verification["sha256"],
            "data_version": output_verification["data_version"],
        },
        "ports": ports,
        "reusable": bool(component.get("reusable", False)),
        "source": {
            "kind": str(component.get("source_kind", "reviewed-reference")),
            "sha256": source_sha256,
            "module_id": str(module.get("module_id")),
            "module_signature": str(module.get("signature")),
            "evidence_label": str(manifest["evidence"]["level"]),
        },
    }
    return {
        "schema_version": 1,
        "id": f"promoted-{entry['id']}-{entry['version']}",
        "components": [entry],
    }


def run_promotion(
    source_path: Path,
    manifest_path: Path,
    trace_path: Path | None,
    schematic_out: Path,
    registry_out: Path,
    report_out: Path | None,
    repo_root: Path,
    output_data_version: int | None,
) -> dict[str, Any]:
    auditor = load_script(repo_root, "component_promotion_schem_audit", "schem-audit.py")
    module_map = load_script(repo_root, "component_promotion_module_map", "cannon-module-map.py")
    module_trace = load_script(repo_root, "component_promotion_module_trace", "analyze-module-trace.py")
    planner = load_script(repo_root, "component_promotion_synthesis_planner", "cannon-synthesis-planner.py")

    manifest = load_json_object(manifest_path)
    validate_manifest(manifest)
    source_path = source_path.resolve()
    source_sha256 = sha256_file(source_path)
    expected_source_sha = str(manifest["source"]["sha256"]).lower()
    if source_sha256 != expected_source_sha:
        raise PromotionError(
            f"source hash mismatch expected={expected_source_sha} actual={source_sha256}"
        )

    root_name, root, trailing, _decoded_size, container_diagnostics = auditor.load(source_path)
    if trailing:
        raise PromotionError("source schematic has trailing NBT bytes")
    decoded = auditor.decode_any(root_name, root)
    blocks, block_entities, source_dims, source_data_version = normalize_model(decoded)
    module_report = module_map.build_report(source_path)
    if str(module_report.get("file_sha256", "")).lower() != source_sha256:
        raise PromotionError("module map source hash does not match source")
    module = select_module(module_report, manifest)
    module_id = str(module["module_id"])
    minimum, maximum = crop_bounds(module, manifest, source_dims)

    boundary = boundary_crossings(
        blocks,
        minimum,
        maximum,
        module_map,
        auditor,
        manifest,
    )
    if boundary["unreviewed_crossings"]:
        raise PromotionError(
            f"crop has {len(boundary['unreviewed_crossings'])} unreviewed functional boundary crossings"
        )

    evidence_level = str(manifest["evidence"]["level"])
    runtime_evidence = None
    trace_report = None
    if EVIDENCE_RANK[evidence_level] >= EVIDENCE_RANK["local-runtime"]:
        if trace_path is None:
            raise PromotionError(f"{evidence_level} promotion requires --trace")
        trace_report = module_trace.build_report(source_path, trace_path.resolve())
        runtime_row = runtime_module_row(trace_report, module_id, source_sha256)
        runtime_evidence = evaluate_runtime_evidence(runtime_row, manifest)
    field_record = validate_field_record(manifest, source_sha256, module_id)
    capabilities = validate_capabilities(manifest)
    ports = validate_ports(manifest, minimum, maximum, blocks)

    target_data_version = source_data_version if output_data_version is None else int(output_data_version)
    if target_data_version != source_data_version and not bool(
        manifest.get("component", {}).get("allow_data_version_retag", False)
    ):
        raise PromotionError(
            "output DataVersion differs from source; set component.allow_data_version_retag=true only after block-state review"
        )
    model = crop_model(
        blocks,
        block_entities,
        minimum,
        maximum,
        target_data_version,
    )
    schematic_out = schematic_out.resolve()
    schematic_out.parent.mkdir(parents=True, exist_ok=True)
    auditor.write_sponge_v2(schematic_out, model, target_data_version)
    output_verification = verify_output(
        schematic_out,
        model,
        auditor,
        target_data_version,
    )

    registry_out = registry_out.resolve()
    registry = registry_document(
        manifest,
        schematic_out,
        registry_out,
        output_verification,
        capabilities,
        ports,
        source_sha256,
        module,
    )
    write_json(registry_out, registry)
    validated_registry = planner.load_registry(registry_out, auditor)
    if set(validated_registry) != {str(manifest["component"]["id"])}:
        raise PromotionError("generated registry did not validate through the synthesis planner")

    report = {
        "schema_version": 1,
        "status": "PASS",
        "promotion": "PROMOTED_COMPONENT_CANDIDATE",
        "source": {
            "path": str(source_path),
            "sha256": source_sha256,
            "format": decoded.get("format"),
            "data_version": source_data_version,
            "dimensions": list(source_dims),
            "container_diagnostics": container_diagnostics,
        },
        "selection": {
            "module_id": module_id,
            "module_signature": module.get("signature"),
            "module_kind": module.get("kind"),
            "module_component_count": module.get("component_count"),
            "crop_minimum": list(minimum),
            "crop_maximum": list(maximum),
            "crop_dimensions": model["source_dimensions"],
        },
        "boundary": boundary,
        "evidence": {
            "level": evidence_level,
            "sources": manifest["evidence"]["sources"],
            "runtime": runtime_evidence,
            "field_record": field_record,
            "module_trace_summary": trace_report.get("summary") if trace_report else None,
        },
        "capabilities": capabilities,
        "ports": ports,
        "output": output_verification,
        "registry": {
            "path": str(registry_out),
            "validated_by_synthesis_planner": True,
            "component_id": str(manifest["component"]["id"]),
        },
        "next_required": [
            "assemble only through declared ports",
            "run preservation checks against the exact source",
            "run real input activation and causal trace on the assembled candidate",
            "compare source-accounted entity and impulse behavior",
            "complete a controlled live ExtremeCraft canary before any EC-ready claim",
        ],
        "truth_boundary": {
            "source_geometry_hash_verified": True,
            "module_signature_verified": True,
            "runtime_role_inferred_from_filename_or_shape": False,
            "capabilities_are_explicit_reviewed_claims": True,
            "crop_boundary_clean_or_explicitly_reviewed": True,
            "standalone_runtime_compatibility_confirmed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }
    if report_out is not None:
        write_json(report_out.resolve(), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote one exact CannonLab module into a deterministic synthesis component "
            "without inventing subsystem roles"
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--schem-out", type=Path, required=True)
    parser.add_argument("--registry-out", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-data-version", type=int)
    args = parser.parse_args()

    try:
        report = run_promotion(
            args.source,
            args.manifest,
            args.trace,
            args.schem_out,
            args.registry_out,
            args.json_out,
            args.repo_root.resolve(),
            args.output_data_version,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, PromotionError, ValueError) as exc:
        failure = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "standalone_runtime_compatibility_confirmed": False,
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
        if args.json_out:
            write_json(args.json_out.resolve(), failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
