# Field-faithful cannon workflow

Large observer-driven cannon schematics must not be tested by loading TNT during paste updates.

Use the scenario controls below when reproducing the known ExtremeCraft field order:

```yaml
cannon:
  file: candidate.schem
  fire-mode: button
  fire-input: {x: 4, y: 11, z: 13}
  fire-pulse-ticks: 20
  suppress-paste-side-effects: true
  settle-before-fill-ticks: 120
  fill-to-fire-ticks: 10
```

The resulting sequence is:

1. paste the cannon with optional WorldEdit side effects suppressed;
2. audit its dispenser distribution and keep every dispenser empty;
3. allow the configured settle window;
4. fill dispensers with the laboratory equivalent of `/p tntfill`;
5. wait the configured post-fill delay;
6. press the actual saved button block or use the selected fire mode;
7. record causal and entity telemetry.

Defaults preserve the previous fixtures: paste side effects are enabled, the settle delay is zero, and filling occurs immediately. Serious imported cannons should opt into the field-faithful settings explicitly.

## Litematica negative regions

A signed `Size` identifies the opposite selection corner. It does not reverse the packed block-state container. CannonLab normalizes every region from its local minimum corner while preserving x-fastest, then z, then y packed order. Tile-entity coordinates are treated as schematic-relative coordinates before final normalization.

## Evidence boundary

This workflow removes two known local-test artifacts. It does not prove that public Sakura matches ExtremeCraft's private plugins, FAWE configuration, TNT mechanics, or regeneration behavior. Live EC canaries remain mandatory.
