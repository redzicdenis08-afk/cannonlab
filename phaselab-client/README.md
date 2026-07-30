# PhaseLab Admin Telemetry 4.2

Passive, client-only Fabric 1.21.11 telemetry for servers you own or are explicitly authorized to test.

## What changed in 4.2

- Always writes an easy-to-find `.minecraft/PHASELAB_LATEST.csv`.
- Also keeps `.minecraft/config/phaselab/PHASELAB_LATEST.csv` and a unique archived session CSV.
- Uses local time in filenames instead of UTC-only names.
- Adds named test types and start/end test segments.
- Captures 20 samples per second while a test is active, mounted, colliding, or in water/lava.
- Keeps idle capture at one sample per second.
- Writes `.minecraft/PHASELAB_STATUS.txt` and `.minecraft/PHASELAB_SUMMARY.txt`.
- Reports I/O errors in chat instead of silently failing.
- Adds dimension, block/chunk coordinates, pose, vehicle collision-box state, and passenger count.

The old active position and boat-movement classes are not included in this artifact.

## Controls

Controls are registered under **PhaseLab Admin Telemetry** and may be rebound:

- `F7`: cycle test type: GENERAL, MOUNT, WALL_CONTACT, WATER, CLAIM_BORDER, DISMOUNT, CONTAINER;
- `F8`: pause or resume capture;
- `F9`: start or end the current named test;
- `F10`: show status, counters, and the exact easy CSV path.

Capture starts automatically when a world/server session becomes available.

## Recommended test rhythm

1. Join the authorized test server.
2. Press `F7` until the correct test type is selected.
3. Press `F9` to start the test.
4. Perform one action only.
5. Press `F9` again when the result is visible.
6. Repeat for the next test type.

## Files

The easiest live file is always:

```text
.minecraft/PHASELAB_LATEST.csv
```

The same live session is mirrored at:

```text
.minecraft/config/phaselab/PHASELAB_LATEST.csv
```

Every connection is archived at:

```text
.minecraft/config/phaselab/telemetry-v4.2-<local-time>-<session>.csv
```

Human-readable status and summary files are written to:

```text
.minecraft/PHASELAB_STATUS.txt
.minecraft/PHASELAB_SUMMARY.txt
```

## Important event meanings

- `TEST_START`, `TEST_END`: exact boundaries of one named player test.
- `MOUNTED`, `DISMOUNTED`, `VEHICLE_CHANGED`: passenger relationship changed.
- `STATE_CHANGE`: environment, collision, movement pose, or dimension changed.
- `LOCAL_LARGE_MOVE`: client position changed by at least 0.75 blocks in one tick.
- `SERVER_SETBACK_CORRELATED`: server correction arrived within two seconds of that move.
- `SERVER_POSITION_PACKET`: inbound server position packet without a recent correlated move.
- `SERVER_VEHICLE_CORRECTION`: inbound server vehicle correction.
- `SERVER_OPEN_SCREEN`: server opened a menu/container screen.
- `SAMPLE`: `detail_20hz` during active tests/risky states or `idle_1hz` otherwise.

## Install

Place the JAR and Fabric API in the client `mods` folder. Fabric Loader 0.19.2 or newer and Java 21 are supported.
