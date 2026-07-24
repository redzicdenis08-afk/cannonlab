# First-Principles Activation Calibration

Verified: 2026-07-24

## Why this experiment exists

The first payload-delay and guider hypotheses were generated from empty geometry rather than copied from legacy cannons. On pinned public Sakura 26.1.2, all eight candidates preserved their structure and filled their dispenser, but none dispensed TNT through the proposed repeater path. Five shots per candidate produced zero TNT entities, zero explosions and the exact contract failure `payload_not_observed`.

That rejection is useful. It prevents CannonLab from promoting a filename or a plausible-looking repeater arrangement into a payload or guider primitive.

This calibration family isolates the next question:

> Which smallest real redstone path reliably activates one protected dispenser on the pinned runtime?

## Candidate matrix

The profile `profiles/from-scratch/activation-calibration-v1.json` generates ten candidates:

- one direct redstone-block control;
- one redstone-dust control;
- four east-facing repeater candidates with delays 1 through 4;
- four west-facing repeater candidates with delays 1 through 4.

Every candidate has:

- exactly one east-facing dispenser;
- one empty dispenser block entity;
- one source-water output cell;
- an obsidian floor and water enclosure;
- one declared air coordinate for the temporary redstone-block pulse;
- all 256 X/Z offsets below the EC160 limit;
- deterministic Sponge v2 output using DataVersion 3465.

The only intentional variable within each repeater orientation is delay. The east/west split is explicit because runtime evidence, not assumed block-state semantics, decides which side is input and which side can power the dispenser in this generated geometry.

## Promotion contract

A candidate can be promoted only if one exact schematic completes ten shots on one paste with:

- at least one TNT entity per shot;
- at least one explosion per shot;
- zero cannon self-damage;
- the dispenser still present after every shot;
- exact source accounting;
- no geometry rebuild between shots.

Direct and dust are positive controls. Repeater candidates remain hypotheses until runtime results select an orientation and delay behavior.

## Why the water cell matters

The calibration asks whether the redstone path activates, not whether an unprotected TNT explosion can eat the fixture. The TNT therefore spawns into a source-water cell surrounded by obsidian. This removes avoidable structure loss from the activation comparison while preserving real dispenser, redstone and TNT behavior.

## Generate

```powershell
python scripts/generate-activation-calibration-rigs.py `
  profiles/from-scratch/activation-calibration-v1.json `
  --output-directory lab-artifacts/activation-calibration/candidates `
  --json-out lab-artifacts/activation-calibration/manifest.json
```

## Truth boundary

Static generation proves only deterministic geometry, block entities and EC160 legality. A direct control that passes does not prove payload timing. A repeater that passes proves only one protected activation path at the tested orientation and delay. Charge coupling, projectile launch, guidance, falling-payload fusion, hammering and regeneration penetration require later experiments.
