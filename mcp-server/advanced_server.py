from __future__ import annotations

import server as base
from advanced_tools import register_advanced_tools

REGISTERED_ADVANCED_TOOLS = register_advanced_tools(
    base.mcp,
    root=base.ROOT,
    scripts=base.SCRIPTS,
    inside_root=base._inside_root,
    run_json=base._run_json,
)

mcp = base.mcp
main = base.main


if __name__ == "__main__":
    main()
