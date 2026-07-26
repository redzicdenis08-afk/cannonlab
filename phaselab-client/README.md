# PhaseLab Client 2.1.1

Client-only Fabric 1.21.11 movement acceptance probe for an authorized Sakura test server.

## Controls

- `F6`: show runtime packet-hook, direction and state status
- `F7`: cycle scan direction: forward, down, up
- `F8`: scan meaningful destinations behind the next solid layer
- `F9`: retry the largest repeatable candidate for a 3-second verification
- `F10`: abort or restore the starting position

## Verification model

- Scans actual player-sized collision boxes instead of blind open-air offsets.
- Tests only destinations where the path crosses a collision and the endpoint is clear.
- Computes scan distance from the current pose's hitbox projection, so upright downward/upward scans can fully clear a one-block layer.
- Sends explicit movement packets so results do not depend only on vanilla batching.
- Hooks the remapped client position-correction handler directly.
- Requires two independent no-setback passes before storing a candidate.
- Restores and settles between attempts.
- Holds the final F9 retry for three seconds and sends two confirmation packets.
- Logs scan range, outbound probe packets, correction packets, target error and result.

Logs are written to:

```text
.minecraft/config/phaselab/scan-v2-*.csv
```

`NO_SETBACK_OBSERVED` means no position-correction packet arrived during the verification window and the client remained near the destination. It is strong client-side evidence, not mathematical proof of the server's hidden authoritative state.

## Install

Place the built JAR and Fabric API in the client `mods` folder. No server plugin is required.
