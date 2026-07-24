# CannonLab v2 — "design any cannon that works" R&D program

Goal: take CannonLab from a runtime test-rig to a full cannon R&D platform that
can **understand, design, and validate** any archetype (nuke / hybrid / worm /
tunneler / OSRB / rail) against any wall, under the exact Sakura 26.1.2 / EC
ruleset — from schematic to canary.

## Execution boundary (honest)
- **Buildable + runnable offline (Python):** physics simulator, solver/designer,
  ruleset, auditors, archetype models. All grounded in Samsuik/Sakura @63f35d7.
- **Needs a live server (owner side):** firing a real Sakura instance, redstone
  circuit proof, EC canary measurements to fill private ruleset values.
- The program is a **loop**: design+predict (sim) → fire (live) → diff → tighten
  model → repeat, until sim predictions match reality.

## Phases
- **P0 Research** — explosion-prime fuse, remaining Sakura cannon patches, a pro
  trajectory solver (lntricate1/CannonLib), proven archetype schematics. (ongoing)
- **P1 Physics core** — `scripts/physics_core.py`: 1352-ray destruction, durable
  DP, entity tick (grav/drag/move/fuse-79), knockback accumulation, prime fuse,
  water-cancel. **LANDED + validated** (obsidian=4DP, water-cancel, ray count).
- **P2 Ruleset** — `calibration/sakura-26.1.2-ruleset.yml`: stock defaults +
  EC-override file (UNKNOWN until probed). **LANDED.**
- **P3 Archetype models** — classifier + per-archetype win-conditions.
- **P4 Designer** — (wall, distance, archetype, ruleset) -> real block-coordinate
  cannon + scenario YAML, iterated in the physics core until breach-with-margin
  under caps.
- **P5 Lab integration** — ruleset-aware gates in `assert-results` (sand-embed,
  regen-race, per-stage depth), penetration-weighted rank, chunk-segmentation
  advisor, metadata cross-check guard.
- **P6 Live validation loop** — `sakura-runtime` CI on generated candidates; EC
  canary probes; sim-vs-live fingerprint diff; iterate.

## Validated physics facts (from `physics_core.py`)
- Explosion = exactly 1352 surface rays; per-ray power `4·(0.7+rand·0.6)`, decay
  0.225/step, resistance march `(res+0.3)·0.3`.
- Sakura obsidian = 4 DP at cobblestone resistance (breaks on the 4th TNT hit).
- Watered obsidian: bare TNT is fully cancelled; only sand-embedded (hybrid)
  blasts spend DP. Confirmed 4 hybrid hits to break.
- Booster knockback is linear in charge count (1 charge = 0.875 blocks/tick).
- At 30 blocks: range is trivial; the levers are **fuse timing** and **stack
  depth** (>=4 hits/obsidian block, hence the 5-stacker meta with 1 DP margin).
