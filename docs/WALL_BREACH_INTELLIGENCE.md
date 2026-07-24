# CannonLab wall-breach intelligence

CannonLab must distinguish a loud shot from a usable breach. A serious wall contract requires the right payload to reach the target, concentrate damage on protected cells, open a connected aperture, continue through the same lane, beat regeneration when enabled, and leave the cannon alive.

`wall-breach-intelligence.py` is the fail-closed post-run layer for that contract.

## Command

```powershell
python scripts/wall-breach-intelligence.py <run-directory-or-run-summary.json> `
  --profile watered-obsidian `
  --json-out wall-breach.json
```

Built-in profiles:

- `diagnostic`: produces root-cause evidence without demanding a successful breach.
- `dry-obsidian`: requires one directly reconstructed four-hit durability sequence, a connected opening, same-lane front-layer progress, zero self-damage and full dispenser survival.
- `watered-obsidian`: adds falling payload, embedded target-contact explosion and zero unembedded water explosions.
- `regen-course`: requires a connected two-layer lane and a positive measured margin before the first actual restore.
- `raid-course`: requires at least five shots, perfect usable-breach rate, stable breach lane, falling payload, course continuation and cannon survival.

CLI flags can tighten a profile. They cannot silently weaken a built-in requirement unless an explicit replacement value is supplied and preserved in the JSON contract.

## Evidence reconstructed

### Per-cell durability concentration

The analyzer groups `DURABILITY_HIT`, `DURABILITY_BREAK`, and `TARGET_DESTROYED` events by exact target coordinate.

A direct four-hit sequence requires the same cell to report:

1. remaining `3/4`,
2. remaining `2/4`,
3. remaining `1/4`,
4. break with `hits=4`.

Four hits spread across four blocks are labeled `durability-hit-scatter`; they do not prove an obsidian break contract.

Native Sakura final destruction without intermediate hit callbacks is labeled `native-final-break-only`. It is real final-break evidence, but not direct proof of the entire concentrated hit sequence.

### Connected opening

Destroyed target cells are projected into the target wall plane. Four-neighbor connected components are measured per layer. A raw destroyed-block total cannot pass when the cells do not form the required aperture.

### Same-lane continuation

Every destroyed cell is assigned a cross-section lane:

- east/west targets: `(y,z)`,
- north/south targets: `(x,y)`.

Contiguous progress counts only when the same lane contains layer `0`, then layer `1`, then layer `2`, and so on. Damage on unrelated heights or lateral positions cannot fake a multi-layer breach.

### Embedded payload

`breach-events.csv` is used to distinguish:

- TNT explosion at the target,
- explosion center inside water,
- measured falling-block overlap,
- water-contact explosion with no falling payload.

A watered-obsidian profile requires direct falling-overlap evidence and rejects unembedded water explosions.

### Falling-payload trajectory and impulse attribution

The analyzer reads every falling-block trajectory from `events.csv` and reports:

- maximum forward displacement,
- reverse displacement,
- closest target distance,
- dominant-axis cosine,
- significant velocity impulses,
- nearest TNT explosion in the same tick window,
- impulse alignment with the target axis.

This separates timing failures from geometry failures. A sideways propulsion impulse is not sent into a blind repeater sweep.

### Regeneration race

The course is evaluated before the first real `REGEN_RESTORE`, not before a configured or guessed delay. A positive race margin requires the required same-lane breach to finish before restoration begins.

### Cannon survival

A wall pass can require:

- zero self-damage,
- minimum remaining-dispenser ratio,
- repeated usable-breach rate,
- repeated dominant-lane stability.

A wall can break while the cannon dies; that is still a failed raid machine.

## Diagnoses

The report can emit:

- `payload-axis-mismatch`
- `falling-payload-stalled`
- `falling-payload-backfire`
- `propulsion-impulse-off-axis`
- `propulsion-impulse-reversed`
- `tnt-only-target-contact`
- `payload-near-wall-timing-gap`
- `durability-hit-scatter`
- `native-hit-sequence-unobserved`
- `no-connected-opening`
- `no-contiguous-breach-lane`
- `regen-wins`
- `self-damage`
- `dispenser-loss`
- `fake-green-contract`
- `target-contact-without-damage`
- `range-underreach`

Every diagnosis includes a specific next-action class. The report does not claim that one diagnosis proves a particular named module without module-source attribution.

## Current v19 one-stacker finding

The current eight-dispenser `EC160-ONE-STACKER-HYBRID-v19-CEILING` is a diagnostic prototype, not a modern raid cannon.

On the real ten-shot watered-obsidian run:

- one TNT reached the east target plane,
- no falling payload reached that plane,
- the main falling entity remained near `x=8.5`,
- the strongest attributed impulse occurred at tick `213`,
- source TNT: approximately `(8.51, 101.0, 6.51)`,
- falling recipient: approximately `(8.498, 102.493, 5.326)`,
- measured delta velocity: approximately `(-0.001685, +0.356121, -0.170161)`,
- east-target impulse cosine: approximately `-0.0043`.

The strongest clean impulse therefore points almost perpendicular to the east target. This is an exposure/orientation problem, not evidence that more TNT or a random delay change is needed.

The decoded geometry supports that diagnosis:

- the falling sand is staged above the east barrel area,
- the main water charge lies west of it,
- two bottom slabs sit in the direct charge-to-payload window,
- the nearest clean impulse comes from the side TNT rather than the intended forward power.

A bounded five-variant exposure experiment tests the baseline, each slab separately removed, both removed, and both replaced by water. Promotion remains forbidden unless runtime evidence improves forward payload displacement without self-damage or dispenser loss.

## Truth boundary

This tool proves only the supplied runtime files and the selected contract. Public Sakura/Paper results do not prove private ExtremeCraft behavior. An EC-ready claim still requires exact paste alignment, EC160 legality, known block-entity pressure, native control activation, repeated live canaries, and the field defense course.
