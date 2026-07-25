#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"unable to read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("contract must be a JSON object")
    return payload


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def verify_contract(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source = payload.get("source") or {}
    defaults = payload.get("defaults") or {}
    cannons = defaults.get("cannons") or {}
    mechanics = cannons.get("mechanics") or {}
    explosion = cannons.get("explosion") or {}
    invariants = payload.get("implementation_invariants") or {}
    truth = payload.get("truth_boundary") or {}

    require(payload.get("schema_version") == 1, "schema_version must be 1", errors)
    require(source.get("repository") == "Samsuik/Sakura", "unexpected source repository", errors)
    require(source.get("commit") == "63f35d74e0fbe6bcd76c58494c01c1632c83010d", "unexpected Sakura commit", errors)
    require(source.get("sakura_version") == "26.1.2", "unexpected Sakura version", errors)
    require(source.get("minecraft_runtime_version") == "26.1.2", "unexpected runtime version", errors)
    require(source.get("schematic_data_version") == 3465, "schematic DataVersion must be 3465", errors)
    require(mechanics.get("tnt_spread") in {"ALL", "Y", "NONE"}, "invalid tnt_spread", errors)
    require(mechanics.get("mechanics_target") == "latest+paper", "default mechanics target must be latest+paper", errors)
    require(explosion.get("durable_materials", {}).get("minecraft:obsidian", {}).get("hits") == 4, "obsidian default must be four hits", errors)
    require(invariants.get("large_movement_collision_axis_scan_threshold_squared") == 12.0, "axis scan threshold mismatch", errors)
    require(truth.get("schematic_data_version_proves_runtime_version") is False, "DataVersion truth boundary must fail closed", errors)
    require(truth.get("public_sakura_defaults_equal_private_extremecraft_config") is False, "private parity truth boundary must fail closed", errors)
    probes = payload.get("required_runtime_probes") or []
    require(len(probes) == len(set(probes)), "runtime probe ids must be unique", errors)
    require(len(probes) >= 10, "contract must require a broad parity probe matrix", errors)
    return errors


def check_source_root(payload: dict[str, Any], source_root: Path) -> list[str]:
    errors: list[str] = []
    files = {
        "gradle": source_root / "gradle.properties",
        "world": source_root / "sakura-server/src/main/java/me/samsuik/sakura/configuration/WorldConfiguration.java",
        "tnt": source_root / "sakura-server/minecraft-patches/sources/net/minecraft/world/entity/item/PrimedTnt.java.patch",
        "movement": source_root / "sakura-server/minecraft-patches/features/0004-Optimise-cannon-entity-movement.patch",
        "target": source_root / "sakura-api/src/main/java/me/samsuik/sakura/mechanics/MinecraftMechanicsTarget.java",
        "command": source_root / "sakura-server/src/main/java/me/samsuik/sakura/command/subcommand/MechanicCommand.java",
    }
    contents: dict[str, str] = {}
    for key, path in files.items():
        try:
            contents[key] = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"missing source file {path}: {exc}")
    if errors:
        return errors

    gradle = contents["gradle"]
    require("version=26.1.2" in gradle, "gradle version mismatch", errors)
    require("mcVersion=26.1.2" in gradle, "gradle mcVersion mismatch", errors)

    world = contents["world"]
    snippets = [
        "public MergeLevel mergeLevel = MergeLevel.LENIENT;",
        "public boolean loadChunks = false;",
        "public boolean forcePositionUpdates;",
        "map.put(Blocks.OBSIDIAN, new DurableMaterial(4",
        "public Duration durableMaterialsExpiration = Duration.of(\"1m\");",
        "public TNTSpread tntSpread = TNTSpread.ALL;",
        "public boolean tntFlowsInWater = true;",
        "public boolean fallingBlockParity = false;",
        "public MinecraftMechanicsTarget mechanicsTarget = MinecraftMechanicsTarget.latest();",
        "public boolean brokenPaperExplosionBehaviour = false;",
    ]
    for snippet in snippets:
        require(snippet in world, f"WorldConfiguration missing: {snippet}", errors)

    tnt = contents["tnt"]
    require("this.cannonEntity = true" in tnt, "PrimedTnt cannonEntity flag missing", errors)
    require("case NONE -> this.setDeltaMovement(0.0, 0.0, 0.0);" in tnt, "TNT spread NONE missing", errors)
    require("tntFlowsInWater" in tnt, "TNT water-flow switch missing", errors)
    require("remove max tnt per tick" in tnt, "max TNT per tick removal missing", errors)

    movement = contents["movement"]
    require("movement.lengthSqr() >= 12.0" in movement, "large movement threshold missing", errors)
    require("collideAxisScan" in movement, "axis scan collision path missing", errors)

    target = contents["target"]
    require("record MinecraftMechanicsTarget" in target, "mechanics target record missing", errors)
    require("LATEST = new MinecraftMechanicsTarget(MechanicVersion.LATEST, ServerType.PAPER)" in target, "latest+paper default missing", errors)

    command = contents["command"]
    for label in ("Mechanic Version", "Height Parity", "Tnt Spread", "Tnt Flow", "Redstone Implementation"):
        require(label in command, f"mechanic command field missing: {label}", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the pinned Sakura cannon mechanics contract.")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    payload = read_json(args.contract)
    errors = verify_contract(payload)
    if args.source_root:
        errors.extend(check_source_root(payload, args.source_root))
    result = {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "contract": str(args.contract),
        "source_root_checked": str(args.source_root) if args.source_root else None,
        "errors": errors,
        "truth_boundary": payload.get("truth_boundary"),
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
