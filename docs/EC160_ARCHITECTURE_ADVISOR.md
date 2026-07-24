# EC160 Architecture Advisor

`scripts/ec160_architecture_advisor.py` answers the first architecture question for every large ExtremeCraft candidate:

> Can exact X/Z placement make this geometry legal, or must its dispenser banks be reconstructed?

The advisor never edits a schematic. It scans all 256 paste-origin residues, maps dispenser-bank pressure and emits a reconstruction scaffold only when placement alone cannot satisfy the configured per-chunk limit.

## Usage

```powershell
python scripts/ec160_architecture_advisor.py cannon.schem `
  --chunk-limit 160 `
  --json-out ec160-advice.json
```

## Output classes

### `ALIGNMENT_ONLY_CANDIDATE`

At least one of the 256 X/Z residues is legal under the configured dispenser limit.

This does not mean the cannon is EC-ready. Required next checks include:

- correct player `//paste` frame,
- field-target Sponge v2 / DataVersion 3465 compatibility,
- unknown FAWE block-entity pressure,
- empty-paste settling,
- real control activation,
- runtime survival and output,
- reduced-risk live canary.

### `ARCHITECTURAL_REDISTRIBUTION_REQUIRED`

No X/Z residue is legal. The candidate must be rebuilt across more chunk columns.

The advisor groups dense same-facing dispenser geometry into banks, identifies probable opposing-bank pairs and proposes coordinate slices whose dispenser counts fit the configured limit. These slices are not automatic redstone repairs.

## Bank preservation rules

Every reconstruction must preserve or re-prove:

- dispenser facing,
- vertical coordinates and panel dimensions,
- opposing-panel symmetry,
- same-tick cohort membership,
- repeater and observer arrival time,
- piston extension and reset order,
- water containment,
- payload alignment,
- source-to-entity attribution,
- output direction and range,
- cannon integrity.

Moving only one side of an opposing panel is a high-risk change. Randomly deleting dispensers or stretching dust is not a valid EC160 conversion.

## Placement frame

The report preserves both frames:

```json
"paste_origin_mod_16": {"x": 7, "z": 5},
"worldedit_paste_point": {
  "best": {"player_chunk_local_x": 7, "player_chunk_local_z": 6}
}
```

The first value is the schematic minimum-corner scan frame. The second applies Sponge `Metadata.WEOffsetX/Z` and is the residue the player should use for `//paste`. Run `scripts/paste-alignment-audit.py` as a second independent confirmation before a live field canary.

## Verified current examples

### Private `2s_384_Nuke.schem`

- 530 dispensers,
- 2 safe residues out of 256,
- best minimum-corner residue X `7`, Z `5`,
- best player `//paste` residue X `7`, Z `6`,
- best maximum 155 dispensers in one chunk,
- best chunk counts 155, 126, 125 and 124,
- eleven inferred banks,
- two probable opposing-bank pairs,
- placement fragility `extreme`.

This corrects the blanket assumption that every current 384 candidate is 0/256 legal. This file should be placed precisely before any architecture rewrite is attempted.

Important remaining blockers:

- source DataVersion is 4556 rather than the field-target 3465,
- explicit block-entity pressure is separate from dispenser legality,
- local firing and live EC behavior remain unproven.

### Leftshot reference

- 1,231 dispensers,
- 0 safe residues out of 256,
- best maximum 347,
- 27 inferred banks,
- five probable opposing-bank pairs.

Alignment cannot save this reference. Its Asser-family core and paired panels must be distributed across additional chunk columns without changing cohort timing or compression geometry.

## Tests

```powershell
python scripts/test-ec160-architecture-advisor.py
```

The tests cover:

- dense same-facing bank grouping,
- opposite-panel separation and pairing,
- east/west segmentation across Z,
- north/south segmentation across X,
- single-slice overflow disclosure,
- paste-origin residue effects on chunk distribution.

## Truth boundary

The advisor proves static dispenser distribution. It does not prove:

- the unknown FAWE block-entity limit,
- redstone transport after segmentation,
- correct entity order,
- Sakura parity,
- ExtremeCraft runtime,
- any archetype label or wall-level win condition.
