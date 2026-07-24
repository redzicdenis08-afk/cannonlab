#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
T = load("debug_repair_tests", ROOT / "scripts" / "test-generate-causal-repair-family.py")
G = T.GENERATOR

with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    reference, module, _secondary = T.reference_fixture(root)
    divergence_path = root / "divergence.json"
    policy_path = root / "policy.json"
    T.divergence(divergence_path)
    T.write_json(policy_path, T.policy_for(reference, module))

    auditor = G.load_script(ROOT, "debug_repair_audit", "schem-audit.py")
    module_map = G.load_script(ROOT, "debug_repair_map", "cannon-module-map.py")
    preservation = G.load_script(ROOT, "debug_repair_preservation", "cannon-preservation-check.py")
    planner = G.load_script(ROOT, "debug_repair_planner", "cannon-synthesis-planner.py")
    policy = G.load_json_object(policy_path)
    divergence = G.first_divergence(G.load_json_object(divergence_path))
    root_name, nbt_root, trailing, _size, _diagnostics = auditor.load(reference)
    decoded = auditor.decode_any(root_name, nbt_root)
    blocks, entities, dimensions, data_version = G.normalize_model(decoded)
    module_report = module_map.build_report(reference)
    controls = G.build_control_variants(policy, divergence["kind"], blocks, module_report, auditor)
    candidates = G.generate_candidates(controls, 2, 16)
    preserve = G.preservation_policy(policy)
    output = []
    for index, candidate in enumerate(candidates, start=1):
        model = G.candidate_model(blocks, entities, dimensions, data_version, candidate.changes)
        path = root / f"candidate-{index}.schem"
        auditor.write_sponge_v2(path, model, data_version)
        verification = G.verify_candidate_output(path, model, auditor, data_version)
        scan = G.dispenser_scan(model["blocks"], planner, preserve["chunk_limit"])
        report = preservation.build_report(
            reference,
            path,
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
        output.append({
            "candidate": candidate.candidate_id,
            "changes": [[*point, state] for point, state in sorted(candidate.changes.items())],
            "verification": verification,
            "safe_alignments": scan["safe_alignment_count"],
            "preservation_status": report["status"],
            "failures": report["failures"],
            "summary": report["summary"],
            "impacted_modules": report["impacted_modules"],
            "disallowed_modules": report["disallowed_modules"],
        })
    print(json.dumps(output, indent=2, sort_keys=True))
