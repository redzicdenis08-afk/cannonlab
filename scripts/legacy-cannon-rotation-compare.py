#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


class RotationCompareError(ValueError):
    pass


def load_architecture() -> Any:
    script = Path(__file__).resolve().with_name("legacy-cannon-architecture.py")
    spec = importlib.util.spec_from_file_location("cannonlab_legacy_cannon_architecture", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rotate_y(point: tuple[int, int, int], turns: int) -> tuple[int, int, int]:
    x, y, z = point
    turns %= 4
    if turns == 0:
        return x, y, z
    if turns == 1:
        return -z, y, x
    if turns == 2:
        return -x, y, -z
    return z, y, -x


def normalized_rows(
    rows: Iterable[tuple[tuple[int, int, int], str]], turns: int
) -> list[list[Any]]:
    rotated = [(rotate_y(point, turns), kind) for point, kind in rows]
    if not rotated:
        return []
    minimum = tuple(min(point[axis] for point, _kind in rotated) for axis in range(3))
    return sorted(
        [
            point[0] - minimum[0],
            point[1] - minimum[1],
            point[2] - minimum[2],
            kind,
        ]
        for point, kind in rotated
    )


def rotation_invariant_signature(
    rows: Iterable[tuple[tuple[int, int, int], str]]
) -> str:
    rows = list(rows)
    encodings = [
        json.dumps(normalized_rows(rows, turns), separators=(",", ":"), ensure_ascii=True)
        for turns in range(4)
    ]
    canonical = min(encodings)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def structural_motifs(
    architecture: Any,
    blocks: dict[tuple[int, int, int], str],
) -> tuple[Counter[str], dict[str, dict[str, Any]]]:
    counts: Counter[str] = Counter()
    metadata: dict[str, dict[str, Any]] = {}
    for anchor, token in sorted(blocks.items()):
        anchor_kind = architecture.token_kind(token)
        if anchor_kind not in architecture.ANCHOR_KINDS:
            continue
        rows: list[tuple[tuple[int, int, int], str]] = []
        for dx, dy, dz in architecture.MOTIF_OFFSETS:
            point = (anchor[0] + dx, anchor[1] + dy, anchor[2] + dz)
            neighbour = blocks.get(point)
            if neighbour is None:
                continue
            rows.append(((dx, dy, dz), architecture.token_kind(neighbour)))
        signature = rotation_invariant_signature(rows)
        counts[signature] += 1
        metadata.setdefault(signature, {
            "anchor_kind": anchor_kind,
            "component_count": len(rows),
        })
    return counts, metadata


def structural_bank_contexts(
    architecture: Any,
    blocks: dict[tuple[int, int, int], str],
    radius: int = 6,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for bank in architecture.dispenser_banks(blocks):
        points = [
            point
            for point in blocks
            if architecture.inside_expanded(point, bank["bounds"], radius)
        ]
        rows = [(point, architecture.token_kind(blocks[point])) for point in points]
        output.append({
            "seed_bank_id": bank["bank_id"],
            "seed_dispenser_count": bank["dispenser_count"],
            "component_count": len(points),
            "signature": rotation_invariant_signature(rows),
            "comparison_model": "four Y-axis quarter-turns; token kinds only; no reflection",
        })
    return output


def multiset_jaccard(first: Counter[str], second: Counter[str]) -> float:
    keys = set(first) | set(second)
    union = sum(max(first[key], second[key]) for key in keys)
    if union == 0:
        return 1.0
    intersection = sum(min(first[key], second[key]) for key in keys)
    return intersection / union


def analyze_source(
    architecture: Any,
    source_id: str,
    path: Path,
) -> dict[str, Any]:
    blocks, metadata = architecture.extract_functional_blocks(path)
    metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    motifs, motif_metadata = structural_motifs(architecture, blocks)
    contexts = structural_bank_contexts(architecture, blocks)
    return {
        "source_id": source_id,
        "source_metadata": metadata,
        "functional_component_count": len(blocks),
        "structural_motif_counts": dict(motifs),
        "structural_motif_metadata": motif_metadata,
        "structural_bank_contexts": contexts,
        "summary": {
            "structural_motif_signature_count": len(motifs),
            "structural_motif_occurrence_count": sum(motifs.values()),
            "structural_bank_context_count": len(contexts),
            "unique_structural_bank_context_count": len({row["signature"] for row in contexts}),
        },
    }


def compare_sources(reports: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for index, first in enumerate(reports):
        for second in reports[index + 1 :]:
            first_motifs = Counter(first["structural_motif_counts"])
            second_motifs = Counter(second["structural_motif_counts"])
            first_contexts = {row["signature"] for row in first["structural_bank_contexts"]}
            second_contexts = {row["signature"] for row in second["structural_bank_contexts"]}
            pairs.append({
                "first": first["source_id"],
                "second": second["source_id"],
                "y_rotation_structural_motif_jaccard": round(
                    multiset_jaccard(first_motifs, second_motifs), 6
                ),
                "shared_y_rotation_structural_motif_count": len(
                    set(first_motifs) & set(second_motifs)
                ),
                "shared_y_rotation_bank_context_count": len(first_contexts & second_contexts),
                "comparison_model": (
                    "four Y-axis quarter-turns; functional token kinds only; "
                    "directional metadata discarded; no reflection"
                ),
            })
    pairs.sort(key=lambda row: (
        -row["y_rotation_structural_motif_jaccard"],
        -row["shared_y_rotation_bank_context_count"],
        row["first"],
        row["second"],
    ))

    motif_sources: dict[str, dict[str, int]] = defaultdict(dict)
    motif_metadata: dict[str, dict[str, Any]] = {}
    for report in reports:
        for signature, count in report["structural_motif_counts"].items():
            motif_sources[signature][report["source_id"]] = int(count)
            motif_metadata.setdefault(signature, report["structural_motif_metadata"][signature])
    shared = []
    for signature, occurrences in motif_sources.items():
        if len(occurrences) < 2:
            continue
        shared.append({
            "signature": signature,
            "source_count": len(occurrences),
            "total_occurrences": sum(occurrences.values()),
            "occurrences_by_source": dict(sorted(occurrences.items())),
            **motif_metadata[signature],
            "truth_boundary": "rotation-normalized structural motif; direction and runtime role unconfirmed",
        })
    shared.sort(key=lambda row: (
        -row["source_count"], -row["total_occurrences"], -row["component_count"], row["signature"]
    ))
    return {
        "pairwise_similarity": pairs,
        "shared_structural_motifs": shared,
        "summary": {
            "source_count": len(reports),
            "pair_count": len(pairs),
            "shared_structural_motif_count": len(shared),
            "motifs_present_in_all_sources": sum(
                row["source_count"] == len(reports) for row in shared
            ),
        },
    }


def compact(report: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(report)
    value.pop("structural_motif_counts", None)
    value.pop("structural_motif_metadata", None)
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare legacy cannon structure under four Y-axis rotations while discarding "
            "directional metadata and refusing reflection or runtime-role inference"
        )
    )
    parser.add_argument("--source", action="append", required=True, help="ID=PATH")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        architecture = load_architecture()
        sources = [architecture.parse_source(raw) for raw in args.source]
        ids = [source_id for source_id, _path in sources]
        if len(set(ids)) != len(ids):
            raise RotationCompareError("source IDs must be unique")
        reports = [analyze_source(architecture, source_id, path) for source_id, path in sources]
        report = {
            "schema_version": 1,
            "status": "PASS",
            "classification": "LEGACY_STATIC_Y_ROTATION_STRUCTURE_ONLY",
            "sources": [compact(source) for source in reports],
            "comparison": compare_sources(reports),
            "truth_boundary": {
                "directional_metadata_preserved_in_similarity": False,
                "reflection_matching_performed": False,
                "rotation_similarity_proves_shared_runtime_semantics": False,
                "source_claims_prove_detected_roles": False,
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
    except (OSError, ValueError, RotationCompareError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
    if args.json_out:
        write_json(args.json_out.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
