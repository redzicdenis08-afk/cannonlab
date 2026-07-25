# CannonLab: start here

Verified against `main` after merged PRs `#43` and `#44` on 2026-07-25.

CannonLab is no longer one Minecraft plugin plus a few test schematics. It is a layered cannon research system. This document maps those layers, their entry points, and their proof limits so a fresh AI can understand the repository before changing geometry.

## The repository in one sentence

CannonLab can intake schematics, audit legal placement, build pinned runtimes, execute controlled shots, record per-tick causal evidence, model defenses, compare modules, synthesize bounded candidates, generate causal repairs, run staged campaigns, and plan private-server parity experiments. It still cannot honestly claim a field-ready advanced ExtremeCraft raid cannon without missing private-server evidence and successful module composition.

## Capability map

### 1. Runtime laboratory

CannonLab can build its Java 25 plugin, build pinned public Sakura 26.1.2, boot isolated servers, paste exact Sponge v2 schematics, settle and fill dispensers, fire real redstone inputs, preserve one physical cannon across repeated shots, and export shot/run artifacts.

Primary entry points:

- `src/`
- `scripts/build-sakura-26.1.2.sh`
- `scripts/cloud-smoke.sh`
- `scenarios/`
- `README.md`

### 2. Schematic and placement forensics

The intake layer supports Sponge v2 and Litematica, deterministic compatible conversion, block-state and block-entity checks, redstone support checks, dispenser counts, separate block-entity pressure, and all 256 X/Z chunk-local placement offsets.

Primary entry points:

- `scripts/schem-audit.py`
- `scripts/paste-alignment-audit.py`
- `docs/LITEMATICA_CONVERSION.md`

Proof limit: static correctness and legal placement do not prove firing behavior.

### 3. Scenario and defense contracts

The runtime can build dry, watered, regeneration, filter, slab-filter, hotdog and pillar defenses with directional placement, offsets, durability rules, regeneration delay/interval/caps, range gates, lane gates, fusion gates, survival gates and one-paste endurance.

Primary entry points:

- `scripts/scenario-integrity-audit.py`
- `docs/DEFENSE_MODELS.md`
- `docs/EXTREMECRAFT_CALIBRATION.md`
- `scenarios/`

Proof limit: deterministic local defense models are not automatically the private ExtremeCraft regeneration implementation.

### 4. Per-tick telemetry and causal analysis

CannonLab records TNT and falling-block positions, velocity, fuse, explosions, target events, falling-payload overlap, cannon integrity and control events. It can compare exact trajectories, build explosion-to-entity impulse graphs, attribute events to modules, and identify the first divergence.

Primary entry points:

- `scripts/classify-cannon-run.py`
- `scripts/analyze-impulse-graph.py`
- `scripts/compare-entity-trajectories.py`
- `scripts/analyze-module-trace.py`
- `scripts/compare-module-traces.py`
- `scripts/analyze-breach-evidence.py`

Proof limit: telemetry explains a local run. It does not import private EC mechanics into the laboratory.

### 5. Cannon grammar

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

Primary entry points:

- `profiles/grammar/modern-factions-cannon-grammar-v1.json`
- `docs/CANNON_GRAMMAR_AND_PARITY.md`
- `scripts/plan-cannon-module-campaign.py`
- `profiles/campaigns/module-proof-request-template-v1.json`

### 6. Public Sakura mechanics contract

The pinned public runtime contract separates three identities:

- schematic DataVersion `3465`;
- Sakura/Minecraft runtime `26.1.2`;
- independently configurable cannon mechanics target.

It records source-backed public defaults and requires behavioral probes for settings that materially affect cannoning.

Primary entry points:

- `profiles/parity/sakura-26.1.2-cannon-contract.json`
- `scripts/verify-sakura-cannon-contract.py`
- `docs/CANNON_GRAMMAR_AND_PARITY.md`

### 7. Private ExtremeCraft parity

The private profile contains sixteen independently variable dimensions, including TNT spread and fuse, dispenser ordering, collision axis behavior, water motion, velocity/removal limits, explosion batching, falling blocks, piston/observer behavior, chunk crossing, dispenser and block-entity limits, durability, regeneration, OSRB clipping and field workflow.

Primary entry points:

- `profiles/parity/extremecraft-private-parity-required-v1.json`
- `profiles/parity/extremecraft-parity-probe-priorities-v1.json`
- `scripts/plan-cannon-parity-campaign.py`
- `docs/CANNON_PARITY_CAMPAIGNS.md`

Proof limit: a plan is not a measurement. Every field dimension still needs raw, dated, hash-bound evidence and local comparison.

### 8. Module mapping and preservation

The forensic layer maps dispenser-bank-centered modules, controls, repeat families, directional endpoints and support risks. Candidate edits are checked against exact references with bounded module ownership and runtime trace preservation.

Primary entry points:

- `scripts/cannon-module-map.py`
- `scripts/compare-cannon-modules.py`
- `scripts/compare-cannon-cores.py`
- `scripts/cannon-preservation-check.py`
- `scripts/promote-cannon-component.py`

Proof limit: a cropped or promoted component remains a candidate until assembled runtime evidence proves it.

### 9. Synthesis and bounded repair

The synthesis layer assembles only hash-verified components with declared ports. Repair generation consumes the first measured divergence and produces finite, predeclared changes under EC160 and preservation gates.

Primary entry points:

- `scripts/cannon-synthesis-planner.py`
- `scripts/generate-causal-repair-family.py`
- `scripts/analyze-repair-family.py`
- `scripts/extend-repair-family-runtime.py`
- `profiles/synthesis/`
- `profiles/components/`
- `profiles/repairs/`

Proof limit: generated candidates are not winners until identical runtime campaigns prove them.

### 10. Staged campaign execution

The campaign runner delivers every exact candidate before testing, performs static gates, respects runtime budgets, builds once, tests bounded survivors, preserves evidence for failures and supports plan/static/execute modes.

Primary entry points:

- `scripts/run-cannon-campaign.py`
- `profiles/campaigns/`
- `docs/CANNON_CAMPAIGNS.md`

### 11. Public architecture corpus

CannonLab securely fetches exact pinned public legacy sources, audits them without silently modernizing numeric IDs, maps local and global architecture, performs metadata-aware overlap analysis and preserves derived evidence without redistributing raw files when licensing is unclear.

Primary entry points:

- `research/public-corpus/`
- `evidence/public-corpus/`
- `docs/PUBLIC_CANNON_CORPUS.md`
- `docs/LEGACY_SHARED_CORE_AUDIT.md`

Known result: the public corpus provides architecture evidence. All six audited sources violate the field-reported EC160 limit unchanged, and no shared region was promoted as a proven subsystem.

### 12. MCP interface for AIs

The production advanced MCP currently exposes nine tools:

- `audit_cannon_ratio`
- `analyze_impulse_graph`
- `plan_cannon_synthesis`
- `promote_cannon_component`
- `generate_causal_repair_family`
- `run_cannon_campaign`
- `classify_cannon_failure`
- `verify_sakura_cannon_contract`
- `list_advanced_cannon_profiles`

Primary entry points:

- `mcp-server/advanced_server.py`
- `mcp-server/advanced_tools.py`
- `.github/workflows/advanced-cannon-mcp.yml`

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
- production MCP execution for the advanced evidence tools;
- a sixteen-module grammar and sixteen-dimension private parity campaign planner.

## What is not proven

- complete private ExtremeCraft mechanics parity;
- a reusable causal guider, hammer, compressor or hybrid module under EC conditions;
- a field-ready watered-wall one-stacker;
- OSRB, nuke, reverse, left/right, slab-bust or bypass operation on current EC;
- a legal advanced cannon capable of penetrating a fifteen-chunk regeneration base;
- exact private FAWE block-entity limits;
- exact private regeneration algorithm and rate.

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
- PR `#44`: paired parity and dependency-ordered module campaigns.

Rejected history matters too:

- PR `#41` was closed unmerged. Its twenty-block scratch cannon proved that raw range can coexist with lane divergence, absent sand fusion, untouched target durability and severe self-damage.
- Open older research PRs must be treated as unreviewed or stale until compared against current `main` and current truth boundaries.

## Correct response to common requests

### “Build a one-stacker”

Do not draw a monolith. Plan and prove charge, payload, lane control, held sand, hammer, fusion and target interaction independently, then compose them.

### “Fix this cannon”

Map the exact reference, run it unchanged, classify the first divergence, preserve unaffected modules, generate bounded repairs, and compare identical traces.

### “Raid a fifteen-chunk regen base”

First require the private parity profile, exact defense course, field workflow, legal dispenser distribution, proven modules, endurance and a controlled field canary. A filename containing `384`, `OSRB` or `NUKE` is not evidence.

### “Send the schematic quickly”

Only send a candidate when its claimed capability passed the appropriate contract. Otherwise send the honest failure diagnosis, not a cannon-shaped lottery ticket.

## Fresh-AI checklist

Before making the first edit, a fresh AI should be able to answer:

- Which facts are field-verified, field-reported, local-runtime, static, inferred or unknown?
- Which three version identities control a run?
- Which private parity dimensions are still unknown?
- Which modules does the requested architecture require?
- Which module is the first unproven dependency?
- Which existing component or architecture specimen is the source?
- What is the exact target distance and independent target fixture?
- What static, local causal, endurance and field gates are required?
- What result would force the candidate to be rejected rather than published?

If any answer is missing, research or measure it before modifying geometry.