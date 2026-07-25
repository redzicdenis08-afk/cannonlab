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
    assert report["schema_version"] == 1, report
    assert report["counts"]["grammar_modules"] == 16, report
    assert report["counts"]["private_parity_dimensions"] == 16, report
    assert report["counts"]["public_runtime_probes"] == 12, report
    assert report["counts"]["paired_parity_priorities"] == 16, report
    assert report["counts"]["chunk_alignment_offsets"] == 256, report
    assert report["current_state"]["field_ready_advanced_extremecraft_cannon_exists"] is False
    assert report["current_state"]["failed_twenty_block_scratch_merged"] is False
    assert report["truth_boundary"]["handoff_proves_field_readiness"] is False
    assert "AGENTS.md" in report["mandatory_read_order"], report
    json.dumps(report)

    full = mcp.tools["get_cannonlab_handoff"](include_documents=True)
    assert "documents" in full, full
    assert "No current full advanced cannon is field-ready" in full["documents"]["AGENTS.md"]
    assert "What is genuinely proven" in full["documents"]["CANNONLAB_START_HERE.md"]

    print("PASS get_cannonlab_handoff structured summary")
    print("PASS get_cannonlab_handoff optional documents")


if __name__ == "__main__":
    main()
