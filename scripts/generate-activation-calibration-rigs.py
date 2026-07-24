#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


class CalibrationError(ValueError):
    pass


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CalibrationError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RIGS = load_module(
    "first_principles_rig_support",
    Path(__file__).with_name("generate-first-principles-rigs.py"),
)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CalibrationError("profile must be a JSON object")
    return payload


def integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CalibrationError(f"{label} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise CalibrationError(f"{label} must be between {minimum} and {maximum}")
    return result


def validate_profile(profile: dict[str, Any]) -> None:
    if int(profile.get("schema_version", 0)) != 1:
        raise CalibrationError("schema_version must equal 1")
    if profile.get("mode") != "from-scratch":
        raise CalibrationError("mode must equal 'from-scratch'")
    if profile.get("source_schematic") not in (None, ""):
        raise CalibrationError("source_schematic is forbidden")
    integer(profile.get("data_version"), "data_version", 1, 10_000_000)
    integer(profile.get("chunk_limit"), "chunk_limit", 1, 10_000)
    integer(profile.get("shots_per_candidate"), "shots_per_candidate", 1, 1000)

    controls = profile.get("controls")
    if not isinstance(controls, list) or set(map(str, controls)) != {"direct", "dust"}:
        raise CalibrationError("controls must contain exactly direct and dust")

    repeater = profile.get("repeater")
    if not isinstance(repeater, dict):
        raise CalibrationError("repeater must be an object")
    facings = repeater.get("facings")
    if not isinstance(facings, list) or set(map(str, facings)) != {"east", "west"}:
        raise CalibrationError("repeater.facings must contain exactly east and west")
    delays = repeater.get("delays")
    if not isinstance(delays, list) or not delays:
        raise CalibrationError("repeater.delays must be non-empty")
    normalized = sorted({integer(value, "repeater delay", 1, 4) for value in delays})
    if normalized != [1, 2, 3, 4]:
        raise CalibrationError("repeater.delays must contain 1, 2, 3 and 4")


def set_block(blocks: dict[tuple[int, int, int], str], pos: tuple[int, int, int], state: str) -> None:
    RIGS.set_block(blocks, pos, state)


def add_floor(blocks: dict[tuple[int, int, int], str], length: int) -> None:
    for x in range(length):
        for z in range(3):
            set_block(blocks, (x, 0, z), "minecraft:obsidian")


def add_protected_output(
    blocks: dict[tuple[int, int, int], str],
    dispenser_x: int,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    dispenser = (dispenser_x, 1, 1)
    water = (dispenser_x + 1, 1, 1)
    set_block(blocks, dispenser, "minecraft:dispenser[facing=east,triggered=false]")
    set_block(blocks, water, "minecraft:water[level=0]")
    for shell in (
        (water[0] + 1, water[1], water[2]),
        (water[0], water[1] + 1, water[2]),
        (water[0], water[1], water[2] - 1),
        (water[0], water[1], water[2] + 1),
    ):
        set_block(blocks, shell, "minecraft:obsidian")
    return dispenser, water


def build_candidate(kind: str, *, delay: int | None = None, facing: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    blocks: dict[tuple[int, int, int], str] = {}
    fire_input = (0, 1, 1)

    if kind == "direct":
        add_floor(blocks, 4)
        dispenser, water = add_protected_output(blocks, 1)
        driver = {"type": "direct-redstone-block", "position": list(fire_input)}
    elif kind == "dust":
        add_floor(blocks, 5)
        set_block(blocks, (1, 1, 1), "minecraft:redstone_wire[power=0,north=none,east=side,south=none,west=side]")
        dispenser, water = add_protected_output(blocks, 2)
        driver = {"type": "dust", "position": [1, 1, 1]}
    elif kind == "repeater":
        if delay is None or facing not in {"east", "west"}:
            raise CalibrationError("repeater candidates require delay and facing")
        add_floor(blocks, 5)
        set_block(
            blocks,
            (1, 1, 1),
            f"minecraft:repeater[delay={delay},facing={facing},locked=false,powered=false]",
        )
        dispenser, water = add_protected_output(blocks, 2)
        driver = {"type": "repeater", "position": [1, 1, 1], "delay": delay, "facing": facing}
    else:
        raise CalibrationError(f"unsupported candidate kind {kind!r}")

    model = RIGS.make_model(blocks, [dispenser])
    metadata = {
        "kind": kind,
        "driver": driver,
        "fire_inputs": [list(fire_input)],
        "dispenser": list(dispenser),
        "water_cell": list(water),
        "dispenser_count": 1,
        "experiment_contract": {
            "shots": 10,
            "minimum_tnt_per_shot": 1,
            "minimum_explosions_per_shot": 1,
            "maximum_self_damage_blocks": 0,
            "minimum_remaining_dispenser_ratio": 1.0,
            "role_promotion_allowed_from_static_geometry": False,
        },
    }
    return model, metadata


def candidates(profile: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    output: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for control in profile["controls"]:
        model, metadata = build_candidate(str(control))
        output.append((f"activation-{control}", model, metadata))
    for facing in sorted(map(str, profile["repeater"]["facings"])):
        for delay in sorted({int(value) for value in profile["repeater"]["delays"]}):
            model, metadata = build_candidate("repeater", delay=delay, facing=facing)
            output.append((f"activation-repeater-{facing}-d{delay}", model, metadata))
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(profile: dict[str, Any], output_directory: Path) -> dict[str, Any]:
    validate_profile(profile)
    audit = RIGS.load_audit()
    output_directory.mkdir(parents=True, exist_ok=True)
    data_version = int(profile["data_version"])
    chunk_limit = int(profile["chunk_limit"])
    reports: list[dict[str, Any]] = []

    for candidate_id, model, metadata in candidates(profile):
        path = output_directory / f"{candidate_id}.schem"
        audit.write_sponge_v2(path, model, data_version, canonical_gzip=True)
        decoded = RIGS.round_trip_verify(audit, path, model)
        pressure = RIGS.chunk_pressure(audit, model, chunk_limit)
        if not pressure["all_alignments_safe"]:
            raise CalibrationError(f"{candidate_id} is not safe across all chunk offsets")
        reports.append({
            "id": candidate_id,
            "status": "STATIC_ACTIVATION_HYPOTHESIS_ONLY",
            "file": path.name,
            "sha256": sha256_file(path),
            "data_version": data_version,
            "dimensions": RIGS.bounds_for(model["blocks"])["dimensions"],
            "occupied_block_count": len(RIGS.occupied(model["blocks"])),
            "palette_entry_count": int(decoded.get("palette_entries", 0)),
            "chunk_pressure": pressure,
            **metadata,
        })

    manifest = {
        "schema_version": 1,
        "status": "STATIC_ACTIVATION_CALIBRATION_ONLY",
        "profile_id": str(profile.get("id", "unnamed")),
        "mode": "from-scratch",
        "source_schematic_used": False,
        "candidate_count": len(reports),
        "candidates": reports,
        "truth_boundary": {
            "direct_control_proven": False,
            "dust_control_proven": False,
            "repeater_orientation_proven": False,
            "payload_role_proven": False,
            "required_next_gate": "ten-shot pinned-Sakura runtime comparison",
        },
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate protected activation calibration rigs")
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
