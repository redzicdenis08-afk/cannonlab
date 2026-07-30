# PhaseLab Proof Harness 7.0.1

Player-mod-only Fabric client for Minecraft 1.21.11. No server plugin, command, handshake, stealth, randomization, or local `noPhysics` movement is used.

## 7.0.1 startup crash fix

7.0.0 was manually remapped without a Mixin refmap, so its named injection selectors (`handleMovePlayer`, `handleMoveVehicle`, and `handleSetEntityPassengersPacket`) could not resolve in the runtime intermediary namespace. 7.0.1 uses the exact Minecraft 1.21.11 intermediary targets with remapping disabled for those three injection selectors. A preflight verifier confirms all three targets exist on runtime `ClientPacketListener` before release.

## What it measures

The harness sends one short fixed packet-only vehicle segment, observes server player/vehicle corrections and passenger graphs, performs the original quiet/remount lifecycle, waits through a two-second coherence window, then writes a verdict:

- `SERVER_ACCEPTED_CANDIDATE`
- `VEHICLE_ONLY`
- `REMOUNT_UNSTABLE`
- `CORRECTED`
- `PASSENGER_REJECTED`
- `REJECTED`

A candidate is not final proof. Relog once and the harness automatically checks whether the saved server position persists.

## Controls

- `L`: cycle fixed profiles
- `P`: run or stop one bounded test
- `O`: emergency abort

Profiles are fixed and non-adaptive:

- `legacy-5.1`: 0.25 step, 1.00 total
- `micro-0.10`: 0.10 step, 0.40 total
- `micro-0.15`: 0.15 step, 0.60 total
- `micro-0.20`: 0.20 step, 0.80 total

## Setup

1. Remove every older PhaseLab jar from `mods`.
2. Install only `phaselab-proof-harness-7.0.1.jar`.
3. Start Minecraft and join the owned/private test server.
4. Press `P` once. The client creates:

   `config/phaselab-proof-harness/authorized-targets.txt`

5. Add the exact multiplayer server address shown by Minecraft, including its port when present.
6. Rejoin, mount a boat, raft, or saddled horse, choose a profile with `L`, then press `P` once.
7. Do not press `P` again during the run. Right-click the same vehicle only when the client asks.

## Evidence files

Results are written under:

`config/phaselab-proof-harness/logs/`

Return both the newest CSV and matching `-summary.json`. If the verdict is `SERVER_ACCEPTED_CANDIDATE`, relog once and also return `relog-witness.log`.
