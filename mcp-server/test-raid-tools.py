from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mcp-server" / "raid_tools.py"
spec = importlib.util.spec_from_file_location("raid_tools", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to import {MODULE_PATH}")
raid_tools = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = raid_tools
spec.loader.exec_module(raid_tools)


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


def main() -> None:
    mcp = FakeMCP()
    calls: list[dict[str, Any]] = []

    def inside_root(path: str, must_exist: bool = True) -> Path:
        candidate = (ROOT / path).resolve()
        candidate.relative_to(ROOT.resolve())
        if must_exist and not candidate.exists():
            raise FileNotFoundError(candidate)
        return candidate

    def run_json(
        script: Path,
        args: list[str],
        *,
        allowed_exit_codes: tuple[int, ...] = (0,),
        timeout: int = 180,
    ) -> dict[str, Any]:
        calls.append(
            {
                "script": script,
                "args": args,
                "allowed_exit_codes": allowed_exit_codes,
                "timeout": timeout,
            }
        )
        return {
            "readiness": "BLOCKED",
            "distinctions": {"buffer_depth_is_projectile_distance": False},
            "truth_boundary": {"program_plan_proves_fifteen_chunk_raid_capability": False},
        }

    registered = raid_tools.register_raid_tools(
        mcp,
        root=ROOT,
        scripts=ROOT / "scripts",
        inside_root=inside_root,
        run_json=run_json,
    )
    assert registered == ("plan_extremecraft_raid_program",), registered
    assert set(mcp.tools) == {"plan_extremecraft_raid_program"}, mcp.tools

    report = mcp.tools["plan_extremecraft_raid_program"]()
    assert report["readiness"] == "BLOCKED", report
    assert report["distinctions"]["buffer_depth_is_projectile_distance"] is False, report
    assert calls[-1]["script"].name == "plan-extremecraft-raid-program.py", calls[-1]
    assert calls[-1]["allowed_exit_codes"] == (0, 2), calls[-1]
    assert calls[-1]["args"][0].endswith("modern-factions-cannon-grammar-v1.json"), calls[-1]
    assert calls[-1]["args"][1].endswith("extremecraft-private-parity-required-v1.json"), calls[-1]
    assert calls[-1]["args"][2].endswith("extremecraft-15-chunk-regen-objective-v1.json"), calls[-1]

    output = "output/raid-program-test.json"
    mcp.tools["plan_extremecraft_raid_program"](report_output_path=output)
    assert calls[-1]["args"][-2:] == ["--json-out", str((ROOT / output).resolve())], calls[-1]

    print("PASS plan_extremecraft_raid_program default fail-closed paths")
    print("PASS plan_extremecraft_raid_program output and exit-code contract")


if __name__ == "__main__":
    main()
