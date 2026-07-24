#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Iterator

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
SAFE_REWRITABLE_BLOCK_ENTITIES = {"minecraft:dispenser", "minecraft:dropper"}
SUPPORTED_CONTROL_KINDS = {"repeater-delay", "block-state-choice"}
SLUG = re.compile(r"[^a-z0-9]+")


class RepairGenerationError(ValueError):
    pass


@dataclass(frozen=True)
class Variant:
    control_id: str
    module_id: str
    kind: str
    label: str
    changes: dict[tuple[int, int, int], str]
    numeric_delta: int
    allowed_types: frozenset[str]
    justification: str


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    variants: tuple[Variant, ...]
    changes: dict[tuple[int, int, int], str]
    numeric_delta: int
    allowed_types: frozenset[str]
    allowed_modules: frozenset[str]


def load_script(repo_root: Path, name: str, filename: str) -> ModuleType:
    path = repo_root / "scripts" / filename
    if not path.is_file():
        raise RepairGenerationError(f"missing CannonLab dependency: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RepairGenerationError(f"cannot import CannonLab dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RepairGenerationError(f"expected JSON object: {path}")
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


def as_point(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise RepairGenerationError(f"{label} must be a three-integer list")
    try:
        return tuple(int(part) for part in value)  # type: ignore[return-value]
    except (TypeError, ValueError) as exc:
        raise RepairGenerationError(f"{label} must be a three-integer list") from exc


def normalize_model(model: dict[str, Any]) -> tuple[
    dict[tuple[int, int, int], str], tuple[dict[str, Any], ...], tuple[int, int, int], int
]:
    raw_blocks = model.get("blocks")
    dimensions = model.get("source_dimensions") or {}
    if not isinstance(raw_blocks, dict):
        raise RepairGenerationError("decoded schematic has no block map")
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
        raise RepairGenerationError("decoded source dimensions are invalid") from exc
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


def safe_block_entities(entities: Iterable[dict[str, Any]]) -> None:
    for entity in entities:
        entity_id = str(entity.get("id", ""))
        if entity_id not in SAFE_REWRITABLE_BLOCK_ENTITIES:
            raise RepairGenerationError(
                f"block entity {entity_id!r} cannot be losslessly rewritten by the deterministic candidate writer"
            )
        raw = entity.get("raw") or {}
        if not isinstance(raw, dict):
            raise RepairGenerationError(f"block entity {entity_id!r} has invalid raw NBT")
        items = raw.get("Items", raw.get("items"))
        if items not in (None, [], ()):
            raise RepairGenerationError(f"block entity {entity_id!r} contains inventory items")


def validate_policy(policy: dict[str, Any]) -> None:
    if int(policy.get("schema_version", 0)) != 1:
        raise RepairGenerationError("repair policy schema_version must equal 1")
    if len(str(policy.get("source_sha256", ""))) != 64:
        raise RepairGenerationError("repair policy source_sha256 must be exact")
    controls = policy.get("controls")
    if not isinstance(controls, list) or not controls:
        raise RepairGenerationError("repair policy controls must be a non-empty list")
    search = policy.get("search") or {}
    if not isinstance(search, dict):
        raise RepairGenerationError("repair policy search must be an object")
    max_controls = int(search.get("max_controls_per_candidate", 1))
    max_candidates = int(search.get("max_candidates", 24))
    if max_controls < 1 or max_controls > 3:
        raise RepairGenerationError("max_controls_per_candidate must be between 1 and 3")
    if max_candidates < 1 or max_candidates > 256:
        raise RepairGenerationError("max_candidates must be between 1 and 256")


def first_divergence(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        payload.get("first_divergence"),
        (payload.get("comparison") or {}).get("first_divergence")
        if isinstance(payload.get("comparison") or {}, dict)
        else None,
    ]
    row = next((value for value in candidates if isinstance(value, dict)), None)
    if row is None:
        raise RepairGenerationError("divergence report has no first_divergence object")
    kind = str(row.get("kind", "")).strip()
    if not kind:
        raise RepairGenerationError("first_divergence.kind is required")
    return dict(row)


def position_modules(module_report: dict[str, Any]) -> dict[tuple[int, int, int], set[str]]:
    output: dict[tuple[int, int, int], set[str]] = {}
    for module in module_report.get("modules") or []:
        module_id = str(module.get("module_id"))
        for raw in module.get("component_positions") or []:
            point = tuple(map(int, raw))
            output.setdefault(point, set()).add(module_id)
    for shared in module_report.get("shared_component_assignments") or []:
        raw = shared.get("pos") or []
        if len(raw) < 3:
            continue
        point = tuple(map(int, raw[:3]))
        output.setdefault(point, set()).update(
            str(value) for value in shared.get("candidate_module_ids") or []
        )
    return output


def replace_property(auditor: ModuleType, state: str, key: str, value: str) -> str:
    block_type = auditor.base(state)
    props = auditor.properties(state)
    props[key] = value
    return block_type + "[" + ",".join(f"{name}={props[name]}" for name in sorted(props)) + "]"


def control_matches_divergence(control: dict[str, Any], kind: str) -> bool:
    kinds = control.get("divergence_kinds")
    if not isinstance(kinds, list) or not kinds:
        raise RepairGenerationError(f"control {control.get('id')!r}: divergence_kinds are required")
    normalized = {str(value) for value in kinds}
    return kind in normalized or "*" in normalized


def validate_control_common(
    raw: Any,
    seen: set[str],
    module_ids: set[str],
) -> tuple[str, str, str]:
    if not isinstance(raw, dict):
        raise RepairGenerationError("each repair control must be an object")
    control_id = str(raw.get("id", "")).strip()
    kind = str(raw.get("kind", "")).strip()
    module_id = str(raw.get("module_id", "")).strip()
    justification = str(raw.get("justification", "")).strip()
    if not control_id or control_id in seen:
        raise RepairGenerationError(f"control id is missing or duplicated: {control_id!r}")
    if kind not in SUPPORTED_CONTROL_KINDS:
        raise RepairGenerationError(f"control {control_id}: unsupported kind {kind!r}")
    if module_id not in module_ids:
        raise RepairGenerationError(f"control {control_id}: unknown module_id {module_id!r}")
    if not justification:
        raise RepairGenerationError(f"control {control_id}: exact causal justification is required")
    seen.add(control_id)
    return control_id, kind, module_id


def validate_positions(
    control_id: str,
    raw: dict[str, Any],
    module_id: str,
    blocks: dict[tuple[int, int, int], str],
    owners: dict[tuple[int, int, int], set[str]],
) -> list[tuple[int, int, int]]:
    raw_positions = raw.get("positions")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise RepairGenerationError(f"control {control_id}: positions must be a non-empty list")
    positions = [as_point(value, f"control {control_id} position") for value in raw_positions]
    if len(set(positions)) != len(positions):
        raise RepairGenerationError(f"control {control_id}: duplicate positions")
    allow_shared = bool(raw.get("allow_shared_position", False))
    for point in positions:
        if base_state(blocks.get(point, "minecraft:air")) in AIR:
            raise RepairGenerationError(f"control {control_id}: position {point} points to air")
        position_owners = owners.get(point, set())
        if module_id not in position_owners:
            raise RepairGenerationError(
                f"control {control_id}: position {point} is not owned by declared module {module_id}"
            )
        if len(position_owners) > 1 and not allow_shared:
            raise RepairGenerationError(
                f"control {control_id}: position {point} has ambiguous module ownership {sorted(position_owners)}"
            )
    return positions


def repeater_variants(
    control_id: str,
    module_id: str,
    raw: dict[str, Any],
    positions: list[tuple[int, int, int]],
    blocks: dict[tuple[int, int, int], str],
    auditor: ModuleType,
) -> list[Variant]:
    values = raw.get("allowed_values")
    if not isinstance(values, list) or not values:
        raise RepairGenerationError(f"control {control_id}: allowed_values are required")
    try:
        allowed = sorted({int(value) for value in values})
    except (TypeError, ValueError) as exc:
        raise RepairGenerationError(f"control {control_id}: repeater delays must be integers") from exc
    if any(value < 1 or value > 4 for value in allowed):
        raise RepairGenerationError(f"control {control_id}: repeater delays must be 1..4")
    current_values = []
    for point in positions:
        state = blocks[point]
        if auditor.base(state) != "minecraft:repeater":
            raise RepairGenerationError(f"control {control_id}: {point} is not a repeater")
        try:
            current_values.append(int(auditor.properties(state).get("delay", "1")))
        except ValueError as exc:
            raise RepairGenerationError(f"control {control_id}: invalid current repeater delay") from exc
    variants = []
    for value in allowed:
        if all(current == value for current in current_values):
            continue
        changes = {
            point: replace_property(auditor, blocks[point], "delay", str(value))
            for point in positions
        }
        variants.append(
            Variant(
                control_id=control_id,
                module_id=module_id,
                kind="repeater-delay",
                label=f"delay-{value}",
                changes=changes,
                numeric_delta=sum(abs(value - current) for current in current_values),
                allowed_types=frozenset({"minecraft:repeater"}),
                justification=str(raw["justification"]),
            )
        )
    if not variants:
        raise RepairGenerationError(f"control {control_id}: allowed delays produce no changes")
    return variants


def state_choice_variants(
    control_id: str,
    module_id: str,
    raw: dict[str, Any],
    positions: list[tuple[int, int, int]],
    blocks: dict[tuple[int, int, int], str],
) -> list[Variant]:
    values = raw.get("allowed_states")
    if not isinstance(values, list) or not values or not all(str(value).strip() for value in values):
        raise RepairGenerationError(f"control {control_id}: allowed_states are required")
    if len(positions) != 1 and not bool(raw.get("apply_same_state_to_cohort", False)):
        raise RepairGenerationError(
            f"control {control_id}: multiple positions require apply_same_state_to_cohort=true"
        )
    allow_type_change = bool(raw.get("allow_type_change", False))
    source_types = {base_state(blocks[point]) for point in positions}
    variants = []
    for state in sorted({str(value) for value in values}):
        if base_state(state) in AIR:
            raise RepairGenerationError(f"control {control_id}: air is not an allowed repair state")
        target_type = base_state(state)
        if not allow_type_change and any(source_type != target_type for source_type in source_types):
            raise RepairGenerationError(
                f"control {control_id}: state {state!r} changes block type without allow_type_change"
            )
        if all(blocks[point] == state for point in positions):
            continue
        allowed_types = {*source_types, target_type}
        variants.append(
            Variant(
                control_id=control_id,
                module_id=module_id,
                kind="block-state-choice",
                label=f"state-{SLUG.sub('-', state.lower()).strip('-')[:48]}",
                changes={point: state for point in positions},
                numeric_delta=0,
                allowed_types=frozenset(allowed_types),
                justification=str(raw["justification"]),
            )
        )
    if not variants:
        raise RepairGenerationError(f"control {control_id}: allowed states produce no changes")
    return variants


def build_control_variants(
    policy: dict[str, Any],
    divergence_kind: str,
    blocks: dict[tuple[int, int, int], str],
    module_report: dict[str, Any],
    auditor: ModuleType,
) -> list[tuple[dict[str, Any], list[Variant]]]:
    owners = position_modules(module_report)
    module_ids = {str(row.get("module_id")) for row in module_report.get("modules") or []}
    seen: set[str] = set()
    output = []
    for raw in policy["controls"]:
        control_id, kind, module_id = validate_control_common(raw, seen, module_ids)
        if not control_matches_divergence(raw, divergence_kind):
            continue
        positions = validate_positions(control_id, raw, module_id, blocks, owners)
        if kind == "repeater-delay":
            variants = repeater_variants(
                control_id, module_id, raw, positions, blocks, auditor
            )
        else:
            variants = state_choice_variants(
                control_id, module_id, raw, positions, blocks
            )
        output.append((raw, variants))
    if not output:
        raise RepairGenerationError(
            f"no declared repair control matches first divergence kind {divergence_kind!r}"
        )
    output.sort(key=lambda row: ("*" in row[0].get("divergence_kinds", []), str(row[0]["id"])))
    return output


def merge_variants(variants: tuple[Variant, ...]) -> Candidate | None:
    changes: dict[tuple[int, int, int], str] = {}
    for variant in variants:
        for point, state in variant.changes.items():
            existing = changes.get(point)
            if existing is not None and existing != state:
                return None
            changes[point] = state
    parts = [
        f"{variant.control_id}-{variant.label}"
        for variant in variants
    ]
    slug = "__".join(SLUG.sub("-", part.lower()).strip("-") for part in parts)
    digest = hashlib.sha256(
        json.dumps(
            [[*point, state] for point, state in sorted(changes.items())],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:10]
    return Candidate(
        candidate_id=f"{slug[:120]}-{digest}",
        variants=variants,
        changes=changes,
        numeric_delta=sum(variant.numeric_delta for variant in variants),
        allowed_types=frozenset(
            block_type for variant in variants for block_type in variant.allowed_types
        ),
        allowed_modules=frozenset(variant.module_id for variant in variants),
    )


def generate_candidates(
    control_variants: list[tuple[dict[str, Any], list[Variant]]],
    max_controls_per_candidate: int,
    max_candidates: int,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen_signatures = set()
    for control_count in range(1, min(max_controls_per_candidate, len(control_variants)) + 1):
        for selected in itertools.combinations(control_variants, control_count):
            for variants in itertools.product(*(row[1] for row in selected)):
                candidate = merge_variants(tuple(variants))
                if candidate is None:
                    continue
                signature = tuple(sorted(candidate.changes.items()))
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                candidates.append(candidate)
                if len(candidates) >= max_candidates:
                    break
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break
    candidates.sort(
        key=lambda row: (
            len(row.variants),
            len(row.changes),
            row.numeric_delta,
            row.candidate_id,
        )
    )
    return candidates[:max_candidates]


def candidate_model(
    source_blocks: dict[tuple[int, int, int], str],
    source_entities: Iterable[dict[str, Any]],
    dimensions: tuple[int, int, int],
    data_version: int,
    changes: dict[tuple[int, int, int], str],
) -> dict[str, Any]:
    blocks = dict(source_blocks)
    blocks.update(changes)
    entities = [
        {
            "pos": tuple(entity["pos"]),
            "id": str(entity.get("id", "unknown")),
            "raw": dict(entity.get("raw") or {}),
        }
        for entity in source_entities
    ]
    return {
        "format": "sponge-v2",
        "version": 2,
        "data_version": data_version,
        "blocks": blocks,
        "block_entities": entities,
        "source_dimensions": {
            "width": dimensions[0],
            "height": dimensions[1],
            "length": dimensions[2],
        },
    }


def verify_candidate_output(
    output_path: Path,
    expected: dict[str, Any],
    auditor: ModuleType,
    data_version: int,
) -> dict[str, Any]:
    root_name, root, trailing, _size, diagnostics = auditor.load(output_path)
    if trailing:
        raise RepairGenerationError("generated candidate has trailing NBT bytes")
    decoded = auditor.decode_any(root_name, root)
    blocks, entities, dimensions, actual_data_version = normalize_model(decoded)
    expected_occupied = {
        point: state
        for point, state in expected["blocks"].items()
        if base_state(state) not in AIR
    }
    actual_occupied = {
        point: state
        for point, state in blocks.items()
        if base_state(state) not in AIR
    }
    if actual_occupied != expected_occupied:
        raise RepairGenerationError("candidate occupied geometry failed exact round-trip")
    expected_entities = sorted(tuple(row["pos"]) for row in expected["block_entities"])
    actual_entities = sorted(tuple(row["pos"]) for row in entities)
    if actual_entities != expected_entities:
        raise RepairGenerationError("candidate block-entity positions failed exact round-trip")
    if actual_data_version != data_version:
        raise RepairGenerationError("candidate DataVersion failed exact round-trip")
    return {
        "sha256": sha256_file(output_path),
        "bytes": output_path.stat().st_size,
        "dimensions": list(dimensions),
        "data_version": actual_data_version,
        "occupied_blocks": len(actual_occupied),
        "block_entities": len(actual_entities),
        "geometry_verified": True,
        "container_diagnostics": diagnostics,
    }


def dispenser_scan(
    blocks: dict[tuple[int, int, int], str],
    planner: ModuleType,
    chunk_limit: int,
) -> dict[str, Any]:
    coords = [
        point for point, state in blocks.items()
        if base_state(state) == "minecraft:dispenser"
    ]
    return planner.scan_chunk_alignments(coords, chunk_limit)


def preservation_policy(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("preservation") or {}
    if not isinstance(raw, dict):
        raise RepairGenerationError("preservation policy must be an object")
    confidence = str(raw.get("minimum_alignment_confidence", "high"))
    alignment_mode = str(raw.get("alignment_mode", "exact"))
    if confidence not in {"low", "medium", "high"}:
        raise RepairGenerationError("invalid minimum_alignment_confidence")
    if alignment_mode not in {"exact", "translate"}:
        raise RepairGenerationError("invalid alignment_mode")
    return {
        "chunk_limit": int(raw.get("chunk_limit", 160)),
        "max_structural_change_ratio": float(raw.get("max_structural_change_ratio", 0.03)),
        "max_functional_change_ratio": float(raw.get("max_functional_change_ratio", 0.05)),
        "max_modules_touched": int(raw.get("max_modules_touched", 1)),
        "max_unexpected_critical_changes": int(raw.get("max_unexpected_critical_changes", 0)),
        "allow_dimension_change": bool(raw.get("allow_dimension_change", False)),
        "allow_block_entity_topology_change": bool(raw.get("allow_block_entity_topology_change", False)),
        "allow_ambiguous_alignment": bool(raw.get("allow_ambiguous_alignment", False)),
        "minimum_alignment_confidence": confidence,
        "alignment_mode": alignment_mode,
    }


def control_to_json(variant: Variant) -> dict[str, Any]:
    return {
        "control_id": variant.control_id,
        "module_id": variant.module_id,
        "kind": variant.kind,
        "label": variant.label,
        "numeric_delta": variant.numeric_delta,
        "justification": variant.justification,
        "changes": [
            {"position": list(point), "state": state}
            for point, state in sorted(variant.changes.items())
        ],
    }


def build_family(
    reference_path: Path,
    divergence_path: Path,
    policy_path: Path,
    output_directory: Path,
    report_out: Path | None,
    repo_root: Path,
) -> dict[str, Any]:
    auditor = load_script(repo_root, "causal_repair_schem_audit", "schem-audit.py")
    module_map = load_script(repo_root, "causal_repair_module_map", "cannon-module-map.py")
    preservation = load_script(repo_root, "causal_repair_preservation", "cannon-preservation-check.py")
    planner = load_script(repo_root, "causal_repair_synthesis_planner", "cannon-synthesis-planner.py")

    policy = load_json_object(policy_path)
    validate_policy(policy)
    divergence_report = load_json_object(divergence_path)
    divergence = first_divergence(divergence_report)
    divergence_kind = str(divergence["kind"])

    reference_path = reference_path.resolve()
    source_sha256 = sha256_file(reference_path)
    if source_sha256 != str(policy["source_sha256"]).lower():
        raise RepairGenerationError(
            f"reference hash mismatch expected={policy['source_sha256']} actual={source_sha256}"
        )
    root_name, root, trailing, _size, source_diagnostics = auditor.load(reference_path)
    if trailing:
        raise RepairGenerationError("reference has trailing NBT bytes")
    decoded = auditor.decode_any(root_name, root)
    blocks, entities, dimensions, data_version = normalize_model(decoded)
    safe_block_entities(entities)
    module_report = module_map.build_report(reference_path)
    if str(module_report.get("file_sha256", "")).lower() != source_sha256:
        raise RepairGenerationError("module map hash does not match reference")

    controls = build_control_variants(
        policy,
        divergence_kind,
        blocks,
        module_report,
        auditor,
    )
    search = policy.get("search") or {}
    max_controls = int(search.get("max_controls_per_candidate", 1))
    max_candidates = int(search.get("max_candidates", 24))
    candidates = generate_candidates(controls, max_controls, max_candidates)
    if not candidates:
        raise RepairGenerationError("bounded repair search produced no candidate changes")

    preserve = preservation_policy(policy)
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    candidate_rows = []
    rejected_rows = []
    output_hashes = set()
    for rank, candidate in enumerate(candidates, start=1):
        model = candidate_model(
            blocks,
            entities,
            dimensions,
            data_version,
            candidate.changes,
        )
        candidate_path = output_directory / f"{rank:03d}-{candidate.candidate_id}.schem"
        auditor.write_sponge_v2(candidate_path, model, data_version)
        verification = verify_candidate_output(candidate_path, model, auditor, data_version)
        if verification["sha256"] in output_hashes:
            candidate_path.unlink(missing_ok=True)
            continue
        output_hashes.add(verification["sha256"])
        scan = dispenser_scan(model["blocks"], planner, preserve["chunk_limit"])
        if scan["safe_alignment_count"] == 0:
            rejected_rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "reason": "no safe EC160 alignment",
                    "chunk_scan": scan,
                }
            )
            candidate_path.unlink(missing_ok=True)
            continue
        preservation_report = preservation.build_report(
            reference_path,
            candidate_path,
            chunk_limit=preserve["chunk_limit"],
            max_structural_change_ratio=preserve["max_structural_change_ratio"],
            max_functional_change_ratio=preserve["max_functional_change_ratio"],
            max_modules_touched=preserve["max_modules_touched"],
            max_unexpected_critical_changes=preserve["max_unexpected_critical_changes"],
            allowed_types=set(candidate.allowed_types),
            allowed_modules=set(candidate.allowed_modules),
            allow_dimension_change=preserve["allow_dimension_change"],
            allow_block_entity_topology_change=preserve["allow_block_entity_topology_change"],
            allow_ambiguous_alignment=preserve["allow_ambiguous_alignment"],
            minimum_alignment_confidence=preserve["minimum_alignment_confidence"],
            alignment_mode=preserve["alignment_mode"],
        )
        if preservation_report["status"] != "PASS":
            rejected_rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "reason": "preservation gate failed",
                    "failures": preservation_report.get("failures") or [],
                    "summary": preservation_report.get("summary") or {},
                }
            )
            candidate_path.unlink(missing_ok=True)
            continue
        manifest_path = candidate_path.with_suffix(".candidate.json")
        row = {
            "rank": len(candidate_rows) + 1,
            "candidate_id": candidate.candidate_id,
            "schematic": {
                "path": str(candidate_path),
                **verification,
            },
            "trigger": divergence,
            "controls": [control_to_json(variant) for variant in candidate.variants],
            "changed_positions": len(candidate.changes),
            "numeric_delta": candidate.numeric_delta,
            "allowed_modules": sorted(candidate.allowed_modules),
            "allowed_types": sorted(candidate.allowed_types),
            "chunk_scan": scan,
            "preservation": {
                "status": preservation_report["status"],
                "summary": preservation_report["summary"],
                "failures": preservation_report["failures"],
            },
            "promotion": "STATIC_REPAIR_CANDIDATE_ONLY",
        }
        write_json(manifest_path, row)
        row["candidate_manifest"] = str(manifest_path)
        candidate_rows.append(row)
    if not candidate_rows:
        raise RepairGenerationError(
            f"all {len(candidates)} generated repairs failed EC160 or preservation gates"
        )

    family = {
        "schema_version": 1,
        "status": "PASS",
        "promotion": "GENERATED_BOUNDED_REPAIR_FAMILY",
        "reference": {
            "path": str(reference_path),
            "sha256": source_sha256,
            "format": decoded.get("format"),
            "data_version": data_version,
            "dimensions": list(dimensions),
            "container_diagnostics": source_diagnostics,
        },
        "divergence": divergence,
        "policy": {
            "path": str(policy_path.resolve()),
            "id": policy.get("id"),
            "matching_controls": [str(raw[0]["id"]) for raw in controls],
            "max_controls_per_candidate": max_controls,
            "max_candidates": max_candidates,
            "preservation": preserve,
        },
        "summary": {
            "generated_combinations": len(candidates),
            "accepted_candidates": len(candidate_rows),
            "rejected_candidates": len(rejected_rows),
        },
        "candidates": candidate_rows,
        "rejected": rejected_rows,
        "next_required": [
            "run each candidate through the exact same CannonLab scenario as the reference",
            "build causal and impulse traces for every candidate",
            "use analyze-repair-family.py to rank runtime evidence and protected-module drift",
            "promote only a runtime-tested Pareto candidate",
            "complete a controlled live ExtremeCraft canary before any EC-ready claim",
        ],
        "truth_boundary": {
            "first_divergence_used_as_search_trigger": True,
            "repair_controls_are_predeclared_and_bounded": True,
            "random_broad_geometry_generation_used": False,
            "all_candidates_roundtrip_geometry_verified": True,
            "all_accepted_candidates_pass_preservation": True,
            "runtime_improvement_confirmed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }
    write_json(output_directory / "repair-family.json", family)
    if report_out is not None:
        write_json(report_out.resolve(), family)
    return family


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a bounded repair family from the first causal/impulse divergence using only predeclared controls"
        )
    )
    parser.add_argument("reference", type=Path)
    parser.add_argument("divergence", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    try:
        report = build_family(
            args.reference,
            args.divergence,
            args.policy,
            args.output_directory,
            args.json_out,
            args.repo_root.resolve(),
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, RepairGenerationError, ValueError) as exc:
        failure = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "runtime_improvement_confirmed": False,
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
