#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
OUTPUT_ROOT = WORKSPACE_ROOT / "output"
SCRIPTS = ROOT / "scripts"
REGISTRY = ROOT / "knowledge" / "source-registry.json"
PAYLOAD_CONTRACTS = ROOT / "knowledge" / "cannon-intelligence" / "payload-contracts.json"


@dataclass(frozen=True)
class Vec3:
    x: int
    y: int
    z: int

    def yaml(self) -> str:
        return f"{{x: {self.x}, y: {self.y}, z: {self.z}}}"


def parse_vec3(raw: str) -> Vec3:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    try:
        return Vec3(*(int(part) for part in parts))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("x,y,z values must be integers") from exc


def slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not slug:
        raise ValueError("job name produced an empty slug")
    return slug[:72]


def allowed_input(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"input escapes CannonLab repository/output roots: {raw}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(args: list[str], timeout: int = 300) -> dict[str, Any]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode not in {0, 2}:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout={result.stdout[-3000:]}\nstderr={result.stderr[-3000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON tool output: {result.stdout[-3000:]}") from exc
    payload["_exit_code"] = result.returncode
    return payload


def failed(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "")).upper()
    return payload.get("_exit_code") == 2 or status in {"FAIL", "BLOCKED", "INVALID"}


def load_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if payload.get("schema") != "cannonlab-source-registry-v1":
        raise ValueError("unsupported source registry schema")
    if not isinstance(payload.get("sources"), list) or not payload["sources"]:
        raise ValueError("source registry contains no sources")
    return payload


def load_payload_contracts() -> dict[str, Any]:
    payload = json.loads(PAYLOAD_CONTRACTS.read_text(encoding="utf-8"))
    if payload.get("schema") != "cannonlab-archetype-payload-contracts-v1":
        raise ValueError("unsupported payload contract schema")
    if not isinstance(payload.get("base_architectures"), dict):
        raise ValueError("payload contracts contain no base architectures")
    if not isinstance(payload.get("specializations"), dict):
        raise ValueError("payload contracts contain no specializations")
    return payload


def resolve_payload_contract(
    base: str,
    specializations: list[str],
    requested_mode: str = "auto",
) -> dict[str, Any]:
    contracts = load_payload_contracts()
    base_modes = contracts["base_architectures"]
    specialization_modes = contracts["specializations"]
    if base not in base_modes:
        raise ValueError(f"unknown base payload contract: {base}")
    unknown_specializations = sorted(set(specializations) - set(specialization_modes))
    if unknown_specializations:
        raise ValueError(
            "unknown specialization payload contracts: " + ", ".join(unknown_specializations)
        )

    base_mode = str(base_modes[base])
    selected = [
        {"id": specialization, "mode": str(specialization_modes[specialization])}
        for specialization in specializations
    ]
    blocked = [item["id"] for item in selected if item["mode"] == "unknown-blocked"]
    if blocked:
        raise ValueError(
            "payload interface is unknown and blocked for: " + ", ".join(blocked)
        )

    falling_required = base_mode == "falling-block-required" or any(
        item["mode"] == "falling-block-required" for item in selected
    )
    base_tnt_only = base_mode == "tnt-only"
    explicit_required = base_mode == "explicit-selection-required"
    if requested_mode not in {"auto", "falling-block-required", "tnt-only"}:
        raise ValueError(f"unsupported payload mode: {requested_mode}")

    if requested_mode == "auto":
        if falling_required:
            mode = "falling-block-required"
            source = "archetype-required"
        elif base_tnt_only:
            mode = "tnt-only"
            source = "base-archetype"
        elif explicit_required:
            raise ValueError(
                f"base {base} requires explicit --payload-mode falling-block-required or tnt-only"
            )
        else:
            raise ValueError(f"unable to resolve payload mode for base {base}")
    else:
        mode = requested_mode
        source = "explicit-operator-selection"
        if mode == "tnt-only" and falling_required:
            raise ValueError(
                "tnt-only conflicts with a falling-block-required base or specialization"
            )
        if mode == "falling-block-required" and base_tnt_only:
            raise ValueError(f"base {base} is contracted as tnt-only")

    definition = contracts["modes"].get(mode)
    if not isinstance(definition, dict):
        raise ValueError(f"payload mode has no definition: {mode}")
    return {
        "schema": "cannonlab-resolved-payload-contract-v1",
        "mode": mode,
        "source": source,
        "base": {"id": base, "mode": base_mode},
        "specializations": selected,
        "require_any_payload": bool(definition.get("require_any_payload", True)),
        "require_falling_block": bool(definition.get("require_falling_block", False)),
        "watered_promotion_allowed": bool(definition.get("watered_promotion_allowed", False)),
        "truth_boundary": contracts["truth_boundary"],
    }


def parse_control_state_json(raw: str) -> dict[str, Any]:
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("control state must be valid JSON") from exc
    if not isinstance(state, dict):
        raise argparse.ArgumentTypeError("control state must be a JSON object")
    name = str(state.get("name", "")).strip()
    block_data = str(state.get("block_data", state.get("block-data", ""))).strip()
    at = state.get("at")
    if not name or not block_data or not isinstance(at, dict):
        raise argparse.ArgumentTypeError("control state requires name, at{x,y,z}, and block_data")
    try:
        point = {axis: int(at[axis]) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("control state at must contain integer x,y,z") from exc
    phase = str(state.get("phase", "before-fill")).lower().replace("_", "-")
    if phase not in {"before-fill", "after-fill"}:
        raise argparse.ArgumentTypeError("control state phase must be before-fill or after-fill")
    apply_tick = int(state.get("apply_tick", state.get("apply-tick", 0)))
    settle_ticks = int(state.get("settle_ticks", state.get("settle-ticks", 1)))
    if apply_tick < 0 or settle_ticks < 0:
        raise argparse.ArgumentTypeError("control state timing must be non-negative")
    return {
        "name": name,
        "at": point,
        "phase": phase,
        "apply_tick": apply_tick,
        "settle_ticks": settle_ticks,
        "apply_physics": bool(state.get("apply_physics", state.get("apply-physics", True))),
        "expected_material": str(
            state.get("expected_material", state.get("expected-material", ""))
        ).strip(),
        "expected_before": str(
            state.get("expected_before", state.get("expected-before", ""))
        ).strip(),
        "block_data": block_data,
    }


def static_intake(
    candidate: Path,
    references: list[Path],
    intent: str,
    chunk_limit: int,
) -> dict[str, Any]:
    reference_args: list[str] = []
    for reference in references:
        reference_args += ["--reference", str(reference)]
    tools = {
        "audit": [
            sys.executable,
            str(SCRIPTS / "schem-audit.py"),
            str(candidate),
            "--chunk-limit",
            str(chunk_limit),
        ],
        "paste_alignment": [
            sys.executable,
            str(SCRIPTS / "paste-alignment-audit.py"),
            str(candidate),
            "--chunk-limit",
            str(chunk_limit),
        ],
        "static_map": [
            sys.executable,
            str(SCRIPTS / "cannon-static-map.py"),
            str(candidate),
            "--chunk-limit",
            str(chunk_limit),
        ],
        "module_map": [
            sys.executable,
            str(SCRIPTS / "cannon-module-map.py"),
            str(candidate),
            "--chunk-limit",
            str(chunk_limit),
        ],
        "geometry_profile": [
            sys.executable,
            str(SCRIPTS / "cannon-geometry-profile.py"),
            str(candidate),
            "--chunk-limit",
            str(chunk_limit),
            "--intent",
            intent,
            *reference_args,
        ],
    }
    results = {name: run_json(command) for name, command in tools.items()}
    blockers = [name for name, payload in results.items() if failed(payload)]
    if intent == "modern-raid" and not references:
        blockers.append("missing_reference")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "blockers": sorted(set(blockers)),
        "results": results,
    }


def acceptance_block(
    *,
    payload_contract: dict[str, Any],
    distance: int,
    water_exposed: bool = False,
    regen_layers: int = 0,
    self_damage: int = 24,
) -> str:
    require_falling = bool(payload_contract["require_falling_block"])
    lines = [
        "acceptance:",
        f"  require-payload: {'true' if payload_contract['require_any_payload'] else 'false'}",
        "  min-target-destroyed: 1",
        f"  min-falling-blocks: {1 if require_falling else 0}",
        f"  min-embedded-payload-explosions: {1 if require_falling and water_exposed else 0}",
        "  max-unembedded-water-explosions: 0",
        f"  min-contiguous-layers-before-first-regen: {regen_layers}",
        "  require-all-layers-before-first-regen: false",
        f"  min-forward-distance: {max(1, int(distance * 0.55))}",
        "  min-remaining-dispenser-ratio: 0.95",
        f"  max-cannon-missing-blocks: {self_damage}",
        "  max-cannon-replaced-type-blocks: 4",
        f"  max-self-damage-blocks: {self_damage}",
    ]
    return "\n".join(lines)


def cannon_block(
    staged_name: str,
    origin: Vec3,
    fire_input: Vec3,
    fire_mode: str,
    control_states: list[dict[str, Any]],
) -> str:
    pulse = 20 if fire_mode == "button" else 4
    lines = [
        "cannon:",
        f"  file: {staged_name}",
        f"  origin: {origin.yaml()}",
        f"  fire-mode: {fire_mode}",
        f"  fire-input: {fire_input.yaml()}",
        f"  fire-pulse-ticks: {pulse}",
        "  suppress-paste-side-effects: false",
        "  settle-before-fill-ticks: 120",
        "  fill-to-fire-ticks: 20",
    ]
    if control_states:
        lines.append("  control-states:")
        for state in control_states:
            lines.extend(
                [
                    f"    - name: {json.dumps(state['name'])}",
                    f"      at: {{x: {state['at']['x']}, y: {state['at']['y']}, z: {state['at']['z']}}}",
                    f"      phase: {state['phase']}",
                    f"      apply-tick: {state['apply_tick']}",
                    f"      settle-ticks: {state['settle_ticks']}",
                    f"      apply-physics: {'true' if state['apply_physics'] else 'false'}",
                ]
            )
            if state["expected_material"]:
                lines.append(f"      expected-material: {json.dumps(state['expected_material'])}")
            if state["expected_before"]:
                lines.append(f"      expected-before: {json.dumps(state['expected_before'])}")
            lines.append(f"      block-data: {json.dumps(state['block_data'])}")
    return "\n".join(lines)


def render_scenarios(
    slug: str,
    staged_name: str,
    origin: Vec3,
    fire_input: Vec3,
    fire_mode: str,
    direction: str,
    distance: int,
    width: int,
    height: int,
    shots: int,
    payload_contract: dict[str, Any] | None = None,
    control_states: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    payload_contract = payload_contract or {
        "mode": "falling-block-required",
        "require_any_payload": True,
        "require_falling_block": True,
        "watered_promotion_allowed": True,
    }
    control_states = list(control_states or [])
    cannon = cannon_block(staged_name, origin, fire_input, fire_mode, control_states)
    common_limits = "limits:\n  enforce-dispenser-limit: true"
    scenarios: list[dict[str, Any]] = []

    def add(
        name: str,
        body: str,
        expected_shots: int,
        assert_args: list[str],
        corridor_args: list[str] | None = None,
    ) -> None:
        filename = f"forge-{slug}-{name}.yml"
        scenarios.append(
            {
                "name": f"forge-{slug}-{name}",
                "filename": filename,
                "text": f"name: forge-{slug}-{name}\n{cannon}\n{common_limits}\n{body}\n",
                "expected_shots": expected_shots,
                "assert_args": assert_args,
                "corridor_args": list(corridor_args or []),
            }
        )

    def corridor(expected_shots: int, *, half_width: int = 3) -> list[str]:
        return [
            "--min-shots", str(expected_shots),
            "--min-forward", str(max(1, int(distance * 0.55))),
            "--half-width", str(half_width),
            "--vertical-tolerance", str(max(6, height // 2)),
            "--max-abs-angle", "8",
            "--max-angular-spread", "5",
            "--max-forward-relative-spread", "0.15",
            "--max-lateral-center-spread", "2",
        ]

    dry_acceptance = acceptance_block(payload_contract=payload_contract, distance=distance)
    add(
        "dry-baseline",
        f"{dry_acceptance}\n"
        "target:\n"
        "  type: dry\n"
        "  material: cobblestone\n"
        f"  direction: {direction}\n"
        f"  distance: {distance}\n"
        f"  width: {width}\n"
        f"  height: {height}\n"
        "  layers: 2\n"
        "  spacing: 3\n"
        "  regeneration: {enabled: false}\n"
        "run:\n"
        "  shots: 3\n"
        "  warmup-ticks: 40\n"
        "  max-shot-ticks: 600\n"
        "  quiet-ticks: 120\n"
        "  shutdown-when-finished: true",
        3,
        ["--expected-shots", "3", "--min-target-peak-destroyed", "1", "--max-self-damage-blocks", "24"],
    )

    if payload_contract["mode"] == "tnt-only":
        directional_acceptance = acceptance_block(
            payload_contract=payload_contract,
            distance=distance,
            self_damage=20,
        )
        add(
            "dry-direction-repeatability",
            f"{directional_acceptance}\n"
            "target:\n"
            "  type: dry\n"
            "  material: cobblestone\n"
            f"  direction: {direction}\n"
            f"  distance: {distance}\n"
            f"  width: {width}\n"
            f"  height: {height}\n"
            "  layers: 3\n"
            "  spacing: 3\n"
            "  regeneration: {enabled: false}\n"
            "run:\n"
            "  shots: 5\n"
            "  warmup-ticks: 40\n"
            "  max-shot-ticks: 700\n"
            "  quiet-ticks: 140\n"
            "  shutdown-when-finished: true",
            5,
            ["--expected-shots", "5", "--min-target-peak-destroyed", "1", "--max-self-damage-blocks", "20"],
            corridor(5),
        )

        multilayer_acceptance = acceptance_block(
            payload_contract=payload_contract,
            distance=distance,
            self_damage=28,
        )
        add(
            "dry-multilayer",
            f"{multilayer_acceptance}\n"
            "target:\n"
            "  type: dry\n"
            "  material: cobblestone\n"
            f"  direction: {direction}\n"
            f"  distance: {distance}\n"
            f"  width: {width}\n"
            f"  height: {height}\n"
            "  layers: 8\n"
            "  spacing: 3\n"
            "  regeneration: {enabled: false}\n"
            "run:\n"
            "  shots: 10\n"
            "  warmup-ticks: 40\n"
            "  max-shot-ticks: 800\n"
            "  quiet-ticks: 160\n"
            "  shutdown-when-finished: true",
            10,
            ["--expected-shots", "10", "--min-layer-breached", "1", "--max-self-damage-blocks", "28"],
            corridor(10, half_width=4),
        )

        gauntlet_acceptance = acceptance_block(
            payload_contract=payload_contract,
            distance=distance,
            self_damage=32,
        )
        add(
            "dry-route-gauntlet",
            f"{gauntlet_acceptance}\n"
            "target:\n"
            "  type: dry\n"
            "  material: cobblestone\n"
            f"  direction: {direction}\n"
            f"  distance: {distance}\n"
            f"  width: {width}\n"
            f"  height: {height}\n"
            "  layers: 1\n"
            "  spacing: 3\n"
            "  regeneration: {enabled: false}\n"
            "  stages:\n"
            "    - name: dry-entry\n"
            "      type: dry\n"
            "      material: cobblestone\n"
            f"      width: {width}\n"
            f"      height: {height}\n"
            "      layers: 4\n"
            "      spacing: 3\n"
            "      gap-after: 3\n"
            "      regeneration: {enabled: false}\n"
            "    - name: slab-filter\n"
            "      type: slab-filter\n"
            "      material: obsidian\n"
            f"      width: {width}\n"
            f"      height: {height}\n"
            "      layers: 3\n"
            "      spacing: 3\n"
            "      gap-after: 3\n"
            "      regeneration: {enabled: false}\n"
            "    - name: staggered-pillars\n"
            "      type: pillars\n"
            "      material: cobblestone\n"
            f"      width: {width}\n"
            f"      height: {height}\n"
            "      layers: 3\n"
            "      spacing: 3\n"
            "      gap-after: 0\n"
            "      pillar-spacing: 3\n"
            "      regeneration: {enabled: false}\n"
            "run:\n"
            f"  shots: {max(10, shots)}\n"
            "  warmup-ticks: 40\n"
            "  max-shot-ticks: 900\n"
            "  quiet-ticks: 180\n"
            "  shutdown-when-finished: true",
            max(10, shots),
            ["--expected-shots", str(max(10, shots)), "--min-layer-breached", "1", "--max-self-damage-blocks", "32"],
            corridor(max(10, shots), half_width=4),
        )

        endurance_shots = max(25, shots)
        endurance_acceptance = acceptance_block(
            payload_contract=payload_contract,
            distance=distance,
            self_damage=16,
        )
        add(
            "dry-endurance",
            f"{endurance_acceptance}\n"
            "target:\n"
            "  type: dry\n"
            "  material: cobblestone\n"
            f"  direction: {direction}\n"
            f"  distance: {distance}\n"
            f"  width: {width}\n"
            f"  height: {height}\n"
            "  layers: 3\n"
            "  spacing: 3\n"
            "  regeneration: {enabled: false}\n"
            "run:\n"
            f"  shots: {endurance_shots}\n"
            "  warmup-ticks: 40\n"
            "  max-shot-ticks: 700\n"
            "  quiet-ticks: 120\n"
            "  shutdown-when-finished: true",
            endurance_shots,
            ["--expected-shots", str(endurance_shots), "--min-target-peak-destroyed", "1", "--max-self-damage-blocks", "16"],
            corridor(endurance_shots),
        )
        return scenarios

    watered_acceptance = acceptance_block(
        payload_contract=payload_contract,
        distance=distance,
        water_exposed=True,
    )
    add(
        "watered-payload",
        f"{watered_acceptance}\n"
        "target:\n"
        "  type: watered\n"
        "  material: cobblestone\n"
        f"  direction: {direction}\n"
        f"  distance: {distance}\n"
        f"  width: {width}\n"
        f"  height: {height}\n"
        "  layers: 2\n"
        "  spacing: 3\n"
        "  regeneration: {enabled: false}\n"
        "run:\n"
        "  shots: 5\n"
        "  warmup-ticks: 40\n"
        "  max-shot-ticks: 700\n"
        "  quiet-ticks: 140\n"
        "  shutdown-when-finished: true",
        5,
        [
            "--expected-shots", "5",
            "--min-embedded-payload-explosions", "1",
            "--max-unembedded-water-explosions", "0",
            "--max-self-damage-blocks", "24",
        ],
        corridor(5),
    )

    regen_acceptance = acceptance_block(
        payload_contract=payload_contract,
        distance=distance,
        water_exposed=True,
        regen_layers=1,
    )
    add(
        "watered-regen-race",
        f"{regen_acceptance}\n"
        "target:\n"
        "  type: watered\n"
        "  material: cobblestone\n"
        f"  direction: {direction}\n"
        f"  distance: {distance}\n"
        f"  width: {width}\n"
        f"  height: {height}\n"
        "  layers: 4\n"
        "  spacing: 3\n"
        "  regeneration:\n"
        "    enabled: true\n"
        "    delay-ticks: 4\n"
        "    interval-ticks: 1\n"
        "    max-blocks-per-cycle: 64\n"
        "run:\n"
        "  shots: 10\n"
        "  warmup-ticks: 40\n"
        "  max-shot-ticks: 700\n"
        "  quiet-ticks: 140\n"
        "  shutdown-when-finished: true",
        10,
        [
            "--expected-shots", "10",
            "--min-embedded-payload-explosions", "1",
            "--max-unembedded-water-explosions", "0",
            "--min-contiguous-layers-before-first-regen", "1",
            "--require-regen",
            "--max-self-damage-blocks", "24",
        ],
        corridor(10),
    )

    mixed_acceptance = acceptance_block(
        payload_contract=payload_contract,
        distance=distance,
        water_exposed=True,
        regen_layers=1,
        self_damage=32,
    )
    add(
        "mixed-gauntlet",
        f"{mixed_acceptance}\n"
        "target:\n"
        "  type: watered\n"
        "  material: cobblestone\n"
        f"  direction: {direction}\n"
        f"  distance: {distance}\n"
        f"  width: {width}\n"
        f"  height: {height}\n"
        "  layers: 1\n"
        "  spacing: 3\n"
        "  regeneration: {enabled: false}\n"
        "  stages:\n"
        "    - name: watered-entry\n"
        "      type: watered\n"
        "      material: cobblestone\n"
        f"      width: {width}\n"
        f"      height: {height}\n"
        "      layers: 4\n"
        "      spacing: 3\n"
        "      gap-after: 3\n"
        "      regeneration: {enabled: false}\n"
        "    - name: fast-regen\n"
        "      type: cobble-regen\n"
        "      material: cobblestone\n"
        f"      width: {width}\n"
        f"      height: {height}\n"
        "      layers: 4\n"
        "      spacing: 3\n"
        "      gap-after: 3\n"
        "      regeneration: {enabled: true, delay-ticks: 4, interval-ticks: 1, max-blocks-per-cycle: 64}\n"
        "    - name: slab-filter\n"
        "      type: slab-filter\n"
        "      material: obsidian\n"
        f"      width: {width}\n"
        f"      height: {height}\n"
        "      layers: 3\n"
        "      spacing: 3\n"
        "      gap-after: 3\n"
        "      regeneration: {enabled: false}\n"
        "    - name: watered-hotdog\n"
        "      type: hotdog\n"
        "      material: cobblestone\n"
        "      alternate-material: obsidian\n"
        f"      width: {width}\n"
        f"      height: {height}\n"
        "      layers: 3\n"
        "      spacing: 3\n"
        "      gap-after: 3\n"
        "      hotdog-band-width: 2\n"
        "      regeneration: {enabled: true, delay-ticks: 10, interval-ticks: 2, max-blocks-per-cycle: 48}\n"
        "    - name: staggered-pillars\n"
        "      type: pillars\n"
        "      material: cobblestone\n"
        f"      width: {width}\n"
        f"      height: {height}\n"
        "      layers: 3\n"
        "      spacing: 3\n"
        "      gap-after: 0\n"
        "      pillar-spacing: 3\n"
        "      regeneration: {enabled: true, delay-ticks: 20, interval-ticks: 4, max-blocks-per-cycle: 32}\n"
        "run:\n"
        f"  shots: {max(10, shots)}\n"
        "  warmup-ticks: 40\n"
        "  max-shot-ticks: 800\n"
        "  quiet-ticks: 160\n"
        "  shutdown-when-finished: true",
        max(10, shots),
        [
            "--expected-shots", str(max(10, shots)),
            "--min-embedded-payload-explosions", "1",
            "--max-unembedded-water-explosions", "0",
            "--min-contiguous-layers-before-first-regen", "1",
            "--max-self-damage-blocks", "32",
        ],
        corridor(max(10, shots), half_width=4),
    )

    endurance_shots = max(25, shots)
    endurance_acceptance = acceptance_block(
        payload_contract=payload_contract,
        distance=distance,
        water_exposed=True,
        self_damage=16,
    )
    add(
        "watered-endurance",
        f"{endurance_acceptance}\n"
        "target:\n"
        "  type: watered\n"
        "  material: cobblestone\n"
        f"  direction: {direction}\n"
        f"  distance: {distance}\n"
        f"  width: {width}\n"
        f"  height: {height}\n"
        "  layers: 3\n"
        "  spacing: 3\n"
        "  regeneration: {enabled: false}\n"
        "run:\n"
        f"  shots: {endurance_shots}\n"
        "  warmup-ticks: 40\n"
        "  max-shot-ticks: 700\n"
        "  quiet-ticks: 120\n"
        "  shutdown-when-finished: true",
        endurance_shots,
        [
            "--expected-shots", str(endurance_shots),
            "--min-embedded-payload-explosions", "1",
            "--max-unembedded-water-explosions", "0",
            "--max-self-damage-blocks", "16",
        ],
        corridor(endurance_shots),
    )
    return scenarios


def stage_candidate(candidate: Path, slug: str) -> tuple[Path, str]:
    if candidate.suffix.lower() != ".schem":
        raise ValueError("runtime staging requires a Sponge .schem; convert Litematica first")
    staged_name = f"forge-{slug}.schem"
    staged_path = ROOT / "cannons" / f"{staged_name}.b64"
    encoded = base64.b64encode(candidate.read_bytes()).decode("ascii") + "\n"
    staged_path.write_text(encoded, encoding="ascii")
    return staged_path, staged_name


def stage_job(args: argparse.Namespace) -> dict[str, Any]:
    candidate = allowed_input(args.candidate)
    references = [allowed_input(path) for path in args.reference]
    payload_contract = resolve_payload_contract(
        args.base,
        list(args.specialization),
        args.payload_mode,
    )
    control_states = list(args.control_state_json)
    slug = slugify(args.job or candidate.stem)
    job_dir = ROOT / "forge-jobs" / slug
    job_dir.mkdir(parents=True, exist_ok=True)

    intake = (
        {
            "status": "SKIPPED",
            "blockers": ["static_intake_skipped"],
            "results": {},
        }
        if args.skip_static
        else static_intake(candidate, references, args.intent, args.chunk_limit)
    )
    staged_path, staged_name = stage_candidate(candidate, slug)
    scenarios = render_scenarios(
        slug=slug,
        staged_name=staged_name,
        origin=args.origin,
        fire_input=args.fire_input,
        fire_mode=args.fire_mode,
        direction=args.direction,
        distance=args.distance,
        width=args.width,
        height=args.height,
        shots=args.shots,
        payload_contract=payload_contract,
        control_states=control_states,
    )

    scenario_records: list[dict[str, Any]] = []
    for scenario in scenarios:
        path = ROOT / "scenarios" / scenario["filename"]
        path.write_text(scenario["text"], encoding="utf-8", newline="\n")
        integrity = run_json(
            [
                sys.executable,
                str(SCRIPTS / "scenario-integrity-audit.py"),
                str(path),
                "--require-field-candidate",
            ]
        )
        scenario_records.append(
            {
                "name": scenario["name"],
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
                "expected_shots": scenario["expected_shots"],
                "assert_args": scenario["assert_args"],
                "corridor_args": scenario["corridor_args"],
                "integrity": integrity,
            }
        )

    integrity_blockers = [record["name"] for record in scenario_records if failed(record["integrity"])]
    status = "PASS" if intake["status"] == "PASS" and not integrity_blockers else "FAIL"
    manifest = {
        "schema": "cannonlab-forge-job-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "job": slug,
        "status": status,
        "truth_boundary": (
            "A PASS authorizes local runtime testing only. It does not prove live ExtremeCraft readiness."
        ),
        "candidate": {
            "source": str(candidate),
            "sha256": sha256(candidate),
            "staged": str(staged_path.relative_to(ROOT)),
            "runtime_name": staged_name,
        },
        "references": [
            {"path": str(path), "sha256": sha256(path)} for path in references
        ],
        "configuration": {
            "intent": args.intent,
            "base": args.base,
            "specializations": list(args.specialization),
            "payload_mode_requested": args.payload_mode,
            "payload_contract": payload_contract,
            "control_states": control_states,
            "chunk_limit": args.chunk_limit,
            "origin": args.origin.__dict__,
            "fire_input": args.fire_input.__dict__,
            "fire_mode": args.fire_mode,
            "direction": args.direction,
            "distance": args.distance,
            "width": args.width,
            "height": args.height,
        },
        "source_registry": {
            "path": str(REGISTRY.relative_to(ROOT)),
            "sha256": sha256(REGISTRY),
            "source_count": len(load_registry()["sources"]),
        },
        "static_intake": intake,
        "scenario_integrity_blockers": integrity_blockers,
        "scenarios": scenario_records,
    }
    manifest_path = job_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    runbook = job_dir / "RUNBOOK.md"
    runbook.write_text(
        "# Cannon Forge runbook\n\n"
        f"Job: `{slug}`\n\n"
        f"Current gate: **{status}**\n\n"
        "Run only when the manifest gate is PASS:\n\n"
        "```powershell\n"
        "$env:CANNONLAB_ACCEPT_EULA='TRUE'\n"
        f"powershell -ExecutionPolicy Bypass -File scripts/run-forge-campaign.ps1 -Manifest forge-jobs/{slug}/manifest.json\n"
        "```\n\n"
        "Local success is not live ExtremeCraft proof. Record a separate EC canary before promotion.\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage evidence-first CannonLab forge campaigns")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sources = subparsers.add_parser("sources", help="Print the durable source registry")
    sources.add_argument("--compact", action="store_true")

    stage = subparsers.add_parser("stage", help="Audit and stage one complete stress campaign")
    stage.add_argument("candidate")
    stage.add_argument("--reference", action="append", default=[])
    stage.add_argument("--job", default="")
    stage.add_argument("--intent", choices=["calibration", "modern-raid"], default="modern-raid")
    stage.add_argument("--base", required=True)
    stage.add_argument("--specialization", action="append", default=[])
    stage.add_argument(
        "--payload-mode",
        choices=["auto", "falling-block-required", "tnt-only"],
        default="auto",
    )
    stage.add_argument(
        "--control-state-json",
        action="append",
        type=parse_control_state_json,
        default=[],
        help="Repeatable JSON control-state object applied before or after fill",
    )
    stage.add_argument("--chunk-limit", type=int, default=160)
    stage.add_argument("--origin", type=parse_vec3, default=Vec3(0, 0, 0))
    stage.add_argument("--fire-input", type=parse_vec3, required=True)
    stage.add_argument("--fire-mode", choices=["button", "redstone"], default="button")
    stage.add_argument("--direction", choices=["north", "south", "east", "west"], default="north")
    stage.add_argument("--distance", type=int, default=160)
    stage.add_argument("--width", type=int, default=17)
    stage.add_argument("--height", type=int, default=32)
    stage.add_argument("--shots", type=int, default=10)
    stage.add_argument("--skip-static", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()
    if args.command == "sources":
        registry = load_registry()
        if args.compact:
            registry = {
                "schema": registry["schema"],
                "sources": [
                    {
                        "id": source["id"],
                        "evidence_level": source["evidence_level"],
                        "paths": source.get("paths") or [source["path"]],
                    }
                    for source in registry["sources"]
                ],
            }
        print(json.dumps(registry, indent=2))
        return

    if args.chunk_limit < 1 or args.distance < 1 or args.width < 1 or args.height < 1 or args.shots < 1:
        parser.error("chunk limit, distance, dimensions and shots must be positive")
    try:
        manifest = stage_job(args)
    except (ValueError, FileNotFoundError) as exc:
        manifest = {
            "schema": "cannonlab-forge-job-v1",
            "status": "FAIL",
            "blockers": [{"code": "forge-configuration-invalid", "message": str(exc)}],
            "truth_boundary": "No runtime campaign was authorized.",
        }
    print(json.dumps(manifest, indent=2))
    raise SystemExit(0 if manifest["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()