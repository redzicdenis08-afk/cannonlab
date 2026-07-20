# CannonLab defense models

CannonLab defense targets are deterministic laboratory fixtures. Their purpose is to make cannon variants comparable under repeatable conditions. They do not claim to reproduce every private factions plugin or every server's names for wall geometry.

## Common geometry

Every target has a direction, distance, width, height, layer count, layer spacing, Y offset, and lateral offset. The direction defines the cannon-to-target axis. Each solid target block is assigned a zero-based layer internally and reported as a one-based `max_layer_breached` value.

The run summary records the complete target bounding box. The assertion harness measures every TNT explosion against that box and can fail a run when the payload travels too little or misses the defense by too much.

## Dry

`dry` creates solid target cells with no protective fluid. It is the baseline for blast placement, target damage, and delayed-regeneration testing.

## Watered

`watered` creates a solid target with one water block on the cannon-facing side. It is a deterministic watered-wall baseline.

## Cobblestone regen cell

`cobble-regen` creates the configured solid target material with water on the cannon-facing side and lava behind it. This exercises native fluid updates and can also be combined with CannonLab's delayed regeneration simulator.

Native water/lava behavior and delayed plugin-style replacement are separate mechanisms. The run summary states whether the delayed simulator was enabled.

## Filter and slab filter

`filter` uses a checkerboard of solid cells and air.

`slab-filter` creates a full solid target with alternating top and bottom slabs on the cannon-facing side.

These are controlled obstruction patterns, not universal definitions for every server's filters.

## Hotdog lanes

`hotdog` creates alternating lateral lane bands:

- solid bands contain the configured target and alternate materials in a checker pattern
- gap bands leave the target plane open
- every lane has water on the cannon-facing side

`target.hotdog-band-width` controls the width of each solid or gap band. This gives CannonLab a repeatable water-lane defense for testing convergence and lateral spread. Server communities use the word "hotdog" for several related layouts, so live server calibration should replace this geometry when a particular server's exact layout is known.

## Staggered pillars

`pillars` places vertical columns at `target.pillar-spacing`. The selected columns shift by one position per target layer, producing a staggered multi-layer defense.

This model measures whether a payload can maintain useful convergence through separated columns and whether deeper layers are reached.

## Delayed regeneration simulator

Delayed regeneration is orthogonal to target type and is configured under:

```yaml
target:
  regeneration:
    enabled: true
    delay-ticks: 40
    interval-ticks: 10
    max-blocks-per-cycle: 32
```

For every solid target cell, CannonLab records the first tick on which the exact expected material and block state disappears. Once the configured delay has elapsed, due cells are restored in oldest-first order, limited by `max-blocks-per-cycle` each interval.

The telemetry contains:

- `TARGET_DESTROYED` events
- `REGEN_RESTORE` events
- final destroyed cells
- peak simultaneously destroyed cells
- unique cells ever destroyed
- total restored cells
- regeneration cycles
- deepest layer breached

This simulator is deliberately configurable because modern servers can use different replacement delays, queues, caps, priorities, and protected materials. The correct values for a private server must come from live measurements.

## Professional pass criteria

A meaningful defense run should combine several gates rather than merely requiring an explosion:

- minimum TNT entities and explosion events per shot
- uninterrupted fuse countdown for every tracked TNT UUID
- minimum forward travel
- maximum distance from an explosion to the target box
- minimum peak target destruction
- minimum layer breached
- required regeneration restorations where regeneration is enabled
- unique UUIDs between shots and clean arena resets

A cannon that passes only the plumbing probes is not considered defense-tested.
