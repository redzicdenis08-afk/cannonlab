# ExtremeCraft candidate pack

This pack contains two real single-input cannon candidates and one controlled legal-versus-over-cap saturation experiment.

## `ec-streambreach-120.schem`

- 112 charge dispensers and 8 payload dispensers
- fires north, toward negative Z
- one fire input at relative coordinate `17,6,25`
- charge bank receives one repeater tick before dispensing
- payload path uses 33 redstone ticks, while the charge path uses one redstone tick
- relative payload delay is therefore 32 redstone ticks, or 64 game ticks
- charge TNT detonates 80 game ticks after dispensing; at the charge explosion the payload has about 64 game ticks of fuse remaining
- broad source-water chamber, obsidian floor/back/sides, and a bottom-slab water stop
- 120 total dispensers, below both a 128-per-chunk conservative cap and the measured 160-per-chunk cap at every alignment

This is a calibration candidate, not a promise of 15-chunk penetration. Private ExtremeCraft anti-lag, TNT caps, velocity clamps, FAWE behavior, durable blocks, and regeneration plugins can only be proven with live canaries.

## `ec-pocketcounter-24.schem`

- exact 16 by 16 footprint
- 20 charge dispensers and 4 payload dispensers
- one fire input at relative coordinate `9,6,15`
- same 64-game-tick relative payload timing as the main candidate
- intended for fast paste/build and short-range counter testing

## Saturation experiment

- `ec-satplate-legal-120.schem` keeps 120 dispensers in one chunk column
- `ec-satplate-overcap-240.schem` deliberately places 240 dispensers in the same chunk column
- both use identical 15-dispenser firing rows and simultaneous lab inputs
- the comparison measures whether additional TNT survives the runtime or simply saturates/truncates

The 240 version is a laboratory control. It is not labeled pasteable or raid-ready on ExtremeCraft.

## Paste discipline

Paste the cannon with its schematic minimum corner on a chunk corner. The audit scans every X/Z offset because a legal aligned distribution can become illegal after an off-grid paste.

Run `python3 scripts/generate-candidates.py` before auditing. Generated `.schem` files are deterministic gzip-compressed Sponge Version 2 files with DataVersion 3465 and explicit empty dispenser block entities.
