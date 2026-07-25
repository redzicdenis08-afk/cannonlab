from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def register_raid_tools(
    mcp: Any,
    *,
    root: Path,
    scripts: Path,
    inside_root: Callable[..., Path],
    run_json: Callable[..., dict[str, Any]],
) -> tuple[str, ...]:
    """Register fail-closed long-course raid planning tools."""

    @mcp.tool()
    def plan_extremecraft_raid_program(
        objective_path: str = "profiles/raid/extremecraft-15-chunk-regen-objective-v1.json",
        grammar_path: str = "profiles/grammar/modern-factions-cannon-grammar-v1.json",
        parity_path: str = "profiles/parity/extremecraft-private-parity-required-v1.json",
        report_output_path: str | None = None,
    ) -> dict[str, Any]:
        """Plan a dependency-ordered fifteen-chunk EC raid program without inventing range or parity."""
        objective = inside_root(objective_path)
        grammar = inside_root(grammar_path)
        parity = inside_root(parity_path)
        args = [str(grammar), str(parity), str(objective)]
        if report_output_path:
            report = inside_root(report_output_path, must_exist=False)
            args.extend(["--json-out", str(report)])
        return run_json(
            scripts / "plan-extremecraft-raid-program.py",
            args,
            allowed_exit_codes=(0, 2),
        )

    return ("plan_extremecraft_raid_program",)
