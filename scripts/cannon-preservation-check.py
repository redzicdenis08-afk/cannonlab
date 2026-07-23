#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
FUNCTIONAL_TYPES = {
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:redstone_wire",
    "minecraft:repeater",
    "minecraft:comparator",
    "minecraft:observer",
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:slime_block",
    "minecraft:honey_block",
    "minecraft:redstone_block",
    "minecraft:redstone_torch",
    "minecraft:redstone_wall_torch",
    "minecraft:tripwire",
    "minecraft:tripwire_hook",
    "minecraft:lever",
    "minecraft:stone_button",
    "minecraft:polished_blackstone_button",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:soul_sand",
    "minecraft:sand",
    "minecraft:red_sand",
    "minecraft:gravel",
    "minecraft:anvil",
    "minecraft:chipped_anvil",
    "minecraft:damaged_anvil",
    "minecraft:piston_head",
    "minecraft:moving_piston",
    "minecraft:note_block",
    "minecraft:target",
    "minecraft:redstone_lamp",
    "minecraft:scaffolding",
    "minecraft:rail",
    "minecraft:detector_rail",
    "minecraft:activator_rail",
    "minecraft:powered_rail",
}
CRITICAL_TYPES = {
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:redstone_wire",
    "minecraft:repeater",
    "minecraft:comparator",
    "minecraft:observer",
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:redstone_block",
    "minecraft:redstone_torch",
    "minecraft:redstone_wall_torch",
    "minecraft:lever",
    "minecraft:stone_button",
    "minecraft:polished_blackstone_button",
    "minecraft:water",
    "minecraft:lava",
}
CONTROL_SUFFIXES = ("_button", "_pressure_plate")
_SCRIPT_CACHE: dict[str, Any] = {}
_MODEL_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
FUNCTIONAL_SUFFIXES = (
    "_button",
    "_pressure_plate",
    "_trapdoor",
    "_fence_gate",
    "_concrete_powder",
)
VOLATILE_PROPERTIES = {"power", "powered", "triggered", "lit"}


def load_script(name: str, filename: str) -> Any:
    cached = _SCRIPT_CACHE.get(filename)
    if cached is not None:
        return cached
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _SCRIPT_CACHE[filename] = module
    return module


def is_control(block_type: str) -> bool:
    return block_type == "minecraft:lever" or block_type.endswith(CONTROL_SUFFIXES)


def is_functional_type(block_type: str) -> bool:
    return block_type in FUNCTIONAL_TYPES or block_type.endswith(FUNCTIONAL_SUFFIXES)


def is_critical_type(block_type: str) -> bool:
    return block_type in CRITICAL_TYPES or is_functional_type(block_type)


def canonical_state(auditor: Any, state: str) -> str:
    block_type = auditor.base(state)
    props = {
        key: value
        for key, value in auditor.properties(state).items()
        if key not in VOLATILE_PROPERTIES
    }
    if not props:
        return block_type
    return block_type + "[" + ",".join(f"{key}={props[key]}" for key in sorted(props)) + "]"


def non_air_blocks(auditor: Any, blocks: dict[tuple[int, int, int], str]) -> dict[tuple[int, int, int], str]:
    return {
        point: state
        for point, state in blocks.items()
        if auditor.base(state) not in AIR
    }


def block_bounds(blocks: dict[tuple[int, int, int], str]) -> dict[str, list[int]] | None:
    if not blocks:
        return None
    points = list(blocks)
    return {
        "min": [min(point[axis] for point in points) for axis in range(3)],
        "max": [max(point[axis] for point in points) for axis in range(3)],
    }


def translated_point(
    point: tuple[int, int, int],
    translation: tuple[int, int, int],
) -> tuple[int, int, int]:
    return tuple(point[axis] + translation[axis] for axis in range(3))


def translate_blocks(
    blocks: dict[tuple[int, int, int], str],
    translation: tuple[int, int, int],
) -> dict[tuple[int, int, int], str]:
    return {
        translated_point(point, translation): state
        for point, state in blocks.items()
    }


def alignment_anchor_blocks(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
) -> dict[str, list[tuple[int, int, int]]]:
    output: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for point, state in blocks.items():
        block_type = auditor.base(state)
        if not is_critical_type(block_type):
            continue
        output[canonical_state(auditor, state)].append(point)
    return dict(output)


def translation_score(
    auditor: Any,
    reference_blocks: dict[tuple[int, int, int], str],
    candidate_blocks: dict[tuple[int, int, int], str],
    translation: tuple[int, int, int],
) -> dict[str, Any]:
    exact_non_air = 0
    exact_functional = 0
    exact_critical = 0
    candidate_functional = 0
    candidate_critical = 0
    for point, candidate_state in candidate_blocks.items():
        aligned = translated_point(point, translation)
        reference_state = reference_blocks.get(aligned, "minecraft:air")
        candidate_type = auditor.base(candidate_state)
        is_functional = is_functional_type(candidate_type)
        is_critical = is_critical_type(candidate_type)
        candidate_functional += int(is_functional)
        candidate_critical += int(is_critical)
        if canonical_state(auditor, reference_state) != canonical_state(auditor, candidate_state):
            continue
        exact_non_air += 1
        exact_functional += int(is_functional)
        exact_critical += int(is_critical)
    return {
        "translation": list(translation),
        "exact_non_air": exact_non_air,
        "exact_functional": exact_functional,
        "exact_critical": exact_critical,
        "candidate_non_air": len(candidate_blocks),
        "candidate_functional": candidate_functional,
        "candidate_critical": candidate_critical,
        "non_air_coverage": round(exact_non_air / max(1, len(candidate_blocks)), 8),
        "functional_coverage": round(exact_functional / max(1, candidate_functional), 8),
        "critical_coverage": round(exact_critical / max(1, candidate_critical), 8),
        "translation_magnitude": sum(abs(value) for value in translation),
    }


def alignment_candidates(
    auditor: Any,
    reference_blocks: dict[tuple[int, int, int], str],
    candidate_blocks: dict[tuple[int, int, int], str],
) -> set[tuple[int, int, int]]:
    candidates: set[tuple[int, int, int]] = {(0, 0, 0)}
    reference_bounds = block_bounds(reference_blocks)
    candidate_bounds = block_bounds(candidate_blocks)
    if reference_bounds and candidate_bounds:
        candidates.add(tuple(
            reference_bounds["min"][axis] - candidate_bounds["min"][axis]
            for axis in range(3)
        ))

    reference_functional = {
        point: state
        for point, state in reference_blocks.items()
        if is_functional_type(auditor.base(state))
    }
    candidate_functional = {
        point: state
        for point, state in candidate_blocks.items()
        if is_functional_type(auditor.base(state))
    }
    reference_functional_bounds = block_bounds(reference_functional)
    candidate_functional_bounds = block_bounds(candidate_functional)
    if reference_functional_bounds and candidate_functional_bounds:
        candidates.add(tuple(
            reference_functional_bounds["min"][axis]
            - candidate_functional_bounds["min"][axis]
            for axis in range(3)
        ))

    reference_anchors = alignment_anchor_blocks(auditor, reference_blocks)
    candidate_anchors = alignment_anchor_blocks(auditor, candidate_blocks)
    vote_counts: Counter[tuple[int, int, int]] = Counter()
    shared_states = sorted(
        set(reference_anchors) & set(candidate_anchors),
        key=lambda state: (
            len(reference_anchors[state]) * len(candidate_anchors[state]),
            state,
        ),
    )
    pair_budget = 25_000
    pairs_used = 0
    for state in shared_states:
        reference_points = reference_anchors[state]
        candidate_points = candidate_anchors[state]
        pair_count = len(reference_points) * len(candidate_points)
        if pair_count > 2_500 or pairs_used + pair_count > pair_budget:
            continue
        for reference_point in reference_points:
            for candidate_point in candidate_points:
                vote_counts[tuple(
                    reference_point[axis] - candidate_point[axis]
                    for axis in range(3)
                )] += 1
        pairs_used += pair_count
    candidates.update(
        translation
        for translation, _votes in vote_counts.most_common(128)
    )
    return candidates


def choose_translation(
    auditor: Any,
    reference_blocks: dict[tuple[int, int, int], str],
    candidate_blocks: dict[tuple[int, int, int], str],
    alignment_mode: str,
) -> dict[str, Any]:
    if alignment_mode not in {"exact", "translate"}:
        raise ValueError("alignment_mode must be exact or translate")
    candidates = (
        {(0, 0, 0)}
        if alignment_mode == "exact"
        else alignment_candidates(auditor, reference_blocks, candidate_blocks)
    )
    scores = [
        translation_score(
            auditor,
            reference_blocks,
            candidate_blocks,
            translation,
        )
        for translation in sorted(candidates)
    ]
    scores.sort(
        key=lambda row: (
            -int(row["exact_critical"]),
            -int(row["exact_functional"]),
            -int(row["exact_non_air"]),
            int(row["translation_magnitude"]),
            tuple(row["translation"]),
        )
    )
    best = scores[0]
    best_key = (
        best["exact_critical"],
        best["exact_functional"],
        best["exact_non_air"],
    )
    equally_scored = [
        row
        for row in scores
        if (
            row["exact_critical"],
            row["exact_functional"],
            row["exact_non_air"],
        ) == best_key
    ]
    confidence = (
        "high"
        if best["critical_coverage"] >= 0.95 and best["functional_coverage"] >= 0.95
        else "medium"
        if best["critical_coverage"] >= 0.70 or best["functional_coverage"] >= 0.70
        else "low"
    )
    return {
        "mode": alignment_mode,
        "selected_translation": best["translation"],
        "confidence": confidence,
        "ambiguous_best_score": len(equally_scored) > 1,
        "equally_scored_translations": [row["translation"] for row in equally_scored[:16]],
        "selected_score": best,
        "top_candidates": scores[:16],
        "candidate_count": len(scores),
        "note": (
            "Translation aligns schematic coordinate frames only. Rotation, reflection, scaling, and local warping are never allowed."
        ),
    }


def point_in_expanded_bounds(point: tuple[int, int, int], box: dict[str, Any] | None, radius: int = 2) -> bool:
    if not box:
        return False
    return all(
        box["min"][axis] - radius <= point[axis] <= box["max"][axis] + radius
        for axis in range(3)
    )


def module_position_index(module_report: dict[str, Any]) -> tuple[dict[tuple[int, int, int], set[str]], list[dict[str, Any]]]:
    exact: dict[tuple[int, int, int], set[str]] = defaultdict(set)
    modules = module_report.get("modules") or []
    for module in modules:
        module_id = str(module.get("module_id"))
        for raw in module.get("component_positions") or []:
            exact[tuple(map(int, raw))].add(module_id)
    for shared in module_report.get("shared_component_assignments") or []:
        raw = shared.get("pos") or []
        if len(raw) < 3:
            continue
        point = tuple(map(int, raw[:3]))
        exact[point].update(
            str(value)
            for value in shared.get("candidate_module_ids") or []
        )
    return exact, modules


def impacted_modules_for_point(
    point: tuple[int, int, int],
    exact: dict[tuple[int, int, int], set[str]],
    modules: list[dict[str, Any]],
) -> list[str]:
    if point in exact:
        return sorted(exact[point])
    nearby = [
        str(module.get("module_id"))
        for module in modules
        if point_in_expanded_bounds(point, module.get("bounds"), 2)
    ]
    return sorted(set(nearby))


def load_model(auditor: Any, path: Path) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    cache_key = (str(path), int(stat.st_size), int(stat.st_mtime_ns))
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    root_name, root, trailing, decoded_size, container_diagnostics = auditor.load(path)
    model = auditor.decode_any(root_name, root)
    model["_trailing_bytes"] = len(trailing)
    model["_decoded_bytes"] = decoded_size
    model["_container_diagnostics"] = container_diagnostics
    _MODEL_CACHE[cache_key] = model
    return copy.deepcopy(model)


def normalize_block_entity_id(value: Any) -> str:
    entity_id = str(value or "unknown").lower()
    if entity_id != "unknown" and ":" not in entity_id:
        entity_id = "minecraft:" + entity_id
    return entity_id


def block_entity_topology(
    model: dict[str, Any],
    translation: tuple[int, int, int] = (0, 0, 0),
) -> Counter[tuple[int, int, int, str]]:
    topology: Counter[tuple[int, int, int, str]] = Counter()
    for entity in model.get("block_entities") or []:
        raw_pos = entity.get("pos")
        if not isinstance(raw_pos, (list, tuple)) or len(raw_pos) < 3:
            continue
        point = translated_point(tuple(map(int, raw_pos[:3])), translation)
        topology[(*point, normalize_block_entity_id(entity.get("id")))] += 1
    return topology


def block_entity_inventory_summary(model: dict[str, Any]) -> dict[str, int]:
    entities = list(model.get("block_entities") or [])
    nonempty = 0
    item_entries = 0
    for entity in entities:
        raw = entity.get("raw") or {}
        items = raw.get("Items", raw.get("items", []))
        if isinstance(items, list) and items:
            nonempty += 1
            item_entries += len(items)
    return {
        "explicit_block_entities": len(entities),
        "nonempty_inventory_entities": nonempty,
        "inventory_item_entries": item_entries,
    }


def topology_rows(counter: Counter[tuple[int, int, int, str]]) -> list[dict[str, Any]]:
    return [
        {"pos": [x, y, z], "id": entity_id, "count": count}
        for (x, y, z, entity_id), count in sorted(counter.items())
    ]


def control_signature(auditor: Any, blocks: dict[tuple[int, int, int], str]) -> list[list[Any]]:
    return [
        [*point, canonical_state(auditor, state)]
        for point, state in sorted(blocks.items())
        if is_control(auditor.base(state))
    ]


def dispenser_bank_signature(module_report: dict[str, Any]) -> list[list[Any]]:
    signature = []
    for module in module_report.get("modules") or []:
        if module.get("kind") != "bank-centric":
            continue
        dimensions = (module.get("seed_bank_bounds") or {}).get("dimensions") or {}
        signature.append([
            module.get("seed_dispenser_count"),
            module.get("seed_facing"),
            module.get("seed_bank_shape"),
            dimensions.get("x"),
            dimensions.get("y"),
            dimensions.get("z"),
        ])
    return sorted(signature)


def classify_edit(structural_changes: int, structural_ratio: float, modules_touched: int, unexpected_critical: int) -> str:
    if structural_changes == 0:
        return "exact-structural-clone"
    if structural_ratio <= 0.03 and modules_touched <= 1 and unexpected_critical == 0:
        return "bounded-module-edit"
    if structural_ratio <= 0.15 and modules_touched <= 3:
        return "multi-module-rearchitecture"
    return "destructive-or-unbounded-rebuild"


def build_report(
    reference_path: Path,
    candidate_path: Path,
    *,
    chunk_limit: int = 160,
    max_structural_change_ratio: float = 0.03,
    max_functional_change_ratio: float = 0.05,
    max_modules_touched: int = 1,
    max_unexpected_critical_changes: int = 0,
    allowed_types: set[str] | None = None,
    allowed_modules: set[str] | None = None,
    allow_dimension_change: bool = False,
    allow_block_entity_topology_change: bool = False,
    allow_ambiguous_alignment: bool = False,
    minimum_alignment_confidence: str = "medium",
    alignment_mode: str = "translate",
) -> dict[str, Any]:
    allowed_types = set(allowed_types or set())
    allowed_modules = set(allowed_modules or set())
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    if minimum_alignment_confidence not in confidence_rank:
        raise ValueError("minimum_alignment_confidence must be low, medium, or high")
    auditor = load_script("cannonlab_schem_audit", "schem-audit.py")
    module_map = load_script("cannonlab_module_map", "cannon-module-map.py")

    reference_model = load_model(auditor, reference_path)
    candidate_model = load_model(auditor, candidate_path)
    reference_blocks = non_air_blocks(auditor, reference_model["blocks"])
    raw_candidate_blocks = non_air_blocks(auditor, candidate_model["blocks"])
    alignment = choose_translation(
        auditor,
        reference_blocks,
        raw_candidate_blocks,
        alignment_mode,
    )
    selected_translation = tuple(map(int, alignment["selected_translation"]))
    candidate_blocks = translate_blocks(raw_candidate_blocks, selected_translation)
    reference_modules = module_map.build_report(reference_path, chunk_limit)
    candidate_modules = module_map.build_report(candidate_path, chunk_limit)
    exact_module_index, module_rows = module_position_index(reference_modules)

    exact_state_changes = 0
    structural_changes: list[dict[str, Any]] = []
    changed_type_counts: Counter[str] = Counter()
    impacted_module_counts: Counter[str] = Counter()
    outside_module_changes = 0
    critical_changes = 0
    unexpected_critical_changes = 0
    functional_changes = 0
    fluid_changes = 0
    control_changes = 0

    for point in sorted(set(reference_blocks) | set(candidate_blocks)):
        before = reference_blocks.get(point, "minecraft:air")
        after = candidate_blocks.get(point, "minecraft:air")
        if before == after:
            continue
        exact_state_changes += 1
        before_canonical = canonical_state(auditor, before)
        after_canonical = canonical_state(auditor, after)
        if before_canonical == after_canonical:
            continue

        before_type = auditor.base(before)
        after_type = auditor.base(after)
        if before_type in AIR:
            kind = "added"
        elif after_type in AIR:
            kind = "removed"
        else:
            kind = "changed"
        changed_types = {value for value in (before_type, after_type) if value not in AIR}
        modules = impacted_modules_for_point(point, exact_module_index, module_rows)
        if modules:
            for module_id in modules:
                impacted_module_counts[module_id] += 1
        else:
            outside_module_changes += 1

        is_critical = any(is_critical_type(value) for value in changed_types)
        is_allowed_type = bool(changed_types) and changed_types.issubset(allowed_types)
        if is_critical:
            critical_changes += 1
            if not is_allowed_type:
                unexpected_critical_changes += 1
        if any(is_functional_type(value) for value in changed_types):
            functional_changes += 1
        if changed_types & {"minecraft:water", "minecraft:lava"}:
            fluid_changes += 1
        if any(is_control(value) for value in changed_types):
            control_changes += 1
        for value in changed_types:
            changed_type_counts[value] += 1

        structural_changes.append({
            "pos": list(point),
            "kind": kind,
            "before": before,
            "after": after,
            "before_canonical": before_canonical,
            "after_canonical": after_canonical,
            "changed_types": sorted(changed_types),
            "critical": is_critical,
            "allowed_by_type": is_allowed_type,
            "impacted_modules": modules,
        })

    reference_non_air = len(reference_blocks)
    reference_functional = sum(
        1 for state in reference_blocks.values() if is_functional_type(auditor.base(state))
    )
    structural_ratio = len(structural_changes) / max(1, reference_non_air)
    functional_ratio = functional_changes / max(1, reference_functional)
    impacted_modules = sorted(impacted_module_counts)
    disallowed_modules = sorted(set(impacted_modules) - allowed_modules) if allowed_modules else []

    dimensions_changed = reference_model["source_dimensions"] != candidate_model["source_dimensions"]
    controls_changed = control_signature(auditor, reference_blocks) != control_signature(auditor, candidate_blocks)
    bank_topology_changed = dispenser_bank_signature(reference_modules) != dispenser_bank_signature(candidate_modules)
    reference_block_entities = block_entity_topology(reference_model)
    candidate_block_entities = block_entity_topology(candidate_model, selected_translation)
    removed_block_entities = reference_block_entities - candidate_block_entities
    added_block_entities = candidate_block_entities - reference_block_entities
    block_entity_topology_changed = bool(removed_block_entities or added_block_entities)
    reference_inventory = block_entity_inventory_summary(reference_model)
    candidate_inventory = block_entity_inventory_summary(candidate_model)

    failures: list[str] = []
    if (
        alignment_mode == "translate"
        and alignment.get("ambiguous_best_score")
        and not allow_ambiguous_alignment
    ):
        failures.append("ambiguous_alignment")
    if confidence_rank.get(str(alignment.get("confidence")), -1) < confidence_rank[minimum_alignment_confidence]:
        failures.append("alignment_confidence_below_minimum")
    if dimensions_changed and not allow_dimension_change:
        failures.append("source_dimensions_changed")
    if block_entity_topology_changed and not allow_block_entity_topology_change:
        failures.append("block_entity_topology_changed")
    if structural_ratio > max_structural_change_ratio:
        failures.append("structural_change_ratio_exceeded")
    if functional_ratio > max_functional_change_ratio:
        failures.append("functional_change_ratio_exceeded")
    if len(impacted_modules) > max_modules_touched:
        failures.append("modules_touched_exceeded")
    if unexpected_critical_changes > max_unexpected_critical_changes:
        failures.append("unexpected_critical_changes_exceeded")
    if allowed_modules and disallowed_modules:
        failures.append("changes_outside_allowed_modules")
    if allowed_modules and outside_module_changes:
        failures.append("changes_outside_reference_modules")
    if controls_changed and not any(is_control(value) for value in allowed_types):
        failures.append("operator_controls_changed")
    if bank_topology_changed and "minecraft:dispenser" not in allowed_types:
        failures.append("dispenser_bank_topology_changed")

    risk_score = min(100, round(
        structural_ratio * 250
        + functional_ratio * 300
        + unexpected_critical_changes * 5
        + max(0, len(impacted_modules) - 1) * 12
        + outside_module_changes * 2
        + control_changes * 12
        + fluid_changes * 4
        + (20 if dimensions_changed else 0)
        + (15 if bank_topology_changed else 0)
        + min(30, 8 * (sum(removed_block_entities.values()) + sum(added_block_entities.values())))
    ))
    risk_level = "low" if risk_score <= 20 else "medium" if risk_score <= 50 else "high" if risk_score <= 80 else "critical"
    edit_class = classify_edit(
        len(structural_changes),
        structural_ratio,
        len(impacted_modules),
        unexpected_critical_changes,
    )

    report = {
        "status": "PASS" if not failures else "FAIL",
        "schema": "cannonlab-preservation-check-v3",
        "reference": str(reference_path),
        "candidate": str(candidate_path),
        "policy": {
            "chunk_limit": chunk_limit,
            "max_structural_change_ratio": max_structural_change_ratio,
            "max_functional_change_ratio": max_functional_change_ratio,
            "max_modules_touched": max_modules_touched,
            "max_unexpected_critical_changes": max_unexpected_critical_changes,
            "allowed_types": sorted(allowed_types),
            "allowed_modules": sorted(allowed_modules),
            "allow_dimension_change": allow_dimension_change,
            "allow_block_entity_topology_change": allow_block_entity_topology_change,
            "allow_ambiguous_alignment": allow_ambiguous_alignment,
            "minimum_alignment_confidence": minimum_alignment_confidence,
            "alignment_mode": alignment_mode,
        },
        "alignment": alignment,
        "summary": {
            "reference_non_air_blocks": reference_non_air,
            "reference_functional_components": reference_functional,
            "exact_state_changes": exact_state_changes,
            "structural_changes": len(structural_changes),
            "structural_change_ratio": round(structural_ratio, 8),
            "functional_changes": functional_changes,
            "functional_change_ratio": round(functional_ratio, 8),
            "critical_changes": critical_changes,
            "unexpected_critical_changes": unexpected_critical_changes,
            "fluid_changes": fluid_changes,
            "control_changes": control_changes,
            "modules_touched": len(impacted_modules),
            "outside_module_changes": outside_module_changes,
            "dimensions_changed": dimensions_changed,
            "controls_changed": controls_changed,
            "dispenser_bank_topology_changed": bank_topology_changed,
            "block_entity_topology_changed": block_entity_topology_changed,
            "removed_block_entities": sum(removed_block_entities.values()),
            "added_block_entities": sum(added_block_entities.values()),
            "edit_class": edit_class,
            "risk_score": risk_score,
            "risk_level": risk_level,
        },
        "failures": failures,
        "changed_type_counts": dict(sorted(changed_type_counts.items())),
        "impacted_modules": [
            {"module_id": module_id, "change_count": impacted_module_counts[module_id]}
            for module_id in impacted_modules
        ],
        "disallowed_modules": disallowed_modules,
        "changes": structural_changes[:1000],
        "changes_truncated": len(structural_changes) > 1000,
        "block_entity_changes": {
            "removed": topology_rows(removed_block_entities),
            "added": topology_rows(added_block_entities),
            "reference_inventory": reference_inventory,
            "candidate_inventory": candidate_inventory,
            "note": (
                "topology compares explicit block-entity position and ID after global translation; inventory counts are reported but not used as a default failure gate"
            ),
        },
        "reference_architecture": {
            "file_sha256": reference_modules.get("file_sha256"),
            "architecture_summary": reference_modules.get("architecture_summary"),
            "dispenser_bank_signature": dispenser_bank_signature(reference_modules),
            "controls": control_signature(auditor, reference_blocks),
        },
        "candidate_architecture": {
            "file_sha256": candidate_modules.get("file_sha256"),
            "architecture_summary": candidate_modules.get("architecture_summary"),
            "dispenser_bank_signature": dispenser_bank_signature(candidate_modules),
            "controls": control_signature(auditor, candidate_blocks),
        },
        "truth_boundary": (
            "PASS proves only that the decoded candidate stayed inside the declared geometry-preservation policy. "
            "It does not prove redstone timing, TNT cohorts, wall penetration, server parity, or ExtremeCraft readiness."
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject broad or accidental cannon rebuilds by comparing a candidate against its exact reference"
    )
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--max-structural-change-ratio", type=float, default=0.03)
    parser.add_argument("--max-functional-change-ratio", type=float, default=0.05)
    parser.add_argument("--max-modules-touched", type=int, default=1)
    parser.add_argument("--max-unexpected-critical-changes", type=int, default=0)
    parser.add_argument("--allow-type", action="append", default=[])
    parser.add_argument("--allow-module", action="append", default=[])
    parser.add_argument("--allow-dimension-change", action="store_true")
    parser.add_argument("--allow-block-entity-topology-change", action="store_true")
    parser.add_argument("--allow-ambiguous-alignment", action="store_true")
    parser.add_argument(
        "--minimum-alignment-confidence",
        choices=("low", "medium", "high"),
        default="medium",
    )
    parser.add_argument("--alignment-mode", choices=("exact", "translate"), default="translate")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.reference,
        args.candidate,
        chunk_limit=args.chunk_limit,
        max_structural_change_ratio=args.max_structural_change_ratio,
        max_functional_change_ratio=args.max_functional_change_ratio,
        max_modules_touched=args.max_modules_touched,
        max_unexpected_critical_changes=args.max_unexpected_critical_changes,
        allowed_types=set(args.allow_type),
        allowed_modules=set(args.allow_module),
        allow_dimension_change=args.allow_dimension_change,
        allow_block_entity_topology_change=args.allow_block_entity_topology_change,
        allow_ambiguous_alignment=args.allow_ambiguous_alignment,
        minimum_alignment_confidence=args.minimum_alignment_confidence,
        alignment_mode=args.alignment_mode,
    )
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
