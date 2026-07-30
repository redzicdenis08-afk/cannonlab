# PhaseLab Player Active Tester 5.2

Fabric 1.21.11 player-side telemetry plus short, bounded vehicle input scenarios. It needs no server plugin, copied keys, server ID, command, or client configuration.

## Install

Place the JAR and Fabric API in the client `mods` folder. Remove older PhaseLab JARs first. Java 21 and Fabric Loader 0.19.2 or newer are supported.

## Two-key operation

- `F6`: cycle the active scenario;
- `F12`: start the selected scenario or abort the current run.

The default scenario is `PRESS_FORWARD`, so the first test needs only F12.

## Exact first run

1. Join the authorized test server.
2. Put a boat about six blocks in front of the wall.
3. Mount the boat and aim the crosshair at the side face of the wall.
4. Press `F12`.
5. The client detects the far side of that wall block, runs the bounded input, stops every automated key, and prints a local verdict.

After a normal run it advances to the next scenario automatically.

## Scenarios

- `PRESS_FORWARD`: continuous forward input;
- `PULSE_FORWARD`: repeated forward pulses;
- `FORWARD_LEFT`: forward plus left steering;
- `FORWARD_RIGHT`: forward plus right steering;
- `BRAKE_RELEASE`: forward pressure followed by bounded reverse braking;
- `FORWARD_BACK_PULSE`: alternating forward and reverse inputs;
- `DISMOUNT_EDGE`: forward input with a fixed two-tick dismount input;
- `IDLE_CONTROL`: mounted control run with no automated movement.

Every scenario is capped at 260 ticks and 24 blocks of observed travel. F12 aborts immediately.

## Local verdicts

- `LOCAL_REPRODUCED`: the tracked vehicle remained beyond the detected far wall plane for at least five ticks;
- `LOCAL_TRANSIENT`: the vehicle crossed the plane briefly but did not remain there;
- `UNEXPECTED_DISMOUNT`: the passenger relationship ended during a scenario that did not request it;
- `DISMOUNT_COMPLETED`: the explicit dismount scenario reached its dismount step;
- `BLOCKED_OR_REJECTED`: movement occurred but the far wall plane was not crossed;
- `NO_MOVEMENT`: the tracked vehicle moved less than 0.25 blocks;
- `SAFETY_ABORT`: the runtime or travel cap was exceeded.

These are client-observed findings. `LOCAL_REPRODUCED` is a candidate that should be confirmed against the existing correction telemetry or server logs.

## Easy files

Active-run evidence:

```text
.minecraft/PHASELAB_ACTIVE_LATEST.csv
.minecraft/PHASELAB_ACTIVE_SUMMARY.txt
.minecraft/config/phaselab/active-v5.2-<run>.csv
```

Existing correction telemetry continues automatically:

```text
.minecraft/PHASELAB_LATEST.csv
.minecraft/PHASELAB_STATUS.txt
.minecraft/PHASELAB_SUMMARY.txt
```

Telemetry controls remain:

- `F7`: cycle telemetry label;
- `F8`: pause/resume telemetry;
- `F9`: manually start/end a telemetry segment;
- `F10`: show telemetry status and paths.

The active runner changes only ordinary key states. It does not directly change coordinates, collision, velocity, or construct movement packets.
