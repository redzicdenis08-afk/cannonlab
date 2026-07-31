# PhaseLab Rider Split Profiler 7.1.0

Player-mod-only Fabric diagnostic for Minecraft 1.21.11. It is designed to measure the exact server transition shown by the 7.0.1 screenshot: the remount is accepted, then the rider is ejected again while progress returns to zero.

## What changed

- Exactly one remount measurement cycle per run. No second retry that pollutes the evidence.
- Three-second final observation window.
- Nanosecond timing for first send, player correction, vehicle correction, first detach, first attach, and the next detach after attach.
- Longest continuously mounted streak after the first packet.
- Ordered event signature in every summary.
- More exact verdicts: `COHERENT_PROGRESS_CANDIDATE`, `VEHICLE_RETENTION_ONLY`, `ATTACHED_THEN_EJECTED`, `ATTACHED_ZERO_PROGRESS`, `CORRECTION_DOMINANT`, `DETACHED_NO_REATTACH`, and `NO_SERVER_TRANSITION`.
- Packet-only movement. No local `setPos`, `noPhysics`, stealth, randomization, server plugin, or server command.

## Controls

- `L`: cycle the four fixed profiles
- `P`: start or stop one bounded run
- `O`: emergency abort

## Setup

1. Delete every older PhaseLab jar.
2. Install only `phaselab-rider-split-profiler-7.1.0.jar`.
3. Join the owned/private test server and press `P` once to create:
   `config/phaselab-rider-split-profiler/authorized-targets.txt`
4. Add the exact multiplayer address, including its port.
5. Rejoin, mount the vehicle, select a profile with `L`, and press `P` once.
6. Right-click the same vehicle only when requested. Do not press `P` again.

Return the newest CSV and matching summary JSON from:
`config/phaselab-rider-split-profiler/logs/`
