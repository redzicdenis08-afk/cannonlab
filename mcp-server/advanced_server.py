from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import server as base
from advanced_tools import register_advanced_tools


def _advanced_run_json(
    script: Path,
    args: list[str],
    *,
    allowed_exit_codes: tuple[int, ...] = (0,),
    timeout: int = 180,
) -> dict[str, Any]:
    """Adapt advanced tools to the production server runner without hiding exit-code contracts."""
    payload = base._run_json(
        [sys.executable, str(script), *args],
        timeout=timeout,
    )
    exit_code = int(payload.get("_exit_code", -1))
    if exit_code not in allowed_exit_codes:
        raise RuntimeError(
            f"advanced CannonLab tool {script.name} returned exit code {exit_code}; "
            f"allowed={allowed_exit_codes}"
        )
    return payload


REGISTERED_ADVANCED_TOOLS = register_advanced_tools(
    base.mcp,
    root=base.ROOT,
    scripts=base.SCRIPTS,
    inside_root=base._inside_root,
    run_json=_advanced_run_json,
)

mcp = base.mcp
main = base.main


if __name__ == "__main__":
    main()
