#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, deque
from pathlib import Path
from typing import Any


class PortInferenceError(ValueError):
    pass


FACE_NAMES = {
    (-1, 0, 0): "west",
    (1, 0, 0): "east",
    (0, -1, 0): "down",
    (0, 1, 0): "up",
    (0, 0, -1): "north",
    (0, 0, 1): "south",
}
NEIGHBOURS = tuple(FACE_NAMES)
SIGNAL_KINDS = {
    "redstone_wire",
    "repeater",
    "comparator",
    "redstone_torch",
    "redstone_block",
    "lever",
    "stone_button",
    "wooden_button",
    "pressure_plate",
    "weighted_pressure_plate",
}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PortInferenceError("assembly report must be a JSON object")
    return payload


def token_kind(token: str | None) -> str:
    if token is None:
        return "air"
    return str(token).split(":", 1)[0]


def token_category(token: str | None) -> str:
    kind = token_kind(token)
    if kind in SIGNAL_KINDS:
        return "signal"
    if kind.startswith("legacy-"):
        return "support-or-unmapped"
    return "other-functional"


def vector(first: list[int], second: list[int]) -> tuple[int, int, int]:
    return tuple(int(second[index]) - int(first[index]) for index in range(3))  # type: ignore[return-value]


def connected_groups(points: set[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    remaining = set(points)
    groups: list[list[tuple[int, int, int]]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        group: list[tuple[int, int, int]] = []
        while queue:
            point = queue.popleft()
            group.append(point)
            for delta in NEIGHBOURS:
                neighbour = tuple(point[index] + delta[index] for index in range(3))
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda group: (group[0], len(group)))


def bounds(points: list[tuple[int, int, int]]) -> dict[str, Any]:
    minimum = tuple(min(point[index] for point in points) for index in range(3))
    maximum = tuple(max(point[index] for point in points) for index in range(3))
    dimensions = tuple(maximum[index] - minimum[index] + 1 for index in range(3))
    return {
        "min": list(minimum),
        "max": list(maximum),
        "dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
    }


def normalized_pattern(rows: list[dict[str, Any]]) -> tuple[str, list[list[Any]]]:
    points = [tuple(map(int, row["outside"])) for row in rows]
    box = bounds(points)
    minimum = box["min"]
    normalized = sorted([
        [
            point[0] - minimum[0],
            point[1] - minimum[1],
            point[2] - minimum[2],
            token_category(row["token"]),
        ]
        for point, row in zip(points, rows)
    ])
    signature = hashlib.sha256(
        json.dumps(normalized, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return signature, normalized


def build_source_groups(
    assembly_id: str,
    examples: list[dict[str, Any]],
    source_side: str,
) -> list[dict[str, Any]]:
    expected_classification = f"{source_side}_only_nonair"
    selected: list[dict[str, Any]] = []
    for example in examples:
        if example.get("classification") != expected_classification:
            continue
        inside = list(map(int, example["inside"]))
        outside = list(map(int, example["outside"]))
        delta = vector(inside, outside)
        face = FACE_NAMES.get(delta)
        if face is None:
            raise PortInferenceError(f"non-face boundary vector in {assembly_id}: {delta}")
        token_key = "first_token" if source_side == "first" else "second_token"
        token = example.get(token_key)
        if token is None:
            raise PortInferenceError(
                f"{assembly_id} {source_side} boundary example is missing its source token"
            )
        selected.append({
            "inside": inside,
            "outside": outside,
            "face": face,
            "token": str(token),
            "token_kind": token_kind(str(token)),
            "token_category": token_category(str(token)),
        })

    by_face: dict[str, list[dict[str, Any]]] = {}
    for row in selected:
        by_face.setdefault(row["face"], []).append(row)

    output: list[dict[str, Any]] = []
    for face, face_rows in sorted(by_face.items()):
        lookup = {tuple(row["outside"]): row for row in face_rows}
        for points in connected_groups(set(lookup)):
            rows = [lookup[point] for point in points]
            rows.sort(key=lambda row: tuple(row["outside"]))
            signature, normalized = normalized_pattern(rows)
            categories = Counter(row["token_category"] for row in rows)
            kinds = Counter(row["token_kind"] for row in rows)
            output.append({
                "group_id": f"{assembly_id}-{source_side.upper()}-{len(output) + 1:02d}",
                "source_side": source_side,
                "face": face,
                "entry_count": len(rows),
                "outside_bounds": bounds(points),
                "y_min": min(point[1] for point in points),
                "y_max": max(point[1] for point in points),
                "token_category_counts": dict(sorted(categories.items())),
                "token_kind_counts": dict(sorted(kinds.items())),
                "normalized_pattern": normalized,
                "normalized_pattern_signature": signature,
                "entries": rows,
                "classification": (
                    "signal-bearing-boundary-group"
                    if categories.get("signal", 0)
                    else "support-only-boundary-group"
                ),
                "truth_boundary": (
                    "source-specific face boundary grouping only; signal-bearing does not prove "
                    "input, output, timing direction, or standalone port semantics"
                ),
            })
    return output


def pair_key(group: dict[str, Any]) -> tuple[Any, ...]:
    return (
        group["normalized_pattern_signature"],
        group["y_min"],
        group["y_max"],
        tuple(sorted(group["token_category_counts"].items())),
    )


def pair_groups(
    assembly_id: str,
    first_groups: list[dict[str, Any]],
    second_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    first_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    second_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for group in first_groups:
        first_by_key.setdefault(pair_key(group), []).append(group)
    for group in second_groups:
        second_by_key.setdefault(pair_key(group), []).append(group)

    pairs: list[dict[str, Any]] = []
    paired_first: set[str] = set()
    paired_second: set[str] = set()
    for key in sorted(set(first_by_key) & set(second_by_key), key=str):
        first_rows = sorted(first_by_key[key], key=lambda row: row["group_id"])
        second_rows = sorted(second_by_key[key], key=lambda row: row["group_id"])
        for first, second in zip(first_rows, second_rows):
            paired_first.add(first["group_id"])
            paired_second.add(second["group_id"])
            pairs.append({
                "port_pair_id": f"{assembly_id}-PORTPAIR-{len(pairs) + 1:02d}",
                "first_group_id": first["group_id"],
                "second_group_id": second["group_id"],
                "first_face": first["face"],
                "second_face": second["face"],
                "entry_count": first["entry_count"],
                "y_min": first["y_min"],
                "y_max": first["y_max"],
                "token_category_counts": first["token_category_counts"],
                "normalized_pattern_signature": first["normalized_pattern_signature"],
                "classification": "variant-boundary-port-hypothesis",
                "promotion_eligible": False,
                "truth_boundary": (
                    "matching normalized source-specific boundary shapes around a shared static "
                    "assembly; does not prove input/output direction, signal timing, role, or runtime function"
                ),
            })

    unpaired_first = [
        group["group_id"] for group in first_groups if group["group_id"] not in paired_first
    ]
    unpaired_second = [
        group["group_id"] for group in second_groups if group["group_id"] not in paired_second
    ]
    return pairs, unpaired_first, unpaired_second


def build_report(assembly_report: dict[str, Any]) -> dict[str, Any]:
    if assembly_report.get("status") != "PASS":
        raise PortInferenceError("assembly report must have status PASS")
    assemblies = assembly_report.get("assemblies")
    if not isinstance(assemblies, list):
        raise PortInferenceError("assembly report is missing assemblies")

    output: list[dict[str, Any]] = []
    for assembly in assemblies:
        if assembly.get("review_classification") not in {
            "FACE_CLOSED_STATIC_REVIEW_CANDIDATE",
            "NEAR_CLOSED_STATIC_REVIEW_CANDIDATE",
        }:
            continue
        residual_edges = assembly.get("residual_boundary_edge_counts") or {}
        expected_examples = sum(int(value) for value in residual_edges.values())
        examples = assembly.get("boundary_examples")
        if not isinstance(examples, list):
            raise PortInferenceError(f"{assembly.get('assembly_id')} is missing boundary examples")
        if len(examples) != expected_examples:
            raise PortInferenceError(
                f"{assembly.get('assembly_id')} boundary examples are truncated: "
                f"expected {expected_examples}, got {len(examples)}"
            )
        assembly_id = str(assembly["assembly_id"])
        first_groups = build_source_groups(assembly_id, examples, "first")
        second_groups = build_source_groups(assembly_id, examples, "second")
        pairs, unpaired_first, unpaired_second = pair_groups(
            assembly_id, first_groups, second_groups
        )
        output.append({
            "assembly_id": assembly_id,
            "assembly_review_classification": assembly["review_classification"],
            "functional_count": assembly["functional_count"],
            "support_count": assembly["support_count"],
            "ec160": assembly["ec160"],
            "first_boundary_groups": first_groups,
            "second_boundary_groups": second_groups,
            "paired_port_hypotheses": pairs,
            "unpaired_first_group_ids": unpaired_first,
            "unpaired_second_group_ids": unpaired_second,
            "promotion_eligible": False,
        })

    pair_count = sum(len(row["paired_port_hypotheses"]) for row in output)
    unpaired_count = sum(
        len(row["unpaired_first_group_ids"]) + len(row["unpaired_second_group_ids"])
        for row in output
    )
    return {
        "schema_version": 1,
        "status": "PASS",
        "classification": "LEGACY_VARIANT_BOUNDARY_PORT_HYPOTHESES_ONLY",
        "source_assembly_classification": assembly_report.get("classification"),
        "transform": assembly_report.get("transform"),
        "assemblies": output,
        "summary": {
            "reviewed_assembly_count": len(output),
            "paired_port_hypothesis_count": pair_count,
            "unpaired_boundary_group_count": unpaired_count,
            "promotion_eligible_port_count": 0,
        },
        "truth_boundary": {
            "boundary_shape_proves_port_semantics": False,
            "signal_bearing_proves_input_or_output": False,
            "runtime_semantics_confirmed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Group and pair source-specific boundaries around near-closed shared legacy assemblies "
            "as conservative variant port hypotheses"
        )
    )
    parser.add_argument("assembly_report", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(read_json(args.assembly_report.resolve()))
    except (OSError, json.JSONDecodeError, ValueError, PortInferenceError) as exc:
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
