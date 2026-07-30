# PhaseLab ExtremeCraft Locked 6.1

Fabric 1.21.11 player-only black-box phase research harness for the ExtremeCraft Test Lab. Active scenarios are hard-locked to `extremecraft.net:25565` and refuse to run on other multiplayer addresses.

No server plugin, backend access, commands, copied keys, or credentials are required.

## Install

Place the JAR and Fabric API in the client `mods` folder. Remove every older PhaseLab JAR first. Use Java 21 and Fabric Loader 0.19.2 or newer.

## Controls

- `F6`: cycle the 20 bounded timing scenarios;
- `F12`: start the selected scenario or abort immediately.

The default scenario is `AUTO_DEEP_SWEEP`.

## Exact first run

1. Join `extremecraft.net` using Minecraft 1.21.11.
2. Put a boat roughly six blocks in front of the test wall.
3. Mount it and aim the crosshair directly at a horizontal side face of the wall.
4. Press `F12`.
5. The client verifies the server-address lock, detects the wall plane, runs the selected ordinary-input sequence, releases every automated key, and writes its local verdict.

## Scenario matrix

The matrix contains:

- automatic deep sweep;
- short and long forward pressure;
- fast, medium, and slow forward pulses;
- sustained left/right steering;
- fast and slow alternating steering;
- short and long brake-release patterns;
- fast and slow forward/back alternation;
- dismount edges at ticks 20, 35, 50, 65, and 80;
- idle control.

Every run is capped at 300 ticks and 24 blocks of observed travel. Disconnecting, changing servers, losing the address lock, or pressing F12 releases all automated keys immediately.

## Local verdicts

- `LOCAL_REPRODUCED`: the tracked vehicle remained beyond the selected wall plane for at least eight consecutive client ticks;
- `LOCAL_TRANSIENT`: the vehicle crossed briefly but did not remain there;
- `CORRECTED_OR_SETBACK`: the client observed one or more sharp backward progress steps;
- `UNEXPECTED_DISMOUNT`: the passenger relationship ended without a requested dismount case;
- `DISMOUNT_COMPLETED`: the selected dismount case reached its dismount;
- `BLOCKED_OR_REJECTED`: movement occurred but the wall plane was not crossed;
- `NO_MOVEMENT`: the vehicle moved less than 0.25 blocks;
- `SAFETY_ABORT`, `LOCK_ABORT`, or `CONNECTION_CHANGED`: the run ended safely.

These are client-observed black-box results. `LOCAL_REPRODUCED` is evidence to verify by moving around, waiting for corrections, and checking whether the position persists server-side.

## Evidence files

```text
.minecraft/PHASELAB_EXTREMECRAFT_LATEST.csv
.minecraft/PHASELAB_EXTREMECRAFT_SUMMARY.txt
.minecraft/config/phaselab/extremecraft-v6.1-<run>.csv
```

Existing passive correction telemetry continues automatically:

```text
.minecraft/PHASELAB_LATEST.csv
.minecraft/PHASELAB_STATUS.txt
.minecraft/PHASELAB_SUMMARY.txt
```

The active runner changes only ordinary forward, back, left, right, and dismount key states. It does not construct movement packets or directly change coordinates, velocity, collision, or bounding boxes.
