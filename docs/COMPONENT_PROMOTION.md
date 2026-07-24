# CannonLab Evidence-Backed Component Promotion

Verified: 2026-07-24

## Purpose

The synthesis planner can assemble proven modules, but it must not receive hand-waved components. `promote-cannon-component.py` converts one reviewed module from an exact source cannon into a deterministic standalone Sponge v2 component and a registry file the synthesis planner validates directly.

The promotion path is:

`exact source hash -> current module map -> exact module signature -> clean crop boundary -> runtime gate -> explicit capability claims -> deterministic .schem -> synthesis registry validation`

The script never derives charge, hammer, booster, payload, OSRB, nuke, leftshot or reverse semantics from filenames, shapes, dispenser counts or static role candidates.

## Required evidence

Every promotion manifest declares:

- exact source schematic SHA-256;
- exact current `module_id`;
- exact module signature, preventing silent module-map drift;
- reviewed crop padding;
- component evidence level and concrete evidence sources;
- explicit capability claims with separate evidence levels and justifications;
- exact source-coordinate ports;
- any explicitly reviewed boundary crossings.

Evidence levels are ordered:

1. `unknown`
2. `inference`
3. `static`
4. `local-runtime`
5. `field-reported`
6. `field-verified`

A capability cannot claim stronger evidence than the component promotion itself.

## Runtime promotion gate

`local-runtime` or stronger promotion requires a real `causal-events.csv` trace. CannonLab rebuilds the current module map, joins it to the trace through `analyze-module-trace.py`, verifies the source hash, finds the exact selected module and enforces the manifest's minimums:

- active module requirement;
- exclusive component-event count;
- correlated entity count;
- unambiguous entity-profile coverage.

Runtime role candidates remain visible only for human review. They are not automatically converted into capability names.

`field-reported` and `field-verified` additionally require an exact field record containing server, date, observation, source, source SHA-256 and selected module ID. A live claim cannot float free of the exact bytes and module that were tested.

## Boundary safety

Module-map bounds describe functional components, not automatically safe standalone crop boundaries. The promoter includes all blocks and block entities inside the padded crop and audits every boundary for:

- functional component face links;
- directional front/back endpoints;
- redstone support dependencies;
- fluid continuity;
- piston, slime and honey motion-cluster links.

A crossing is accepted only when it is the exact direction of a declared port or is listed in `boundary.allowed_crossings` with exact inside/outside coordinates, crossing kind and a review reason. Stale allowances that no longer match current geometry fail.

## Block entities

The current deterministic Sponge writer preserves block states and emits minimal block-entity identity/position data. Promotion therefore fails closed unless every cropped block entity is an empty dispenser or dropper. Chests, signs, custom NBT and non-empty inventories are rejected rather than silently stripped.

## Usage

```powershell
python scripts/promote-cannon-component.py `
  private/reference-cannon.litematic `
  profiles/components/my-component-manifest.json `
  --trace lab-artifacts/reference-shot/causal-events.csv `
  --schem-out lab-artifacts/components/control-core-v1.schem `
  --registry-out lab-artifacts/components/control-core-v1.registry.json `
  --json-out lab-artifacts/components/control-core-v1.report.json
```

The generated registry can be fed directly to:

```powershell
python scripts/cannon-synthesis-planner.py `
  lab-artifacts/components/control-core-v1.registry.json `
  profiles/synthesis/my-request.json
```

For a real multi-component registry, merge only reviewed `components[]` entries whose source hashes and generated schematic hashes remain exact.

## Promotion status

A successful result is `PROMOTED_COMPONENT_CANDIDATE`, not a proven standalone cannon subsystem. Cropping can change neighboring update context even when geometry and boundary review are exact.

Before a promoted module becomes trusted for serious synthesis, still require:

1. assembly only through declared ports;
2. preservation comparison against the exact source;
3. real input activation on the assembled candidate;
4. source-accounted causal and impulse comparison;
5. target, range, survival and self-damage contracts;
6. a controlled live ExtremeCraft canary before any EC-ready claim.
