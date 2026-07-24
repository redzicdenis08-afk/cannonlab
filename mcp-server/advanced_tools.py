from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def register_advanced_tools(
    mcp: Any,
    *,
    root: Path,
    scripts: Path,
    inside_root: Callable[..., Path],
    run_json: Callable[..., dict[str, Any]],
) -> tuple[str, ...]:
    """Register the research, impulse, synthesis, promotion and repair tools."""

    @mcp.tool()
    def audit_cannon_ratio(
        profile_path: str,
        compare_profile_path: str | None = None,
    ) -> dict[str, Any]:
        """Audit an authored 384/OSRB ratio without inventing runtime timing proof."""
        profile = inside_root(profile_path)
        args = [str(profile)]
        if compare_profile_path:
            comparison = inside_root(compare_profile_path)
            args.extend(["--compare", str(comparison)])
        return run_json(scripts / "cannon-ratio-audit.py", args, allowed_exit_codes=(0, 2))

    @mcp.tool()
    def analyze_impulse_graph(
        events_path: str,
        causal_events_path: str,
        compare_events_path: str | None = None,
        compare_causal_events_path: str | None = None,
        motion_model: str = "nominal-air",
        min_velocity_residual: float = 0.05,
        max_velocity_delta: float = 0.05,
        max_position_delta: float = 0.5,
        max_timing_delta: int = 1,
    ) -> dict[str, Any]:
        """Build or compare explosion-to-entity impulse graphs from real CannonLab traces."""
        events = inside_root(events_path)
        causal = inside_root(causal_events_path)
        if (compare_events_path is None) != (compare_causal_events_path is None):
            raise ValueError(
                "compare_events_path and compare_causal_events_path must be supplied together"
            )
        if motion_model not in {"nominal-air", "none"}:
            raise ValueError("motion_model must be 'nominal-air' or 'none'")
        if min_velocity_residual < 0 or max_velocity_delta < 0 or max_position_delta < 0:
            raise ValueError("velocity and position thresholds must be non-negative")
        if max_timing_delta < 0:
            raise ValueError("max_timing_delta must be non-negative")

        args = [
            str(events),
            str(causal),
            "--motion-model",
            motion_model,
            "--min-velocity-residual",
            str(min_velocity_residual),
            "--max-velocity-delta",
            str(max_velocity_delta),
            "--max-position-delta",
            str(max_position_delta),
            "--max-timing-delta",
            str(max_timing_delta),
        ]
        if compare_events_path and compare_causal_events_path:
            compare_events = inside_root(compare_events_path)
            compare_causal = inside_root(compare_causal_events_path)
            args.extend(
                [
                    "--compare-events",
                    str(compare_events),
                    "--compare-causal-events",
                    str(compare_causal),
                ]
            )
        return run_json(scripts / "analyze-impulse-graph.py", args, allowed_exit_codes=(0, 2))

    @mcp.tool()
    def plan_cannon_synthesis(
        registry_path: str,
        request_path: str,
        compile_best_path: str | None = None,
        output_data_version: int = 3465,
    ) -> dict[str, Any]:
        """Plan a hash-verified, declared-port cannon assembly and optionally compile its best candidate."""
        registry = inside_root(registry_path)
        request = inside_root(request_path)
        if output_data_version <= 0:
            raise ValueError("output_data_version must be positive")
        args = [
            str(registry),
            str(request),
            "--repo-root",
            str(root),
            "--output-data-version",
            str(output_data_version),
        ]
        if compile_best_path:
            output = inside_root(compile_best_path, must_exist=False)
            args.extend(["--compile-best", str(output)])
        return run_json(scripts / "cannon-synthesis-planner.py", args, allowed_exit_codes=(0, 2))

    @mcp.tool()
    def promote_cannon_component(
        source_path: str,
        manifest_path: str,
        schematic_output_path: str,
        registry_output_path: str,
        trace_path: str | None = None,
        report_output_path: str | None = None,
        output_data_version: int | None = None,
    ) -> dict[str, Any]:
        """Promote one exact reviewed source module into a deterministic synthesis component."""
        source = inside_root(source_path)
        manifest = inside_root(manifest_path)
        schematic_output = inside_root(schematic_output_path, must_exist=False)
        registry_output = inside_root(registry_output_path, must_exist=False)
        args = [
            str(source),
            str(manifest),
            "--schem-out",
            str(schematic_output),
            "--registry-out",
            str(registry_output),
            "--repo-root",
            str(root),
        ]
        if trace_path:
            trace = inside_root(trace_path)
            args.extend(["--trace", str(trace)])
        if report_output_path:
            report_output = inside_root(report_output_path, must_exist=False)
            args.extend(["--json-out", str(report_output)])
        if output_data_version is not None:
            if output_data_version <= 0:
                raise ValueError("output_data_version must be positive")
            args.extend(["--output-data-version", str(output_data_version)])
        return run_json(scripts / "promote-cannon-component.py", args, allowed_exit_codes=(0, 2))

    @mcp.tool()
    def generate_causal_repair_family(
        reference_path: str,
        divergence_path: str,
        policy_path: str,
        output_directory_path: str,
        report_output_path: str | None = None,
    ) -> dict[str, Any]:
        """Generate EC160 and preservation-gated repairs from the first measured divergence."""
        reference = inside_root(reference_path)
        divergence = inside_root(divergence_path)
        policy = inside_root(policy_path)
        output_directory = inside_root(output_directory_path, must_exist=False)
        args = [
            str(reference),
            str(divergence),
            str(policy),
            "--output-directory",
            str(output_directory),
            "--repo-root",
            str(root),
        ]
        if report_output_path:
            report_output = inside_root(report_output_path, must_exist=False)
            args.extend(["--json-out", str(report_output)])
        return run_json(
            scripts / "generate-causal-repair-family.py",
            args,
            allowed_exit_codes=(0, 2),
        )

    @mcp.tool()
    def list_advanced_cannon_profiles() -> dict[str, Any]:
        """List ratio, parity, archetype, synthesis, component and repair profiles."""
        profile_root = root / "profiles"
        categories = ("ratios", "parity", "archetypes", "synthesis", "components", "repairs")
        result: dict[str, list[dict[str, Any]]] = {}
        for category in categories:
            rows: list[dict[str, Any]] = []
            directory = profile_root / category
            if directory.is_dir():
                for path in sorted(directory.glob("*.json")):
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        rows.append(
                            {
                                "path": str(path.relative_to(root)),
                                "status": "invalid-json",
                                "error": str(exc),
                            }
                        )
                        continue
                    rows.append(
                        {
                            "path": str(path.relative_to(root)),
                            "status": "ok",
                            "id": payload.get("id"),
                            "title": payload.get("title"),
                            "schema_version": payload.get("schema_version"),
                        }
                    )
            result[category] = rows
        return {
            "schema_version": 1,
            "categories": result,
            "profile_count": sum(len(rows) for rows in result.values()),
            "truth_boundary": {
                "profile_presence_proves_runtime_function": False,
                "profile_presence_proves_extremecraft_parity": False,
            },
        }

    return (
        "audit_cannon_ratio",
        "analyze_impulse_graph",
        "plan_cannon_synthesis",
        "promote_cannon_component",
        "generate_causal_repair_family",
        "list_advanced_cannon_profiles",
    )
