#!/usr/bin/env python3
"""Deterministic reference physics and drift diagnosis for CannonLab.

This module is intentionally an independent oracle, not a replacement runtime.
It predicts empty-space TNT/falling-block motion and explosion impulse using
source-audited Java-edition constants. World collision, voxel shapes, live
redstone order, private server patches, and plugin regeneration remain runtime
questions and are never silently approximated.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


TNT_TYPES = {"TNT", "PRIMED_TNT", "TNT_PRIMED"}
FALLING_TYPES = {"FALLING_BLOCK", "FALLING_SAND", "FALLING_GRAVEL"}
EPSILON = 1.0e-12


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def add(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def subtract(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def scale(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def horizontal_length(self) -> float:
        return math.hypot(self.x, self.z)

    def normalize(self) -> "Vec3":
        length = self.length()
        return self if length <= EPSILON else self.scale(1.0 / length)

    def distance(self, other: "Vec3") -> float:
        return self.subtract(other).length()

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]


ZERO = Vec3(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class PhysicsProfile:
    id: str
    minecraft_range: str
    gravity: float
    drag: float
    ground_horizontal: float
    ground_vertical: float
    water_flow_scale: float
    tnt_water_push: bool
    falling_block_water_push: bool
    tnt_fuse_mode: str
    truth_boundary: str


PROFILES: dict[str, PhysicsProfile] = {
    "modern-java": PhysicsProfile(
        id="modern-java",
        minecraft_range="Java 1.17.1 through 26.1.x numeric motion profile",
        gravity=0.04,
        drag=0.98,
        ground_horizontal=0.7,
        ground_vertical=-0.5,
        water_flow_scale=0.014,
        tnt_water_push=True,
        falling_block_water_push=False,
        tnt_fuse_mode="pre-decrement-modern",
        truth_boundary=(
            "Source-audited modern empty-space motion constants. This profile does not "
            "model voxel collisions, private fork patches, anti-lag, region scheduling, "
            "redstone ordering, or live ExtremeCraft behavior."
        ),
    ),
    "legacy-java-1.8": PhysicsProfile(
        id="legacy-java-1.8",
        minecraft_range="Java 1.8.x legacy comparison profile",
        gravity=0.03999999910593033,
        drag=0.9800000190734863,
        ground_horizontal=0.699999988079071,
        ground_vertical=-0.5,
        water_flow_scale=0.0,
        tnt_water_push=False,
        falling_block_water_push=False,
        tnt_fuse_mode="post-decrement-legacy-extra-zero-tick",
        truth_boundary=(
            "Legacy comparison profile. It is not the ExtremeCraft target and intentionally "
            "does not claim full 1.8 collision or server-fork parity."
        ),
    ),
}


@dataclass(frozen=True)
class BodyState:
    kind: str
    position: Vec3
    velocity: Vec3
    fuse_or_age: int
    on_ground: bool = False


@dataclass(frozen=True)
class TickResult:
    state: BodyState
    detonated: bool
    landed: bool
    applied_water_push: Vec3


@dataclass(frozen=True)
class Observation:
    tick: int
    position: Vec3
    velocity: Vec3
    fuse: int
    uuid: str = ""
    entity_type: str = ""


def _kind(kind: str) -> str:
    normalized = kind.strip().upper().replace("-", "_")
    if normalized in TNT_TYPES or normalized == "TNT":
        return "tnt"
    if normalized in FALLING_TYPES or normalized in {"FALLING", "SAND", "GRAVEL"}:
        return "falling_block"
    raise ValueError(f"unsupported body kind: {kind}")


def water_push_vector(flow: Vec3, scale: float) -> Vec3:
    """Return the modern non-player fluid-current contribution for one tick.

    The caller supplies the already-aggregated flow direction from intersected
    water cells. The live runtime must determine that direction from fluid cells
    and entity AABB overlap. This oracle only applies the source-audited final
    normalize-and-scale step.
    """
    if scale == 0.0 or flow.length() <= EPSILON:
        return ZERO
    return flow.normalize().scale(scale)


def tick_body(
    state: BodyState,
    profile: PhysicsProfile = PROFILES["modern-java"],
    *,
    water_flow: Vec3 = ZERO,
    resolved_movement: Vec3 | None = None,
    on_ground_after_move: bool | None = None,
) -> TickResult:
    """Advance one entity tick with an optional externally resolved collision.

    `resolved_movement` lets a runtime feed its exact voxel-collision result into
    the oracle. Without it, the model is intentionally empty-space. This keeps
    collision uncertainty visible instead of pretending blocks are full cubes.
    """
    kind = _kind(state.kind)
    velocity_after_gravity = Vec3(
        state.velocity.x,
        state.velocity.y - profile.gravity,
        state.velocity.z,
    )
    movement = resolved_movement if resolved_movement is not None else velocity_after_gravity
    position = state.position.add(movement)
    on_ground = state.on_ground if on_ground_after_move is None else on_ground_after_move
    velocity = velocity_after_gravity
    applied_push = ZERO

    if kind == "tnt":
        velocity = velocity.scale(profile.drag)
        if on_ground:
            velocity = Vec3(
                velocity.x * profile.ground_horizontal,
                velocity.y * profile.ground_vertical,
                velocity.z * profile.ground_horizontal,
            )
        fuse = state.fuse_or_age - 1
        if profile.tnt_fuse_mode == "post-decrement-legacy-extra-zero-tick":
            detonated = state.fuse_or_age < 0
        else:
            detonated = fuse <= 0
        if not detonated and profile.tnt_water_push:
            applied_push = water_push_vector(water_flow, profile.water_flow_scale)
            velocity = velocity.add(applied_push)
        next_state = BodyState("tnt", position, velocity, fuse, on_ground)
        return TickResult(next_state, detonated, False, applied_push)

    if on_ground:
        velocity = Vec3(
            velocity.x * profile.ground_horizontal,
            velocity.y * profile.ground_vertical,
            velocity.z * profile.ground_horizontal,
        )
    velocity = velocity.scale(profile.drag)
    if profile.falling_block_water_push:
        applied_push = water_push_vector(water_flow, profile.water_flow_scale)
        velocity = velocity.add(applied_push)
    next_state = BodyState("falling_block", position, velocity, state.fuse_or_age + 1, on_ground)
    return TickResult(next_state, False, on_ground, applied_push)


def simulate(
    initial: BodyState,
    ticks: int,
    profile: PhysicsProfile = PROFILES["modern-java"],
    *,
    water_flow: Vec3 = ZERO,
    stop_on_detonation: bool = True,
) -> list[TickResult]:
    if ticks < 0:
        raise ValueError("ticks must be non-negative")
    state = initial
    results: list[TickResult] = []
    for _ in range(ticks):
        result = tick_body(state, profile, water_flow=water_flow)
        results.append(result)
        state = result.state
        if stop_on_detonation and result.detonated:
            break
    return results


def explosion_impulse(
    explosion_center: Vec3,
    target_position: Vec3,
    *,
    power: float = 4.0,
    exposure: float = 1.0,
    knockback_resistance: float = 0.0,
    target_eye_height: float = 0.0,
    target_is_tnt: bool = True,
    count: int = 1,
) -> Vec3:
    """Calculate the source-audited entity velocity contribution from explosions."""
    if power < 1.0e-5 or count <= 0:
        return ZERO
    if not 0.0 <= exposure <= 1.0:
        raise ValueError("exposure must be between 0 and 1")
    if not 0.0 <= knockback_resistance <= 1.0:
        raise ValueError("knockback_resistance must be between 0 and 1")
    diameter = power * 2.0
    feet_distance = target_position.subtract(explosion_center).length()
    normalized_distance = feet_distance / diameter
    if normalized_distance > 1.0:
        return ZERO
    origin = target_position if target_is_tnt else target_position.add(Vec3(0.0, target_eye_height, 0.0))
    direction = origin.subtract(explosion_center).normalize()
    scalar = (1.0 - normalized_distance) * exposure * (1.0 - knockback_resistance)
    return direction.scale(scalar * count)


def explosion_damage(
    explosion_center: Vec3,
    target_feet: Vec3,
    *,
    power: float = 4.0,
    exposure: float = 1.0,
) -> float:
    diameter = power * 2.0
    normalized_distance = target_feet.subtract(explosion_center).length() / diameter
    if normalized_distance > 1.0:
        return 0.0
    d1 = (1.0 - normalized_distance) * exposure
    return (d1 * d1 + d1) / 2.0 * 7.0 * diameter + 1.0


def read_cannonlab_events(path: Path, *, entity_kind: str = "tnt", uuid: str | None = None, index: int = 0) -> list[Observation]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    wanted = TNT_TYPES if _kind(entity_kind) == "tnt" else FALLING_TYPES
    by_uuid: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("event") != "ENTITY" or row.get("type", "").upper() not in wanted:
            continue
        entity_uuid = row.get("uuid", "")
        if entity_uuid:
            by_uuid.setdefault(entity_uuid, []).append(row)
    if not by_uuid:
        raise ValueError(f"no {entity_kind} trajectories found in {path}")
    for trajectory in by_uuid.values():
        trajectory.sort(key=lambda item: int(item["tick"]))
    if uuid is None:
        ordered = sorted(
            by_uuid,
            key=lambda item: (
                int(by_uuid[item][0]["tick"]),
                float(by_uuid[item][0]["x"]),
                float(by_uuid[item][0]["y"]),
                float(by_uuid[item][0]["z"]),
                item,
            ),
        )
        if index < 0 or index >= len(ordered):
            raise ValueError(f"entity index {index} outside 0..{len(ordered) - 1}")
        uuid = ordered[index]
    if uuid not in by_uuid:
        raise ValueError(f"entity UUID {uuid} not present")
    observations: list[Observation] = []
    for row in by_uuid[uuid]:
        observations.append(
            Observation(
                tick=int(row["tick"]),
                position=Vec3(float(row["x"]), float(row["y"]), float(row["z"])),
                velocity=Vec3(float(row["vx"]), float(row["vy"]), float(row["vz"])),
                fuse=int(row.get("fuse", 0) or 0),
                uuid=uuid,
                entity_type=row.get("type", ""),
            )
        )
    return observations


def _near(value: float, target: float, tolerance: float) -> bool:
    return abs(value - target) <= tolerance


def diagnose_step(
    previous: Observation,
    observed: Observation,
    predicted: TickResult,
    *,
    position_tolerance: float,
    velocity_tolerance: float,
    fuse_tolerance: int,
    water_flow: Vec3,
    profile: PhysicsProfile,
) -> list[dict[str, Any]]:
    diagnoses: list[dict[str, Any]] = []
    position_error = observed.position.subtract(predicted.state.position)
    velocity_error = observed.velocity.subtract(predicted.state.velocity)
    fuse_error = observed.fuse - predicted.state.fuse_or_age

    if abs(fuse_error) > fuse_tolerance:
        diagnoses.append(
            {
                "code": "fuse-order-or-tick-phase-divergence",
                "confidence": "high" if abs(fuse_error) == 1 else "medium",
                "evidence": {"observed_minus_predicted_fuse": fuse_error},
            }
        )

    if observed.position.distance(predicted.state.position) <= position_tolerance and observed.velocity.distance(predicted.state.velocity) <= velocity_tolerance:
        return diagnoses

    if abs(velocity_error.x) <= velocity_tolerance and abs(velocity_error.z) <= velocity_tolerance:
        if _near(abs(velocity_error.y), profile.gravity, max(velocity_tolerance * 5.0, 1.0e-4)):
            diagnoses.append(
                {
                    "code": "gravity-order-or-missing-gravity",
                    "confidence": "high",
                    "evidence": {"vertical_velocity_error": velocity_error.y, "profile_gravity": profile.gravity},
                }
            )

    expected_water = water_push_vector(water_flow, profile.water_flow_scale)
    if expected_water.length() > EPSILON:
        if velocity_error.distance(expected_water.scale(-1.0)) <= max(velocity_tolerance * 5.0, 1.0e-4):
            diagnoses.append(
                {
                    "code": "missing-water-current-push",
                    "confidence": "high",
                    "evidence": {"expected_push": expected_water.to_list()},
                }
            )
        elif velocity_error.distance(expected_water) <= max(velocity_tolerance * 5.0, 1.0e-4):
            diagnoses.append(
                {
                    "code": "extra-water-current-push",
                    "confidence": "high",
                    "evidence": {"unexpected_push": expected_water.to_list()},
                }
            )

    previous_speed = previous.velocity.length()
    observed_speed = observed.velocity.length()
    predicted_speed = predicted.state.velocity.length()
    if previous_speed > 1.0e-6 and predicted_speed > 1.0e-6:
        observed_ratio = observed_speed / previous_speed
        if not _near(observed_ratio, profile.drag, 5.0e-3) and observed.position.distance(predicted.state.position) > position_tolerance:
            diagnoses.append(
                {
                    "code": "drag-or-velocity-multiplier-divergence",
                    "confidence": "medium",
                    "evidence": {"observed_speed_ratio": observed_ratio, "profile_drag": profile.drag},
                }
            )

    axis_zeroed = []
    for axis, before, after, expected in (
        ("x", previous.velocity.x, observed.velocity.x, predicted.state.velocity.x),
        ("y", previous.velocity.y, observed.velocity.y, predicted.state.velocity.y),
        ("z", previous.velocity.z, observed.velocity.z, predicted.state.velocity.z),
    ):
        if abs(before) > 1.0e-3 and abs(after) <= velocity_tolerance and abs(expected) > velocity_tolerance:
            axis_zeroed.append(axis)
    if axis_zeroed:
        diagnoses = [
            item
            for item in diagnoses
            if item["code"] != "drag-or-velocity-multiplier-divergence"
        ]
        diagnoses.append(
            {
                "code": "collision-or-axis-resolution",
                "confidence": "high",
                "evidence": {"zeroed_axes": axis_zeroed},
            }
        )

    if not diagnoses or all(item["code"].startswith("fuse-") for item in diagnoses):
        diagnoses.append(
            {
                "code": "unmodelled-world-or-fork-effect",
                "confidence": "low",
                "evidence": {
                    "position_error": position_error.to_list(),
                    "velocity_error": velocity_error.to_list(),
                    "note": "Likely candidates include voxel collision, piston/water phase ordering, explosion impulse, spawn order, region scheduling, or a private fork patch.",
                },
            }
        )
    return diagnoses


def compare_observations(
    observations: Sequence[Observation],
    *,
    kind: str = "tnt",
    profile: PhysicsProfile = PROFILES["modern-java"],
    water_flow: Vec3 = ZERO,
    position_tolerance: float = 1.0e-5,
    velocity_tolerance: float = 1.0e-5,
    fuse_tolerance: int = 0,
) -> dict[str, Any]:
    if len(observations) < 2:
        raise ValueError("at least two trajectory observations are required")
    samples: list[dict[str, Any]] = []
    first_divergence: dict[str, Any] | None = None
    max_position_error = 0.0
    max_velocity_error = 0.0
    max_fuse_error = 0

    for previous, observed in zip(observations, observations[1:]):
        tick_gap = observed.tick - previous.tick
        if tick_gap != 1:
            sample = {
                "from_tick": previous.tick,
                "to_tick": observed.tick,
                "status": "UNMODELLED_GAP",
                "diagnoses": [{"code": "non-consecutive-telemetry", "confidence": "high", "evidence": {"tick_gap": tick_gap}}],
            }
            samples.append(sample)
            if first_divergence is None:
                first_divergence = sample
            continue
        state = BodyState(kind, previous.position, previous.velocity, previous.fuse, False)
        predicted = tick_body(state, profile, water_flow=water_flow)
        position_error = observed.position.distance(predicted.state.position)
        velocity_error = observed.velocity.distance(predicted.state.velocity)
        fuse_error = abs(observed.fuse - predicted.state.fuse_or_age)
        max_position_error = max(max_position_error, position_error)
        max_velocity_error = max(max_velocity_error, velocity_error)
        max_fuse_error = max(max_fuse_error, fuse_error)
        divergent = position_error > position_tolerance or velocity_error > velocity_tolerance or fuse_error > fuse_tolerance
        diagnoses = diagnose_step(
            previous,
            observed,
            predicted,
            position_tolerance=position_tolerance,
            velocity_tolerance=velocity_tolerance,
            fuse_tolerance=fuse_tolerance,
            water_flow=water_flow,
            profile=profile,
        ) if divergent else []
        sample = {
            "from_tick": previous.tick,
            "to_tick": observed.tick,
            "status": "DIVERGED" if divergent else "MATCH",
            "observed": {
                "position": observed.position.to_list(),
                "velocity": observed.velocity.to_list(),
                "fuse": observed.fuse,
            },
            "predicted": {
                "position": predicted.state.position.to_list(),
                "velocity": predicted.state.velocity.to_list(),
                "fuse": predicted.state.fuse_or_age,
                "detonated": predicted.detonated,
                "applied_water_push": predicted.applied_water_push.to_list(),
            },
            "errors": {
                "position": position_error,
                "velocity": velocity_error,
                "fuse": fuse_error,
            },
            "diagnoses": diagnoses,
        }
        if divergent and first_divergence is None:
            first_divergence = sample
        if divergent or len(samples) < 2:
            samples.append(sample)

    return {
        "schema": "cannonlab-reference-physics-compare-v1",
        "status": "MATCH" if first_divergence is None else "DIVERGED",
        "profile": asdict(profile),
        "entity": {
            "kind": _kind(kind),
            "uuid": observations[0].uuid,
            "type": observations[0].entity_type,
            "samples": len(observations),
            "first_tick": observations[0].tick,
            "last_tick": observations[-1].tick,
        },
        "inputs": {"water_flow": water_flow.to_list()},
        "thresholds": {
            "position": position_tolerance,
            "velocity": velocity_tolerance,
            "fuse": fuse_tolerance,
        },
        "summary": {
            "max_position_error": max_position_error,
            "max_velocity_error": max_velocity_error,
            "max_fuse_error": max_fuse_error,
            "first_divergence": first_divergence,
        },
        "selected_samples": samples[:100],
        "truth_boundary": {
            "independent_empty_space_oracle": True,
            "collision_requires_runtime_resolved_movement": True,
            "private_extremecraft_parity_proven": False,
            "diagnoses_are_hypotheses_until_reproduced": True,
        },
    }


def _vec(values: Sequence[float]) -> Vec3:
    if len(values) != 3:
        raise ValueError("expected exactly three vector components")
    return Vec3(float(values[0]), float(values[1]), float(values[2]))


def _render(data: Any, output: Path | None) -> None:
    rendered = json.dumps(data, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CannonLab independent TNT/falling-block reference physics oracle")
    sub = parser.add_subparsers(dest="command", required=True)

    profiles = sub.add_parser("profiles", help="show audited physics profiles and boundaries")
    profiles.add_argument("--json-out", type=Path)

    simulation = sub.add_parser("simulate", help="predict empty-space entity motion")
    simulation.add_argument("--kind", choices=("tnt", "falling_block"), default="tnt")
    simulation.add_argument("--profile", choices=tuple(PROFILES), default="modern-java")
    simulation.add_argument("--position", nargs=3, type=float, default=(0.0, 0.0, 0.0))
    simulation.add_argument("--velocity", nargs=3, type=float, required=True)
    simulation.add_argument("--fuse-or-age", type=int, default=80)
    simulation.add_argument("--ticks", type=int, required=True)
    simulation.add_argument("--water-flow", nargs=3, type=float, default=(0.0, 0.0, 0.0))
    simulation.add_argument("--no-stop-on-detonation", action="store_true")
    simulation.add_argument("--json-out", type=Path)

    impulse = sub.add_parser("impulse", help="calculate explosion velocity contribution")
    impulse.add_argument("--explosion", nargs=3, type=float, required=True)
    impulse.add_argument("--target", nargs=3, type=float, required=True)
    impulse.add_argument("--power", type=float, default=4.0)
    impulse.add_argument("--exposure", type=float, default=1.0)
    impulse.add_argument("--knockback-resistance", type=float, default=0.0)
    impulse.add_argument("--target-eye-height", type=float, default=0.0)
    impulse.add_argument("--target-is-tnt", action=argparse.BooleanOptionalAction, default=True)
    impulse.add_argument("--count", type=int, default=1)
    impulse.add_argument("--json-out", type=Path)

    comparison = sub.add_parser("compare-events", help="compare one CannonLab trajectory to the oracle")
    comparison.add_argument("events", type=Path)
    comparison.add_argument("--kind", choices=("tnt", "falling_block"), default="tnt")
    comparison.add_argument("--profile", choices=tuple(PROFILES), default="modern-java")
    comparison.add_argument("--uuid")
    comparison.add_argument("--entity-index", type=int, default=0)
    comparison.add_argument("--water-flow", nargs=3, type=float, default=(0.0, 0.0, 0.0))
    comparison.add_argument("--position-tolerance", type=float, default=1.0e-5)
    comparison.add_argument("--velocity-tolerance", type=float, default=1.0e-5)
    comparison.add_argument("--fuse-tolerance", type=int, default=0)
    comparison.add_argument("--json-out", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "profiles":
            report = {
                "schema": "cannonlab-reference-physics-profiles-v1",
                "profiles": {key: asdict(value) for key, value in PROFILES.items()},
                "source_boundary": (
                    "Constants are implementation evidence, not private-server parity. Every profile must be "
                    "validated against recorded runtime and live field calibration before promotion."
                ),
            }
            _render(report, args.json_out)
            return 0
        if args.command == "simulate":
            profile = PROFILES[args.profile]
            initial = BodyState(args.kind, _vec(args.position), _vec(args.velocity), args.fuse_or_age)
            results = simulate(
                initial,
                args.ticks,
                profile,
                water_flow=_vec(args.water_flow),
                stop_on_detonation=not args.no_stop_on_detonation,
            )
            report = {
                "schema": "cannonlab-reference-physics-simulation-v1",
                "profile": asdict(profile),
                "initial": {
                    "kind": initial.kind,
                    "position": initial.position.to_list(),
                    "velocity": initial.velocity.to_list(),
                    "fuse_or_age": initial.fuse_or_age,
                },
                "ticks": [
                    {
                        "age": index + 1,
                        "position": item.state.position.to_list(),
                        "velocity": item.state.velocity.to_list(),
                        "fuse_or_age": item.state.fuse_or_age,
                        "detonated": item.detonated,
                        "landed": item.landed,
                        "applied_water_push": item.applied_water_push.to_list(),
                    }
                    for index, item in enumerate(results)
                ],
            }
            _render(report, args.json_out)
            return 0
        if args.command == "impulse":
            center = _vec(args.explosion)
            target = _vec(args.target)
            vector = explosion_impulse(
                center,
                target,
                power=args.power,
                exposure=args.exposure,
                knockback_resistance=args.knockback_resistance,
                target_eye_height=args.target_eye_height,
                target_is_tnt=args.target_is_tnt,
                count=args.count,
            )
            report = {
                "schema": "cannonlab-reference-explosion-impulse-v1",
                "impulse": vector.to_list(),
                "damage": explosion_damage(center, target, power=args.power, exposure=args.exposure),
                "inputs": {
                    "explosion": center.to_list(),
                    "target": target.to_list(),
                    "power": args.power,
                    "exposure": args.exposure,
                    "knockback_resistance": args.knockback_resistance,
                    "target_is_tnt": args.target_is_tnt,
                    "target_eye_height": args.target_eye_height,
                    "count": args.count,
                },
            }
            _render(report, args.json_out)
            return 0
        observations = read_cannonlab_events(
            args.events,
            entity_kind=args.kind,
            uuid=args.uuid,
            index=args.entity_index,
        )
        report = compare_observations(
            observations,
            kind=args.kind,
            profile=PROFILES[args.profile],
            water_flow=_vec(args.water_flow),
            position_tolerance=args.position_tolerance,
            velocity_tolerance=args.velocity_tolerance,
            fuse_tolerance=args.fuse_tolerance,
        )
        _render(report, args.json_out)
        return 0 if report["status"] == "MATCH" else 2
    except (OSError, ValueError, KeyError) as exc:
        _render(
            {
                "schema": "cannonlab-reference-physics-error-v1",
                "status": "FAIL",
                "error": str(exc),
            },
            getattr(args, "json_out", None),
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
