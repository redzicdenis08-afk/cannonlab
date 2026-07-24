#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPO_ROOT = Path(__file__).resolve().parents[1]
PLANNER = load_module("cannon_synthesis_planner", REPO_ROOT / "scripts" / "cannon-synthesis-planner.py")
AUDIT = load_module("cannonlab_schem_audit_for_synthesis_test", REPO_ROOT / "scripts" / "schem-audit.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_schematic(
    path: Path,
    dimensions: tuple[int, int, int],
    occupied: dict[tuple[int, int, int], str],
    entity_positions: list[tuple[int, int, int]] | None = None,
    entity_id: str = "minecraft:dispenser",
) -> None:
    width, height, length = dimensions
    blocks = {
        (x, y, z): occupied.get((x, y, z), "minecraft:air")
        for y in range(height)
        for z in range(length)
        for x in range(width)
    }
    entities = [
        {"pos": pos, "id": entity_id, "raw": {"Id": entity_id, "Pos": list(pos)}}
        for pos in entity_positions or []
    ]
    model = {
        "format": "sponge-v2",
        "version": 2,
        "data_version": 3465,
        "blocks": blocks,
        "block_entities": entities,
        "source_dimensions": {"width": width, "height": height, "length": length},
    }
    AUDIT.write_sponge_v2(path, model, 3465)


def component(
    component_id: str,
    schematic: Path,
    evidence: str,
    capabilities: list[str],
    ports: list[dict[str, Any]],
    *,
    source_note: str = "synthetic regression fixture",
    reusable: bool = False,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "version": "1",
        "evidence": {"level": evidence, "sources": [source_note]},
        "capabilities": [{"id": capability, "evidence": evidence} for capability in capabilities],
        "schematic": {
            "path": schematic.name,
            "sha256": digest(schematic),
            "data_version": 3465,
        },
        "ports": ports,
        "reusable": reusable,
        "source": {"kind": "synthetic-test", "note": source_note},
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def standard_ports(kind: str) -> list[dict[str, Any]]:
    if kind == "control":
        return [
            {
                "id": "signal-out",
                "kind": "output",
                "medium": "redstone",
                "position": [2, 0, 0],
                "direction": [1, 0, 0],
                "contract": {"pulse_ticks": 4},
            }
        ]
    if kind == "charge":
        return [
            {
                "id": "signal-in",
                "kind": "input",
                "medium": "redstone",
                "position": [0, 0, 0],
                "direction": [-1, 0, 0],
                "contract": {"pulse_ticks": 4},
            },
            {
                "id": "entity-out",
                "kind": "output",
                "medium": "tnt-entity",
                "position": [2, 0, 0],
                "direction": [1, 0, 0],
                "contract": {"entity": "primed_tnt"},
            },
        ]
    if kind == "payload":
        return [
            {
                "id": "entity-in",
                "kind": "input",
                "medium": "tnt-entity",
                "position": [0, 0, 0],
                "direction": [-1, 0, 0],
                "contract": {"entity": "primed_tnt"},
            }
        ]
    raise AssertionError(kind)


def request_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "synthetic-three-module-pipeline",
        "min_evidence": "local-runtime",
        "root_node": "control",
        "nodes": [
            {"id": "control", "requires": ["control-spine"]},
            {"id": "charge", "requires": ["charge-cohort"]},
            {"id": "payload", "requires": ["payload-interface"]},
        ],
        "edges": [
            {
                "from": {"node": "control", "port": "signal-out"},
                "to": {"node": "charge", "port": "signal-in"},
                "connection": "adjacent",
            },
            {
                "from": {"node": "charge", "port": "entity-out"},
                "to": {"node": "payload", "port": "entity-in"},
                "connection": "adjacent",
            },
        ],
        "constraints": {
            "chunk_limit": 160,
            "min_safe_alignments": 256,
            "max_dimensions": [32, 8, 8],
            "allow_identical_overlap": False,
            "require_lossless_block_entities": True,
        },
        "max_combinations": 64,
        "max_plans": 8,
    }


def build_standard_fixture(root: Path) -> tuple[Path, Path]:
    control_static = root / "control-static.schem"
    control_runtime = root / "control-runtime.schem"
    charge = root / "charge.schem"
    payload = root / "payload.schem"

    write_schematic(
        control_static,
        (3, 1, 1),
        {(0, 0, 0): "minecraft:stone", (1, 0, 0): "minecraft:repeater", (2, 0, 0): "minecraft:stone"},
    )
    write_schematic(
        control_runtime,
        (3, 1, 1),
        {(0, 0, 0): "minecraft:stone", (1, 0, 0): "minecraft:repeater", (2, 0, 0): "minecraft:stone"},
    )
    write_schematic(
        charge,
        (3, 1, 1),
        {
            (0, 0, 0): "minecraft:stone",
            (1, 0, 0): "minecraft:dispenser[facing=east]",
            (2, 0, 0): "minecraft:dispenser[facing=east]",
        },
        [(1, 0, 0), (2, 0, 0)],
    )
    write_schematic(
        payload,
        (2, 1, 1),
        {(0, 0, 0): "minecraft:stone", (1, 0, 0): "minecraft:dispenser[facing=east]"},
        [(1, 0, 0)],
    )

    registry = root / "registry.json"
    write_json(
        registry,
        {
            "schema_version": 1,
            "id": "synthetic-registry",
            "components": [
                component(
                    "control-static",
                    control_static,
                    "static",
                    ["control-spine"],
                    standard_ports("control"),
                ),
                component(
                    "control-runtime",
                    control_runtime,
                    "local-runtime",
                    ["control-spine"],
                    standard_ports("control"),
                ),
                component(
                    "charge-runtime",
                    charge,
                    "local-runtime",
                    ["charge-cohort"],
                    standard_ports("charge"),
                ),
                component(
                    "payload-runtime",
                    payload,
                    "local-runtime",
                    ["payload-interface"],
                    standard_ports("payload"),
                ),
            ],
        },
    )
    request = root / "request.json"
    write_json(request, request_payload())
    return registry, request


def test_evidence_first_selection_and_compile() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        registry_path, request_path = build_standard_fixture(root)
        components = PLANNER.load_registry(registry_path, AUDIT)
        request = PLANNER.parse_request(request_path)
        plans, search = PLANNER.plan_assemblies(components, request)
        assert plans, search
        best = plans[0]
        assert best.assignments["control"].id == "control-runtime", best.assignments
        assert best.translations == {
            "control": (0, 0, 0),
            "charge": (3, 0, 0),
            "payload": (6, 0, 0),
        }, best.translations
        assert best.chunk_scan["safe_alignment_count"] == 256, best.chunk_scan
        assert best.bounds["dimensions"] == [8, 1, 1], best.bounds

        output_a = root / "assembled-a.schem"
        output_b = root / "assembled-b.schem"
        verification_a = PLANNER.compile_plan(best, output_a, AUDIT, 3465)
        verification_b = PLANNER.compile_plan(best, output_b, AUDIT, 3465)
        assert verification_a["geometry_verified"] is True
        assert verification_a["block_entities"] == 3, verification_a
        assert verification_a["sha256"] == verification_b["sha256"]
        assert output_a.read_bytes() == output_b.read_bytes()

        report = PLANNER.build_report(
            registry_path,
            request_path,
            components,
            request,
            plans,
            search,
            verification_a,
        )
        assert report["status"] == "PASS"
        assert report["promotion"]["status"] == "ASSEMBLY_CANDIDATE_ONLY"
        assert report["truth_boundary"]["private_extremecraft_parity_confirmed"] is False
        assert report["truth_boundary"]["runtime_physics_confirmed"] is False
        assert report["truth_boundary"]["ec_ready"] is False


def test_filename_does_not_promote_role() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        fake = root / "definitely-hammer-osrb-nuke.schem"
        write_schematic(fake, (1, 1, 1), {(0, 0, 0): "minecraft:stone"})
        registry = root / "registry.json"
        write_json(
            registry,
            {
                "schema_version": 1,
                "components": [
                    component(
                        "filename-only",
                        fake,
                        "local-runtime",
                        ["generic-control"],
                        [
                            {
                                "id": "out",
                                "kind": "output",
                                "medium": "redstone",
                                "position": [0, 0, 0],
                                "direction": [1, 0, 0],
                                "contract": {},
                            }
                        ],
                    )
                ],
            },
        )
        request = root / "request.json"
        write_json(
            request,
            {
                "schema_version": 1,
                "nodes": [{"id": "hammer", "requires": ["hammer"]}],
                "edges": [],
            },
        )
        components = PLANNER.load_registry(registry, AUDIT)
        parsed = PLANNER.parse_request(request)
        try:
            PLANNER.plan_assemblies(components, parsed)
        except PLANNER.SynthesisError as exc:
            assert "no component satisfies" in str(exc)
        else:
            raise AssertionError("filename-only role promotion must fail")


def test_ec160_overflow_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        overflow = root / "overflow.schem"
        occupied = {(0, y, 0): "minecraft:dispenser[facing=east]" for y in range(161)}
        write_schematic(overflow, (1, 161, 1), occupied, list(occupied))
        registry = root / "registry.json"
        write_json(
            registry,
            {
                "schema_version": 1,
                "components": [
                    component(
                        "overflow-161",
                        overflow,
                        "local-runtime",
                        ["charge-cohort"],
                        [
                            {
                                "id": "out",
                                "kind": "output",
                                "medium": "tnt-entity",
                                "position": [0, 160, 0],
                                "direction": [1, 0, 0],
                                "contract": {},
                            }
                        ],
                    )
                ],
            },
        )
        request = root / "request.json"
        write_json(
            request,
            {
                "schema_version": 1,
                "nodes": [{"id": "charge", "requires": ["charge-cohort"]}],
                "edges": [],
                "constraints": {"chunk_limit": 160},
            },
        )
        components = PLANNER.load_registry(registry, AUDIT)
        parsed = PLANNER.parse_request(request)
        plans, search = PLANNER.plan_assemblies(components, parsed)
        assert not plans
        assert search["rejected_by_kind"]["constraints"] == 1, search


def test_overlap_and_contract_mismatch_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        left = root / "left.schem"
        right = root / "right.schem"
        write_schematic(left, (1, 1, 1), {(0, 0, 0): "minecraft:stone"})
        write_schematic(right, (1, 1, 1), {(0, 0, 0): "minecraft:obsidian"})
        registry = root / "registry.json"
        write_json(
            registry,
            {
                "schema_version": 1,
                "components": [
                    component(
                        "left",
                        left,
                        "local-runtime",
                        ["left"],
                        [
                            {
                                "id": "out",
                                "kind": "output",
                                "medium": "redstone",
                                "position": [0, 0, 0],
                                "direction": [1, 0, 0],
                                "contract": {"pulse_ticks": 4},
                            }
                        ],
                    ),
                    component(
                        "right",
                        right,
                        "local-runtime",
                        ["right"],
                        [
                            {
                                "id": "in",
                                "kind": "input",
                                "medium": "redstone",
                                "position": [0, 0, 0],
                                "direction": [-1, 0, 0],
                                "contract": {"pulse_ticks": 4},
                            }
                        ],
                    ),
                ],
            },
        )
        request = root / "request.json"
        write_json(
            request,
            {
                "schema_version": 1,
                "nodes": [
                    {"id": "left", "requires": ["left"]},
                    {"id": "right", "requires": ["right"]},
                ],
                "edges": [
                    {
                        "from": {"node": "left", "port": "out"},
                        "to": {"node": "right", "port": "in"},
                        "connection": "coincident",
                    }
                ],
                "constraints": {"chunk_limit": 160, "allow_identical_overlap": False},
            },
        )
        components = PLANNER.load_registry(registry, AUDIT)
        parsed = PLANNER.parse_request(request)
        plans, search = PLANNER.plan_assemblies(components, parsed)
        assert not plans
        assert search["rejected_by_kind"]["geometry-or-block-entity"] == 1, search


def test_lossy_block_entity_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        chest = root / "chest.schem"
        write_schematic(
            chest,
            (1, 1, 1),
            {(0, 0, 0): "minecraft:chest[facing=north,type=single,waterlogged=false]"},
            [(0, 0, 0)],
            entity_id="minecraft:chest",
        )
        registry = root / "registry.json"
        write_json(
            registry,
            {
                "schema_version": 1,
                "components": [
                    component(
                        "lossy-chest",
                        chest,
                        "local-runtime",
                        ["storage"],
                        [
                            {
                                "id": "out",
                                "kind": "output",
                                "medium": "item",
                                "position": [0, 0, 0],
                                "direction": [1, 0, 0],
                                "contract": {},
                            }
                        ],
                    )
                ],
            },
        )
        request = root / "request.json"
        write_json(
            request,
            {
                "schema_version": 1,
                "nodes": [{"id": "storage", "requires": ["storage"]}],
                "edges": [],
                "constraints": {"require_lossless_block_entities": True},
            },
        )
        components = PLANNER.load_registry(registry, AUDIT)
        parsed = PLANNER.parse_request(request)
        plans, search = PLANNER.plan_assemblies(components, parsed)
        assert not plans
        assert search["rejected_by_kind"]["geometry-or-block-entity"] == 1, search


def main() -> None:
    tests = [
        test_evidence_first_selection_and_compile,
        test_filename_does_not_promote_role,
        test_ec160_overflow_fails_closed,
        test_overlap_and_contract_mismatch_fail_closed,
        test_lossy_block_entity_is_rejected,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} cannon synthesis planner regressions passed.")


if __name__ == "__main__":
    main()
