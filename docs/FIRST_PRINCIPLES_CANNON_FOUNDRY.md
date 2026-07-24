# First-Principles Cannon Foundry

Verified: 2026-07-24

## Purpose

CannonLab can already decode, audit, compare, preserve, execute and rank existing cannon schematics. The missing capability is different: start without a source schematic, discover reliable cannon primitives through controlled experiments, and compose only primitives that have earned causal runtime evidence.

This foundry begins that source-free path:

`raid objective -> primitive dependency graph -> bounded experiments -> EC160 architecture budgets -> promoted runtime components -> synthesized cannon -> defense campaign -> live canary`

The first version intentionally stops before geometry generation. A dispenser budget is not a cannon, a component name is not a proven role, and a successful public Paper or Sakura run is not private ExtremeCraft parity.

## Research conclusions

### 1. Advanced cannons are staged machines

Even basic TNT cannons separate a protected propellant charge from a delayed projectile. Advanced faction designs add distinct mechanisms for trajectory control, falling payload fusion, sand compression, vertical hammering, slab clearance, regeneration racing, separated damage cohorts and sustained cycling. Treating the machine as one undifferentiated redstone sculpture makes failures difficult to localize and encourages lucky-shot tuning.

### 2. Names are requirements, not evidence

Public cannon collections use labels such as hybrid, OSRB, nuke, slabbust, double tap, diagonal and pseudo. Those names help define desired capabilities, but they do not establish what any region of blocks does. CannonLab promotes a capability only after one exact geometry produces source-accounted runtime evidence.

### 3. Server mechanics and rules shape architecture

Redstone implementations, TNT handling, speed rules, dispenser limits, regeneration and allowed cannon classes differ between servers. A design should therefore expose its timing, entity cohorts, chunk pressure and survival contract instead of assuming one universal factions meta.

### 4. A deep raid is a campaign

A cannon that damages one watered wall once is not a 15-chunk raid system. The full machine must preserve one physical paste, reset reliably, refill, survive repeated shots and advance one aligned breach lane through a manifested sequence of changing defense stages before regeneration closes it.

## Hard rules

- `mode` must be `from-scratch`.
- `source_schematic` is forbidden.
- The minimum evidence level is `local-runtime`.
- Static shape, filenames, labels and dispenser counts cannot promote capabilities.
- Every primitive has prerequisites, experiments and an acceptance contract.
- Architecture search is finite, deterministic and capped.
- Every dispenser budget is packed under the configured per-column limit and safety margin.
- Architecture budgets do not imply physical routability, timing correctness or runtime success.
- Public Paper or Sakura evidence remains local evidence.
- The final readiness gate is a controlled live ExtremeCraft canary.

## Primitive dependency graph

The default 15-chunk research profile resolves to thirteen stages:

| Stage | Primitive | Capability | Main proof |
|---:|---|---|---|
| 1 | `control-spine` | one-button deterministic cycle | real activation and cumulative reset |
| 2 | `protected-charge-cell` | water-protected impulse | causal TNT trace and one-paste survival |
| 3 | `payload-injector` | source-accounted payload cohort | fuse separation and muzzle clearance |
| 4 | `guider` | trajectory alignment | range, height and dispersion sweeps |
| 5 | `falling-payload-fusion` | watered-wall hybrid | falling-block overlap and four registered hits |
| 6 | `staged-booster` | additional measured impulse | isolated stages and cohort separation |
| 7 | `sand-compressor` | compressed falling payload | count, ordering, volume and jam recovery |
| 8 | `hammer` | vertical stacking impulse | separately sourced downward cohort |
| 9 | `slab-bust` | slab/filter clearance | timing sweep without losing the stack |
| 10 | `regen-bust` | regeneration-race penetration | one contiguous lane before first restore |
| 11 | `nuke-cohort` | separated multi-height damage | deliberate cohort spacing and coverage |
| 12 | `osrb-sequence` | one-shot regen-bust phase sequence | exact phase order and source accounting |
| 13 | `campaign-cycle` | sustained raid cycle | 100 one-paste shots, refill, reset and survival |

Dependency order is derived from the requested capabilities. A hybrid-only request does not silently pull in hammer, nuke or campaign machinery.

## Default research objective

`profiles/from-scratch/ec160-15chunk-from-scratch-v1.json` asks for:

- 256-block range target;
- four registered watered-obsidian hits;
- 255-block stack-height target;
- fifteen chunks of staged raid depth;
- at most 40 ticks between campaign shots;
- hybrid, stacker, slab-bust, regen-bust, nuke, OSRB and sustained campaign capabilities;
- 160 dispensers per X/Z chunk column;
- an 8-dispenser safety margin, so candidate budgets may use at most 152 per column;
- at most 12 chunk columns and 1,200 total dispensers;
- 48 bounded architecture candidates.

The default profile currently produces 48 deterministic architecture budgets. The strongest score is simply the most compact legal budget under the planner's ordering. It is not predicted to work better than the others.

## Usage

```powershell
python scripts/plan-first-principles-cannon.py `
  profiles/from-scratch/ec160-15chunk-from-scratch-v1.json `
  --json-out lab-artifacts/from-scratch/ec160-15chunk-plan.json
```

The report contains:

- the exact dependency closure;
- the experiment and promotion contract for every primitive;
- bounded dispenser-budget choices;
- a chunk-column packing proposal;
- the minimum remaining chunk margin;
- explicit truth boundaries.

A successful report has status `RESEARCH_PROGRAM_ONLY`. It does not emit a schematic.

## What comes next

The next engineering layer should generate isolated, deterministic schematic families for the earliest primitives, starting with:

1. `protected-charge-cell`;
2. `payload-injector`;
3. `guider`;
4. `falling-payload-fusion`.

Each family should vary one declared dimension at a time, run through the staged CannonLab campaign, preserve exact candidate hashes and promote no component until repeated causal traces agree. Only then should the synthesis planner receive real component ports and compose larger machines.

Later layers should add compressor and hammer search, slab/filter courses, regeneration races, separated nuke cohorts, OSRB sequencing and the full 15-stage defense campaign. Failed candidates remain valuable because the first causal divergence narrows the next bounded search.

## Truth boundary

This foundry replaces random legacy editing with an explicit source-free research program. It does not yet produce a raid cannon. No architecture candidate is working geometry, no primitive is promoted by this planner, and no serious cannon is ExtremeCraft-ready without local runtime evidence followed by a controlled live canary.
