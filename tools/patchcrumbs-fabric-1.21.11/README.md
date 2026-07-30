# Denis Patchcrumbs

Standalone client-side Fabric mod for Minecraft 1.21.11. It captures the exact explosion center sent by the multiplayer server, clusters nearby explosions from the same volley, shows the likely patch coordinates in the action bar, and draws an end-rod particle marker at the selected block.

## Install in Dawn or Feather

1. Use the Minecraft 1.21.11 Fabric profile.
2. Install Fabric API for 1.21.11.
3. Put `denis-patchcrumbs-1.0.0.jar` into that profile's `mods` folder.
4. Launch and join the server.

The mod is automatic. When the client receives explosions, the HUD shows `X Y Z`, estimated wall axis, distance, and clustered blast count for 30 seconds. The marker remains visible for 10 seconds.

## Detection model

This does not guess from sound direction. It injects into `ClientPacketListener.handleExplosion` and reads `ClientboundExplodePacket.center()`, then merges explosion centers within three blocks and eight client ticks. The displayed candidate favors impacts that are both recent and near the player.

## Boundaries

- Client-side only. The server does not need the mod.
- No printer, automatic block placement, combat automation, or hidden-player detection.
- It can only mark explosions the server actually sends to the client.
- Compile success proves API compatibility, not that a specific server permits the mod. Check that server's rules before using it.
