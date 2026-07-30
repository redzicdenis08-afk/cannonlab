# PhaseLab ExtremeCraft Geometry 6.2

Fabric 1.21.11 player-only black-box phase research harness for the ExtremeCraft Test Lab. Active scenarios are hard-locked to `extremecraft.net:25565` and refuse to run on other multiplayer addresses.

No server plugin, backend access, commands, copied keys, or credentials are required.

## What 6.2 fixes

The 6.1 detector could report a plane crossing when the boat drove around a wall edge or beneath a selected upper block. Version 6.2 now:

- rejects non-collidable target blocks;
- rejects target blocks whose collision height does not overlap the vehicle bounding box;
- requires the vehicle to begin aligned with the selected block;
- counts a reproduced crossing only while the vehicle remains inside the selected block's lateral corridor;
- reports `LATERAL_ESCAPE` when it crosses the plane outside that corridor;
- logs target coordinates, vertical validation, corridor progress, and lateral offset.

## Install

Place the JAR and Fabric API in the client `mods` folder. Remove every older PhaseLab JAR first. Use Java 21 and Fabric Loader 0.19.2 or newer.

## Controls

- `F6`: cycle the 20 bounded timing scenarios;
- `F12`: start the selected scenario or abort immediately.

The default scenario is `PRESS_FORWARD_SHORT` so the first result is a clean straight-wall control.

## Exact first run

1. Join `extremecraft.net` using Minecraft 1.21.11.
2. Build a solid wall whose bottom row physically overlaps boat height.
3. Put a boat roughly five blocks in front of the middle block.
4. Mount it and aim at the lowest solid vertical wall face directly ahead.
5. Press `F12`.
6. If the selected block is above the boat or has no collision, the client refuses to run and explains why.
7. Otherwise it runs the bounded ordinary-input sequence, releases every automated key, and writes its local verdict.

## Scenario matrix

The matrix contains straight pressure controls, automatic deep sweep, pulse rates, steering patterns, brake-release patterns, forward/back alternation, five dismount timings, and idle control.

Every run is capped at 300 ticks and 24 blocks of observed travel. Disconnecting, changing servers, losing the address lock, or pressing F12 releases all automated keys immediately.

## Local verdicts

- `LOCAL_REPRODUCED`: persistent crossing inside the selected solid block corridor;
- `LATERAL_ESCAPE`: the vehicle crossed the infinite plane only after leaving the selected block corridor;
- `LOCAL_TRANSIENT`: a brief in-corridor crossing;
- `CORRECTED_OR_SETBACK`: one or more sharp backward progress steps;
- `UNEXPECTED_DISMOUNT`: passenger relationship ended without a requested dismount case;
- `DISMOUNT_COMPLETED`: selected dismount case reached its dismount;
- `BLOCKED_OR_REJECTED`: movement occurred but no valid crossing was observed;
- `NO_MOVEMENT`: vehicle moved less than 0.25 blocks;
- safety and lock verdicts end the run immediately.

These remain client-observed black-box results. A `LOCAL_REPRODUCED` result still needs persistence confirmation in the live Test Lab.

## Evidence files

```text
.minecraft/PHASELAB_EXTREMECRAFT_LATEST.csv
.minecraft/PHASELAB_EXTREMECRAFT_SUMMARY.txt
.minecraft/config/phaselab/extremecraft-v6.2-<run>.csv
```

The active runner changes only ordinary forward, back, left, right, and dismount key states. It does not construct movement packets or directly change coordinates, velocity, collision, or bounding boxes.
