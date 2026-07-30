# PhaseLab Ash Client-Only 6.1.0

Player mod only. No server plugin, command, handshake, or server-file installation.

## Install

1. Delete every older PhaseLab jar from the Minecraft `mods` folder.
2. Put `phaselab-ash-client-only-6.1.0.jar` in `mods`.
3. Use Minecraft/Fabric 1.21.11 with Fabric API.
4. Start Minecraft and join the private test server.
5. The mod creates:
   `config/phaselab-ash-client-only/authorized-targets.txt`
6. Add the server address exactly as it appears in the multiplayer entry, including the port when present. One address per line.
7. Mount the boat, raft, or supported horse and press `P` once. `O` aborts.

## Test behavior

The client preserves the original 5.1 bounded lifecycle:

- 0.25-block vehicle steps
- one short pulse
- quiet window after authoritative passenger separation
- one automatic normal interaction attempt
- manual right-click fallback on the same vehicle
- stable-remount check before continuing
- same-UUID vehicle tracker recovery
- passenger/correction CSV logging
- eight-block attempt cap

Logs are written under `config/phaselab/` with an `ash-client-only-6.1-` filename.

The address file is checked whenever `P` starts and while the run is active. An unlisted address remains blocked.
