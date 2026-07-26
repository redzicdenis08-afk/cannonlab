# PhaseLab Client

Client-only Fabric 1.21.11 microclip tester for an authorized Sakura test server.

## Controls

- `F8`: scan forward offsets from 0.05 to 1.60 blocks
- `F9`: retry the largest offset that survived the correction window
- `F10`: abort or restore the starting position

## What it does

The mod temporarily disables local collision, places the real client player at each tested offset, waits for the server response, and records whether the position held or was corrected.

Logs are written to:

```text
.minecraft/config/phaselab/scan-*.csv
```

A result marked `ACCEPTED` means the client position remained near the target for the test window. It does not prove long-term acceptance under every plugin or movement condition.

## Install

Place the built JAR and Fabric API in the client `mods` folder. No server plugin is required.
