# PhaseLab Lab-Locked Red Team 5.0

Fabric 1.21.11 telemetry plus bounded active scenario automation for an explicitly paired PhaseLab test server.

## Safety and trust model

Active scenarios are fail-closed. They do not run merely because the player joins a server.

The paired PhaseLab server plugin must:

1. own an Ed25519 private signing key;
2. export its server ID and public key;
3. configure a bounded laboratory region and barrier plane;
4. issue a short-lived authorization tied to the player UUID and that region.

The client verifies the signature, player UUID, server ID, expiry, and region before pressing any automated key. It does not send forged movement packets or directly mutate player/vehicle position.

## Install the client lock

After the server plugin has started once, copy these two files:

```text
plugins/PhaseLabServer/client-lock/server-id.txt
plugins/PhaseLabServer/client-lock/server-public-key.txt
```

into:

```text
.minecraft/config/phaselab/server-id.txt
.minecraft/config/phaselab/server-public-key.txt
```

The server private key remains in `plugins/PhaseLabServer/identity.properties` and must never be copied to the client or committed.

## Controls

Telemetry controls remain available:

- `F7`: cycle telemetry test label;
- `F8`: pause/resume telemetry;
- `F9`: start/end a named telemetry segment;
- `F10`: show telemetry status and file paths.

Signed active controls:

- `F6`: cycle active scenario;
- `F12`: run the selected scenario or abort the current one.

Available v5 scenarios:

- `PRESS_FORWARD`: hold forward for 160 ticks, then observe;
- `PULSE_FORWARD`: repeated bounded forward pulses;
- `DISMOUNT_EDGE`: forward input with a fixed two-tick dismount input;
- `BRAKE_RELEASE`: forward pressure followed by a stationary observation window.

## Exact run rhythm

1. Stand inside the configured PhaseLab region.
2. Mount the test boat or vehicle.
3. Run `/phaselab authorize <player>` as an operator.
4. Confirm the client says `SIGNED LAB AUTH ACTIVE`.
5. Press `F6` to select the scenario.
6. Press `F9` to start a matching telemetry segment if desired.
7. Press `F12` to run.
8. The server classifies the outcome and rolls back the player and vehicle.
9. Press `F9` to close the telemetry segment.

## Server verdicts

- `BLOCKED`: no meaningful crossing was observed;
- `TRANSIENT_CROSSING`: the barrier coordinate was crossed briefly, without persistent solid overlap;
- `FORCED_DISMOUNT`: the passenger relationship ended during a scenario that did not request a dismount;
- `REPRODUCED`: player or vehicle remained beyond the barrier while overlapping solid blocks for the configured number of ticks;
- `SAFETY_ABORT`: world, region, or distance limits were violated;
- `ABORTED` / `EXPIRED`: operator/client abort or authorization expiry.

## Evidence files

Client telemetry:

```text
.minecraft/PHASELAB_LATEST.csv
.minecraft/config/phaselab/PHASELAB_LATEST.csv
.minecraft/PHASELAB_STATUS.txt
.minecraft/PHASELAB_SUMMARY.txt
```

Server-authoritative reports:

```text
plugins/PhaseLabServer/reports/<date>.jsonl
```

## Install

Place the client JAR and Fabric API in the client `mods` folder. Place the server JAR in the test server's `plugins` folder. Java 21 is the build target.
