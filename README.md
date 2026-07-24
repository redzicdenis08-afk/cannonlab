# CannonLab

CannonLab is an automated, headless Minecraft cannon laboratory for building, validating, firing, measuring, and ranking cannon schematics against reproducible Paper and Sakura mechanics.

## Readiness

The laboratory can:

- build the CannonLab plugin with JDK 25
- compile a pinned public Sakura 26.1.2 source commit
- boot isolated Paper or Sakura test servers with WorldEdit
- decode and audit Sponge v2 `.schem` and Litematica `.litematic` files
- convert compatible Litematica designs to Sponge v2 before runtime testing
- paste Sponge `.schem` files at exact origins
- clear only the planned cannon/flight/target corridor between shots instead of scanning the entire configured arena cube
- choose explicitly between fresh-paste reliability and preserving one physical cannon across every shot
- audit and fill every dispenser with TNT
- enforce the current user-reported ExtremeCraft limit of 160 dispensers per chunk
- test conservative or historical limits such as 128 through an explicit CLI override
- audit total and per-chunk block-entity pressure separately from dispenser limits
- map dispenser-bank-centered modules, repeated translated lanes, controls, timing parts, and directional links
- compare every candidate against its exact reference and fail closed on broad, cross-module, control, fluid, or dispenser-bank changes
- trigger one or multiple cannon inputs through real redstone power
- generate dry, watered, fluid-regen, filter, slab-filter, hotdog-lane, and staggered-pillar targets
- place targets north, south, east, or west with vertical and lateral offsets
- simulate configurable plugin-style delayed regeneration with delay, interval, and per-cycle caps
- keep all arena chunks ticking without a connected player
- record TNT and falling-block position, velocity, fuse, and explosion data every tick
- record per-explosion center material, water contact, and measured falling-payload overlap in `breach-events.csv`
- compare recorded entity motion against an independent source-audited reference-physics oracle
- diagnose first divergence as likely fuse, gravity, drag, water-push, collision, or unmodelled fork behavior
- record target destruction and regeneration events in the same CSV timeline
- measure forward travel, target miss distance, peak damage, the strongest aligned breach lane before the first actual restore, deepest layer breached, and restored blocks
- reconstruct exact per-cell durability pressure, connected wall openings, and same-lane multi-layer continuation
- attribute significant falling-payload velocity changes to nearby TNT explosions and score each impulse against the target axis
- reject flight-only, explosion-only, scattered-hit, disconnected-hole, regen-lost, and cannon-died fake greens
- compare one TNT entity tick by tick to find the first changed position, velocity, fuse, or landing point
- export per-shot and per-run JSON/CSV evidence
- rank cannon variants by reliability, penetration, errors, and repeatability
- compare local physics fingerprints against measured server fingerprints
- apply hash-stamped Paper/Sakura parity profiles instead of inheriting hidden machine state
- audit declared field observations against the active profile and fail closed on mismatches
- generate the same seven-scenario EC defense pack for every private cannon
- expose isolated `/p tntfill`, `/p gui`, and `/bonetool` workflow shims for manual testing
- scan all 256 EC160 placements before redesign and map which dispenser banks create each overloaded chunk
- propose symmetry-preserving bank-segmentation scaffolds when alignment alone cannot satisfy the limit

## Runtime gates

The CI suite contains:

- clean Java 25 compilation and plugin packaging
- one-dispenser direct and redstone plumbing tests
- a real four-dispenser cannon fixture
- one hundred consecutive redstone-triggered shots on one preserved cannon paste
- a five-scenario professional-defense matrix
- one hundred one-paste redstone endurance shots on pinned public Sakura 26.1.2
- ten four-TNT shots on pinned public Sakura 26.1.2
- exact TNT fuse continuity and lifetime checks
- unique-entity and no-leak validation between resets
- directional travel and target-proximity gates
- target-damage, layer-breach, and regeneration gates
- falling-payload overlap, unembedded-water-explosion, and regen-race gates
- direct four-hit obsidian sequences, connected-opening, same-lane continuation, impulse-axis, and dispenser-survival gates
- all 256 X/Z chunk-alignment scans
- legal, over-limit, truncated, and corrupted schematic fixtures
- download checksum verification for Paper and WorldEdit

Every runtime workflow stores logs, summaries, CSV telemetry, and physics fingerprints as GitHub Actions artifacts.

## Important ExtremeCraft boundary

CannonLab reproduces pinned public Sakura 26.1.2 code and measurable mechanics. ExtremeCraft can still use private configuration, custom plugins, anti-lag rules, FAWE permissions, durable-block values, TNT restrictions, and regeneration behavior that are not public.

The current field report is 160 dispensers per chunk. The older 128 figure is stale for ExtremeCraft, although it remains useful as an optional conservative audit threshold. ExtremeCraft also has a separate FAWE block-entity or tile-entity paste limit whose exact value is not yet verified. CannonLab therefore reports dispenser pressure and block-entity pressure independently and does not invent a numeric FAWE cap.

The built-in regeneration model is a deterministic test simulator, not a claim that every server uses the same private replacement algorithm. A cannon is not labeled ExtremeCraft-ready until it passes the local suite and a small live calibration/canary test. CannonLab does not connect to or automate actions on ExtremeCraft and contains no Minecraft credentials or session tokens.

The dated candidate profile is `profiles/extremecraft-observed.yml`. It records every requested Sakura cannon setting, the EC160 limit, the schematic workflow, evidence grade, and unresolved private mechanics. Every profiled run embeds the profile ID and SHA-256 in `run-summary.json`. See `docs/EXTREMECRAFT_PARITY.md`.

Run an EC-candidate scenario with a pinned Sakura JAR:

```powershell
$env:CANNONLAB_ACCEPT_EULA = 'TRUE'
$env:CANNONLAB_SAKURA_JAR = 'C:\path\to\sakura-26.1.2.jar'
.\scripts\run-ec-lab.ps1 -Scenario my-cannon-ec-defense-gauntlet.yml
```

Generate a consistent defense pack for a cannon:

```powershell
py scripts\make-ec-scenario-pack.py cannon.schem `
  --output-dir scenarios\generated\cannon `
  --fire-input 7,2,12 `
  --fire-mode button `
  --direction west `
  --distance 939
```

## Commands

```text
/cannonlab status
/cannonlab smoke
/cannonlab run <scenario.yml>
/cannonlab cancel
/p tntfill
/p gui
/bonetool
```

The server can autorun a scenario with:

```text
-Dcannonlab.scenario=multi-tnt-range.yml
```

## Schematic intake

Audit a field-ready Sponge schematic:

```powershell
python scripts/schem-audit.py cannon.schem --chunk-limit 160 --expect-format sponge-v2
```

Audit a Litematica file before conversion:

```powershell
python scripts/schem-audit.py cannon.litematic --chunk-limit 160 --expect-format litematic --json-out audit.json
```

Convert a compatible Litematica design to the field-verified ExtremeCraft shape, then re-audit the output:

```powershell
python scripts/schem-audit.py cannon.litematic `
  --chunk-limit 160 `
  --convert-sponge-out cannon-ec.schem `
  --output-data-version 3465 `
  --allow-data-version-retag

python scripts/schem-audit.py cannon-ec.schem `
  --chunk-limit 160 `
  --expect-format sponge-v2
```

`--allow-data-version-retag` changes the numeric DataVersion and does not run Mojang's DataFixerUpper. Use it only after confirming every block and block-state property exists in the target version. The converter preserves geometry, palette states, empty dispenser block entities, and signed Litematica region orientation, then emits deterministic gzip-compressed Sponge v2 NBT.

Use `--block-entity-limit N` only when a live server test has established a real cap. Do not guess the ExtremeCraft FAWE limit.

Convert schematic-minimum chunk offsets into the actual player `//paste` frame before publishing placement instructions:

```powershell
python scripts/paste-alignment-audit.py cannon.schem `
  --chunk-limit 160 `
  --json-out paste-alignment.json
```

Sponge `Metadata.WEOffsetX/Z` can move the schematic minimum relative to the player's paste point. The report preserves both frames and reports the safe player chunk-local X/Z offsets explicitly. It also reports block-entity pressure separately without inventing a live FAWE cap.

## Reference physics and EC160 architecture

Inspect the source-audited physics profiles:

```powershell
python scripts/cannon_physics_reference.py profiles
```

Compare one recorded CannonLab TNT trajectory to the independent motion oracle:

```powershell
python scripts/cannon_physics_reference.py compare-events `
  lab-artifacts/results/<run>/shot-001/events.csv `
  --kind tnt `
  --json-out physics-comparison.json
```

The oracle predicts empty-space TNT and falling-block motion, calculates explosion impulse, and identifies the first likely fuse, gravity, drag, water-current, or collision divergence. It deliberately does not approximate complex voxel collisions or claim private ExtremeCraft parity. See `docs/REFERENCE_PHYSICS_ORACLE.md`.

Before rebuilding a large cannon around the 160-per-chunk rule, determine whether exact placement already solves it:

```powershell
python scripts/ec160_architecture_advisor.py cannon.schem `
  --chunk-limit 160 `
  --json-out ec160-advice.json
```

The advisor scans all 256 X/Z residues, maps the dispenser banks contributing to every chunk, identifies probable opposing-panel pairs, and emits a symmetry-preserving segmentation scaffold only when no legal placement exists. It never rewrites the cannon. See `docs/EC160_ARCHITECTURE_ADVISOR.md` and `docs/EXPERT_CANNON_RESEARCH_2026.md`.

## Reference-first module preservation

Map a real cannon before editing it:

```powershell
python scripts/cannon-module-map.py reference.litematic `
  --chunk-limit 160 `
  --json-out reference-modules.json
```

The module map anchors functional components to real dispenser banks, detects exact translated module and slice families, inventories controls and timing components, measures support-gap bridge risk, and emits a static module-coupling graph from shared components, face adjacency, and directional endpoints. It never promotes a tall bank or piston cluster into a confirmed charge, hammer, nuke, OSRB, leftshot, or payload module without causal runtime evidence.

Gate a proposed edit against the exact reference:

```powershell
python scripts/cannon-preservation-check.py reference.litematic candidate.schem `
  --max-structural-change-ratio 0.03 `
  --max-functional-change-ratio 0.05 `
  --max-modules-touched 1 `
  --allow-module MODULE-003 `
  --allow-type minecraft:repeater `
  --json-out preservation.json
```

The default policy rejects unexpected critical-component edits, source-dimension changes, operator-control changes, dispenser-bank topology changes, explicit block-entity topology changes, ambiguous alignment, and edits spanning more than one inferred module. A preservation pass proves only that geometry stayed inside the declared edit budget. The candidate must still reproduce the reference firing sequence and pass runtime defense tests.

By default, the preservation gate may apply one global integer translation to align Litematica and Sponge coordinate frames. The selected translation, candidate scores, coverage, and ambiguity are reported. Ambiguous best translations fail unless explicitly allowed, and alignment confidence must be at least `medium`. Rotation, reflection, scaling, and local warping are never permitted. Use `--alignment-mode exact` when coordinate identity itself is part of the contract.

Compare two proven designs and extract only exact translated module families:

```powershell
python scripts/compare-cannon-modules.py nuke.litematic leftshot.litematic `
  --near-match-threshold 0.82 `
  --minimum-shared-core-components 8 `
  --json-out shared-core.json
```

Exact matches require the same canonical block states and relative coordinates after translation. Near matches use block-count, dimensions, dispenser, kind, and facing features and remain heuristic. Neither result proves that the modules fire in the same phase.

When two related cannons preserve a timing spine or lower machine core but attach enough extra banks to change the inferred whole-module boundaries, use the partial-core comparator:

```powershell
python scripts/compare-cannon-cores.py nuke.litematic leftshot.litematic `
  --minimum-shared-functional 16 `
  --minimum-connected-functional 8 `
  --minimum-shared-non-dispenser 8 `
  --minimum-mechanism-diversity 2 `
  --json-out translated-core.json
```

The search votes on intact local functional neighborhoods, evaluates exact canonical-state overlap under the strongest translations, and requires a connected, mechanism-diverse, non-dispenser core. Matching only a generic dispenser panel is reported but rejected as a shared-core candidate. The result is still static geometry evidence, not proof of common runtime semantics.

Join a static module map to a real shot trace:

```powershell
python scripts/analyze-module-trace.py reference.schem `
  lab-artifacts/results/shot-001/causal-events.csv `
  --json-out module-trace.json
```

The trace analyzer maps component events by exact schematic-relative coordinates, preserves equal-distance shared-module ambiguity, groups simultaneous modules into firing phases, correlates entity spawns to nearby dispense events within a bounded tick and distance window, follows unambiguous TNT UUIDs into explosions, and records source-attributed spawn and explosion cohorts with position, velocity, and fuse evidence. It deliberately emits labels such as `early-tnt-cohort-source-candidate` rather than pretending it has proven charge, booster, hammer, nuke, OSRB, leftshot, or reverse semantics.

After editing, enforce the unchanged-module runtime contract:

```powershell
python scripts/compare-module-traces.py `
  reference.schem reference-causal-events.csv `
  candidate.schem candidate-causal-events.csv `
  --max-timing-delta 2 `
  --max-spawn-position-delta 0.25 `
  --max-spawn-velocity-delta 0.02 `
  --max-explosion-position-delta 1.0 `
  --allow-reference-module MODULE-003 `
  --max-extra-active-candidate-modules 1 `
  --json-out runtime-contract.json
```

Every exact-geometry module outside the declared change set must retain its configured activation timing, event counts, dispensed items, correlated entity cohorts, spawn position, velocity, fuse, and attributed explosion timing and location. Candidate coordinates are normalized through the exact module translation, so harmless schematic padding passes while real trajectory drift fails. Runtime contract v3 does not invent one owner when multiple modules can equally source the same event or entity. It requires complete source accounting, compares shared-component event cohorts, and compares joint entity-source cohorts down to translated dispenser identities, source timing, entity counts, velocity, fuse distributions, and explosion timing. This permits legitimate shared-source ambiguity without turning missing attribution into a silent pass. A pass protects the untouched portion of the machine; it does not prove the edited module itself works.

Rank a family of bounded repair attempts instead of guessing from filenames or one lucky shot:

```powershell
python scripts/analyze-repair-family.py `
  reference.schem reference-results/run-summary.json `
  candidate-results/ `
  --cannon-directory cannons/ `
  --max-geometry-candidates 24 `
  --max-runtime-candidates 8 `
  --max-runtime-contract-runs 3 `
  --json-out repair-family.json
```

The repair-family analyzer deduplicates mirrored results by `run_id`, rejects conflicting duplicates and runs whose target, distance, layers, bounds, arena, or regeneration contract differs from the reference, then runs a three-stage tournament: cheap run-metric screening for every candidate, exact geometry for the strongest `--max-geometry-candidates`, and causal replay for the strongest `--max-runtime-candidates`. Candidates outside either evidence budget remain visible but cannot be promoted. The report exposes metric, geometry, and final score components, marks the Pareto front only among runtime-tested candidates, and only returns `PROMOTION_READY_BOUNDED_REPAIR` when the performance gain is real, the structural edit stays bounded, and untouched modules retain their runtime contract.

Extend an existing tournament without rerunning metric or geometry stages:

```powershell
python scripts/extend-repair-family-runtime.py repair-family.json `
  --runtime-rank-from 9 `
  --runtime-count 4 `
  --max-runtime-contract-runs 1 `
  --json-out repair-family-ranks-9-12.json
```

## General cannon operator

The general operator binds family planning, exact reference hashes, optional bounded mutation, architecture policy, archetype-specific payload contracts, verified control states, Forge staging, runtime assertions, and measured output-corridor repeatability into one fail-closed job.

```powershell
python scripts/cannon-operator.py prepare candidate.schem `
  --architecture-manifest architecture.json `
  --base hammered-stacker `
  --specialization hybrid `
  --specialization osrb `
  --payload-mode auto `
  --reference proven-reference.litematic `
  --fire-input 4,11,13 `
  --fire-mode button `
  --direction north `
  --distance 160 `
  --job repaired-osrb
```

For a mode lever or other exact pre-fire state, repeat `--control-state-json` with a JSON object containing `name`, `at`, `phase`, `block_data`, and preferably `expected_material` plus the complete `expected_before` state. Unknown payload interfaces, conflicting TNT-only and falling-block requirements, stale architecture manifests, broad mutations, missing runtime metrics, and unstable output direction all block the job.

`hammered-stacker`, `hammerless-stacker`, `asser-multiwave`, anti-gravity, hybrid, OSRB, overstack, reverse-hybrid, and slab-bust contracts require falling-block evidence. A source-bounded `rev-worm` can use the TNT-only campaign. Selectable or unknown families require an explicit mode or remain blocked. TNT-only success never counts as watered-defense proof.

Run the staged campaign only after the operator manifest is `PASS`:

```powershell
# Default: one-shot smoke gate. Obvious failures stop here.
python scripts/cannon-operator.py run operator-jobs/repaired-osrb/manifest.json --execute

# After smoke passes: short nine-shot cumulative qualification.
python scripts/cannon-operator.py run operator-jobs/repaired-osrb/manifest.json `
  --execute --max-tier qualify

# Full local campaign. Passed smoke/qualification stages resume by exact
# candidate, scenario, tool, runtime-JAR and CANNONLAB_* environment fingerprint.
python scripts/cannon-operator.py run operator-jobs/repaired-osrb/manifest.json `
  --execute --max-tier full
```

Inspect the exact work without starting Minecraft, or cap one operator session:

```powershell
python scripts/cannon-operator.py run operator-jobs/repaired-osrb/manifest.json `
  --max-tier full --plan-only

python scripts/cannon-operator.py run operator-jobs/repaired-osrb/manifest.json `
  --execute --max-tier qualify --wall-clock-budget-seconds 900
```

Forge static intake runs its independent schematic, alignment, map, module, and geometry checks concurrently and caches them by command plus file hashes. Bounded mutation tournaments also run unique variants concurrently, deduplicate identical rendered edits, and reuse exact cached results. Cache hits do not promote evidence: they only reuse an unchanged static or runtime contract. Changing a candidate, scenario, assertion, analysis tool, plugin/server JAR, lab home, or `CANNONLAB_*` setting invalidates the relevant runtime stage.

Allocate a whole variant tournament under one real wall-clock budget before launching Minecraft:

```powershell
python scripts/cannon-factory-budget.py `
  variant-jobs/delay-sweep/manifest.json `
  forge-jobs/reference-campaign/manifest.json `
  --budget-seconds 1800 `
  --runtime-workers 2 `
  --max-smoke 16 `
  --max-qualify 4 `
  --max-full 1
```

The planner maximizes the useful funnel that fits the budget. It can send many cheap candidates through smoke, fewer runtime survivors through qualification, and only the strongest finalists into the full campaign. Historical clean campaign summaries can replace the conservative fallback timing model. If the budget cannot carry even one candidate through the requested tier, the plan is `BLOCKED` instead of quietly overrunning.

After runtime scorecard ranking, `cannon-variant-search.py rank` writes `winner/winner-handoff.json` and copies the winning `.schem` when the exact artifact exists. The handoff contains source and copied hashes, selected mutation values, and scores. It remains a local winner only until its required Forge tier and live EC canary pass.

The general infrastructure audit can prove that the tooling surface is complete. It cannot promote a particular schematic. A candidate still needs its own repeated local runtime evidence and a recorded live ExtremeCraft canary before any EC-ready claim.

## Scenario structure

```yaml
name: modern-defense-example
cannon:
  file: cannon.schem
  origin: {x: 0, y: 0, z: 0}
  fire-mode: redstone
  fire-input: {x: 0, y: 1, z: 1}
  fire-inputs:
    - {x: 0, y: 1, z: 1}
    - {x: 8, y: 1, z: 1}
  direct-dispenser: {x: 1, y: 1, z: 1}
  fire-pulse-ticks: 4
  settle-before-fill-ticks: 4
  fill-to-fire-ticks: 4
  control-states:
    - name: select-nuke-mode
      at: {x: 4, y: 2, z: 1}
      phase: before-fill
      apply-tick: 1
      settle-ticks: 2
      apply-physics: true
      expected-material: lever
      expected-before: minecraft:lever[face=wall,facing=west,powered=false]
      block-data: minecraft:lever[face=wall,facing=west,powered=true]
limits:
  enforce-dispenser-limit: true
acceptance:
  require-payload: true
  min-target-destroyed: 1
  min-falling-blocks: 0
  min-embedded-payload-explosions: 1
  max-unembedded-water-explosions: 0
  min-contiguous-layers-before-first-regen: 20
  require-all-layers-before-first-regen: true
  min-forward-distance: 120
  min-remaining-dispenser-ratio: 0.99
  max-cannon-missing-blocks: 20
  max-cannon-replaced-type-blocks: 10
  max-cannon-unexpected-blocks: 0
  max-self-damage-blocks: 20
target:
  type: hotdog
  material: cobblestone
  alternate-material: obsidian
  direction: north
  distance: 160
  width: 17
  height: 32
  y-offset: 0
  lateral-offset: 0
  layers: 20
  spacing: 3
  hotdog-band-width: 2
  pillar-spacing: 3
  regeneration:
    enabled: true
    delay-ticks: 40
    interval-ticks: 10
    max-blocks-per-cycle: 32
run:
  shots: 100
  rebuild-cannon-between-shots: false
  warmup-ticks: 20
  max-shot-ticks: 240
  quiet-ticks: 20
  shutdown-when-finished: true
```

Supported target types are `dry`, `watered`, `cobble-regen`, `filter`, `slab-filter`, `hotdog`, and `pillars`. Supported directions are `north`, `south`, `east`, and `west`. Supported fire modes are `redstone`, `button`, `direct-dispense`, and diagnostic-only `tnt-probe`; `direct` is accepted as an alias. `tnt-probe` isolates defense physics and is never evidence that a cannon schematic works. Optional `cannon.probe-falling-material` and `cannon.probe-falling-origin` fields add a stationary diagnostic falling payload so the overlap sensor can be calibrated independently.

`cannon.fire-input` preserves the simple one-input format. `cannon.fire-inputs` powers every listed coordinate on the same tick and is intended for segmented or distributed cannon circuits.

`cannon.control-states` configures required mode blocks before a shot instead of assuming the pasted schematic already has the correct lever, repeater, comparator, trapdoor, piston, or dispenser state. Each entry is relative to the pasted cannon origin, validates the optional expected material and complete `expected-before` block state, applies the requested `block-data`, waits its declared settle time, and verifies the exact resulting state before fill or fire can continue. Supported phases are `before-fill` and `after-fill`. Every application, verification, and failure is written to `causal-events.csv`; a mismatch fails closed and cancels delayed fill or volley work.

The configured arena radius must include the cannon, complete flight path, every target layer, and one extra block for water, lava, or slab frontage. CannonLab fails loudly instead of silently building targets outside the loaded arena.

Audit the scenario itself before promoting a result:

```powershell
python scripts/scenario-integrity-audit.py scenarios/candidate.yml `
  --require-field-candidate `
  --json-out scenario-integrity.json
```

The integrity audit exposes collision guides, forced TNT velocities, diagnostic magazine cutoffs, direct-dispenser fire, disabled dispenser limits, ambiguous multi-shot lifecycles, and weak survival/range/target gates. An endurance-labelled scenario is rejected if it rebuilds the cannon between shots. For water-facing targets the audit also requires explicit falling-payload overlap and unembedded-water limits. For regenerating targets it requires one aligned penetration lane through successive layers before the first actual restoration. Assisted scenarios remain useful diagnostics, but their results cannot be promoted as standalone cannon or EC-readiness evidence.

Acceptance is enforced inside the Java runtime. A failed shot writes `contract_pass: false`, the exact failure list, cannon survival counts, and `cannon-integrity.csv`; the run ends with `finish_reason: contract_failed`. Each shot also writes `breach-events.csv`. `falling_overlap_evidence=true` means a recorded falling-block trajectory overlapped the TNT explosion envelope at that tick. Runtime breach counters only use TNT explosions whose center is inside the recorded target envelope, so water inside the cannon cannot satisfy or poison the wall-impact gate. It is direct local runtime evidence, but it is not by itself proof of private ExtremeCraft water-bypass behavior. The regen race stops at the first target block that CannonLab actually restores, not merely at the first configured cycle. Scattered damage at different heights or lateral positions cannot be combined into a fake full-depth breach. Existing scenarios without explicit acceptance remain runnable for diagnosis, but the scenario audit classifies them as `INCOMPLETE`. Set `CANNONLAB_REQUIRE_FIELD_CANDIDATE=true` or `CANNONLAB_REQUIRE_READINESS=true` in either launcher to fail before server startup when the requested evidence level is not met.

`run.rebuild-cannon-between-shots` defaults to `true` for backward compatibility. That mode measures repeatability across fresh schematic pastes. Set it to `false` for cumulative endurance: CannonLab pastes the cannon once, preserves every block and redstone-state change, removes only transient TNT/falling/item entities, rebuilds only the target, refills surviving dispensers, and compares every later shot against the original cannon snapshot. It also counts blocks or fluids that appear inside originally-air cells as `cannon_unexpected_blocks`; use `acceptance.max-cannon-unexpected-blocks: 0` for strict endurance. `run-summary.json` records `cannon_lifecycle`, `cannon_pastes_performed`, and `cannon_rebuilt_before_shot` for every shot. Use `assert-results.py --require-cumulative-cannon` or `CANNONLAB_REQUIRE_CUMULATIVE_CANNON=true` so a fresh-paste run cannot masquerade as endurance evidence.

## Included defense scenarios

```text
multi-tnt-range.yml
plugin-regen-wall.yml
fluid-regen-defense.yml
hotdog-defense.yml
pillar-defense.yml
breach-telemetry-probe.yml  # diagnostic sensor calibration only
```

The four-dispenser fixture is deliberately compact. It proves simultaneous multi-TNT activation, entity tracking, range measurement, target damage accounting, and regeneration plumbing. It is a laboratory cannon, not a raid cannon or OSRB replacement.

See `docs/DEFENSE_MODELS.md` for the precise geometry and limitations of each defense model.

## Build

Requirements:

- JDK 25
- Gradle 9.2.1 or newer

```powershell
gradle clean build
```

The plugin JAR is written to `build/libs/`.

## Headless launcher configuration

`scripts/cloud-smoke.sh` is the general scenario runner. Important environment variables include:

```text
CANNONLAB_SCENARIO
CANNONLAB_SERVER_JAR
CANNONLAB_SERVER_LABEL
CANNONLAB_TIMEOUT_SECONDS
CANNONLAB_EXPECTED_SHOTS
CANNONLAB_STRICT_SINGLE_TNT
CANNONLAB_MIN_TNT_PER_SHOT
CANNONLAB_MIN_EXPLOSIONS_PER_SHOT
CANNONLAB_EXPECTED_LIFETIME
CANNONLAB_LIFETIME_TOLERANCE
CANNONLAB_MIN_FORWARD_TRAVEL
CANNONLAB_MAX_TARGET_MISS_DISTANCE
CANNONLAB_MIN_TARGET_PEAK_DESTROYED
CANNONLAB_MIN_TARGET_PEAK_MEAN
CANNONLAB_MIN_LAYER_BREACHED
CANNONLAB_MIN_EMBEDDED_PAYLOAD_EXPLOSIONS
CANNONLAB_MAX_UNEMBEDDED_WATER_EXPLOSIONS
CANNONLAB_MIN_CONTIGUOUS_LAYERS_BEFORE_FIRST_REGEN
CANNONLAB_REQUIRE_ALL_LAYERS_BEFORE_FIRST_REGEN
CANNONLAB_REQUIRE_REGEN
CANNONLAB_MIN_REGEN_RESTORED
CANNONLAB_ARENA_RADIUS_X
CANNONLAB_ARENA_RADIUS_Y
CANNONLAB_ARENA_RADIUS_Z
```

Set `CANNONLAB_STRICT_SINGLE_TNT=false` for real multi-dispenser cannons. Set `CANNONLAB_EXPECTED_LIFETIME=none` only where fixed individual TNT lifetime is intentionally not a valid assertion.

## Analysis tools

```text
scripts/schem-audit.py
scripts/assert-results.py
scripts/analyze-breach-evidence.py
scripts/wall-breach-intelligence.py
scripts/compare-entity-trajectories.py
scripts/analyze-output-corridor.py
scripts/rank-runs.py
scripts/compare-fingerprints.py
scripts/build-sakura-26.1.2.sh
scripts/cloud-smoke.sh
```

The static auditor validates Sponge v2 and Litematica structure, packed block-state data, block data, tile coordinates, redstone supports, repeater states, water states, dispenser counts, block-entity pressure, and every possible chunk alignment before a cannon consumes server time. Compatible Litematica inputs can be converted to deterministic Sponge v2 output through the same audited path.

Audit a completed watered or regenerating run:

```powershell
python scripts/analyze-breach-evidence.py lab-artifacts/results `
  --min-embedded-payload-explosions 1 `
  --max-unembedded-water-explosions 0 `
  --min-contiguous-layers-before-first-regen 20 `
  --require-all-layers-before-first-regen `
  --json-out breach-evidence.json
```

Apply the strict target-facing wall contract and get a repair diagnosis:

```powershell
python scripts/wall-breach-intelligence.py lab-artifacts/results `
  --profile watered-obsidian `
  --json-out wall-breach.json
```

The wall-breach report reconstructs exact per-cell durability sequences, connected apertures, same-lane layer continuation, embedded payload, first real regeneration restore, cannon survival, falling-payload direction, and the TNT explosion nearest each significant payload impulse. It rejects raw explosion counts, scattered hits, disconnected damage, wrong-axis payload and walls broken by a cannon that destroyed itself. See `docs/WALL_BREACH_INTELLIGENCE.md`.

Pinpoint the first per-tick TNT drift between a baseline and candidate:

```powershell
python scripts/compare-entity-trajectories.py `
  baseline/shot-001/events.csv candidate/shot-001/events.csv `
  --reference-uuid <baseline-tnt-uuid> `
  --candidate-uuid <candidate-tnt-uuid> `
  --json-out trajectory-diff.json
```

Require at least five shots to leave through one measured output corridor:

```powershell
python scripts/analyze-output-corridor.py lab-artifacts/results `
  --min-shots 5 `
  --min-forward 120 `
  --half-width 2 `
  --vertical-tolerance 6 `
  --max-abs-angle 3 `
  --max-angular-spread 2 `
  --max-forward-relative-spread 0.08 `
  --json-out output-corridor.json
```

The output-corridor analyzer reads every per-shot `events.csv`, projects TNT and falling-block trajectories onto the scenario target direction, rejects reverse or missing output, measures lateral and vertical corridor violations, and fails when shot direction, angle, lateral center, or forward distance drifts beyond the declared repeatability budget. Charge TNT that never crosses `--min-forward` is excluded from the output cohort. This is local trajectory evidence, not private ExtremeCraft parity.

## Cannon-development loop

1. Audit the source file and reject structural, chunk-limit, or known block-entity failures.
2. Convert Litematica input to Sponge v2 and re-audit the exact output that will be pasted.
3. Run direct activation to prove dispenser and telemetry plumbing.
4. Run real redstone activation to verify the actual firing circuit.
5. Run the cannon against dry and watered baseline targets.
6. Require one-paste cumulative shots instead of rebuilding a fresh cannon for every attempt.
7. Run wall-breach intelligence and reject targetless explosions, scattered durability pressure, disconnected damage, wrong-axis payload, regen loss, and cannon death.
8. Require one dominant output corridor with bounded angle, lateral drift, and forward-distance spread.
9. Stress it across range, height, hotdog lanes, pillars, fluid cells, and delayed regeneration.
10. Rank bounded variants from evidence rather than visual impressions.
11. Compare the local fingerprint with the ExtremeCraft calibration fingerprint.
12. Export the winning schematic plus its scenario, audit, timing, and test evidence.

See `docs/EXTREMECRAFT_CALIBRATION.md` for the final live calibration contract.
