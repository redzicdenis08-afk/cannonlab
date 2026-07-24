# General modern cannon engineering contract

CannonLab must understand cannons as **three-dimensional causal machines**, not as redstone art and not as rows of dispensers.

This layer covers the major public modern factions cannon families and specializations currently represented by the private reference corpus and the transcript-derived community corpus. It deliberately separates what is known, what is only hypothesized, and what still needs a working reference.

## Covered base architectures

- conventional hammered falling-block stackers
- hammerless/shared-power stackers
- Asser-family east/west multi-wave machines
- Rev-Worm north/south observer/slime machines
- anti-gravity staged-motion stackers
- force, sidecounter and buffer-counter style staged propulsion
- reduced field-calibration stackers

## Covered specializations

- hybrid
- overstack
- OSRB
- efficient nuke
- webbust nuke
- pseudo nuke
- push nuke, intentionally unresolved
- up/down nuke
- leftshoot/rightshoot
- reverse hybrid
- worm routing
- midair/L-stack
- slab bust
- tunnel effect
- anti-patch
- bypass
- double tap
- alien probe, intentionally unresolved

## The seven mandatory interfaces

Every serious cannon must be described through these interfaces:

1. `control-signal`
2. `tnt-cohort`
3. `falling-payload`, when the archetype uses one
4. `impulse-transfer`
5. `alignment-corridor`
6. `target-effect`
7. `reset-contract`

A module name is not an interface. “Hammer,” “OSRB,” “force,” “nuke,” and “worm” are accepted only after their claimed input and output are measured.

## Composition rule

A proposed cannon is:

```text
one base architecture
+ zero or more specializations
+ explicit interface bindings
+ one defense-specific acceptance contract
```

A valid composition must prove:

- relative ticks and same-tick sequence
- entity type and payload mode
- chamber coordinates and direction axes
- collision envelope and water corridor
- source explosion to recipient velocity change
- target effect
- reset and repeated-shot equivalence

A module passing alone does not prove the combined machine. OSRB plus efficient nuke, for example, requires a shared order-of-entities experiment because both may depend on the same creation order and chamber.

## Payload modes

CannonLab must not globally require sand or falling blocks.

- Hammered, hammerless, hybrid, overstack and most OSRB contracts require falling payload.
- The studied Rev-Worm mode is allowed to be TNT-only.
- Force, counter, leftshoot, midair, bypass and double-tap are archetype-selectable.
- Unknown labels remain blocked until a reference defines their payload.

## Capability labels are claims

`384`, `255`, `200`, `120`, `60`, and similar labels do not automatically describe dispenser count. They must be verified at several points:

- created falling-block count
- barrel-entry count
- target-arrival count
- final stack result
- repeated-shot consistency

The same applies to fire-rate and range labels. A stray TNT traveling far does not prove cannon range.

## Defense-specific acceptance

A cannon does not become “good” by breaking one generic wall.

- Dry wall proves only dry contact.
- Watered wall requires embedded payload overlap.
- Regen requires winning the restore race and preserving continuation.
- Slab filters require correct-height contact and continued payload.
- Bypass courses require a specific obstruction benefit.
- Hotdogs and pillars require route stability across their geometry.
- Anti-patch requires a late package that removes the reproduced patch after the primary opening.

## EC160 redesign

A correct redesign is not dispenser deletion.

For every moved or split bank, preserve and remeasure:

- cohort count
- facing ratio
- relative timing
- opposing-panel symmetry
- compression or output corridor
- piston, observer, rail and slime order
- water containment
- payload-to-charge alignment
- final trajectory

Only then move the next bank.

## Commands

Audit the catalog and current runtime capability surface:

```powershell
python scripts/general-cannon-intelligence.py audit
```

The unqualified audit is deliberately honest: it returns `PARTIAL` until both broad runtime gates and operator integration are complete. Require one exact level when automating a gate:

```powershell
python scripts/general-cannon-intelligence.py audit --require diagnostic-prototype
python scripts/general-cannon-intelligence.py audit --require operator-ready
```

Show the complete family matrix:

```powershell
python scripts/general-cannon-intelligence.py matrix
```

Build a fail-closed diagnostic plan:

```powershell
python scripts/general-cannon-intelligence.py plan `
  --base hammered-stacker `
  --specialization overstack `
  --specialization osrb `
  --specialization efficient-nuke `
  --lifecycle diagnostic-prototype
```

Diagnose where to measure first:

```powershell
python scripts/general-cannon-intelligence.py diagnose `
  --symptom "regen wins" `
  --symptom "sand lands one block high"
```

Rank missing knowledge:

```powershell
python scripts/general-cannon-intelligence.py gaps
```

Bind a general family plan, architecture manifest, and Cannon Forge campaign in one fail-closed command:

```powershell
python scripts/cannon-operator.py prepare path/to/candidate.schem `
  --architecture-manifest path/to/architecture.json `
  --base hammered-stacker `
  --specialization overstack `
  --specialization osrb `
  --reference path/to/proven-reference.schem `
  --fire-input 12,4,8
```

That command does not invent a cannon. It prevents the planner, architecture policy, optional bounded mutation, and Forge campaign from drifting into disconnected systems. The operator now verifies that the architecture manifest names the exact source candidate. After a mutation it generates a derived manifest bound to the new candidate hash, reruns the geometry profile, attaches the mutation preservation evidence, and only then invokes the architecture policy and Forge.

Apply one reviewed bounded mutation:

```powershell
python scripts/cannon-mutator.py mutation-jobs/example-plan.json
```

Enumerate every declared timing or geometry variant without random sampling:

```powershell
python scripts/cannon-variant-search.py generate variant-jobs/example-search.json
```

Bind each variant to its completed run summaries and extract conservative metrics:

```powershell
python scripts/cannon-variant-scorecard.py `
  variant-jobs/example/manifest.json `
  variant-jobs/example/result-map.json
```

Rank only candidates with complete runtime scorecards and passing hard limits:

```powershell
python scripts/cannon-variant-search.py rank `
  variant-jobs/example/manifest.json `
  variant-jobs/example/runtime-scorecard.json
```

Static ranking never substitutes for runtime performance. The ranking contract rejects missing metrics, nonnumeric evidence, excessive self-damage, and any other predeclared hard limit.

## Current runtime gaps

The dynamic audit currently identifies these major missing surfaces before CannonLab can claim broad automatic modern-cannon repair:

- explicit pre-fire mode/control state application
- archetype-specific payload acceptance
- output-corridor and direction-repeatability acceptance

Those are implementation targets, not permission to guess around them.

The operator surface is now complete: general planning, architecture policy, bounded mutation, deterministic variant search, private corpus regression, Forge staging, and MCP wrappers are connected. This still does not make an unproven cannon work. The remaining ceiling is runtime physics evidence and live ExtremeCraft canaries.
