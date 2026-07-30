# PhaseLab Red-Team Client 5.7.0

Fabric 1.21.11 client for servers you own or are explicitly authorized to test.

## Controls

- `F6`: cycle the bamboo-raft red-team profile.
- `F7`: run the selected profile.
- `P`: run the older bounded boat/horse diagnostic ladder.
- `O`: abort immediately.

The selected profile is shown in chat before it runs. Keep your hands off movement controls while packets are being sent.

## What changed from 5.5/5.6

The old client moved the local raft model before every packet and started immediately after the keypress. On stricter stacks that can separate the local passenger graph before the server has fully stabilized the mount.

5.7 waits ten client ticks after the probe is armed, then defaults to packet-only movement. Packet-only profiles leave the local raft untouched, use absolute targets from the mounted start position, synchronize forward-input frames, and record the exact server detach/correction sequence.

## Raft profiles

1. `packet-only-005-3t`: 0.05-block steps, one move every three ticks.
2. `packet-only-010-2t`: 0.10-block steps, one move every two ticks.
3. `packet-only-015-2t`: 0.15-block steps, one move every two ticks.
4. `packet-only-020-1t`: 0.20-block steps every tick.
5. `packet-only-025-1t`: 0.25-block steps every tick.
6. `packet-edge-140`: three 0.25-block approach packets followed by one bounded edge packet.
7. `packet-adaptive-ramp`: ramps 0.05, 0.10, 0.15, then 0.20 blocks.
8. `legacy-local-025`: the old local-mirror route for A/B comparison.

All profiles are bounded to 2.15 blocks and bamboo-raft-only. `F7` never runs the retired 241-block route.

## Current local-runtime evidence

On the isolated Sakura 26.1.2 + Grim + ViaVersion/ViaBackwards runtime:

- one-plane packet-shape matrix: 10/12 server-witness verified;
- accepted stepped envelope: 0.15 through 0.30 blocks;
- 0.40-block stepping: rejected with vehicle corrections;
- edge-leap profile: server-witness verified with four total packets;
- direct 2.15-block leap: rejected;
- chained two-plane profiles: 0/9;
- normal non-invulnerable bamboo raft: verified;
- plain obsidian, water-backed obsidian, and water-before-obsidian with normal shift-input dismount: 9/9 server-authoritative passes.

This does not prove a multi-wall route or private-production parity. Client coordinates remain non-authoritative until matched with a server snapshot and far-side witness.

## Target authorization

Singleplayer, `localhost`, `127.0.0.1`, and `[::1]` are allowed automatically. For another private server you are authorized to test, add the exact multiplayer-list address to:

```text
.minecraft/config/phaselab-verifier/authorized-targets.txt
```

Include the port when present.

## Evidence integrity

The probe refuses to start if its evidence session cannot open. Append, flush, or summary failures abort the run. Passenger detach and reattach are latched separately. Every event has a monotonic sequence number.

After a mounted crossing, open the far-side witness while still mounted, then use normal sneak to dismount. Preserve the newest JSONL and summary files plus matching server, Grim, Via, and claim-plugin logs.

## Exact first test

Mount a normal bamboo raft, face horizontally, press `F7`, and do not touch movement. The default `packet-only-005-3t` profile arms for ten ticks before sending anything. If it survives, use `F6` to advance through the envelope. Preserve the newest JSONL and summary after each detach or correction.

## Build

```text
gradle -p output/phaselab-redteam-5.7.0-authenticated remapJar --offline --no-daemon --stacktrace --console=plain
```
