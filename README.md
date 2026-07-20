# CannonLab

CannonLab is an automated, headless Minecraft cannon laboratory for building, validating, firing, measuring, and ranking cannon schematics against reproducible Paper and Sakura mechanics.

## Readiness

The laboratory is operational and CI-tested. It can:

- build the CannonLab plugin with JDK 25
- compile a pinned public Sakura 26.1.2 source commit
- boot isolated Paper or Sakura test servers with WorldEdit
- paste a Sponge `.schem` at an exact origin
- clear and rebuild the test arena between shots
- audit and fill every dispenser with TNT
- enforce the 128-dispensers-per-chunk rule
- trigger cannons directly or through real redstone power
- generate dry, watered, cobblestone-regen, filter, and slab-filter targets
- place targets north, south, east, or west with vertical and lateral offsets
- keep all arena chunks ticking without a connected player
- record TNT and falling-block position, velocity, fuse, and explosion data every tick
- export per-shot and per-run JSON/CSV evidence
- rank cannon variants by reliability, errors, penetration, and repeatability
- compare local physics fingerprints against measured server fingerprints

## Proven gates

The merged stress suite includes:

- clean Java 25 compilation and plugin packaging
- ten direct-dispenser shots on a real headless server
- ten real redstone-triggered shots
- one hundred consecutive redstone-triggered endurance shots
- ten shots on a source-built, pinned public Sakura 26.1.2 runtime
- exact TNT fuse continuity and 79-tick observed lifetime checks
- unique-entity and no-leak validation between resets
- all 256 X/Z chunk-alignment scans
- legal, over-limit, truncated, and corrupted schematic fixtures
- download checksum verification for Paper and WorldEdit

Every workflow stores logs, summaries, CSV telemetry, and physics fingerprints as GitHub Actions artifacts.

## Important ExtremeCraft boundary

CannonLab reproduces the pinned public Sakura 26.1.2 code and measurable mechanics. ExtremeCraft can still use private configuration, custom plugins, anti-lag rules, FAWE permissions, durable-block values, TNT restrictions, and regen behavior that are not public.

Therefore, a cannon is not labeled ExtremeCraft-ready until it passes the local suite and a small live calibration/canary test. CannonLab does not connect to or automate actions on ExtremeCraft and contains no Minecraft credentials or session tokens.

## Commands

```text
/cannonlab status
/cannonlab smoke
/cannonlab run <scenario.yml>
/cannonlab cancel
```

The server can also autorun a scenario with:

```text
-Dcannonlab.scenario=probe-cloud-stress.yml
```

## Scenario structure

```yaml
name: north-firing-example
cannon:
  file: cannon.schem
  origin: {x: 0, y: 0, z: 0}
  fire-mode: redstone
  fire-input: {x: 0, y: 1, z: 1}
  direct-dispenser: {x: 1, y: 1, z: 1}
  fire-pulse-ticks: 4
limits:
  enforce-dispenser-limit: true
target:
  type: watered
  direction: north
  distance: 160
  width: 17
  height: 32
  y-offset: 0
  lateral-offset: 0
  layers: 20
  spacing: 3
run:
  shots: 100
  warmup-ticks: 20
  max-shot-ticks: 240
  quiet-ticks: 20
  shutdown-when-finished: true
```

Supported target types are `dry`, `watered`, `cobble-regen`, `filter`, and `slab-filter`. Supported directions are `north`, `south`, `east`, and `west`. Supported fire modes are `redstone` and `direct-dispense`; `direct` is accepted as a convenience alias.

The configured arena radius must include the cannon, complete flight path, every target layer, and one extra block for water, lava, or slab frontage. CannonLab fails loudly instead of silently building targets outside the loaded arena.

## Build

Requirements:

- JDK 25
- Gradle 9.2.1 or newer

```powershell
gradle clean build
```

The plugin JAR is written to `build/libs/`.

## Headless launcher configuration

`scripts/cloud-smoke.sh` is also the general scenario runner. Important environment variables include:

```text
CANNONLAB_SCENARIO
CANNONLAB_SERVER_JAR
CANNONLAB_SERVER_LABEL
CANNONLAB_TIMEOUT_SECONDS
CANNONLAB_EXPECTED_SHOTS
CANNONLAB_STRICT_SINGLE_TNT
CANNONLAB_EXPECTED_LIFETIME
CANNONLAB_LIFETIME_TOLERANCE
CANNONLAB_ARENA_RADIUS_X
CANNONLAB_ARENA_RADIUS_Y
CANNONLAB_ARENA_RADIUS_Z
```

Set `CANNONLAB_STRICT_SINGLE_TNT=false` for real multi-dispenser cannons. Set `CANNONLAB_EXPECTED_LIFETIME=none` only for a scenario where a fixed individual TNT lifetime is intentionally not a valid assertion.

## Analysis tools

```text
scripts/schem-audit.py
scripts/assert-results.py
scripts/rank-runs.py
scripts/compare-fingerprints.py
scripts/build-sakura-26.1.2.sh
scripts/cloud-smoke.sh
```

The static auditor validates Sponge v2 structure, block data, tile coordinates, redstone supports, repeater states, water states, dispenser counts, and every possible chunk alignment before a cannon consumes server time.

## Cannon-development loop

1. Audit the schematic and reject structural or chunk-limit failures.
2. Run direct activation to prove dispenser and telemetry plumbing.
3. Run real redstone activation to verify the actual firing circuit.
4. Stress the cannon across directions, ranges, heights, target types, and repeated shots.
5. Rank variants from evidence rather than visual impressions.
6. Compare the local fingerprint with the ExtremeCraft calibration fingerprint.
7. Export the winning schematic plus its scenario, audit, timing, and test evidence.

See `docs/EXTREMECRAFT_CALIBRATION.md` for the final live calibration contract.
