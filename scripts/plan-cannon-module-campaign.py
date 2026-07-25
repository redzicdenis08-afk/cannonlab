#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LEVELS = ["STATIC", "LOCAL_CAUSAL", "LOCAL_ENDURANCE", "FIELD_CANARY", "FIELD_READY"]


class CampaignError(ValueError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"unable to read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CampaignError(f"expected JSON object in {path}")
    return payload


def _level_index(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError as exc:
        raise CampaignError(f"unsupported evidence level {level!r}") from exc


def build_campaign(grammar: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    modules = {row["id"]: row for row in grammar.get("modules", [])}
    if len(modules) != len(grammar.get("modules", [])):
        raise CampaignError("duplicate module ids")
    targets = request.get("target_modules") or []
    if not targets:
        raise CampaignError("request needs at least one target module")
    unknown_targets = sorted(set(targets) - set(modules))
    if unknown_targets:
        raise CampaignError(f"unknown target modules: {unknown_targets}")
    desired_level = str(request.get("desired_level", "LOCAL_CAUSAL"))
    desired_index = _level_index(desired_level)
    evidence = request.get("available_evidence") or {}
    for module_id, level in evidence.items():
        if module_id not in modules:
            raise CampaignError(f"evidence references unknown module {module_id}")
        _level_index(str(level))

    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []
    external_requirements: dict[str, set[str]] = {}

    def visit(module_id: str) -> None:
        if module_id in visited:
            return
        if module_id in visiting:
            raise CampaignError(f"module dependency cycle at {module_id}")
        visiting.add(module_id)
        external: set[str] = set()
        for dependency in modules[module_id].get("requires", []):
            if dependency in modules:
                visit(dependency)
            else:
                external.add(dependency)
        external_requirements[module_id] = external
        visiting.remove(module_id)
        visited.add(module_id)
        order.append(module_id)

    for target in targets:
        visit(target)

    stages: list[dict[str, Any]] = []
    for module_id in order:
        module = modules[module_id]
        current_level = str(evidence.get(module_id, "UNPROVEN"))
        current_index = _level_index(current_level) if current_level != "UNPROVEN" else -1
        action = "REUSE_EVIDENCE" if current_index >= desired_index else "PROVE_MODULE"
        stages.append({
            "order": len(stages) + 1,
            "module": module_id,
            "action": action,
            "current_level": current_level,
            "required_level": desired_level,
            "purpose": module["purpose"],
            "module_dependencies": [dependency for dependency in module.get("requires", []) if dependency in modules],
            "fixture_requirements": sorted(external_requirements[module_id]),
            "expected_outputs": module.get("outputs", []),
            "acceptance_evidence": module.get("minimum_evidence", []),
            "stop_on_failures": module.get("failure_signals", []),
            "composition_gate": "Do not compose downstream modules until this stage reaches the required level.",
        })

    return {
        "schema_version": 1,
        "id": "cannon-module-proof-campaign-v1",
        "request_id": request.get("id"),
        "target_modules": targets,
        "desired_level": desired_level,
        "server_profile": request.get("server_profile"),
        "constraints": request.get("constraints", {}),
        "stage_count": len(stages),
        "prove_count": sum(row["action"] == "PROVE_MODULE" for row in stages),
        "reuse_count": sum(row["action"] == "REUSE_EVIDENCE" for row in stages),
        "stages": stages,
        "truth_boundary": {
            "campaign_plan_proves_geometry": False,
            "campaign_plan_proves_runtime": False,
            "local_module_evidence_proves_private_parity": False,
            "downstream_composition_without_dependencies": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan dependency-ordered cannon module proof campaigns.")
    parser.add_argument("grammar", type=Path)
    parser.add_argument("request", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_campaign(read_object(args.grammar), read_object(args.request))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
