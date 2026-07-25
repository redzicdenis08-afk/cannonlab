#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAMMAR = ROOT / "profiles/grammar/modern-factions-cannon-grammar-v1.json"
PARITY = ROOT / "profiles/parity/sakura-26.1.2-cannon-contract.json"
SOURCES = ROOT / "research/sources/cannon-community-sources-v1.json"


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    grammar = load(GRAMMAR)
    parity = load(PARITY)
    sources = load(SOURCES)

    require(grammar["schema_version"] == 1, "unexpected grammar schema")
    require(parity["schema_version"] == 1, "unexpected parity schema")
    require(sources["schema_version"] == 1, "unexpected source registry schema")

    modules = grammar.get("modules", [])
    module_ids = [row["id"] for row in modules]
    require(len(module_ids) == len(set(module_ids)), "duplicate module IDs")
    require(len(module_ids) >= 15, "grammar is missing major modern cannon modules")

    required_fields = {
        "id",
        "community_names",
        "purpose",
        "requires",
        "outputs",
        "minimum_evidence",
        "failure_signals",
    }
    for module in modules:
        require(required_fields <= set(module), f"incomplete module {module.get('id')}")
        require(module["minimum_evidence"], f"module {module['id']} has no evidence gate")
        require(module["failure_signals"], f"module {module['id']} has no failure signals")

    architecture_ids = [row["id"] for row in grammar.get("architecture_rules", [])]
    require("separate-runtime-version-from-schematic-version" in architecture_ids, "missing three-version rule")
    require("external-defense-course" in architecture_ids, "missing external-defense rule")
    require("module-before-monolith" in architecture_ids, "missing module-first rule")
    require("no-filename-proof" in architecture_ids, "missing filename truth boundary")

    levels = [row["level"] for row in grammar.get("promotion_levels", [])]
    require(
        levels == ["STATIC", "LOCAL_CAUSAL", "LOCAL_ENDURANCE", "FIELD_CANARY", "FIELD_READY"],
        f"unexpected promotion ladder: {levels}",
    )

    source = parity["source"]
    require(source["sakura_version"] == "26.1.2", "wrong Sakura runtime version")
    require(source["minecraft_runtime_version"] == "26.1.2", "wrong Minecraft runtime version")
    require(source["schematic_data_version"] == 3465, "wrong schematic DataVersion")
    require(
        str(source["minecraft_runtime_version"]) != str(source["schematic_data_version"]),
        "runtime and schematic versions were collapsed",
    )

    probes = parity.get("required_runtime_probes", [])
    probe_ids = list(probes)
    require(len(probe_ids) == len(set(probe_ids)), "duplicate parity probe IDs")
    require(len(probe_ids) >= 12, "parity probe matrix is too small")

    source_rows = sources.get("sources", [])
    source_ids = [row["id"] for row in source_rows]
    require(len(source_ids) == len(set(source_ids)), "duplicate source IDs")
    require(any(row.get("type") == "primary-source-code" for row in source_rows), "missing source-code authority")
    require(any("community" in str(row.get("type", "")) for row in source_rows), "missing community vocabulary")

    truth = grammar.get("truth_boundary", {})
    require(truth.get("static_module_name_proves_behavior") is False, "grammar profile must not prove runtime")
    require(truth.get("local_sakura_success_proves_extremecraft_success") is False, "private parity boundary missing")

    print(
        "cannon grammar contract: "
        f"{len(module_ids)} modules, {len(probe_ids)} parity probes, {len(source_ids)} sources passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
