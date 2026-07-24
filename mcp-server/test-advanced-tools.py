from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mcp-server" / "advanced_tools.py"
spec = importlib.util.spec_from_file_location("advanced_tools", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to import {MODULE_PATH}")
advanced_tools = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = advanced_tools
spec.loader.exec_module(advanced_tools)


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


def make_registry():
    mcp = FakeMCP()
    calls: list[dict[str, Any]] = []

    def inside_root(raw: str, *, must_exist: bool = True) -> Path:
        candidate = (ROOT / raw).resolve()
        if not candidate.is_relative_to(ROOT.resolve()):
            raise ValueError("path escapes CannonLab root")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(candidate)
        return candidate

    def run_json(
        script: Path,
        args: list[str],
        *,
        allowed_exit_codes=(0,),
        timeout: int = 180,
    ) -> dict[str, Any]:
        call = {
            "script": script,
            "args": list(args),
            "allowed_exit_codes": tuple(allowed_exit_codes),
            "timeout": timeout,
        }
        calls.append(call)
        return {"status": "captured", "call": call}

    registered = advanced_tools.register_advanced_tools(
        mcp,
        root=ROOT,
        scripts=ROOT / "scripts",
        inside_root=inside_root,
        run_json=run_json,
    )
    return mcp, calls, registered


def expected_tools() -> set[str]:
    return {
        "audit_cannon_ratio",
        "analyze_impulse_graph",
        "plan_cannon_synthesis",
        "promote_cannon_component",
        "generate_causal_repair_family",
        "run_cannon_campaign",
        "list_advanced_cannon_profiles",
    }


def test_registers_exact_advanced_tools() -> None:
    mcp, _, registered = make_registry()
    assert set(registered) == expected_tools(), registered
    assert set(mcp.tools) == expected_tools(), mcp.tools


def test_ratio_tool_preserves_comparison_contract() -> None:
    mcp, calls, _ = make_registry()
    result = mcp.tools["audit_cannon_ratio"](
        "profiles/ratios/public-0.7-384-osrb-1-above-barrel.json",
        "profiles/ratios/public-1.2-384-4os-derived.json",
    )
    assert result["status"] == "captured", result
    call = calls[-1]
    assert call["script"].name == "cannon-ratio-audit.py", call
    assert "--compare" in call["args"], call
    assert call["allowed_exit_codes"] == (0, 2), call


def test_impulse_tool_requires_paired_comparison_paths() -> None:
    mcp, _, _ = make_registry()
    try:
        mcp.tools["analyze_impulse_graph"](
            "audit-fixtures/impulse-events-reference.csv",
            "audit-fixtures/impulse-causal-events.csv",
            compare_events_path="audit-fixtures/impulse-events-candidate.csv",
        )
    except ValueError as exc:
        assert "must be supplied together" in str(exc), exc
    else:
        raise AssertionError("half-specified comparison unexpectedly passed")


def test_impulse_tool_builds_bounded_compare_command() -> None:
    mcp, calls, _ = make_registry()
    mcp.tools["analyze_impulse_graph"](
        "audit-fixtures/impulse-events-reference.csv",
        "audit-fixtures/impulse-causal-events.csv",
        compare_events_path="audit-fixtures/impulse-events-candidate.csv",
        compare_causal_events_path="audit-fixtures/impulse-causal-events.csv",
        max_timing_delta=0,
        max_velocity_delta=0.02,
    )
    call = calls[-1]
    assert call["script"].name == "analyze-impulse-graph.py", call
    assert "--compare-events" in call["args"], call
    assert call["args"][call["args"].index("--max-timing-delta") + 1] == "0", call
    assert call["args"][call["args"].index("--max-velocity-delta") + 1] == "0.02", call


def test_synthesis_tool_allows_only_root_scoped_output() -> None:
    mcp, calls, _ = make_registry()
    mcp.tools["plan_cannon_synthesis"](
        "profiles/synthesis/component-registry-template-v1.json",
        "profiles/synthesis/request-template-v1.json",
        compile_best_path="lab-artifacts/mcp/candidate.schem",
    )
    call = calls[-1]
    assert call["script"].name == "cannon-synthesis-planner.py", call
    assert "--compile-best" in call["args"], call
    output = Path(call["args"][call["args"].index("--compile-best") + 1])
    assert output == (ROOT / "lab-artifacts/mcp/candidate.schem").resolve(), output

    try:
        mcp.tools["plan_cannon_synthesis"](
            "profiles/synthesis/component-registry-template-v1.json",
            "profiles/synthesis/request-template-v1.json",
            compile_best_path="../outside.schem",
        )
    except ValueError as exc:
        assert "escapes CannonLab root" in str(exc), exc
    else:
        raise AssertionError("path escape unexpectedly passed")


def test_component_promotion_builds_exact_guarded_command() -> None:
    mcp, calls, _ = make_registry()
    mcp.tools["promote_cannon_component"](
        "profiles/synthesis/component-registry-template-v1.json",
        "profiles/components/promotion-manifest-template-v1.json",
        "lab-artifacts/mcp/promoted.schem",
        "lab-artifacts/mcp/promoted.registry.json",
        trace_path="audit-fixtures/impulse-causal-events.csv",
        report_output_path="lab-artifacts/mcp/promoted.report.json",
        output_data_version=3465,
    )
    call = calls[-1]
    assert call["script"].name == "promote-cannon-component.py", call
    assert call["allowed_exit_codes"] == (0, 2), call
    assert "--trace" in call["args"], call
    assert "--schem-out" in call["args"], call
    assert "--registry-out" in call["args"], call
    assert "--json-out" in call["args"], call
    assert call["args"][call["args"].index("--output-data-version") + 1] == "3465"

    try:
        mcp.tools["promote_cannon_component"](
            "profiles/synthesis/component-registry-template-v1.json",
            "profiles/components/promotion-manifest-template-v1.json",
            "../promoted.schem",
            "lab-artifacts/mcp/promoted.registry.json",
        )
    except ValueError as exc:
        assert "escapes CannonLab root" in str(exc), exc
    else:
        raise AssertionError("promotion output path escape unexpectedly passed")


def test_repair_family_builds_exact_guarded_command() -> None:
    mcp, calls, _ = make_registry()
    mcp.tools["generate_causal_repair_family"](
        "profiles/synthesis/component-registry-template-v1.json",
        "profiles/parity/extremecraft-private-parity-required-v1.json",
        "profiles/repairs/causal-repair-policy-template-v1.json",
        "lab-artifacts/mcp/repair-family",
        report_output_path="lab-artifacts/mcp/repair-family.json",
    )
    call = calls[-1]
    assert call["script"].name == "generate-causal-repair-family.py", call
    assert call["allowed_exit_codes"] == (0, 2), call
    assert "--output-directory" in call["args"], call
    assert "--json-out" in call["args"], call
    output = Path(call["args"][call["args"].index("--output-directory") + 1])
    assert output == (ROOT / "lab-artifacts/mcp/repair-family").resolve(), output

    try:
        mcp.tools["generate_causal_repair_family"](
            "profiles/synthesis/component-registry-template-v1.json",
            "profiles/parity/extremecraft-private-parity-required-v1.json",
            "profiles/repairs/causal-repair-policy-template-v1.json",
            "../../outside-repairs",
        )
    except ValueError as exc:
        assert "escapes CannonLab root" in str(exc), exc
    else:
        raise AssertionError("repair output path escape unexpectedly passed")


def test_campaign_tool_builds_bounded_command_and_timeout() -> None:
    mcp, calls, _ = make_registry()
    mcp.tools["run_cannon_campaign"](
        "profiles/campaigns/staged-campaign-template-v1.json",
        "lab-artifacts/mcp/campaigns",
        mode="execute",
        report_output_path="lab-artifacts/mcp/campaign-report.json",
    )
    call = calls[-1]
    assert call["script"].name == "run-cannon-campaign.py", call
    assert call["allowed_exit_codes"] == (0, 2), call
    assert call["timeout"] == 3700, call
    assert call["args"][call["args"].index("--mode") + 1] == "execute", call
    output = Path(call["args"][call["args"].index("--output-directory") + 1])
    assert output == (ROOT / "lab-artifacts/mcp/campaigns").resolve(), output
    assert "--json-out" in call["args"], call

    mcp.tools["run_cannon_campaign"](
        "profiles/campaigns/staged-campaign-template-v1.json",
        "lab-artifacts/mcp/campaign-plan",
        mode="plan",
    )
    assert calls[-1]["timeout"] == 300, calls[-1]

    try:
        mcp.tools["run_cannon_campaign"](
            "profiles/campaigns/staged-campaign-template-v1.json",
            "../outside-campaign",
        )
    except ValueError as exc:
        assert "escapes CannonLab root" in str(exc), exc
    else:
        raise AssertionError("campaign output path escape unexpectedly passed")

    try:
        mcp.tools["run_cannon_campaign"](
            "profiles/campaigns/staged-campaign-template-v1.json",
            "lab-artifacts/mcp/campaign",
            mode="forever",
        )
    except ValueError as exc:
        assert "mode must be" in str(exc), exc
    else:
        raise AssertionError("invalid campaign mode unexpectedly passed")


def test_profile_listing_is_machine_readable_and_truth_bounded() -> None:
    mcp, _, _ = make_registry()
    report = mcp.tools["list_advanced_cannon_profiles"]()
    assert report["schema_version"] == 1, report
    assert report["profile_count"] >= 9, report
    assert report["categories"]["ratios"], report
    assert report["categories"]["parity"], report
    assert report["categories"]["archetypes"], report
    assert report["categories"]["synthesis"], report
    assert report["categories"]["components"], report
    assert report["categories"]["repairs"], report
    assert report["categories"]["campaigns"], report
    assert report["truth_boundary"]["profile_presence_proves_runtime_function"] is False
    json.dumps(report)


def main() -> None:
    tests = [
        test_registers_exact_advanced_tools,
        test_ratio_tool_preserves_comparison_contract,
        test_impulse_tool_requires_paired_comparison_paths,
        test_impulse_tool_builds_bounded_compare_command,
        test_synthesis_tool_allows_only_root_scoped_output,
        test_component_promotion_builds_exact_guarded_command,
        test_repair_family_builds_exact_guarded_command,
        test_campaign_tool_builds_bounded_command_and_timeout,
        test_profile_listing_is_machine_readable_and_truth_bounded,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
