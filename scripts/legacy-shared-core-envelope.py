#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


class EnvelopeError(ValueError):
    pass


ROTATION_INVARIANT_SUPPORT_IDS = {
    1, 4, 7, 20, 35, 41, 42, 43, 44, 45, 47, 48, 49, 57,
    79, 80, 82, 87, 88, 89, 95, 98, 101, 102, 121, 129, 133,
    159, 160, 166, 169, 172, 173, 174, 179, 206, 213, 214, 215,
    251, 252,
}


def load(name: str, filename: str) -> Any:
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def support_kind(block_id: int) -> str:
    return f"legacy-{block_id}"


def classify_outside_position(
    shared: Any,
    architecture: Any,
    first_value: tuple[int, int] | None,
    second_value: tuple[int, int] | None,
    turns: int,
) -> str:
    if first_value is None and second_value is None:
        return "air"
    if first_value is None:
        return "second_only_nonair"
    if second_value is None:
        return "first_only_nonair"

    first_id, first_data = first_value
    second_id, second_data = second_value
    functional_ids = architecture.FUNCTIONAL_IDS
    if first_id in functional_ids or second_id in functional_ids:
        result = shared.compare_block(architecture, first_value, second_value, turns)
        if result == "proven_equivalent":
            return "shared_equivalent_functional"
        if result in {"same_kind_unresolved_metadata", "same_kind_unresolved_id"}:
            return "shared_unresolved_functional"
        return "shared_conflicting_functional"

    if (
        first_id == second_id
        and first_data == second_data
        and first_id in ROTATION_INVARIANT_SUPPORT_IDS
    ):
        return "shared_equivalent_support"
    if first_id == second_id:
        return "shared_unresolved_support"
    return "shared_conflicting_support"


def boundary_state(
    shared: Any,
    architecture: Any,
    region: set[tuple[int, int, int]],
    first_all: dict[tuple[int, int, int], tuple[int, int]],
    second_all: dict[tuple[int, int, int], tuple[int, int]],
    turns: int,
) -> dict[str, Any]:
    edge_counts: Counter[str] = Counter()
    outside_positions: dict[str, set[tuple[int, int, int]]] = {}
    outside_kind_counts: dict[str, Counter[str]] = {}
    for point in sorted(region):
        for delta in shared.FACE_NEIGHBOURS:
            neighbour = tuple(point[index] + delta[index] for index in range(3))
            if neighbour in region:
                continue
            first_value = first_all.get(neighbour)
            second_value = second_all.get(neighbour)
            classification = classify_outside_position(
                shared, architecture, first_value, second_value, turns
            )
            if classification == "air":
                continue
            edge_counts[classification] += 1
            outside_positions.setdefault(classification, set()).add(neighbour)
            kinds = outside_kind_counts.setdefault(classification, Counter())
            if first_value is not None:
                kinds[f"first:{shared.kind_name(architecture, first_value)}"] += 1
            if second_value is not None:
                kinds[f"second:{shared.kind_name(architecture, second_value)}"] += 1
    return {
        "edge_counts": dict(sorted(edge_counts.items())),
        "unique_outside_position_counts": {
            key: len(value) for key, value in sorted(outside_positions.items())
        },
        "outside_kind_counts": {
            key: dict(sorted(value.items())) for key, value in sorted(outside_kind_counts.items())
        },
        "positions": outside_positions,
    }


def expand_support_shell(
    shared: Any,
    architecture: Any,
    seed: set[tuple[int, int, int]],
    first_all: dict[tuple[int, int, int], tuple[int, int]],
    second_all: dict[tuple[int, int, int], tuple[int, int]],
    turns: int,
    *,
    max_layers: int,
    max_added_support: int,
) -> dict[str, Any]:
    if max_layers < 0 or max_added_support < 0:
        raise EnvelopeError("support expansion limits cannot be negative")
    region = set(seed)
    added_by_layer: list[dict[str, Any]] = []
    added_total = 0
    truncated = False

    for layer in range(1, max_layers + 1):
        state = boundary_state(shared, architecture, region, first_all, second_all, turns)
        candidates = sorted(state["positions"].get("shared_equivalent_support", set()))
        candidates = [point for point in candidates if point not in region]
        if not candidates:
            break
        if added_total + len(candidates) > max_added_support:
            truncated = True
            break
        region.update(candidates)
        added_total += len(candidates)
        kind_counts = Counter(
            support_kind(first_all[point][0]) for point in candidates
        )
        added_by_layer.append({
            "layer": layer,
            "added_support_count": len(candidates),
            "added_support_kind_counts": dict(sorted(kind_counts.items())),
        })

    final_state = boundary_state(shared, architecture, region, first_all, second_all, turns)
    residual = final_state["edge_counts"]
    blocking = sum(
        count
        for key, count in residual.items()
        if key != "shared_equivalent_support"
    )
    remaining_support = residual.get("shared_equivalent_support", 0)
    if blocking == 0 and remaining_support == 0:
        classification = "FACE_CLOSED_AFTER_SHARED_SUPPORT_EXPANSION"
    elif blocking == 0 and (truncated or remaining_support):
        classification = "SHARED_SUPPORT_EXPANSION_INCOMPLETE"
    else:
        classification = "OPEN_OR_UNRESOLVED_SHARED_REGION"

    return {
        "classification": classification,
        "seed_component_count": len(seed),
        "expanded_region_count": len(region),
        "added_support_count": added_total,
        "layers_completed": len(added_by_layer),
        "added_by_layer": added_by_layer,
        "support_expansion_truncated": truncated,
        "residual_boundary_edge_counts": residual,
        "residual_unique_outside_position_counts": final_state[
            "unique_outside_position_counts"
        ],
        "residual_outside_kind_counts": final_state["outside_kind_counts"],
        "promotion_eligible": False,
        "truth_boundary": (
            "bounded face-adjacent expansion through explicitly rotation-invariant shared support "
            "blocks only; quasi-connectivity, indirect power, motion reach, fluids, conversion, and "
            "runtime ownership remain unproven"
        ),
    }


def build_report(
    first_id: str,
    first_path: Path,
    second_id: str,
    second_path: Path,
    *,
    turns: int,
    translation: tuple[int, int, int],
    minimum_component_size: int,
    max_layers: int,
    max_added_support: int,
) -> dict[str, Any]:
    shared = load("cannonlab_shared_core_envelope_base", "legacy-shared-core-audit.py")
    architecture = shared.load_script(
        "cannonlab_shared_core_envelope_architecture", "legacy-cannon-architecture.py"
    )
    first_all, first_metadata = shared.load_legacy_map(first_path)
    raw_second, second_metadata = shared.load_legacy_map(second_path)
    second_all = {
        shared.transform_point(point, turns, translation): value
        for point, value in raw_second.items()
    }
    functional_ids = architecture.FUNCTIONAL_IDS
    first_functional = {
        point: value for point, value in first_all.items() if value[0] in functional_ids
    }
    second_functional = {
        point: value for point, value in second_all.items() if value[0] in functional_ids
    }
    shared_positions = set(first_functional) & set(second_functional)
    proven = {
        point
        for point in shared_positions
        if shared.compare_block(
            architecture, first_functional[point], second_functional[point], turns
        ) == "proven_equivalent"
    }

    rows: list[dict[str, Any]] = []
    for index, component in enumerate(shared.face_components(proven), start=1):
        if len(component) < minimum_component_size:
            continue
        seed = set(component)
        envelope = expand_support_shell(
            shared,
            architecture,
            seed,
            first_all,
            second_all,
            turns,
            max_layers=max_layers,
            max_added_support=max_added_support,
        )
        rows.append({
            "component_id": f"SHARED-{index:03d}",
            "component_count": len(component),
            "bounds": shared.point_bounds(component),
            "canonical_signature": shared.normalized_signature(
                architecture, component, first_functional
            ),
            "envelope": envelope,
        })
    rows.sort(key=lambda row: (
        row["envelope"]["classification"] != "FACE_CLOSED_AFTER_SHARED_SUPPORT_EXPANSION",
        -row["component_count"],
        row["component_id"],
    ))

    counts = Counter(row["envelope"]["classification"] for row in rows)
    return {
        "schema_version": 1,
        "status": "PASS",
        "classification": "LEGACY_SHARED_CORE_SUPPORT_ENVELOPE_ONLY",
        "sources": [
            {"id": first_id, **first_metadata},
            {"id": second_id, **second_metadata},
        ],
        "transform": {"turns": turns, "degrees": turns * 90, "translation": list(translation)},
        "policy": {
            "minimum_component_size": minimum_component_size,
            "max_support_layers": max_layers,
            "max_added_support_per_component": max_added_support,
            "rotation_invariant_support_ids": sorted(ROTATION_INVARIANT_SUPPORT_IDS),
        },
        "components": rows,
        "summary": {
            "reported_component_count": len(rows),
            "classification_counts": dict(sorted(counts.items())),
            "promotion_eligible_component_count": 0,
        },
        "truth_boundary": {
            "support_shell_proves_standalone_operation": False,
            "runtime_semantics_confirmed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def parse_triplet(raw: str) -> tuple[int, int, int]:
    values = tuple(int(value.strip()) for value in raw.split(","))
    if len(values) != 3:
        raise EnvelopeError("translation must be X,Y,Z")
    return values  # type: ignore[return-value]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expand metadata-equivalent legacy shared-core components through bounded, explicitly "
            "rotation-invariant support shells without claiming standalone runtime behavior"
        )
    )
    parser.add_argument("--first-id", required=True)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second-id", required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--turns", type=int, required=True)
    parser.add_argument("--translation", required=True)
    parser.add_argument("--minimum-component-size", type=int, default=8)
    parser.add_argument("--max-support-layers", type=int, default=8)
    parser.add_argument("--max-added-support", type=int, default=4096)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(
            args.first_id,
            args.first.resolve(),
            args.second_id,
            args.second.resolve(),
            turns=args.turns,
            translation=parse_triplet(args.translation),
            minimum_component_size=args.minimum_component_size,
            max_layers=args.max_support_layers,
            max_added_support=args.max_added_support,
        )
    except (OSError, ValueError, EnvelopeError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {"ec_ready": False},
        }
    if args.json_out:
        write_json(args.json_out.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
