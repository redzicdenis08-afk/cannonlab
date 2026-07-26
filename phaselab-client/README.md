# PhaseLab Client 2.0

Client-only Fabric 1.21.11 movement acceptance probe for an authorized Sakura test server.

## Controls

- `F7`: cycle scan direction: forward, down, up
- `F8`: scan meaningful destinations behind the next solid layer
- `F9`: retry the largest candidate that received no server setback
- `F10`: abort or restore the starting position

## What changed in 2.0

- Scans actual player-sized collision boxes instead of blind open-air offsets.
- Tests only destinations where the path crosses a collision and the endpoint is clear.
- Sends explicit movement packets so results do not depend only on vanilla batching.
- Hooks `ClientboundPlayerPositionPacket` directly to detect Sakura/Paper setbacks.
- Restores and settles between attempts.
- Logs outbound probe packets, correction packets, target error and result.

Logs are written to:

```text
.minecraft/config/phaselab/scan-v2-*.csv
```

`NO_SETBACK_OBSERVED` means no position-correction packet arrived during the verification window and the client remained near the destination. It is stronger evidence than the old client-only check, but only the server itself can prove its final authoritative position with certainty.

## Install

Place the built JAR and Fabric API in the client `mods` folder. No server plugin is required.
