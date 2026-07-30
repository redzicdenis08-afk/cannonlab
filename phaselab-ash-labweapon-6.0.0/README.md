# PhaseLab Ash Lab Weapon 6.0

Independent build from the untouched original PhaseLab Pulse 5.1 source and raw 5.1 field behavior.

## Boundary

The client cannot start from a local config toggle. It requires a five-minute arm message emitted by the included OP-only server plugin. This keeps the aggressive original 5.1 detach/remount ratchet tied to an explicitly opted-in private lab server.

## What it preserves

- original 0.25-block vehicle steps
- original 1.00-block boat-forward pulse
- persistent local vehicle noPhysics state during the run
- server detach -> eight-tick silence -> one automatic remount interaction
- manual same-vehicle right-click fallback
- twenty-tick stable remount window
- immediate continuation from the current same-UUID vehicle after stable remount

## Independent fixes

- tracks the original vehicle by UUID and entity ID
- observes authoritative passenger attach/detach packets
- tolerates a forty-tick tracker replacement window during remount
- rebinds to the same vehicle object after client tracker replacement
- stops after eight attempted blocks
- clears authorization on disconnect and after five minutes
- writes client CSV plus server-side arm/witness/vehicle-event CSV

## Install

Server:

1. Put `PhaseLab-Ash-LabAuth-6.0.0-ash-lab.jar` in the private server `plugins` folder.
2. Restart the server.
3. OP the test account or grant `phaselab.labauth.admin`.

Client:

1. Remove all other PhaseLab jars from `mods`.
2. Put `phaselab-ash-labweapon-client-6.0.0-ash-lab.jar` in `mods`.
3. Start Minecraft 1.21.11 with Fabric API.

## Run

1. Join the private lab server.
2. Run `/phaselabarm arm`.
3. Mount the same boat or bamboo raft for the entire attempt.
4. Face the wall and press `P` once.
5. Do not move while the client is silent.
6. When the client explicitly asks, right-click the same vehicle once.
7. Use `/phaselabarm witness` after the attempt for authoritative server coordinates.
8. `O` aborts immediately.

Client logs: `.minecraft/config/phaselab/ash-labweapon-6.0-*.csv`

Server logs: `plugins/PhaseLabAshLabAuth/lab-auth-*.csv`
