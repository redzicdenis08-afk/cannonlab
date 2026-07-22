# CannonLab MCP

This local MCP exposes CannonLab's evidence tools to an AI client.

## Install

```bash
cd mcp-server
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python server.py
```

On Windows, use `.venv\\Scripts\\python.exe`.

The server uses stdio by default and never connects to ExtremeCraft. Paths are jailed to the CannonLab repository.

## Tools

- `inspect_cannon`: static format, chunk, block-entity and functional-component analysis
- `explain_shot`: converts `causal-events.csv` into firing cohorts and a compact timeline
- `query_timeline`: filters exact events by tick and event type
- `list_shot_traces`: lists local runtime evidence
- `compare_shots`: compares two traces without pretending a subsystem role is proven

## Truth boundary

Static geometry can confirm blocks, orientations, connectivity and chunk pressure. It cannot prove that a bank is a charge, hammer, booster, nuke or OSRB stage. Runtime traces provide firing order and entity motion. ExtremeCraft readiness still requires a live canary because its private configuration and plugins are not public.
