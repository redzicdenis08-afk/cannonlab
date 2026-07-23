# CannonLab MCP

This local MCP exposes CannonLab's evidence tools to an AI client.

## Install

```bash
cd mcp-server
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python server.py
```

On Windows, use `.venv\Scripts\python.exe`.

The server uses stdio by default and never connects to ExtremeCraft. Paths are jailed to the CannonLab repository.

## Fast path

Use one of these before spending time on runtime tests:

- `fast_cannon_intake`: one call for format/limit audit, functional mapping, and anti-pancake geometry profiling against real reference cannons
- `profile_cannon`: rapidly compare a candidate with one or more decoded references and reject fake-modern geometry
- `prepare_reference_cannon`: convert a proven Litematica or Sponge source into deterministic Sponge v2, then audit and profile the exact output

For modern raid work, pass the strongest real reference cannons available and use `intent=modern-raid`. Small field-calibration cannons must use `intent=calibration` so the morphology gate does not pretend every valid diagnostic build needs full raid-cannon complexity.

## All tools

- `inspect_cannon`: static format, chunk, block-entity and functional-component analysis
- `fast_cannon_intake`: combined fast audit, structural map, reference comparison, and next-action verdict
- `profile_cannon`: structural morphology and real-reference comparison without inventing subsystem roles
- `prepare_reference_cannon`: deterministic Sponge v2 conversion plus output audit and geometry profile
- `audit_cannon_corpus`: batch-compares a private folder of `.schem` and `.litematic` designs without publishing the files
- `explain_shot`: converts `causal-events.csv` into firing cohorts and a compact timeline
- `analyze_shot_quality`: scores trigger latency, firing cohorts, target convergence, falling payload and cannon self-damage
- `audit_ec_calibration`: refuses an EC-calibrated label until every required live evidence probe is present and valid
- `query_timeline`: filters exact events by tick and event type
- `list_shot_traces`: lists local runtime evidence
- `compare_shots`: compares two traces without pretending a subsystem role is proven

## Exact target schematics

Runtime scenarios may use either generated `target.stages` or an exact Sponge v2 defense schematic:

```yaml
target:
  file: captured-hotdog-course.schem
  origin: {x: 160, y: 0, z: 0}
  direction: east
  regeneration:
    enabled: false
```

Put private target files under `plugins/CannonLab/targets` for a local server. CI fixtures live as `targets/*.schem.b64`. The target is pasted block-for-block and every solid block becomes a tracked target cell. Use generated stages when deliberately sweeping variables; use exact target schematics when reproducing a captured defense module.

## Truth boundary

Static geometry can confirm blocks, orientations, connectivity and chunk pressure. It cannot prove that a bank is a charge, hammer, booster, nuke, rev-worm or OSRB stage. Runtime traces provide firing order and entity motion. Public Paper/Sakura tests do not prove ExtremeCraft parity. `docs/EC_READINESS_LEVELS.md` defines the evidence needed before any candidate can be labeled EC-ready.
