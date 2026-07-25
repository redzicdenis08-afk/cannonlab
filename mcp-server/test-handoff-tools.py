from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mcp-server" / "handoff_tools.py"
spec = importlib.util.spec_from_file_location("handoff_tools", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to import {MODULE_PATH}")
handoff_tools = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = handoff_tools
spec.loader.exec_module(handoff_tools)


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
    registered = handoff_tools.register_handoff_tools(mcp, root=ROOT)
    assert registered == ("get_cannonlab_handoff",), registered
    assert set(mcp.tools) == {"get_cannonlab_handoff"}, mcp.tools

    report = mcp.tools["get_cannonlab_handoff"]()
    assert report["schema_version"] == 2, report
    assert report["counts"]["grammar_modules"] == 16, report
    assert report["counts"]["private_parity_dimensions"] == 16, report
    assert report["counts"]["public_runtime_probes"] == 12, report
    assert report["counts"]["paired_parity_priorities"] == 16, report
    assert report["counts"]["raid_required_modules"] == 3, report
    assert report["counts"]["raid_conditional_modules"] == 6, report
    assert report["counts"]["chunk_alignment_offsets"] == 256, report
    assert report["current_state"]["field_ready_advanced_extremecraft_cannon_exists"] is False
    assert report["current_state"]["fifteen_chunk_raid_program_exists"] is True
    assert report["current_state"]["fifteen_chunk_regen_raid_capability_proven"] is False
    assert report["current_state"]["failed_twenty_block_scratch_merged"] is False
    assert report["raid_objective"]["buffer_depth_chunks"] == 15, report
    assert report["raid_objective"]["exact_flight_distance_blocks"] is None, report
    assert report["raid_objective"]["buffer_depth_is_projectile_distance"] is False, report
    assert report["truth_boundary"]["handoff_proves_field_readiness"] is False
    assert report["truth_boundary"]["raid_program_proves_fifteen_chunk_capability"] is False
    assert "AGENTS.md" in report["mandatory_read_order"], report
    assert "docs/EXTREMECRAFT_15_CHUNK_RAID_PROGRAM.md" in report["mandatory_read_order"], report
    json.dumps(report)

    full = mcp.tools["get_cannonlab_handoff"](include_documents=True)
    assert "documents" in full, full
    assert "No current full advanced cannon is field-ready" in full["documents"]["AGENTS.md"]
    assert "What is genuinely proven" in full["documents"]["CANNONLAB_START_HERE.md"]
    assert "five distances and counts" in full["documents"]["docs/EXTREMECRAFT_15_CHUNK_RAID_PROGRAM.md"]

    print("PASS get_cannonlab_handoff structured raid-aware summary")
    print("PASS get_cannonlab_handoff optional raid documents")


if __name__ == "__main__":
    main()
