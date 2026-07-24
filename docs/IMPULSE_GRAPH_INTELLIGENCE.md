# CannonLab Impulse Graph Intelligence

Verified: 2026-07-24

## Purpose

CannonLab already records two complementary files for every shot:

- `events.csv`: every nearby TNT and falling-block UUID, position, velocity and fuse on every recorded tick;
- `causal-events.csv`: exact redstone, dispense, piston, entity-add, fluid and explosion events.

`analyze-impulse-graph.py` joins them into a conservative graph:

`dispenser candidate -> spawned entity -> recorded trajectory -> candidate explosion impulse -> terminal explosion`

The graph answers a narrower and more useful question than “did the shot fail?”:

> Which recorded entity first changed motion differently, on which transition, and which explosion cohort could have caused it?

It does not assign charge, hammer, OSRB, nuke or leftshot semantics merely from the graph.

## Build one graph

```powershell
python scripts/analyze-impulse-graph.py `
  lab-artifacts/results/<run>/shot-001/events.csv `
  lab-artifacts/results/<run>/shot-001/causal-events.csv `
  --json-out lab-artifacts/impulse-graph.json
```

Important outputs:

- `source.candidates`: nearby matching dispenser activations for each entity spawn;
- `impulse_edges`: abrupt passive-motion residuals with candidate source explosions;
- `unexplained_abrupt_changes`: collision, fluid, piston, plugin or unobserved effects that were not falsely assigned to an explosion;
- `terminal_explosion`: the exact explosion sharing that entity UUID;
- `match_key`: stable type/spawn-cohort ordinal for trace comparison;
- `truth_boundary`: everything the graph deliberately refuses to claim.

## Compare a reference and candidate shot

```powershell
python scripts/analyze-impulse-graph.py `
  reference/shot-001/events.csv `
  reference/shot-001/causal-events.csv `
  --compare-events candidate/shot-001/events.csv `
  --compare-causal-events candidate/shot-001/causal-events.csv `
  --max-timing-delta 1 `
  --max-velocity-delta 0.05 `
  --max-position-delta 0.5 `
  --json-out lab-artifacts/impulse-comparison.json
```

A divergent comparison exits with code `2` and emits `comparison.first_divergence`.

Comparison checks:

- missing or extra entity cohorts;
- source-candidate drift;
- spawn timing drift;
- impulse edge count;
- impulse transition timing;
- passive-residual velocity drift;
- terminal explosion presence, timing and translation-normalized position.

The first divergence is a repair target, not automatic permission to edit the whole machine.

## Passive-motion baseline

Raw velocity change alone is unsafe. A fast entity loses substantial velocity to drag even when no explosion touches it. CannonLab therefore preserves both:

- `observed_velocity_delta`, the literal recorded change;
- `passive_velocity_residual`, the change remaining after a declared passive model.

The default `nominal-air` model applies, once per elapsed recorded tick:

```text
vx' = vx * 0.98
vy' = (vy - 0.04) * 0.98
vz' = vz * 0.98
```

These constants are a diagnostic baseline for TNT/falling-block air motion. They are not a private ExtremeCraft parity claim. Use `--motion-model none` to disable the baseline, or explicitly change `--gravity` and `--drag` for a measured profile.

Ground contact, block collision, fluids, pistons, entity collisions, async processing and private plugins can all produce residuals. When an explosion cannot be conservatively sourced, the graph leaves the change unexplained.

## Source ambiguity

Large cannons intentionally stack entities and explosions in the same place and tick. CannonLab never invents one owner when several sources remain plausible.

An impulse edge can be:

- `high`: one strongly outward source candidate;
- `medium`: one weaker candidate, or one candidate clearly outranking alternatives;
- `ambiguous`: multiple similarly supported candidates;
- `unexplained`: no conservative explosion candidate.

Later module and ratio intelligence can narrow ambiguity, but raw evidence remains intact.

## Regression fixtures

The dedicated test suite proves:

1. a uniquely sourced outward impulse;
2. two indistinguishable stacked explosion sources remain ambiguous;
3. a collision-like stop remains unexplained;
4. reference/candidate comparison identifies the first velocity divergence;
5. identical graphs compare cleanly;
6. missing continuous telemetry fails closed;
7. recorded tick identity is preserved;
8. high-speed nominal drag/gravity do not become fake impulses.

## Truth boundary

This graph is stronger causal evidence than run totals or screenshots, but it still does not recreate:

- block exposure and occlusion;
- exact vanilla explosion ray casting;
- private server collision patches;
- water or plugin forces not present in telemetry;
- subsystem slang semantics;
- live ExtremeCraft parity.

The next layer is the parity fingerprint matrix: minimal paired scenarios for spawn kick, fuse distribution, redstone order, collision axis, water motion, explosion batching, chunk continuity, OSRB clipping, durability and regeneration.
