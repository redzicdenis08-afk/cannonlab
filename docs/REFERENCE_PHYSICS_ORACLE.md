# Reference Physics Oracle

`scripts/cannon_physics_reference.py` is an independent diagnostic oracle for CannonLab TNT and falling-block traces.

It does not replace Paper/Sakura runtime testing. Its job is to predict source-audited empty-space motion, compare that prediction to recorded telemetry and identify the first physical phase where the runtime stops matching the reference model.

## Supported operations

Show the available profiles and boundaries:

```powershell
python scripts/cannon_physics_reference.py profiles
```

Predict empty-space TNT motion:

```powershell
python scripts/cannon_physics_reference.py simulate `
  --kind tnt `
  --velocity 0.50 0.20 0.00 `
  --fuse-or-age 80 `
  --ticks 20 `
  --json-out predicted-tnt.json
```

Calculate one or more simultaneous explosion contributions:

```powershell
python scripts/cannon_physics_reference.py impulse `
  --explosion 0 0 0 `
  --target 3 0 0 `
  --power 4 `
  --exposure 1 `
  --count 20
```

Compare a real CannonLab entity trace:

```powershell
python scripts/cannon_physics_reference.py compare-events `
  lab-artifacts/results/<run>/shot-001/events.csv `
  --kind tnt `
  --profile modern-java `
  --json-out physics-comparison.json
```

Use `--uuid` to select an exact entity, or `--entity-index` to select the Nth entity by spawn tick and position.

## Modern profile

The modern profile records these source-audited numeric rules:

- gravity `0.04`,
- drag `0.98`,
- grounded horizontal multiplier `0.7`,
- grounded vertical multiplier `-0.5`,
- TNT water-current scale `0.014`,
- falling blocks do not receive the same fluid push in the inspected implementation,
- modern TNT fuse is decremented before the detonation condition is evaluated.

The profile is intentionally not a complete world simulator. Exact voxel shapes, collision ordering, pistons, water-cell overlap, region scheduling, explosion cohorts and private fork changes remain runtime questions.

## Collision boundary

Without `resolved_movement`, simulation is empty-space. This is deliberate. Approximating ladders, slabs, gates, rails, cobwebs and moving pistons as generic full cubes would produce confident nonsense.

When a real trace reaches a collision, the comparator reports the first axis clamp or movement difference. A future runtime adapter may feed exact collision-resolved movement into `tick_body` for a closed replay.

## Diagnosis codes

- `fuse-order-or-tick-phase-divergence`: observed fuse differs from the profile.
- `gravity-order-or-missing-gravity`: vertical error resembles a missing or reordered gravity step.
- `missing-water-current-push`: expected TNT flow contribution is absent.
- `extra-water-current-push`: an unconfigured flow-like contribution appears.
- `drag-or-velocity-multiplier-divergence`: free-flight speed decay differs.
- `collision-or-axis-resolution`: one or more expected velocity axes are clipped or zeroed.
- `unmodelled-world-or-fork-effect`: the current evidence does not isolate one cause.

Diagnosis labels are hypotheses until reproduced with the relevant variable isolated.

## Verified example

A real 79-sample TNT trace from the ten-shot `multi-tnt-range` run matched the modern reference during free flight. The first meaningful divergence occurred at tick 32 when Y motion hit the floor and vertical velocity was clamped. Fuse drift remained zero.

That result proves the comparator can separate normal collision from fuse or free-flight drift. It does not prove private ExtremeCraft parity.

## Tests

```powershell
python scripts/test-reference-physics.py
```

The test suite covers:

- modern TNT tick order,
- falling-block ground response,
- TNT versus falling-block water push,
- modern fuse detonation,
- explosion impulse and cohort summation,
- exact synthetic trace matching,
- fuse divergence detection,
- CannonLab CSV entity selection.
