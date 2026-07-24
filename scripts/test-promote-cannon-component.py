#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMOTION = load_script("test_component_promotion", REPO_ROOT / "scripts" / "promote-cannon-component.py")
AUDIT = load_script("test_component_promotion_audit", REPO_ROOT / "scripts" / "schem-audit.py")
MODULE_MAP = load_script("test_component_promotion_module_map", REPO_ROOT / "scripts" / "cannon-module-map.py")
PLANNER = load_script("test_component_promotion_planner", REPO_ROOT / "scripts" / "cannon-synthesis-planner.py")

TRACE_COLUMNS = [
    "tick",
    "server_tick",
    "sequence",
    "event",
    "component_id",
    "block_type",
    "world_x",
    "world_y",
    "world_z",
    "relative_x",
    "relative_y",
    "relative_z",
    "old_power",
    "new_power",
    "direction",
    "moved_blocks",
    "item",
    "entity_uuid",
    "entity_type",
    "vx",
    "vy",
    "vz",
    "fuse",
    "details",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_schematic(
    path: Path,
    dimensions: tuple[int, int, int],
    occupied: dict[tuple[int, int, int], str],
) -> None:
    width, height, length = dimensions
    blocks = {
        (x, y, z): occupied.get((x, y, z), "minecraft:air")
        for y in range(height)
        for z in range(length)
        for x in range(width)
    }
    block_entities = [
        {
            "pos": pos,
            "id": "minecraft:dispenser",
            "raw": {"Id": "minecraft:dispenser", "Pos": list(pos)},
        }
        for pos, state in occupied.items()
        if state.startswith("minecraft:dispenser")
    ]
    AUDIT.write_sponge_v2(
        path,
        {
            "format": "sponge-v2",
            "version": 2,
            "data_version": 3465,
            "blocks": blocks,
            "block_entities": block_entities,
            "source_dimensions": {
                "width": width,
                "height": height,
                "length": length,
            },
        },
        3465,
    )


def write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACE_COLUMNS)
        writer.writeheader()
        for index, raw in enumerate(rows, start=1):
            row = {column: "" for column in TRACE_COLUMNS}
            row.update(raw)
            row.setdefault("sequence", index)
            writer.writerow(row)


def standard_source(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    source = root / "source.schem"
    occupied = {
        (0, 0, 1): "minecraft:stone",
        (1, 0, 1): "minecraft:stone",
        (2, 0, 1): "minecraft:stone",
        (0, 1, 1): "minecraft:stone_button[face=wall,facing=west,powered=false]",
        (1, 1, 1): "minecraft:repeater[delay=1,facing=east,locked=false,powered=false]",
        (2, 1, 1): "minecraft:dispenser[facing=east,triggered=false]",
        (25, 0, 1): "minecraft:stone",
        (25, 1, 1): "minecraft:dispenser[facing=west,triggered=false]",
    }
    write_schematic(source, (30, 3, 3), occupied)
    report = MODULE_MAP.build_report(source)
    modules = report["modules"]
    first = min(modules, key=lambda row: row["bounds"]["min"][0])
    second = max(modules, key=lambda row: row["bounds"]["min"][0])
    assert first["module_id"] != second["module_id"], modules
    return source, first, second


def active_trace(path: Path, dispenser_x: int = 2) -> None:
    write_trace(
        path,
        [
            {
                "tick": 0,
                "sequence": 1,
                "event": "FIRE_INPUT",
                "component_id": "C[0,1,1]",
                "relative_x": 0,
                "relative_y": 1,
                "relative_z": 1,
            },
            {
                "tick": 1,
                "sequence": 2,
                "event": "REDSTONE_CHANGE",
                "component_id": "R[1,1,1]",
                "relative_x": 1,
                "relative_y": 1,
                "relative_z": 1,
                "old_power": 0,
                "new_power": 15,
            },
            {
                "tick": 2,
                "sequence": 3,
                "event": "DISPENSE",
                "component_id": f"D[{dispenser_x},1,1]",
                "relative_x": dispenser_x,
                "relative_y": 1,
                "relative_z": 1,
                "item": "TNT",
            },
            {
                "tick": 2,
                "sequence": 4,
                "event": "ENTITY_ADD",
                "relative_x": dispenser_x + 0.5,
                "relative_y": 1.5,
                "relative_z": 1.5,
                "entity_uuid": "TNT-1",
                "entity_type": "PRIMED_TNT",
                "vx": 0,
                "vy": 0,
                "vz": 0,
                "fuse": 79,
            },
            {
                "tick": 81,
                "sequence": 5,
                "event": "EXPLOSION",
                "relative_x": dispenser_x + 0.5,
                "relative_y": 1.5,
                "relative_z": 1.5,
                "entity_uuid": "TNT-1",
                "entity_type": "PRIMED_TNT",
            },
        ],
    )


def manifest_for(
    source: Path,
    module: dict[str, Any],
    *,
    evidence_level: str = "local-runtime",
    capability_evidence: str | None = None,
    padding: list[int] | None = None,
) -> dict[str, Any]:
    capability_level = capability_evidence or evidence_level
    return {
        "schema_version": 1,
        "id": "synthetic-promotion",
        "source": {"sha256": digest(source)},
        "component": {
            "id": "promoted-control-charge",
            "version": "1",
            "reusable": False,
            "source_kind": "synthetic-regression",
        },
        "selection": {
            "module_id": module["module_id"],
            "expected_signature": module["signature"],
            "padding": padding if padding is not None else [0, 1, 0],
        },
        "evidence": {
            "level": evidence_level,
            "sources": ["synthetic causal trace fixture"],
            "runtime_requirements": {
                "require_active": True,
                "min_exclusive_component_events": 1,
                "min_correlated_entities": 1,
                "min_entity_profile_coverage": 1.0,
            },
        },
        "capabilities": [
            {
                "id": "source-accounted-tnt-stage",
                "evidence": capability_level,
                "justification": "Exclusive mapped dispense event and unambiguous correlated TNT entity in the supplied trace.",
            }
        ],
        "ports": [
            {
                "id": "signal-in",
                "kind": "input",
                "medium": "redstone",
                "source_position": [0, 1, 1],
                "direction": [-1, 0, 0],
                "contract": {"pulse_ticks": 4},
            },
            {
                "id": "entity-out",
                "kind": "output",
                "medium": "tnt-entity",
                "source_position": [2, 1, 1],
                "direction": [1, 0, 0],
                "contract": {"entity": "primed_tnt"},
            },
        ],
        "boundary": {"allowed_crossings": []},
    }


def run(
    root: Path,
    source: Path,
    module: dict[str, Any],
    trace: Path | None,
    manifest_payload: dict[str, Any] | None = None,
    suffix: str = "one",
) -> dict[str, Any]:
    manifest = root / f"manifest-{suffix}.json"
    write_json(manifest, manifest_payload or manifest_for(source, module))
    return PROMOTION.run_promotion(
        source,
        manifest,
        trace,
        root / f"component-{suffix}.schem",
        root / f"registry-{suffix}.json",
        root / f"report-{suffix}.json",
        REPO_ROOT,
        None,
    )


def test_runtime_promotion_roundtrips_and_feeds_planner() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source, module, _second = standard_source(root)
        trace = root / "trace.csv"
        active_trace(trace)
        first = run(root, source, module, trace, suffix="a")
        second = run(root, source, module, trace, suffix="b")
        assert first["status"] == "PASS"
        assert first["promotion"] == "PROMOTED_COMPONENT_CANDIDATE"
        assert first["evidence"]["runtime"]["exclusive_component_events"] >= 1
        assert first["evidence"]["runtime"]["correlated_entities"] == 1
        assert first["output"]["geometry_verified"] is True
        assert first["registry"]["validated_by_synthesis_planner"] is True
        assert first["output"]["sha256"] == second["output"]["sha256"]
        assert (root / "component-a.schem").read_bytes() == (root / "component-b.schem").read_bytes()
        registry = PLANNER.load_registry(root / "registry-a.json", AUDIT)
        assert set(registry) == {"promoted-control-charge"}
        assert first["truth_boundary"]["standalone_runtime_compatibility_confirmed"] is False
        assert first["truth_boundary"]["ec_ready"] is False


def test_source_hash_drift_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source, module, _second = standard_source(root)
        trace = root / "trace.csv"
        active_trace(trace)
        manifest = manifest_for(source, module)
        manifest["source"]["sha256"] = "0" * 64
        try:
            run(root, source, module, trace, manifest, "hash")
        except PROMOTION.PromotionError as exc:
            assert "source hash mismatch" in str(exc)
        else:
            raise AssertionError("source hash drift must fail")


def test_runtime_inactive_module_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source, first, second = standard_source(root)
        trace = root / "trace.csv"
        active_trace(trace, dispenser_x=25)
        try:
            run(root, source, first, trace, suffix="inactive")
        except PROMOTION.PromotionError as exc:
            assert "runtime promotion gate failed" in str(exc)
        else:
            raise AssertionError("inactive module must not receive local-runtime promotion")
        assert second["module_id"] != first["module_id"]


def test_capability_cannot_exceed_component_evidence() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source, module, _second = standard_source(root)
        manifest = manifest_for(
            source,
            module,
            evidence_level="static",
            capability_evidence="local-runtime",
        )
        manifest["evidence"].pop("runtime_requirements", None)
        try:
            run(root, source, module, None, manifest, "evidence")
        except PROMOTION.PromotionError as exc:
            assert "evidence exceeds component" in str(exc)
        else:
            raise AssertionError("capability evidence escalation must fail")


def test_field_verified_requires_exact_field_record() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source, module, _second = standard_source(root)
        trace = root / "trace.csv"
        active_trace(trace)
        manifest = manifest_for(source, module, evidence_level="field-verified")
        try:
            run(root, source, module, trace, manifest, "field")
        except PROMOTION.PromotionError as exc:
            assert "field_record" in str(exc)
        else:
            raise AssertionError("field-verified promotion without field record must fail")


def test_unreviewed_functional_boundary_cut_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "boundary.schem"
        occupied = {
            (0, 0, 0): "minecraft:stone",
            (1, 0, 0): "minecraft:stone",
            (0, 1, 0): "minecraft:dispenser[facing=east,triggered=false]",
            (1, 1, 0): "minecraft:dispenser[facing=west,triggered=false]",
        }
        write_schematic(source, (3, 3, 2), occupied)
        module_report = MODULE_MAP.build_report(source)
        modules = module_report["modules"]
        assert len(modules) >= 2, modules
        module = min(modules, key=lambda row: row["bounds"]["min"][0])
        manifest = {
            "schema_version": 1,
            "source": {"sha256": digest(source)},
            "component": {"id": "cut-module", "version": "1"},
            "selection": {
                "module_id": module["module_id"],
                "expected_signature": module["signature"],
                "padding": [0, 1, 0],
            },
            "evidence": {"level": "static", "sources": ["synthetic static map"]},
            "capabilities": [
                {
                    "id": "reviewed-static-bank",
                    "evidence": "static",
                    "justification": "Exact selected dispenser-bank geometry only.",
                }
            ],
            "ports": [
                {
                    "id": "top",
                    "kind": "output",
                    "medium": "review",
                    "source_position": module["component_positions"][0],
                    "direction": [0, 1, 0],
                    "contract": {},
                }
            ],
            "boundary": {"allowed_crossings": []},
        }
        try:
            run(root, source, module, None, manifest, "boundary")
        except PROMOTION.PromotionError as exc:
            assert "unreviewed functional boundary crossings" in str(exc)
        else:
            raise AssertionError("functional boundary cut must fail")


def main() -> None:
    tests = [
        test_runtime_promotion_roundtrips_and_feeds_planner,
        test_source_hash_drift_fails,
        test_runtime_inactive_module_fails,
        test_capability_cannot_exceed_component_evidence,
        test_field_verified_requires_exact_field_record,
        test_unreviewed_functional_boundary_cut_fails,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} component promotion regressions passed.")


if __name__ == "__main__":
    main()
