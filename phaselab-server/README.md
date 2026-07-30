# PhaseLab Server 5.0

Sakura/Paper-side authorization, authoritative verdict, evidence, and rollback plugin for the PhaseLab client.

## First startup

1. Put `phaselab-server-5.0.0.jar` in the test server `plugins` folder.
2. Start the server once.
3. The plugin generates:

```text
plugins/PhaseLabServer/identity.properties
plugins/PhaseLabServer/client-lock/server-id.txt
plugins/PhaseLabServer/client-lock/server-public-key.txt
```

Keep `identity.properties` private. Copy only the two files in `client-lock` to the client's `.minecraft/config/phaselab/` folder.

## Configure the lab

As an operator:

1. Stand at one corner and run `/phaselab setcorner1`.
2. Stand at the opposite corner and run `/phaselab setcorner2`.
3. Stand on the wall/barrier plane.
4. Run `/phaselab setbarrier X` when crossing happens along X, or `/phaselab setbarrier Z` when crossing happens along Z.
5. Run `/phaselab status` and verify the bounds and barrier coordinate.

The configured region should contain the complete fixture, runway, rollback point, and expected movement envelope.

## Authorize and run

```text
/phaselab authorize <player>
```

The signed authorization is player-bound, region-bound, and expires after the configured number of seconds. The client must already have the matching public key and server ID.

Use `/phaselab abort <player>` for an immediate rollback and session cancellation.

## Configuration caps

`config.yml` controls:

- authorization lifetime;
- maximum scenario runtime;
- maximum displacement from the snapshot;
- penetration threshold;
- number of persistent crossing ticks needed for `REPRODUCED`.

The plugin refuses authorization until the region is configured.

## Evidence

Every start and final verdict is appended to:

```text
plugins/PhaseLabServer/reports/<date>.jsonl
```

The server, not the client, calculates crossing progress and performs rollback.
