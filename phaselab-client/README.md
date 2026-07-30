# PhaseLab Admin Telemetry 4.1

Passive, client-only Fabric 1.21.11 telemetry for servers you own or are explicitly authorized to test.

## What this build does

PhaseLab 4.1 observes the player and current vehicle without changing movement or collision. It records:

- player and vehicle position/velocity;
- mount, dismount, and vehicle-change events;
- water, lava, swimming, fall-flying, collision, and no-physics state changes;
- periodic one-second samples;
- inbound player and vehicle correction packets;
- correction handler time and correlation to a recent large local move;
- server `OpenScreen` evidence;
- health, air, ground state, player-to-vehicle distance, and client collision-box clearance.

The previous active position and boat-movement classes are not included in this artifact.

## Controls

Controls are registered under **PhaseLab Admin Telemetry** and may be rebound:

- `F8`: pause or resume capture;
- `F9`: write a manual marker before/after an important action;
- `F10`: show current recording, mount, water/lava, and log-path status.

Capture starts automatically when a world/server session becomes available.

## Recommended player test rhythm

1. Join the authorized test server.
2. Press `F9` immediately before the action being tested.
3. Perform one action only, such as mounting, dismounting, entering water, touching a wall, crossing a test boundary, or interacting with a witness container.
4. Press `F9` again after the result is visible.
5. Repeat with a fresh marker pair for the next action.

This creates clean evidence windows instead of one ambiguous movement soup.

## Logs

Each connection receives a unique session file:

```text
.minecraft/config/phaselab/telemetry-v4.1-<timestamp>-<session>.csv
```

The old stale-correlation bug is fixed. A large local move expires after two seconds and is consumed by the next correction packet, so unrelated later teleports cannot inherit an ancient snap timestamp.

## Event meanings

- `SESSION_START`: logger initialized for the current connection.
- `MANUAL_MARK`: player pressed F9.
- `MOUNTED`, `DISMOUNTED`, `VEHICLE_CHANGED`: passenger relationship changed.
- `STATE_CHANGE`: water/lava/collision/swimming/fall-flying/no-physics changed.
- `LOCAL_LARGE_MOVE`: client position changed by at least 0.75 blocks in one tick.
- `SERVER_SETBACK_CORRELATED`: server correction arrived within two seconds of that move.
- `SERVER_POSITION_PACKET`: inbound server position packet without a recent correlated move.
- `SERVER_VEHICLE_CORRECTION`: inbound server vehicle correction.
- `SERVER_OPEN_SCREEN`: server opened a menu/container screen.
- `SAMPLE`: periodic one-second state snapshot.

## Install

Place the JAR and Fabric API in the client `mods` folder. Fabric Loader 0.19.2 or newer and Java 21 are supported.
