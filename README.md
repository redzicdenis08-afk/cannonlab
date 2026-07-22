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
- clear and rebuild the arena between every shot
- audit and fill every dispenser with TNT
- enforce the current user-reported ExtremeCraft limit of 160 dispensers per chunk
- test conservative or historical limits such as 128 through an explicit CLI override
- audit total and per-chunk block-entity pressure separately from dispenser limits
- trigger one or multiple cannon inputs through real redstone power
- generate dry, watered, fluid-regen, filter, slab-filter, hotdog-lane, and staggered-pillar targets
- place targets north, south, east, or west with vertical and lateral offsets
- simulate configurable plugin-style delayed regeneration with delay, interval, and per-cycle caps
- keep all arena chunks ticking without a connected player
- record TNT and falling-block position, velocity, fuse, and explosion data every tick
- record target destruction and regeneration events in the same CSV timeline
- measure forward travel, target miss distance, peak damage, deepest layer breached, and restored blocks
- export per-shot and per-run JSON/CSV evidence
- rank cannon variants by reliability, penetration, errors, and repeatability
- compare local physics fingerprints against measured server fingerprints

## Runtime gates

The CI suite contains:

- clean Java 25 compilation and plugin packaging
- one-dispenser direct and redstone plumbing tests
- a real four-dispenser cannon fixture
- one hundred consecutive redstone-triggered endurance shots
- a five-scenario professional-defense matrix
- one hundred redstone endurance shots on pinned public Sakura 26.1.2
- ten four-TNT shots on pinned public Sakura 26.1.2
- exact TNT fuse continuity and lifetime checks
- unique-entity and no-leak validation between resets
- directional travel and target-proximity gates
- target-damage, layer-breach, and regeneration gates
- all 256 X/Z chunk-alignment scans
- legal, over-limit, truncated, and corrupted schematic fixtures
- download checksum verification for Paper and WorldEdit

Every runtime workflow stores logs, summaries, CSV telemetry, and physics fingerprints as GitHub Actions artifacts.

## Important ExtremeCraft boundary

CannonLab reproduces pinned public Sakura 26.1.2 code and measurable mechanics. ExtremeCraft can still use private configuration, custom plugins, anti-lag rules, FAWE permissions, durable-block values, TNT restrictions, and regeneration behavior that are not public.

The current field report is 160 dispensers per chunk. The older 128 figure is stale for ExtremeCraft, although it remains useful as an optional conservative audit threshold. ExtremeCraft also has a separate FAWE block-entity or tile-entity paste limit whose exact value is not yet verified. CannonLab therefore reports dispenser pressure and block-entity pressure independently and does not invent a numeric FAWE cap.

The built-in regeneration model is a deterministic test simulator, not a claim that every server uses the same private replacement algorithm. A cannon is not labeled ExtremeCraft-ready until it passes the local suite and a small live calibration/canary test. CannonLab does not connect to or automate actions on ExtremeCraft and contains no Minecraft credentials or session tokens.

## Commands

```text
/cannonlab status
/cannonlab smoke
/cannonlab run <scenario.yml>
/cannonlab cancel
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
limits:
  enforce-dispenser-limit: true
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
  warmup-ticks: 20
  max-shot-ticks: 240
  quiet-ticks: 20
  shutdown-when-finished: true
```

Supported target types are `dry`, `watered`, `cobble-regen`, `filter`, `slab-filter`, `hotdog`, and `pillars`. Supported directions are `north`, `south`, `east`, and `west`. Supported fire modes are `redstone` and `direct-dispense`; `direct` is accepted as an alias.

`cannon.fire-input` preserves the simple one-input format. `cannon.fire-inputs` powers every listed coordinate on the same tick and is intended for segmented or distributed cannon circuits.

The configured arena radius must include the cannon, complete flight path, every target layer, and one extra block for water, lava, or slab frontage. CannonLab fails loudly instead of silently building targets outside the loaded arena.

## Included defense scenarios

```text
multi-tnt-range.yml
plugin-regen-wall.yml
fluid-regen-defense.yml
hotdog-defense.yml
pillar-defense.yml
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
CANNONLAB_MIN_LAYER_BREACHED
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
scripts/rank-runs.py
scripts/compare-fingerprints.py
scripts/build-sakura-26.1.2.sh
scripts/cloud-smoke.sh
```

The static auditor validates Sponge v2 and Litematica structure, packed block-state data, block data, tile coordinates, redstone supports, repeater states, water states, dispenser counts, block-entity pressure, and every possible chunk alignment before a cannon consumes server time. Compatible Litematica inputs can be converted to deterministic Sponge v2 output through the same audited path.

## Cannon-development loop

1. Audit the source file and reject structural, chunk-limit, or known block-entity failures.
2. Convert Litematica input to Sponge v2 and re-audit the exact output that will be pasted.
3. Run direct activation to prove dispenser and telemetry plumbing.
4. Run real redstone activation to verify the actual firing circuit.
5. Run the cannon against dry and watered baseline targets.
6. Stress it across range, height, hotdog lanes, pillars, fluid cells, and delayed regeneration.
7. Rank variants from evidence rather than visual impressions.
8. Compare the local fingerprint with the ExtremeCraft calibration fingerprint.
9. Export the winning schematic plus its scenario, audit, timing, and test evidence.

See `docs/EXTREMECRAFT_CALIBRATION.md` for the final live calibration contract.
