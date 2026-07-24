# CannonLab MCP

This local MCP exposes CannonLab's evidence tools to an AI client.

## Install

```bash
cd mcp-server
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/cannonlab-mcp
```

On Windows, use `.venv\Scripts\cannonlab-mcp.exe`.

The server uses stdio by default and never connects to ExtremeCraft. Paths are jailed to the CannonLab repository.

## Fast path

Use one of these before spending time on runtime tests:

- `fast_cannon_intake`: one call for format/limit audit, functional and module mapping, and anti-pancake geometry profiling against real reference cannons
- `profile_cannon`: rapidly compare a candidate with one or more decoded references and reject fake-modern geometry
- `prepare_reference_cannon`: convert a proven Litematica or Sponge source into deterministic Sponge v2, then audit and profile the exact output
- `audit_cannon_ratio`: parse authored 384/OSRB ratios, preserve uncertain timing tokens, account base versus attachment payload, and compare profiles
- `analyze_impulse_graph`: identify the first motion-level divergence between real reference and candidate traces without inventing one source for ambiguous stacked explosions
- `plan_cannon_synthesis`: select hash-verified modules, join declared ports, scan EC160 alignments, and optionally compile the strongest assembly candidate
- `list_advanced_cannon_profiles`: inventory ratio, parity, archetype and synthesis profiles with explicit truth boundaries
- `audit_paste_alignment`: translate schematic-minimum chunk scans into the actual WorldEdit player paste-point frame, including `WEOffsetX/Z`
- `audit_scenario_integrity`: expose lab assists and weak evidence gates before a result is promoted
- `map_cannon_modules`: map bank-centered modules, exact repeated lanes, controls, timing parts, directional links, and conservative role candidates
- `check_cannon_preservation`: fail closed when an edit exceeds its declared block, module, control, fluid, dispenser-bank, block-entity, or alignment-confidence budget
- `compare_cannon_modules`: find exact translated module families and clearly labeled feature-level near matches across two designs
- `compare_cannon_cores`: recover exact translated partial functional cores even when bank-centric module boundaries differ, while rejecting generic dispenser-panel overlap
- `analyze_module_trace`: join a real schematic to `causal-events.csv`, recover observed module phases, correlate spawned entities, and capture spawn velocity, fuse, and explosion positions for unambiguous UUIDs
- `compare_module_traces`: enforce translation-normalized runtime contract v3 for exclusive modules plus fully accounted shared-component and joint entity-source cohorts
- `analyze_repair_family`: screen every repair by run metrics, spend exact geometry on the strongest metric candidates, then spend full causal replay only on the strongest bounded candidates; candidates skipped by either evidence budget remain non-promotable
- `extend_repair_family_runtime`: add causal replay to a requested runtime-rank window from an existing tournament without paying the metric and geometry cost again

For modern raid work, pass the strongest real reference cannons available and use `intent=modern-raid`. Small field-calibration cannons must use `intent=calibration` so the morphology gate does not pretend every valid diagnostic build needs full raid-cannon complexity.

## All tools

- `inspect_cannon`: static format, chunk, block-entity, functional-component, and module analysis
- `fast_cannon_intake`: combined fast audit, structural map, reference comparison, and next-action verdict
- `audit_paste_alignment`: safe player chunk-local paste offsets plus separate block-entity pressure
- `audit_scenario_integrity`: field-candidate and readiness eligibility for one runtime scenario
- `map_cannon_modules`: conservative module boundaries and exact translation-family detection without invented runtime roles
- `check_cannon_preservation`: exact reference-to-candidate structural and block-entity diff, module impact map, alignment confidence, risk score, and fail-closed policy verdict
- `compare_cannon_modules`: exact whole-module families plus conservative unmatched/near-match analysis
- `compare_cannon_cores`: translation-voted partial-core overlap with connectedness, mechanism-diversity, and generic-bank rejection gates
- `analyze_module_trace`: exact component-to-module runtime mapping, shared-component ambiguity, and bounded entity-source physics correlations
- `compare_module_traces`: exact-geometry replay contracts with source accounting, shared-component timing, joint source dispensers, velocity, fuse, impact, and allowed-change controls
- `analyze_repair_family`: transparent repair scoring, Pareto-front ranking, promotion blockers, and deterministic collateral-drift summaries
- `audit_cannon_ratio`: authored timing/order evidence, base-stack accounting and profile comparison
- `analyze_impulse_graph`: source-to-motion graphing and first-divergence comparison
- `plan_cannon_synthesis`: evidence-gated module assembly and deterministic candidate compilation
- `list_advanced_cannon_profiles`: machine-readable advanced profile inventory
- `profile_cannon`: structural morphology and real-reference comparison without inventing subsystem roles
- `prepare_reference_cannon`: deterministic Sponge v2 conversion plus output audit and geometry profile
- `audit_cannon_corpus`: batch-compares a private folder of `.schem` and `.litematic` designs without publishing the files
- `explain_shot`: converts `causal-events.csv` into firing cohorts and a compact timeline
- `analyze_shot_quality`: scores trigger latency, firing cohorts, target convergence, falling payload and cannon self-damage
- `audit_ec_calibration`: requires the full hash-backed 16-dimension ExtremeCraft parity evidence contract; legacy eight-probe packs remain fail closed
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
