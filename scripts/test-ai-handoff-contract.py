#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require_path(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"missing handoff target: {relative}")
    return path


def require_tokens(path: Path, tokens: set[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = sorted(token for token in tokens if token not in text)
    if missing:
        raise AssertionError(f"{path.relative_to(ROOT)} missing tokens: {missing}")


def main() -> None:
    required_paths = [
        "AGENTS.md",
        "CANNONLAB_START_HERE.md",
        "README.md",
        "docs/CANNON_GRAMMAR_AND_PARITY.md",
        "docs/CANNON_PARITY_CAMPAIGNS.md",
        "docs/CANNON_CAMPAIGNS.md",
        "docs/LITEMATICA_CONVERSION.md",
        "docs/DEFENSE_MODELS.md",
        "docs/EXTREMECRAFT_CALIBRATION.md",
        "docs/PUBLIC_CANNON_CORPUS.md",
        "docs/LEGACY_SHARED_CORE_AUDIT.md",
        "profiles/grammar/modern-factions-cannon-grammar-v1.json",
        "profiles/parity/sakura-26.1.2-cannon-contract.json",
        "profiles/parity/extremecraft-private-parity-required-v1.json",
        "profiles/parity/extremecraft-parity-probe-priorities-v1.json",
        "profiles/campaigns/module-proof-request-template-v1.json",
        "scripts/plan-cannon-parity-campaign.py",
        "scripts/plan-cannon-module-campaign.py",
        "scripts/classify-cannon-run.py",
        "scripts/verify-sakura-cannon-contract.py",
        "scripts/schem-audit.py",
        "scripts/paste-alignment-audit.py",
        "scripts/scenario-integrity-audit.py",
        "scripts/cannon-module-map.py",
        "scripts/analyze-module-trace.py",
        "scripts/compare-module-traces.py",
        "scripts/analyze-impulse-graph.py",
        "scripts/generate-causal-repair-family.py",
        "scripts/run-cannon-campaign.py",
        "mcp-server/advanced_tools.py",
        ".github/workflows/advanced-cannon-mcp.yml",
    ]
    paths = {relative: require_path(relative) for relative in required_paths}

    grammar = json.loads(
        paths["profiles/grammar/modern-factions-cannon-grammar-v1.json"].read_text(encoding="utf-8")
    )
    private_profile = json.loads(
        paths["profiles/parity/extremecraft-private-parity-required-v1.json"].read_text(encoding="utf-8")
    )
    public_contract = json.loads(
        paths["profiles/parity/sakura-26.1.2-cannon-contract.json"].read_text(encoding="utf-8")
    )
    priorities = json.loads(
        paths["profiles/parity/extremecraft-parity-probe-priorities-v1.json"].read_text(encoding="utf-8")
    )

    modules = grammar.get("modules")
    dimensions = private_profile.get("dimensions")
    probes = public_contract.get("required_runtime_probes")
    priority_rows = priorities.get("dimensions")
    if not isinstance(modules, list) or len(modules) != 16:
        raise AssertionError(f"expected 16 grammar modules, got {len(modules or [])}")
    if not isinstance(dimensions, list) or len(dimensions) != 16:
        raise AssertionError(f"expected 16 private parity dimensions, got {len(dimensions or [])}")
    if not isinstance(probes, list) or len(probes) != 12:
        raise AssertionError(f"expected 12 public runtime probes, got {len(probes or [])}")
    if not isinstance(priority_rows, list) or len(priority_rows) != 16:
        raise AssertionError(f"expected 16 parity priority rows, got {len(priority_rows or [])}")

    module_ids = {row.get("id") for row in modules}
    expected_modules = {
        "charge",
        "payload",
        "guider",
        "slab-bust",
        "sand-release",
        "hammer",
        "sand-compression",
        "hybrid",
        "scatter",
        "one-shot",
        "double-tap",
        "osrb",
        "nuke",
        "reverse",
        "left-right-shot",
        "bypass-pseudo",
    }
    if module_ids != expected_modules:
        raise AssertionError(
            f"grammar module IDs drifted: missing={sorted(expected_modules - module_ids)} "
            f"extra={sorted(module_ids - expected_modules)}"
        )

    advanced_tools = paths["mcp-server/advanced_tools.py"].read_text(encoding="utf-8")
    expected_tools = {
        "audit_cannon_ratio",
        "analyze_impulse_graph",
        "plan_cannon_synthesis",
        "promote_cannon_component",
        "generate_causal_repair_family",
        "run_cannon_campaign",
        "classify_cannon_failure",
        "verify_sakura_cannon_contract",
        "list_advanced_cannon_profiles",
    }
    missing_tools = sorted(name for name in expected_tools if f"def {name}(" not in advanced_tools)
    if missing_tools:
        raise AssertionError(f"AI handoff lists missing MCP tools: {missing_tools}")

    require_tokens(
        paths["AGENTS.md"],
        {
            "No current full advanced cannon is field-ready",
            "all 256",
            "DataVersion `3465`",
            "PR `#41`",
            "classify_cannon_failure",
            "plan-cannon-parity-campaign.py",
            "Never publish a generated schematic as working",
        },
    )
    require_tokens(
        paths["CANNONLAB_START_HERE.md"],
        {
            "sixteen evidence-gated modules",
            "sixteen independently variable dimensions",
            "nine tools",
            "What is genuinely proven",
            "What is not proven",
            "PR `#41` was closed unmerged",
        },
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "required_paths": len(required_paths),
                "grammar_modules": len(modules),
                "private_parity_dimensions": len(dimensions),
                "public_runtime_probes": len(probes),
                "advanced_mcp_tools": len(expected_tools),
                "truth_boundary": {
                    "handoff_contract_proves_field_ready_cannon": False,
                    "handoff_contract_proves_private_extremecraft_parity": False,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
