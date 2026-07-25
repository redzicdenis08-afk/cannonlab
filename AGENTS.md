# CannonLab AI operating contract

This file is the mandatory entry point for any AI or contributor working on CannonLab.

## Read order

Before designing, repairing, converting, rating, or publishing a cannon, read these files in order:

1. `CANNONLAB_START_HERE.md`
2. `README.md`
3. `docs/CANNON_GRAMMAR_AND_PARITY.md`
4. `docs/CANNON_PARITY_CAMPAIGNS.md`
5. `profiles/parity/extremecraft-private-parity-required-v1.json`
6. `profiles/parity/sakura-26.1.2-cannon-contract.json`
7. `profiles/grammar/modern-factions-cannon-grammar-v1.json`
8. `docs/EXTREMECRAFT_CALIBRATION.md`

When the CannonLab MCP is available, call `get_cannonlab_handoff` before any other advanced cannon tool. Use `include_documents=true` when the current session has not already read this file and `CANNONLAB_START_HERE.md`.

When exact historical hashes, timings, coordinates, field reports, or experiment results matter, inspect the relevant evidence file, workflow artifact, merged pull request, or raw trace. Do not reconstruct exact facts from filenames or memory.

## Current truth snapshot

- CannonLab is a serious automated laboratory and evidence pipeline.
- CannonLab is not yet a proven advanced ExtremeCraft raid-cannon factory.
- No current full advanced cannon is field-ready for a fifteen-chunk regen base.
- The field-verified pocket counter is a dry-wall calibration fixture, not proof of water, regen, OSRB, nuke, leftshot, slab-bust, or full-raid capability.
- Public Paper or pinned public Sakura results are local evidence only.
- Private ExtremeCraft configuration and patches remain incomplete until the sixteen-dimension field fingerprint is measured.
- Sponge v2 DataVersion `3465` is a schematic serialization identity. It does not prove Minecraft 1.20.1 runtime physics.
- The pinned public laboratory runtime is Sakura 26.1.2 from exact commit `63f35d74e0fbe6bcd76c58494c01c1632c83010d`.
- Sakura's cannon mechanics target is independently configurable. Public defaults do not prove the private ExtremeCraft value.
- The current dispenser rule is field-reported as 160 dispensers per X/Z chunk column. Scan all 256 player chunk-local X/Z offsets and report block-entity pressure separately.

## Evidence labels

Use these meanings consistently:

- `field-verified`: reproduced by the operator on ExtremeCraft with exact evidence.
- `field-reported`: reported from live play but not independently measured in CannonLab.
- `local-runtime`: reproduced on Paper or pinned public Sakura.
- `static`: derived from schematic bytes or geometry without firing proof.
- `inference`: reasoned from evidence but not directly measured.
- `unknown`: not established.

Never silently promote an item to a stronger label.

## Non-negotiable design rules

1. A target wall must be a separate runtime fixture, not embedded beside the cannon to manufacture a pass.
2. Obey the requested muzzle-to-target distance and prove the clear corridor geometrically.
3. Do not call a design a stacker because it contains sand. Prove held-to-falling release, hammer impulse, compression or stack formation, payload-sand overlap, and target interaction as required by the requested architecture.
4. Do not diagnose every failure as timing. Classify range, lane, fuse, sand release, sand range, sand lane, fusion, durability, regeneration, self-damage, and dispenser survival separately.
5. Do not tune a downstream fuse while the payload lane is divergent.
6. Do not add TNT to hide missing charge coupling, guider, hammer, compression, or hybrid logic.
7. Static legality, filenames, signs, community names, explosions, screenshots, or green CI do not prove subsystem semantics.
8. A local winner is not ExtremeCraft-ready until the relevant field canary reproduces it.
9. Never publish a generated schematic as working when its runtime contract failed.
10. Preserve rejected attempts as evidence, but do not merge failed cannon geometry into `main` as a promoted component.

## Required workflow

For a serious cannon request:

1. Identify the target server profile, defense class, distance, height, dispenser limit, workflow, and required cannon modules.
2. Run or inspect the paired parity campaign before assuming private mechanics.
3. Expand the requested architecture through the module dependency planner.
4. Reuse only exact evidence that already meets the requested promotion level.
5. Audit the source and exact output schematic, including all 256 EC160 alignments.
6. Verify paste-frame offsets, block entities, controls, fluids, supports, and scenario integrity.
7. Prove modules in dependency order: charge, payload, guider, held sand, hammer, compression or fusion, preparation stages, then composition.
8. Run bounded local campaigns and classify the first causal failure.
9. Generate only bounded repairs tied to the first measured divergence.
10. Require one-paste endurance before field canary promotion.
11. Deliver the schematic only with its audit, scenario, controls, timing, evidence label, known limits, and exact unproven claims.

## Important tools

Advanced MCP tools currently include:

- `get_cannonlab_handoff`
- `audit_cannon_ratio`
- `analyze_impulse_graph`
- `plan_cannon_synthesis`
- `promote_cannon_component`
- `generate_causal_repair_family`
- `run_cannon_campaign`
- `classify_cannon_failure`
- `verify_sakura_cannon_contract`
- `list_advanced_cannon_profiles`

Important CLI planners and gates include:

- `scripts/plan-cannon-parity-campaign.py`
- `scripts/plan-cannon-module-campaign.py`
- `scripts/schem-audit.py`
- `scripts/paste-alignment-audit.py`
- `scripts/scenario-integrity-audit.py`
- `scripts/classify-cannon-run.py`
- `scripts/cannon-module-map.py`
- `scripts/analyze-module-trace.py`
- `scripts/compare-module-traces.py`
- `scripts/analyze-impulse-graph.py`
- `scripts/generate-causal-repair-family.py`
- `scripts/run-cannon-campaign.py`

## Branch and pull-request hygiene

- Re-check pull-request state live before citing or merging it.
- Merged PRs `#43` and `#44` established the grammar, causal classifier, parity contract, and campaign planners.
- PR `#41` was closed unmerged after the twenty-block scratch cannon failed convergence, fusion, target, and survival gates.
- Older open research PRs may be stale, based on obsolete branches, or contain rejected assumptions. Do not merge them merely because they contain more files.
- Prefer a clean branch from current `main` and a narrow evidence-backed pull request.

## Stop conditions

Stop and report honestly instead of publishing a cannon when any of these remain unresolved:

- target embedded in or too close to the cannon;
- private mechanics assumed rather than measured;
- payload does not reach the intended plane;
- payload lane exceeds tolerance;
- held sand is not released on command;
- hammer or compression lacks causal evidence;
- payload and sand do not overlap at the intended interaction;
- target durability or regeneration is untouched;
- the cannon damages itself beyond the declared contract;
- dispenser survival or one-paste endurance fails;
- the exact field workflow is unknown.

The goal is not to create cannon-shaped files quickly. The goal is to reduce uncertainty until a design survives the correct proof ladder.