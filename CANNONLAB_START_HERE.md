# CannonLab: start here

Verified against `main` after merged PR `#45` on 2026-07-25.

CannonLab is a layered cannon research system, not one plugin plus a folder of schematics. A fresh AI should call `get_cannonlab_handoff`, read `AGENTS.md`, then use this document to find the correct evidence and tools before changing geometry.

## The repository in one sentence

CannonLab can intake schematics, audit legal placement, build pinned runtimes, execute controlled shots, record per-tick causal evidence, model defenses, compare modules, synthesize bounded candidates, generate causal repairs, run staged campaigns, plan private-server parity experiments, and plan a fail-closed fifteen-chunk raid qualification program. It still cannot honestly claim a field-ready advanced ExtremeCraft raid cannon without missing private-server evidence and successful module composition.

## Capability map

### Runtime laboratory

CannonLab can build its Java 25 plugin, build pinned public Sakura 26.1.2, boot isolated servers, paste exact Sponge v2 schematics, settle and fill dispensers, fire real redstone inputs, preserve one physical cannon across repeated shots, and export shot/run artifacts.

Start with `src/`, `scripts/build-sakura-26.1.2.sh`, `scripts/cloud-smoke.sh`, `scenarios/` and `README.md`.

For private movement/exploit-stack parity, also read `docs/PHASELAB_STACK_PARITY.md`, inspect `profiles/phaselab/extremecraft-plugin-stack-observed-v1.json`, and use `scripts/phaselab_stack_audit.py`. Unknown private plugin versions are blockers, not invitations to install arbitrary latest releases.

### Schematic and placement forensics

The intake layer supports Sponge v2 and Litematica, deterministic compatible conversion, block-state and block-entity checks, redstone support checks, dispenser counts, separate block-entity pressure, and all 256 X/Z chunk-local placement offsets.

Start with `scripts/schem-audit.py`, `scripts/paste-alignment-audit.py` and `docs/LITEMATICA_CONVERSION.md`.

Static correctness and legal placement do not prove firing behavior.

### Scenario and defense contracts

The runtime can build dry, watered, regeneration, filter, slab-filter, hotdog and pillar defenses with directional placement, offsets, durability rules, regeneration delay/interval/caps, range gates, lane gates, fusion gates, survival gates and one-paste endurance.

Start with `scripts/scenario-integrity-audit.py`, `docs/DEFENSE_MODELS.md`, `docs/EXTREMECRAFT_CALIBRATION.md` and `scenarios/`.

Deterministic local defense models are not automatically the private ExtremeCraft regeneration implementation.

### Per-tick telemetry and causal analysis

CannonLab records TNT and falling-block positions, velocity, fuse, explosions, target events, falling-payload overlap, cannon integrity and control events. It can compare exact trajectories, build explosion-to-entity impulse graphs, attribute events to modules, and identify the first divergence.

Start with:

- `scripts/classify-cannon-run.py`
- `scripts/analyze-impulse-graph.py`
- `scripts/compare-entity-trajectories.py`
- `scripts/analyze-module-trace.py`
- `scripts/compare-module-traces.py`
- `scripts/analyze-breach-evidence.py`

Telemetry explains a local run. It does not import private EC mechanics into the laboratory.

### Cannon grammar

The machine-readable grammar defines sixteen evidence-gated modules:

1. charge force;
2. payload;
3. guider or realignment;
4. slab/drop bust;
5. held sand release;
6. hammer;
7. sand compression;
8. hybrid fusion;
9. scatter;
10. one-shot cycle;
11. double tap;
12. OSRB;
13. nuke;
14. reverse;
15. left/right shot;
16. bypass/pseudo variants.

Each module declares dependencies, outputs, minimum evidence and failure signals. Names never prove behavior.

Start with `profiles/grammar/modern-factions-cannon-grammar-v1.json`, `docs/CANNON_GRAMMAR_AND_PARITY.md`, `scripts/plan-cannon-module-campaign.py` and `profiles/campaigns/module-proof-request-template-v1.json`.

### Public Sakura mechanics contract

The pinned public runtime contract separates three identities:

- schematic DataVersion `3465`;
- Sakura/Minecraft runtime `26.1.2`;
- independently configurable cannon mechanics target.

It records source-backed public defaults and requires twelve behavioral probes for settings that materially affect cannoning.

Start with `profiles/parity/sakura-26.1.2-cannon-contract.json`, `scripts/verify-sakura-cannon-contract.py` and `docs/CANNON_GRAMMAR_AND_PARITY.md`.

### Private ExtremeCraft parity

The private profile contains sixteen independently variable dimensions, including TNT spread and fuse, dispenser ordering, collision axis behavior, water motion, velocity/removal limits, explosion batching, falling blocks, piston/observer behavior, chunk crossing, dispenser and block-entity limits, durability, regeneration, OSRB clipping and field workflow.

Start with:

- `profiles/parity/extremecraft-private-parity-required-v1.json`
- `profiles/parity/extremecraft-parity-probe-priorities-v1.json`
- `scripts/plan-cannon-parity-campaign.py`
- `docs/CANNON_PARITY_CAMPAIGNS.md`

A plan is not a measurement. Every field dimension still needs raw, dated, hash-bound evidence and local comparison.

### Fifteen-chunk raid qualification

CannonLab has a dedicated fail-closed program for the long-term fifteen-chunk regeneration objective.

It keeps these values independent:

- buffer depth in chunks;
- exact muzzle-to-first-target distance in blocks;
- exact muzzle-to-core distance in blocks;
- regeneration depth in chunks;
- wall-group count and target heights.

Fifteen chunks is not automatically a 240-block shot, a wall count or a regeneration depth. The planner blocks downstream qualification until the exact raid lane, current rules, private mechanics and module evidence are supplied.

Start with:

- `profiles/raid/extremecraft-15-chunk-regen-objective-v1.json`
- `scripts/plan-extremecraft-raid-program.py`
- `docs/EXTREMECRAFT_15_CHUNK_RAID_PROGRAM.md`
- `research/sources/extremecraft-raid-sources-v1.json`
- MCP tool `plan_extremecraft_raid_program`

The program orders work through private parity, course survey, module proof, one external cell, one chunk, three chunks, measured regen depth, full fifteen-chunk course, one-paste endurance and a controlled field canary.

### Module mapping and preservation

The forensic layer maps dispenser-bank-centered modules, controls, repeat families, directional endpoints and support risks. Candidate edits are checked against exact references with bounded module ownership and runtime trace preservation.

Start with `scripts/cannon-module-map.py`, `scripts/compare-cannon-modules.py`, `scripts/compare-cannon-cores.py`, `scripts/cannon-preservation-check.py` and `scripts/promote-cannon-component.py`.

A cropped or promoted component remains a candidate until assembled runtime evidence proves it.

### Synthesis and bounded repair

The synthesis layer assembles only hash-verified components with declared ports. Repair generation consumes the first measured divergence and produces finite, predeclared changes under EC160 and preservation gates.

Start with `scripts/cannon-synthesis-planner.py`, `scripts/generate-causal-repair-family.py`, `scripts/analyze-repair-family.py`, `scripts/extend-repair-family-runtime.py` and the `profiles/synthesis/`, `profiles/components/` and `profiles/repairs/` directories.

Generated candidates are not winners until identical runtime campaigns prove them.

### Staged campaign execution

The campaign runner delivers every exact candidate before testing, performs static gates, respects runtime budgets, builds once, tests bounded survivors, preserves evidence for failures and supports plan/static/execute modes.

Start with `scripts/run-cannon-campaign.py`, `profiles/campaigns/` and `docs/CANNON_CAMPAIGNS.md`.

### Public architecture corpus

CannonLab securely fetches exact pinned public legacy sources, audits them without silently modernizing numeric IDs, maps local and global architecture, performs metadata-aware overlap analysis and preserves derived evidence without redistributing raw files when licensing is unclear.

Start with `research/public-corpus/`, `evidence/public-corpus/`, `docs/PUBLIC_CANNON_CORPUS.md` and `docs/LEGACY_SHARED_CORE_AUDIT.md`.

Known result: the public corpus provides architecture evidence. All six audited sources violate the field-reported EC160 limit unchanged, and no shared region was promoted as a proven subsystem.

### MCP interface for AIs

The production advanced MCP currently exposes eleven tools:

- `get_cannonlab_handoff`
- `plan_extremecraft_raid_program`
- `audit_cannon_ratio`
- `analyze_impulse_graph`
- `plan_cannon_synthesis`
- `promote_cannon_component`
- `generate_causal_repair_family`
- `run_cannon_campaign`
- `classify_cannon_failure`
- `verify_sakura_cannon_contract`
- `list_advanced_cannon_profiles`

Start with `mcp-server/advanced_server.py`, `mcp-server/advanced_tools.py`, `mcp-server/handoff_tools.py`, `mcp-server/raid_tools.py` and `.github/workflows/advanced-cannon-mcp.yml`.

## What is genuinely proven

- deterministic audited Sponge v2/Litematica intake;
- all-256-offset EC160 scans;
- exact paste-frame reporting;
- real Paper and pinned public-Sakura runtime execution;
- per-tick TNT/falling-block telemetry;
- exact 79-tick TNT lifetime checks in pinned runs;
- one-paste endurance plumbing;
- native public-Sakura four-hit obsidian calibration;
- defense construction and deterministic regeneration simulation;
- strict scenario and evidence gates;
- public corpus provenance, static forensics and architecture comparison;
- production MCP execution for advanced evidence tools;
- a sixteen-module grammar and sixteen-dimension private parity campaign planner;
- a fail-closed, dependency-ordered fifteen-chunk raid research program.

## What is not proven

- complete private ExtremeCraft mechanics parity;
- the current exact buffer, regen, cannon-speed and cannon-rule profile;
- a reusable causal guider, hammer, compressor or hybrid module under EC conditions;
- a field-ready watered-wall one-stacker;
- OSRB, nuke, reverse, left/right, slab-bust or bypass operation on current EC;
- a legal advanced cannon capable of penetrating a fifteen-chunk regeneration base;
- exact private FAWE block-entity limits;
- exact private regeneration algorithm and rate;
- a completed one-chunk, three-chunk or full-course qualification run.

## Important history

High-value merged milestones include:

- PR `#24`: hash-backed sixteen-dimension EC parity evidence;
- PR `#25`: evidence-backed component promotion;
- PR `#27`: bounded repairs from first divergence;
- PR `#28`: one-paste endurance and public-Sakura durability;
- PR `#30`: production MCP execution fix;
- PR `#31`: staged campaign execution;
- PRs `#33` to `#36`: secure public corpus and metadata-aware architecture forensics;
- PR `#43`: Sakura contract, grammar and causal failure classifier;
- PR `#44`: paired parity and dependency-ordered module campaigns;
- PR `#45`: mandatory AI handoff and production MCP handoff tool.

Rejected history matters too:

- PR `#41` was closed unmerged. Its twenty-block scratch cannon proved that raw range can coexist with lane divergence, absent sand fusion, untouched target durability and severe self-damage.
- Open older research PRs must be treated as unreviewed or stale until compared against current `main` and current truth boundaries.

## Correct response to common requests

### “Build a one-stacker”

Do not draw a monolith. Plan and prove charge, payload, lane control, held sand, hammer, fusion and target interaction independently, then compose them.

### “Fix this cannon”

Map the exact reference, run it unchanged, classify the first divergence, preserve unaffected modules, generate bounded repairs, and compare identical traces.

### “Raid a fifteen-chunk regen base”

Run `plan_extremecraft_raid_program`. Measure the exact course and current rules, complete the private parity profile, prove the dependency-expanded modules, and qualify from one external cell through the full course. A filename containing `384`, `OSRB` or `NUKE` is not evidence.

### “Send the schematic quickly”

Only send a candidate when its claimed capability passed the appropriate contract. Otherwise send the honest failure diagnosis, not a cannon-shaped lottery ticket.

## Fresh-AI checklist

Before making the first edit, a fresh AI should be able to answer:

- Which facts are field-verified, field-reported, local-runtime, static, inferred or unknown?
- Which three version identities control a run?
- Which private parity dimensions are still unknown?
- What are the exact flight distance, wall-group count, regen depth, target heights and lane?
- Which modules does the requested architecture require?
- Which module is the first unproven dependency?
- Which existing component or architecture specimen is the source?
- What static, local causal, endurance and field gates are required?
- What result would force the candidate to be rejected rather than published?

If any answer is missing, research or measure it before modifying geometry.
