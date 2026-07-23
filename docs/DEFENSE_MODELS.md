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

## Sustained pressure runs

`run.volleys-per-shot` and `run.volley-interval-ticks` fire repeated inputs into the same pasted cannon and the same live defense course. The recorder stays open through the final volley plus the configured quiet window. This is the correct mode for comparing burst pressure against regeneration because the wall is not reset between impacts.

```yaml
run:
  shots: 1
  volleys-per-shot: 4
  volley-interval-ticks: 100
  quiet-ticks: 80
```

Every scheduled input produces a `VOLLEY_FIRE` event. Runtime evidence must contain the expected number of events; configuration alone is not accepted as proof that every volley fired.

For defense calibration independent of a cannon schematic, `cannon.fire-mode: tnt-probe` spawns one stationary, measured TNT entity per volley at `cannon.probe-tnt-origin`, relative to the arena origin. This mode is explicitly diagnostic and records `FIRE_INPUT` with `mode=tnt-probe`. It proves target, durability, fluid and regeneration behavior only. It must never be used as evidence that a cannon's redstone, charge or payload works.

## Durable blocks

Durability is configured independently from wall geometry:

```yaml
target:
  durability:
    mode: auto
    expiration-ticks: 1200
    only-tnt: true
    hit-radius: 4.0
    materials:
      obsidian: 4
      anvil: 3
```

- `native` requires Sakura's durable-block runtime and fails loudly elsewhere.
- `auto` uses native Sakura durability when available and the diagnostic simulator on Paper.
- `simulate` is a clearly labeled Paper diagnostic. It uses explosion proximity and must not be presented as private-server parity.
- `disabled` leaves vanilla or server behavior untouched.

The simulator exports `DURABILITY_HIT` and `DURABILITY_BREAK`. Native Sakura runs prove the actual server implementation through target damage rather than pretending simulator counters came from Sakura.

## Water, lava and slab companion cells

Generated water fronts, lava backs and slab fronts are tracked separately from solid target blocks. Exact target schematics also preserve and track non-air, non-solid cells. CannonLab records `COMPANION_MISSING` when protection changes and `COMPANION_RESTORE` when stage regeneration restores it.

This prevents a false pass where the obsidian remains but the water curtain disappeared. Companion restoration shares the stage's `max-blocks-per-cycle` budget with solid-block restoration.
