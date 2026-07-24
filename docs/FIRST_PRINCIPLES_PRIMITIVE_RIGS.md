# First-Principles Primitive Rigs

Verified: 2026-07-24

## Why these rigs exist

A serious cannon cannot be designed truthfully by drawing a thousand dispensers and naming regions after expected roles. The first-principles foundry therefore begins with tiny source-free rigs whose activation, water protection, timing and geometry can be isolated.

These rigs are generated from code. They are not cropped from public or user-provided cannons.

## Current families

### Protected charge cells

Four variants contain one to four independent charge cells:

- `charge-c01`: 4 dispensers
- `charge-c02`: 8 dispensers
- `charge-c03`: 12 dispensers
- `charge-c04`: 16 dispensers

Each cell places four east-facing dispensers around one air activation coordinate. Every dispenser faces into its own fully enclosed source-water block. A temporary redstone block at the activation coordinate powers all four adjacent dispensers at once.

This layout is designed to answer narrow questions:

- do all sources activate on one real redstone pulse;
- does every TNT spawn in the intended source-water cell;
- does the exact pasted structure survive repeated shots;
- do the four source cohorts remain causally attributable?

It does **not** claim that separate cells combine into one useful propellant impulse.

### Payload timing rigs

Four variants use one supported east-facing repeater with delay 1 through 4, followed directly by one east-facing dispenser:

- `payload-d1`
- `payload-d2`
- `payload-d3`
- `payload-d4`

A temporary redstone block at the declared air input powers the repeater. These rigs exist to establish exact activation, fuse timing and muzzle-clearance evidence before any payload source is combined with charge cells.

The label `payload` is an experiment goal, not a promoted runtime role.

### Guider rigs

Four variants extend the delay-1 payload rig with open-top obsidian side rails:

- `guider-l004-d1`
- `guider-l008-d1`
- `guider-l012-d1`
- `guider-l016-d1`

Only the declared rail length changes. This supports controlled trajectory comparisons without changing the source, repeater delay or dispenser geometry.

The rails are static guide hypotheses until repeated TNT trajectories prove reduced lateral dispersion without unacceptable collisions or range loss.

## Generate

```powershell
python scripts/generate-first-principles-rigs.py `
  profiles/from-scratch/primitive-rig-families-v1.json `
  --output-directory lab-artifacts/primitive-rigs/candidates `
  --json-out lab-artifacts/primitive-rigs/manifest.json
```

The generator writes deterministic Sponge v2 schematics using DataVersion 3465. Every output is decoded again, compared against the generated occupied geometry and block-entity coordinates, hashed, and scanned across all 256 X/Z chunk offsets.

## Current contract

The default profile produces twelve schematics:

- four protected-charge variants;
- four payload-delay variants;
- four guider-length variants.

Every candidate must:

- be generated without a source schematic;
- round-trip through CannonLab's Sponge decoder;
- preserve exact empty dispenser block entities;
- preserve declared fire-input air coordinates;
- remain below the 160-dispenser limit at all 256 offsets;
- receive only `STATIC_EXPERIMENT_RIG_ONLY` status.

## Runtime progression

The intended promotion sequence is:

1. static round-trip and EC160 audit;
2. one real redstone activation with no TNT fill;
3. one-unit TNT fill with exact dispenser-source tracing;
4. repeated water-survival or trajectory runs on one paste;
5. causal comparison across only the declared family variable;
6. primitive promotion only when one exact geometry satisfies its runtime contract.

Charge and payload should then be combined through a separate composition experiment. Falling payload fusion, compressor and hammer families come later because they introduce entity ordering, piston motion and target-phase timing that should not be mixed into the first experiment.

## Truth boundary

These schematics are laboratory instruments, not raid cannons. Static success does not prove charge impulse, payload function, guidance, hybrid fusion, regeneration penetration or ExtremeCraft parity. Public Paper or Sakura runtime evidence remains local evidence until a controlled live EC canary confirms the relevant mechanic.
