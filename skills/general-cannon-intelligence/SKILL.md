---
name: general-cannon-intelligence
description: Plan, diagnose, compose and evidence-check modern factions cannons across hammered, hammerless, Asser, Rev-Worm, anti-gravity, force/counter, OSRB, nuke, leftshoot, reverse, worm, slab-bust, bypass, anti-patch and double-tap families. Use before building, repairing or claiming any advanced cannon.
---

# General Cannon Intelligence

Use `scripts/general-cannon-intelligence.py` before editing a serious cannon.

## First classify the request

Choose exactly one base architecture:

- hammered-stacker
- hammerless-stacker
- asser-multiwave
- rev-worm
- anti-gravity-stacker
- force-or-counter
- compact-calibration-stacker

Then choose only the specializations actually requested. Do not silently add every mode to one cannon.

## Build the plan

Run:

```powershell
python scripts/general-cannon-intelligence.py plan --base <base> --specialization <mode> --lifecycle diagnostic-prototype
```

A `BLOCKED` plan is useful. It identifies the missing interface proof or runtime capability. Do not bypass it by changing the name or lifecycle.


When a candidate and architecture manifest exist, use the unified operator instead of manually running three disconnected tools:

```powershell
python scripts/cannon-operator.py prepare <candidate.schem> `
  --architecture-manifest <architecture.json> `
  --base <base> `
  --specialization <mode> `
  --reference <reference.schem> `
  --fire-input x,y,z
```

The operator must pass the general plan, architecture policy, and Forge staging in that order. It records hashes and stops immediately on the first failed gate.

For a timing or geometry hypothesis, use bounded mutation and deterministic search. Never hand-edit a family of candidates by memory:

```powershell
python scripts/cannon-mutator.py <reviewed-mutation-plan.json>
python scripts/cannon-variant-search.py generate <bounded-search-spec.json>
python scripts/cannon-variant-scorecard.py <search-manifest.json> <result-map.json>
python scripts/cannon-variant-search.py rank <search-manifest.json> <runtime-scorecard.json>
```

The search must enumerate the complete declared domain, respect the candidate budget, reject candidates that fail preservation or hard runtime limits, and keep static score separate from cannon-performance score.


## Mandatory reasoning model

For every stage record:

- what entity cohort exists
- where and when it exists
- which explosion or piston acts on it
- its velocity before and after
- its next chamber or waypoint
- its failure signature
- the runtime artifact that proves the edge

Redstone schedules the machine. Physical impulses operate it.

## Composition discipline

- Add one specialization at a time.
- Bind every specialization input to a measured base output.
- Preserve untouched stage traces.
- Treat same-tick entity order as part of the interface.
- Treat payload mode as explicit: TNT-only, falling-block-required or archetype-selectable.
- Do not transplant Rev-Worm and Asser modules without axis, chamber, timing and payload proof.
- Do not combine OSRB and nuke modules without a shared order-of-entities experiment.

## Diagnosis

Use symptoms to rank measurements, not to assign a module name as fact:

```powershell
python scripts/general-cannon-intelligence.py diagnose --symptom "wrong side" --symptom "backboard return"
```

Then inspect the recommended cohort, trajectory, target and self-damage evidence.

## Promotion

- Community evidence creates hypotheses.
- Static reference evidence creates geometry and control contracts.
- Local runtime proves only the exact local build and scenario.
- EC-ready requires a reduced live ExtremeCraft canary.

Never claim a 255/384 stack, fire rate, range, OSRB, one-shot, nuke, worm, leftshoot or regen win without the matching measured acceptance contract.
