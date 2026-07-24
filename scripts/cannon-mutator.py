#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nbtlib
from nbtlib import ByteArray, Compound, File, Int, IntArray, List, Short, String


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
OUTPUT_ROOT = WORKSPACE_ROOT / "output"
SCRIPTS = ROOT / "scripts"
AUDITOR_PATH = SCRIPTS / "schem-audit.py"
ALIGNMENT_AUDITOR = SCRIPTS / "paste-alignment-audit.py"
PRESERVATION_CHECK = SCRIPTS / "cannon-preservation-check.py"
MUTATION_ROOT = ROOT / "mutation-jobs"
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
TILE_BLOCKS = {
    "minecraft:dispenser", "minecraft:dropper", "minecraft:chest", "minecraft:trapped_chest",
    "minecraft:barrel", "minecraft:hopper", "minecraft:furnace", "minecraft:blast_furnace",
    "minecraft:smoker", "minecraft:brewing_stand", "minecraft:comparator", "minecraft:beacon",
    "minecraft:ender_chest", "minecraft:spawner", "minecraft:lectern", "minecraft:sign",
    "minecraft:wall_sign", "minecraft:shulker_box",
}


def load_auditor() -> Any:
    spec = importlib.util.spec_from_file_location("cannonlab_schem_audit", AUDITOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {AUDITOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDITOR = load_auditor()


def slugify(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return value[:72] or "bounded-mutation"


def allowed_path(raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"path escapes CannonLab repository/output roots: {raw}")
    if must_exist and not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def point(raw: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError(f"{label} must be [x,y,z]")
    try:
        return tuple(int(value) for value in raw)  # type: ignore[return-value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain integers") from exc


def state_with_properties(block_type: str, properties: dict[str, str]) -> str:
    if not properties:
        return block_type
    return block_type + "[" + ",".join(f"{key}={properties[key]}" for key in sorted(properties)) + "]"


def is_tile_block(block_type: str) -> bool:
    return (
        block_type in TILE_BLOCKS
        or block_type.endswith("_sign")
        or block_type.endswith("_wall_sign")
        or block_type.endswith("_shulker_box")
    )


def inside_dimensions(position: tuple[int, int, int], dimensions: dict[str, int]) -> bool:
    x, y, z = position
    return (
        0 <= x < int(dimensions["width"])
        and 0 <= y < int(dimensions["height"])
        and 0 <= z < int(dimensions["length"])
    )


def read_model(path: Path) -> dict[str, Any]:
    root_name, root, trailing, _decoded_size, diagnostics = AUDITOR.load(path)
    if trailing:
        raise ValueError(f"source NBT has {len(trailing)} trailing bytes")
    model = AUDITOR.decode_any(root_name, root)
    model["load_diagnostics"] = diagnostics
    return model


def entity_position(entity: Compound) -> tuple[int, int, int] | None:
    pos = entity.get("Pos")
    if pos is not None and len(pos) >= 3:
        return tuple(int(pos[index]) for index in range(3))  # type: ignore[return-value]
    if all(axis in entity for axis in ("x", "y", "z")):
        return tuple(int(entity[axis]) for axis in ("x", "y", "z"))  # type: ignore[return-value]
    return None


def normalize_entity(entity: Compound, position: tuple[int, int, int], block_state: str) -> Compound:
    result = copy.deepcopy(entity)
    for key in ("x", "y", "z", "pos"):
        result.pop(key, None)
    existing_id = result.pop("id", None)
    if "Id" not in result:
        result["Id"] = String(str(existing_id) if existing_id is not None else AUDITOR.block_entity_id(AUDITOR.base(block_state)))
    result["Pos"] = IntArray(position)
    return result


def extract_block_entities(path: Path, model: dict[str, Any]) -> list[Compound]:
    source = nbtlib.load(path)
    entities: list[Compound] = []
    if model["format"] == "sponge-v2":
        for raw in source.get("BlockEntities", List[Compound]([])):
            if not isinstance(raw, Compound):
                continue
            pos = entity_position(raw)
            if pos is None:
                continue
            entities.append(normalize_entity(raw, pos, model["blocks"].get(pos, "minecraft:air")))
        return entities

    regions = source.get("Regions")
    if not isinstance(regions, Compound):
        return entities
    region_geometry: list[tuple[Compound, tuple[int, int, int]]] = []
    global_mins: list[tuple[int, int, int]] = []
    for region in regions.values():
        if not isinstance(region, Compound):
            continue
        size = region.get("Size", Compound())
        position = region.get("Position", Compound())
        signed = tuple(int(size.get(axis, 0)) for axis in ("x", "y", "z"))
        corner = tuple(int(position.get(axis, 0)) for axis in ("x", "y", "z"))
        region_min = tuple(
            min(corner[index], corner[index] + signed[index] + (1 if signed[index] < 0 else -1))
            for index in range(3)
        )
        region_geometry.append((region, region_min))
        global_mins.append(region_min)
    if not global_mins:
        return entities
    global_min = tuple(min(item[axis] for item in global_mins) for axis in range(3))
    for region, region_min in region_geometry:
        for raw in region.get("TileEntities", List[Compound]([])):
            if not isinstance(raw, Compound):
                continue
            local = entity_position(raw)
            if local is None:
                continue
            normalized = tuple(region_min[index] + local[index] - global_min[index] for index in range(3))
            entities.append(normalize_entity(raw, normalized, model["blocks"].get(normalized, "minecraft:air")))
    return entities


def entity_map(entities: list[Compound]) -> dict[tuple[int, int, int], Compound]:
    result: dict[tuple[int, int, int], Compound] = {}
    for entity in entities:
        pos = entity_position(entity)
        if pos is None:
            continue
        if pos in result:
            raise ValueError(f"duplicate block entity at {pos}")
        result[pos] = entity
    return result


def apply_set_repeater_delay(
    operation: dict[str, Any],
    blocks: dict[tuple[int, int, int], str],
    dimensions: dict[str, int],
) -> dict[str, Any]:
    pos = point(operation.get("position"), "position")
    if not inside_dimensions(pos, dimensions):
        raise ValueError(f"repeater position outside dimensions: {pos}")
    current = blocks.get(pos, "minecraft:air")
    expected = str(operation.get("expected_state", ""))
    if not expected:
        raise ValueError("set-repeater-delay requires expected_state")
    if current != expected:
        raise ValueError(f"expected {expected} at {pos}, found {current}")
    if AUDITOR.base(current) != "minecraft:repeater":
        raise ValueError(f"block at {pos} is not a repeater: {current}")
    delay = int(operation.get("delay", 0))
    if delay not in {1, 2, 3, 4}:
        raise ValueError("repeater delay must be 1..4")
    props = AUDITOR.properties(current)
    props["delay"] = str(delay)
    updated = state_with_properties("minecraft:repeater", props)
    blocks[pos] = updated
    return {"type": "set-repeater-delay", "position": list(pos), "before": current, "after": updated}


def apply_set_block_state(
    operation: dict[str, Any],
    blocks: dict[tuple[int, int, int], str],
    dimensions: dict[str, int],
    entities: dict[tuple[int, int, int], Compound],
) -> dict[str, Any]:
    pos = point(operation.get("position"), "position")
    if not inside_dimensions(pos, dimensions):
        raise ValueError(f"block position outside dimensions: {pos}")
    current = blocks.get(pos, "minecraft:air")
    expected = str(operation.get("expected_state", ""))
    updated = str(operation.get("new_state", ""))
    if not expected or not updated:
        raise ValueError("set-block-state requires expected_state and new_state")
    if current != expected:
        raise ValueError(f"expected {expected} at {pos}, found {current}")
    if AUDITOR.base(updated) in AIR:
        raise ValueError("set-block-state cannot delete a block; use a reviewed region move instead")
    current_tile = is_tile_block(AUDITOR.base(current))
    updated_tile = is_tile_block(AUDITOR.base(updated))
    if current_tile != updated_tile or (current_tile and AUDITOR.base(current) != AUDITOR.base(updated)):
        raise ValueError("set-block-state cannot add, remove, or change a block-entity type")
    if pos in entities and not updated_tile:
        raise ValueError(f"block entity at {pos} would become invalid")
    blocks[pos] = updated
    return {"type": "set-block-state", "position": list(pos), "before": current, "after": updated}


def region_points(minimum: tuple[int, int, int], maximum: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    if any(minimum[index] > maximum[index] for index in range(3)):
        raise ValueError("region min must be <= max on every axis")
    return [
        (x, y, z)
        for y in range(minimum[1], maximum[1] + 1)
        for z in range(minimum[2], maximum[2] + 1)
        for x in range(minimum[0], maximum[0] + 1)
    ]


def apply_translate_region(
    operation: dict[str, Any],
    blocks: dict[tuple[int, int, int], str],
    dimensions: dict[str, int],
    entities: dict[tuple[int, int, int], Compound],
) -> dict[str, Any]:
    minimum = point(operation.get("min"), "min")
    maximum = point(operation.get("max"), "max")
    delta = point(operation.get("delta"), "delta")
    if delta == (0, 0, 0):
        raise ValueError("translate-region delta cannot be zero")
    points = region_points(minimum, maximum)
    if not all(inside_dimensions(pos, dimensions) for pos in points):
        raise ValueError("translate-region source leaves schematic dimensions")
    selected = {
        pos: blocks.get(pos, "minecraft:air")
        for pos in points
        if AUDITOR.base(blocks.get(pos, "minecraft:air")) not in AIR
    }
    expected_non_air = operation.get("expected_non_air")
    if expected_non_air is None:
        raise ValueError("translate-region requires expected_non_air")
    if len(selected) != int(expected_non_air):
        raise ValueError(f"translate-region expected {expected_non_air} non-air blocks, found {len(selected)}")
    if not selected:
        raise ValueError("translate-region selection is empty")
    source_positions = set(points)
    targets = {pos: tuple(pos[index] + delta[index] for index in range(3)) for pos in selected}
    if not all(inside_dimensions(pos, dimensions) for pos in targets.values()):
        raise ValueError("translate-region target leaves schematic dimensions")
    for source, target in targets.items():
        target_state = blocks.get(target, "minecraft:air")
        if target not in source_positions and AUDITOR.base(target_state) not in AIR:
            raise ValueError(f"translate-region collision at {target}: {target_state}")
    moving_entities = {pos: entities[pos] for pos in selected if pos in entities}
    for pos in selected:
        blocks[pos] = "minecraft:air"
        entities.pop(pos, None)
    for source, state in selected.items():
        target = targets[source]
        blocks[target] = state
        if source in moving_entities:
            moved = copy.deepcopy(moving_entities[source])
            moved["Pos"] = IntArray(target)
            entities[target] = moved
    return {
        "type": "translate-region",
        "min": list(minimum),
        "max": list(maximum),
        "delta": list(delta),
        "moved_non_air": len(selected),
        "moved_block_entities": len(moving_entities),
    }


def block_diff(
    before: dict[tuple[int, int, int], str],
    after: dict[tuple[int, int, int], str],
) -> list[dict[str, Any]]:
    changed = []
    for pos in sorted(set(before) | set(after)):
        old = before.get(pos, "minecraft:air")
        new = after.get(pos, "minecraft:air")
        if old != new:
            changed.append({"position": list(pos), "before": old, "after": new})
    return changed


def signed_bytes(data: bytes) -> list[int]:
    return [value if value < 128 else value - 256 for value in data]


def write_sponge_v2(
    path: Path,
    *,
    blocks: dict[tuple[int, int, int], str],
    dimensions: dict[str, int],
    entities: dict[tuple[int, int, int], Compound],
    data_version: int,
) -> None:
    width = int(dimensions["width"])
    height = int(dimensions["height"])
    length = int(dimensions["length"])
    states = sorted(set(blocks.values()), key=lambda value: (AUDITOR.base(value) not in AIR, value))
    if "minecraft:air" not in states:
        states.insert(0, "minecraft:air")
    palette = {state: index for index, state in enumerate(states)}
    ids = [
        palette[blocks.get((x, y, z), "minecraft:air")]
        for y in range(height)
        for z in range(length)
        for x in range(width)
    ]
    encoded = AUDITOR.encode_varints(ids)
    block_entities = []
    for pos, entity in sorted(entities.items()):
        state = blocks.get(pos, "minecraft:air")
        if not is_tile_block(AUDITOR.base(state)):
            raise ValueError(f"orphaned block entity at {pos}: {state}")
        normalized = copy.deepcopy(entity)
        normalized["Pos"] = IntArray(pos)
        if "Id" not in normalized:
            normalized["Id"] = String(AUDITOR.block_entity_id(AUDITOR.base(state)))
        block_entities.append(normalized)
    schematic = File(
        {
            "Metadata": Compound({"WEOffsetX": Int(0), "WEOffsetY": Int(0), "WEOffsetZ": Int(0)}),
            "Palette": Compound({state: Int(value) for state, value in palette.items()}),
            "BlockEntities": List[Compound](block_entities),
            "DataVersion": Int(data_version),
            "Height": Short(height),
            "Length": Short(length),
            "PaletteMax": Int(len(palette)),
            "Version": Int(2),
            "Width": Short(width),
            "BlockData": ByteArray(signed_bytes(encoded)),
            "Offset": IntArray([0, 0, 0]),
        },
        gzipped=True,
        root_name="Schematic",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    schematic.save(path, gzipped=True)


def run_json(command: list[str], timeout: int = 600) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"status": "ERROR", "error": result.stderr[-3000:] or result.stdout[-3000:]}
    return result.returncode, payload


def apply_plan(plan_path_raw: str) -> dict[str, Any]:
    plan_path = allowed_path(plan_path_raw)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != "cannonlab-bounded-mutation-plan-v1":
        raise ValueError("unsupported mutation plan schema")
    parent = allowed_path(plan.get("parent", ""))
    output = allowed_path(plan.get("output", ""), must_exist=False)
    if output == parent:
        raise ValueError("mutation output must not overwrite the parent")
    if output.suffix.lower() != ".schem":
        raise ValueError("mutation output must be a Sponge .schem")
    declared_variable = str(plan.get("declared_variable", "")).strip()
    if not declared_variable:
        raise ValueError("declared_variable is required")
    max_changed_blocks = int(plan.get("max_changed_blocks", 0))
    if max_changed_blocks < 1:
        raise ValueError("max_changed_blocks must be positive")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations must be a non-empty list")

    model = read_model(parent)
    before_blocks = dict(model["blocks"])
    blocks = dict(before_blocks)
    dimensions = dict(model["source_dimensions"])
    entities = entity_map(extract_block_entities(parent, model))
    before_entity_count = len(entities)
    operation_reports = []
    allowed_operations = {"set-repeater-delay", "set-block-state", "translate-region"}
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise ValueError(f"operations[{index}] must be an object")
        operation_type = str(raw.get("type", ""))
        if operation_type not in allowed_operations:
            raise ValueError(f"unsupported bounded mutation operation: {operation_type}")
        if operation_type == "set-repeater-delay":
            operation_reports.append(apply_set_repeater_delay(raw, blocks, dimensions))
        elif operation_type == "set-block-state":
            operation_reports.append(apply_set_block_state(raw, blocks, dimensions, entities))
        else:
            operation_reports.append(apply_translate_region(raw, blocks, dimensions, entities))

    changes = block_diff(before_blocks, blocks)
    if not changes:
        raise ValueError("mutation plan produced no block-state changes")
    if len(changes) > max_changed_blocks:
        raise ValueError(f"mutation changed {len(changes)} blocks, budget is {max_changed_blocks}")
    data_version = int(plan.get("data_version", 3465))
    write_sponge_v2(
        output,
        blocks=blocks,
        dimensions=dimensions,
        entities=entities,
        data_version=data_version,
    )

    decoded = read_model(output)
    if decoded["blocks"] != blocks:
        raise RuntimeError("written schematic does not decode to the intended block geometry")
    output_entities = entity_map(extract_block_entities(output, decoded))
    if set(output_entities) != set(entities):
        raise RuntimeError("written schematic changed block-entity positions unexpectedly")

    job = slugify(str(plan.get("job") or output.stem))
    job_dir = MUTATION_ROOT / job
    job_dir.mkdir(parents=True, exist_ok=True)
    diff_path = job_dir / "block-diff.json"
    diff_path.write_text(json.dumps({"changes": changes}, indent=2) + "\n", encoding="utf-8")
    rollback_path = job_dir / "rollback.json"
    rollback_path.write_text(json.dumps({
        "schema": "cannonlab-exact-parent-rollback-v1",
        "restore_parent": str(parent),
        "restore_parent_sha256": sha256(parent),
        "replace_output": str(output),
        "rule": "Restore the exact parent binary; do not reverse-edit a mutated cannon by memory.",
    }, indent=2) + "\n", encoding="utf-8")

    alignment_code, alignment = run_json([
        sys.executable, str(ALIGNMENT_AUDITOR), str(output),
        "--chunk-limit", str(int(plan.get("chunk_limit", 160))),
    ])
    preservation_options = plan.get("preservation", {}) if isinstance(plan.get("preservation"), dict) else {}
    structural_ratio = float(preservation_options.get("max_structural_change_ratio", 0.05))
    functional_ratio = float(preservation_options.get("max_functional_change_ratio", 0.10))
    max_modules = int(preservation_options.get("max_modules_touched", 1))
    preservation_command = [
        sys.executable, str(PRESERVATION_CHECK), str(parent), str(output),
        "--chunk-limit", str(int(plan.get("chunk_limit", 160))),
        "--alignment-mode", "exact",
        "--max-structural-change-ratio", str(structural_ratio),
        "--max-functional-change-ratio", str(functional_ratio),
        "--max-modules-touched", str(max_modules),
        "--max-unexpected-critical-changes", str(max_changed_blocks),
    ]
    parent_entity_positions = set(entity_map(extract_block_entities(parent, model)))
    if set(output_entities) != parent_entity_positions:
        preservation_command.append("--allow-block-entity-topology-change")
    preservation_code, preservation = run_json(preservation_command)

    blockers = []
    if preservation_code != 0 or str(preservation.get("status", "")).upper() in {"FAIL", "BLOCKED", "ERROR"}:
        blockers.append({"code": "preservation-failed", "message": "reference preservation gate did not pass"})
    require_ec160 = plan.get("require_ec160_safe") is True
    alignment_safe = alignment_code == 0 and str(alignment.get("status", "")).upper() not in {"FAIL", "BLOCKED", "ERROR"}
    if require_ec160 and not alignment_safe:
        blockers.append({"code": "ec160-alignment-failed", "message": "mutated output has no accepted EC160 alignment"})

    manifest = {
        "schema": "cannonlab-bounded-mutation-result-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": (
            "This proves a bounded deterministic file mutation and static preservation checks only. "
            "It does not prove runtime function, one-shot behavior, or ExtremeCraft readiness."
        ),
        "job": job,
        "declared_variable": declared_variable,
        "parent": {"path": str(parent), "sha256": sha256(parent), "format": model["format"]},
        "output": {"path": str(output), "sha256": sha256(output), "data_version": data_version},
        "operation_reports": operation_reports,
        "changed_blocks": len(changes),
        "max_changed_blocks": max_changed_blocks,
        "block_entities_before": before_entity_count,
        "block_entities_after": len(output_entities),
        "diff_report": str(diff_path.relative_to(ROOT)).replace("\\", "/"),
        "rollback_report": str(rollback_path.relative_to(ROOT)).replace("\\", "/"),
        "alignment": alignment,
        "preservation": preservation,
        "blockers": blockers,
    }
    manifest_path = job_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["manifest"] = str(manifest_path.relative_to(ROOT)).replace("\\", "/")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a reviewed, bounded, non-destructive cannon mutation plan")
    parser.add_argument("plan")
    args = parser.parse_args()
    result = apply_plan(args.plan)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
