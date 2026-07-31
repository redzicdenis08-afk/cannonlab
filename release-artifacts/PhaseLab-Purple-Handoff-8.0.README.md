# PhaseLab Purple Handoff Client 8.0

This is a player-mod-only Fabric 1.21.11 reproducer for the isolated PhaseLab laboratory.

## Hard lock

The client runs only on these loopback endpoints:

- `127.0.0.1:25568`
- `127.0.0.1:25569`
- equivalent `localhost` or IPv6 loopback forms

There is no editable allowlist and no server plugin.

## Install

1. Remove every older PhaseLab jar from `mods`.
2. Install only `phaselab-purple-handoff-8.0.0.jar`.
3. Join the guarded runtime on port `25568` or the unguarded red-team runtime on port `25569`.
4. Mount and control a boat or bamboo raft.
5. Face directly toward the one-plane wall.
6. Press `P` once.
7. Press `O` to abort.

## Fixed profile

- ten stable mount ticks
- `0.25` blocks per tick
- eight quarter steps plus one final `0.15` step
- `2.15` blocks total
- two-second observation window
- no remount loop
- no adaptive timing
- no local `setPos`
- no `noPhysics`

## Evidence

Client logs are written to:

`config/phaselab-purple-handoff/logs/`

Return the newest CSV and matching summary JSON. Client coordinates are supporting evidence only. The authoritative laboratory proof is the server snapshot plus far-side witness contained in `PURPLE_TEAM_HANDOFF.md` and the bundled stress reports.
