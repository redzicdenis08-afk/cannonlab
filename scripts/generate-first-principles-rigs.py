#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
ALLOWED_FAMILIES = {"protected-charge-cell", "payload-injector", "guider"}


class RigGenerationError(ValueError):
    pass


def load_audit() -> Any:
    script = Path(__file__).with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("first_principles_rig_audit", script)
    if spec is None or spec.loader is None:
        raise RigGenerationError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RigGenerationError("profile must be a JSON object")
    return payload


def integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RigGenerationError(f"{label} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise RigGenerationError(f"{label} must be between {minimum} and {maximum}")
    return result


def validate_profile(profile: dict[str, Any]) -> None:
    if int(profile.get("schema_version", 0)) != 1:
        raise RigGenerationError("schema_version must equal 1")
    if profile.get("mode") != "from-scratch":
        raise RigGenerationError("mode must equal 'from-scratch'")
    if profile.get("source_schematic") not in (None, ""):
        raise RigGenerationError("source_schematic is forbidden")
    integer(profile.get("data_version"), "data_version", 1, 10_000_000)
    integer(profile.get("chunk_limit"), "chunk_limit", 1, 10_000)
    families = profile.get("families")
    if not isinstance(families, list) or not families:
        raise RigGenerationError("families must be a non-empty list")
    seen: set[str] = set()
    for raw in families:
        if not isinstance(raw, dict):
            raise RigGenerationError("each family must be an object")
        family_id = str(raw.get("id", "")).strip()
        if family_id not in ALLOWED_FAMILIES:
            raise RigGenerationError(f"unsupported family {family_id!r}")
        if family_id in seen:
            raise RigGenerationError(f"duplicate family {family_id}")
        seen.add(family_id)
        key = {
            "protected-charge-cell": "cell_counts",
            "payload-injector": "repeater_delays",
            "guider": "lengths",
        }[family_id]
        values = raw.get(key)
        if not isinstance(values, list) or not values:
            raise RigGenerationError(f"{family_id}.{key} must be non-empty")
        limits = {
            "protected-charge-cell": (1, 16),
            "payload-injector": (1, 4),
            "guider": (1, 128),
        }[family_id]
        for index, value in enumerate(values):
            integer(value, f"{family_id}.{key}[{index}]", *limits)
        if family_id == "guider":
            integer(raw.get("repeater_delay", 1), "guider.repeater_delay", 1, 4)


def base_state(state: str) -> str:
    return state.split("[", 1)[0]


def occupied(blocks: dict[tuple[int, int, int], str]) -> dict[tuple[int, int, int], str]:
    return {pos: state for pos, state in blocks.items() if base_state(state) not in AIR}


def bounds_for(blocks: dict[tuple[int, int, int], str]) -> dict[str, Any]:
    positions = list(occupied(blocks))
    if not positions:
        raise RigGenerationError("generated rig is empty")
    minimum = [min(pos[index] for pos in positions) for index in range(3)]
    maximum = [max(pos[index] for pos in positions) for index in range(3)]
    if minimum != [0, 0, 0]:
        raise RigGenerationError(f"rig must be normalized to origin, observed minimum {minimum}")
    return {
        "min": minimum,
        "max": maximum,
        "dimensions": [maximum[index] + 1 for index in range(3)],
    }


def set_block(blocks: dict[tuple[int, int, int], str], pos: tuple[int, int, int], state: str) -> None:
    previous = blocks.get(pos)
    if previous is not None and previous != state:
        raise RigGenerationError(f"conflicting generated blocks at {pos}: {previous!r} vs {state!r}")
    blocks[pos] = state


def make_model(
    blocks: dict[tuple[int, int, int], str],
    dispenser_positions: Iterable[tuple[int, int, int]],
) -> dict[str, Any]:
    bounds = bounds_for(blocks)
    return {
        "blocks": blocks,
        "block_entities": [
            {"pos": tuple(pos), "id": "minecraft:dispenser", "raw": {}}
            for pos in sorted(set(dispenser_positions))
        ],
        "source_dimensions": {
            "width": bounds["dimensions"][0],
            "height": bounds["dimensions"][1],
            "length": bounds["dimensions"][2],
        },
    }


def build_protected_charge_cells(cell_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    blocks: dict[tuple[int, int, int], str] = {}
    dispensers: list[tuple[int, int, int]] = []
    fire_inputs: list[list[int]] = []
    water_cells: list[list[int]] = []

    for cell_index in range(cell_count):
        base_z = 1 + cell_index * 6
        center_z = base_z + 1
        fire_inputs.append([1, 2, center_z])
        cell_dispensers = [
            (1, 1, center_z),
            (1, 3, center_z),
            (1, 2, base_z),
            (1, 2, base_z + 2),
        ]
        for dispenser in cell_dispensers:
            dispensers.append(dispenser)
            set_block(blocks, dispenser, "minecraft:dispenser[facing=east,triggered=false]")
            x, y, z = dispenser
            set_block(blocks, (0, y, z), "minecraft:obsidian")
            water = (x + 1, y, z)
            water_cells.append(list(water))
            set_block(blocks, water, "minecraft:water[level=0]")
            for shell in (
                (water[0] + 1, water[1], water[2]),
                (water[0], water[1] - 1, water[2]),
                (water[0], water[1] + 1, water[2]),
                (water[0], water[1], water[2] - 1),
                (water[0], water[1], water[2] + 1),
            ):
                set_block(blocks, shell, "minecraft:obsidian")
        set_block(blocks, (0, 2, center_z), "minecraft:obsidian")

    return make_model(blocks, dispensers), {
        "family": "protected-charge-cell",
        "variant": {"cell_count": cell_count},
        "fire_inputs": fire_inputs,
        "dispenser_count": len(dispensers),
        "water_source_count": len(water_cells),
        "water_cells": water_cells,
        "experiment_contract": {
            "purpose": "simultaneous enclosed source-water charge survival",
            "combined_impulse_claimed": False,
            "minimum_one_paste_shots": 100,
            "maximum_self_damage_blocks": 0,
        },
    }


def build_payload_or_guider(delay: int, guider_length: int, family: str) -> tuple[dict[str, Any], dict[str, Any]]:
    blocks: dict[tuple[int, int, int], str] = {}
    dispenser = (2, 1, 1)
    final_x = 2 + guider_length
    for x in range(final_x + 1):
        for z in range(3):
            set_block(blocks, (x, 0, z), "minecraft:obsidian")
    set_block(
        blocks,
        (1, 1, 1),
        f"minecraft:repeater[delay={delay},facing=east,locked=false,powered=false]",
    )
    set_block(blocks, dispenser, "minecraft:dispenser[facing=east,triggered=false]")
    for x in range(3, final_x + 1):
        set_block(blocks, (x, 1, 0), "minecraft:obsidian")
        set_block(blocks, (x, 1, 2), "minecraft:obsidian")

    return make_model(blocks, [dispenser]), {
        "family": family,
        "variant": {"repeater_delay": delay, "guider_length": guider_length},
        "fire_inputs": [[0, 1, 1]],
        "dispenser_count": 1,
        "experiment_contract": {
            "purpose": (
                "repeatable open-top lateral guide lane"
                if guider_length
                else "single delayed payload source and muzzle-clearance trace"
            ),
            "minimum_forward_range_blocks": guider_length or None,
            "payload_role_proven": False,
            "guider_role_proven": False,
        },
    }


def family_candidates(profile: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for family in profile["families"]:
        family_id = str(family["id"])
        if family_id == "protected-charge-cell":
            for count in sorted({int(value) for value in family["cell_counts"]}):
                model, metadata = build_protected_charge_cells(count)
                result.append((f"charge-c{count:02d}", model, metadata))
        elif family_id == "payload-injector":
            for delay in sorted({int(value) for value in family["repeater_delays"]}):
                model, metadata = build_payload_or_guider(delay, 0, family_id)
                result.append((f"payload-d{delay}", model, metadata))
        elif family_id == "guider":
            delay = int(family.get("repeater_delay", 1))
            for length in sorted({int(value) for value in family["lengths"]}):
                model, metadata = build_payload_or_guider(delay, length, family_id)
                result.append((f"guider-l{length:03d}-d{delay}", model, metadata))
    return result


def chunk_pressure(audit: Any, model: dict[str, Any], chunk_limit: int) -> dict[str, Any]:
    coords = [
        (x, z)
        for (x, _y, z), state in model["blocks"].items()
        if base_state(state) == "minecraft:dispenser"
    ]
    scans = audit.scan_alignments(coords)
    best, worst = min(scans), max(scans)
    safe = [row for row in scans if row[0] <= chunk_limit]
    return {
        "chunk_limit": chunk_limit,
        "safe_alignment_count": len(safe),
        "best_max": best[0],
        "worst_max": worst[0],
        "all_alignments_safe": len(safe) == 256,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def round_trip_verify(audit: Any, path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    root_name, root, trailing, _decoded_size, diagnostics = audit.load(path)
    decoded = audit.decode_any(root_name, root)
    if occupied(decoded.get("blocks") or {}) != occupied(expected["blocks"]):
        raise RigGenerationError(f"round-trip occupied geometry mismatch for {path.name}")
    expected_entities = sorted(tuple(map(int, row["pos"])) for row in expected["block_entities"])
    observed_entities = sorted(tuple(map(int, row["pos"])) for row in decoded.get("block_entities") or [])
    if observed_entities != expected_entities:
        raise RigGenerationError(f"round-trip block-entity mismatch for {path.name}")
    if trailing:
        raise RigGenerationError(f"unexpected trailing NBT in {path.name}")
    if diagnostics.get("strict_gzip_valid") is not True:
        raise RigGenerationError(f"strict gzip validation failed for {path.name}")
    return decoded


def generate(profile: dict[str, Any], output_directory: Path) -> dict[str, Any]:
    validate_profile(profile)
    audit = load_audit()
    output_directory.mkdir(parents=True, exist_ok=True)
    data_version = int(profile["data_version"])
    chunk_limit = int(profile["chunk_limit"])
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()

    for candidate_id, model, metadata in family_candidates(profile):
        if candidate_id in seen:
            raise RigGenerationError(f"duplicate candidate id {candidate_id}")
        seen.add(candidate_id)
        path = output_directory / f"{candidate_id}.schem"
        audit.write_sponge_v2(path, model, data_version, canonical_gzip=True)
        decoded = round_trip_verify(audit, path, model)
        pressure = chunk_pressure(audit, model, chunk_limit)
        if not pressure["all_alignments_safe"]:
            raise RigGenerationError(f"{candidate_id} is not safe across all chunk offsets")
        reports.append({
            "id": candidate_id,
            "status": "STATIC_EXPERIMENT_RIG_ONLY",
            "file": path.name,
            "sha256": sha256_file(path),
            "data_version": data_version,
            "dimensions": bounds_for(model["blocks"])["dimensions"],
            "occupied_block_count": len(occupied(model["blocks"])),
            "palette_entry_count": int(decoded.get("palette_entries", 0)),
            "chunk_pressure": pressure,
            **metadata,
        })

    manifest = {
        "schema_version": 1,
        "status": "STATIC_EXPERIMENT_FAMILY_ONLY",
        "profile_id": str(profile.get("id", "unnamed")),
        "mode": "from-scratch",
        "source_schematic_used": False,
        "candidate_count": len(reports),
        "candidates": reports,
        "truth_boundary": {
            "static_rig_is_proven_primitive": False,
            "static_rig_is_raid_cannon": False,
            "water_enclosure_proves_combined_impulse": False,
            "guider_geometry_proves_trajectory_control": False,
            "required_next_gate": "identical local runtime scenarios with causal source accounting",
        },
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate source-free primitive cannon experiment rigs")
    parser.add_argument("profile", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    manifest = generate(load_json(args.profile), args.output_directory)
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(2)
