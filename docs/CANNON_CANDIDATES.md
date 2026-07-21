# ExtremeCraft candidate pack

This pack contains two single-input cannon candidates and one controlled legal-versus-over-cap saturation experiment.

## `ec-streambreach-120.schem`

- 112 charge dispensers and 8 payload dispensers
- fires north, toward negative Z
- one fire input at relative coordinate `17,6,25`
- 120 total dispensers, statically audited below the conservative 128-per-chunk limit at every alignment

This remains a design candidate. It is not runtime-proven and is not claimed to penetrate modern ExtremeCraft defenses.

## `ec-pocketcounter-24.schem`

- exact `16 x 8 x 16` dimensions
- 20 charge dispensers and 4 payload dispensers
- one included stone button at relative coordinate `9,6,15`, mounted on the cyan fire-control block
- graded water flow toward an open-trapdoor water stop
- payload delay path is 10 redstone ticks versus one redstone tick for charge, a relative delay of 9 redstone ticks or 18 game ticks
- fires north, toward negative Z
- official proof scenario uses ten button-pressed shots against five cobblestone layers at distance 8

After pasting, run `/p tntfill` and press the included button. Do not place another button anywhere on the delay bank. Runtime assertions require two exact TNT spawn cohorts on every shot: 20 charge TNT first, then 4 payload TNT exactly 18 game ticks later. The exact generated geometry must pass the button-powered Paper and Sakura runtime gates before this version is described as repository-verified. ExtremeCraft still requires a live field test.

## Saturation experiment

- `ec-satplate-legal-120.schem` keeps 120 dispensers in one chunk column
- `ec-satplate-overcap-240.schem` deliberately places 240 dispensers in the same chunk column
- both use identical 15-dispenser firing rows and simultaneous lab inputs
- the 240 version is a laboratory control, not a pasteable or raid-ready ExtremeCraft cannon

## Paste discipline

Paste with the schematic minimum corner on a chunk corner. The audit scans every X/Z offset because an aligned legal distribution can become illegal after an off-grid paste.

Run `python3 scripts/generate-candidates.py` before auditing. Generated files are deterministic gzip-compressed Sponge Version 2 schematics with DataVersion 3465 and explicit empty dispenser block entities.

Repeater convention: generator calls use intended signal output direction. Minecraft's saved repeater `facing` blockstate points toward the input, so the writer stores the opposite cardinal direction.
