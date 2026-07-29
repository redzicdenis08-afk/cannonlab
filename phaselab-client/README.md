# PhaseLab Client 4.3

Client-only Fabric 1.21.11 position laboratory for servers you own or are explicitly authorized to test.

## Why V3 exists

V2 treated â€œno correction packetâ€ as evidence that the server accepted a move. That was too weak: a server or proxy can silently ignore movement while leaving the client visually displaced.

V3 has three labels:

- `LOCAL_ONLY_NO_SETBACK`: the client moved and no setback arrived, but the server did not prove the target position.
- `SETBACK_*`: a real server position correction arrived.
- `SERVER_VERIFIED_WITNESS_OPEN`: a container reachable only from the target opened through a server `OpenScreen` packet.

Only the third result is called server-verified.

## Controls

The controls are registered under the **PhaseLab** category and can be rebound normally:

- `P`: start or stop the verified vehicle ratchet
- `O`: emergency stop

- `F5`: status
- `F6`: set or clear the block under the crosshair as the witness
- `F7`: cycle forward, right, backward, left, down, up
- `F8`: scan the first complete collision layer and clear exit gap
- `F9`: apply the best geometry point and run witness verification
- `F10`: abort and restore

## One-button vehicle mode

1. Mount and control a normal boat or a tamed saddled horse.
2. Look horizontally in the direction you want to travel.
3. Press `P` once. The direction and starting height are locked immediately.
4. Press `P` again to stop, or `O` to emergency stop.

Boat mode automatically uses 19-block bursts. Horse mode automatically uses 10-block bursts. Both use 0.25-block packet steps and 100 ms pauses. Horse mode still needs normal survival precautions such as Fire Resistance for lava courses.

## Witness test rig

Use a barrel, chest, furnace, crafting table, or another block that causes the server to send an `OpenScreen` packet.

Place it so that:

- it is within about 5.5 blocks of the intended target position;
- it is at least about 6.25 blocks from the starting eye position;
- it is exposed and can be right-clicked;
- it cannot be opened from the start position.

Look directly at it and press the Witness key before scanning/applying.

## Verification model

- Registered keybindings avoid Feather/Dawn raw-function-key conflicts.
- Uses `absSnapTo` plus explicit full position/rotation packets.
- Scans actual player-sized collision boxes using the current pose.
- Detects the first clear interval after a real collision layer.
- Scores interior gap points by clearance instead of choosing the farthest offset.
- Tests scan candidates twice.
- Hooks both server position-correction and server open-screen packets.
- Refuses to call an apply successful without target-only witness proof.
- Automatically restores on correction or witness timeout.

Logs are written to:

```text
.minecraft/config/phaselab/phaselab-v3-*.csv
```

## Install

Place the JAR and Fabric API in the client `mods` folder. Fabric Loader 0.19.2 or newer is supported. No server plugin is required.
