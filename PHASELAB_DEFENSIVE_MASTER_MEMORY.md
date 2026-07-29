# PHASELAB DEFENSIVE MASTER MEMORY

Verified through July 27, 2026.

This document is the canonical source of truth for PhaseLab's authorized Sakura movement-security research. Do not promote client visuals, filenames, local coordinates, workflow color, or a missing correction packet into server acceptance.

## Evidence labels

- **[exact-runtime]** Pinned Sakura server, translated 1.21.11 client, server-side snapshots, and a completed CI artifact.
- **[server-witness]** Server-originated interaction or plugin-authoritative coordinate proof.
- **[local-client]** Client state only. Never sufficient for a success claim.
- **[fixture]** Laboratory setup behavior, not a production defense guarantee.
- **[unknown]** Not yet reproduced.

## Exact runtime

- Sakura source commit: `63f35d74e0fbe6bcd76c58494c01c1632c83010d`.
- Sakura runtime JAR SHA-256: `88cba5c98e3f31990e8219738ba4f743d3d75aebf1de2770797cb30b81710ed2`.
- Java: 25.
- Translated client: Minecraft 1.21.11 through ViaVersion + ViaBackwards 5.9.0.
- Bot observations are diagnostic only. Final verdicts use plugin snapshots and server-originated witnesses.

## Private plugin-stack parity

**Status: incomplete [unknown].**

The exact PhaseLab reference runtime currently proves pinned public Sakura plus ViaVersion/ViaBackwards behavior. Its public Sakura hash and Via 5.9.0 pair are not promoted to live-server identity. The lab does not yet include a hash-locked export of the live backend, Velocity, FactionsUUID, AuraSkills, ExcellentEnchants, Vault, FactionsUUIDPlus, or the observed custom integration plugins. `profiles/phaselab/extremecraft-plugin-stack-observed-v1.json` preserves the known names without guessing unknown versions. `scripts/phaselab_stack_audit.py` inventories, locks, verifies, and stages only operator-supplied live exports. Until that lock passes with backend, proxy, plugin, and configuration fingerprints, the laboratory must not be called identical to the live server.

## Retired false-positive rules

1. **No correction packet is not acceptance.** A server or proxy may ignore movement silently.
2. **A millisecond visual clip is not server movement.** The local client moves before a correction arrives.
3. **A relative zero-delta `/tp` is not an authoritative coordinate snapshot.** Use a server plugin snapshot command.
4. **Mineflayer passenger state can be stale after translated mount/dismount traffic.** Verify with server-side `vehicle=none` or mounted graph snapshots.
5. **Workflow green is not proof by itself.** Inspect the completed rows and server telemetry.

## Raw movement branch

**Status: rejected [exact-runtime].**

Direct player coordinate packets, position+rotation, grounded/airborne flags, collision flags, segmented movement, Y epsilon, and sneak variants were corrected by Sakura. This branch is closed unless the server source or configuration changes.

## Basic pearl branch

**Status: no verified crossing [exact-runtime].**

Basic face, edge, corner, and top-down pearl matrices produced no exclusive witness-verified phase. Apparent numerical crossings caused by void/fall or client state are invalid.

## Bare Sakura vehicle branch

**Status: core vehicle validation weakness reproduced [exact-runtime].**

Quarter-block vehicle movement can pass ordinary collision validation in the clean Sakura laboratory. This does not imply hostile-claim entry on a production faction stack.

## Claim cancellation ratchet

**Status: vulnerability reproduced, then defensively closed [exact-runtime].**

A cancellation-only mounted player listener can roll the player back after the vehicle has already advanced. Later movement may begin from an already-inside vehicle position and evade an outside-to-inside-only check.

### Required defensive invariants

- Store an outside root-vehicle anchor.
- Inspect every protected destination, not only border transitions.
- Roll the root vehicle and every player passenger back atomically.
- Eject passengers and clear velocity.
- Maintain a post-ejection quarantine because stale mounted traffic can become ordinary player movement.
- Validate the player body after ejection as well as the vehicle.

### Verified regression

`RatchetGuard` blocks batches 8, 10, 16, and 20. Final server player X is `-0.050000`, vehicle is `none`, and no protected witness succeeds.

## SurfaceGuard matrix

**Status: 12/12 passed [exact-runtime].**

Blocked negative controls:

- ender-pearl protected-zone crossing
- chorus-fruit protected-zone crossing
- nether-portal protected-zone crossing
- end-portal protected-zone crossing
- pearl destination overlapping solid geometry
- mounted protected-zone crossing plus stale post-ejection traffic
- four boundary dismount geometries

Allowed positive controls:

- temporary transition token
- TRUCE relation

### SurfaceGuard design

- server-side player and vehicle anchors
- guarded teleport causes
- protected-zone and solid-overlap checks
- recursive passenger rollback
- post-transition quarantine
- dedicated server snapshot command

## DismountAnchorGuard

**Status: required and verified [exact-runtime].**

Vehicle rollback coordinates must not overwrite the player's clean pre-mount escape anchor. `DismountAnchorGuard` captures the last clear unmounted outside position and keeps it distinct from vehicle-local rollback coordinates.

The exact matrix returned all four invalid dismount destinations to `X=-4.500000`, outside the zone, collision-free, and unmounted.

## TransportGraphGuard

**Status: 12/12 passed [exact-runtime].**

Entity classes:

- horse
- pig
- camel
- strider
- minecart
- oak chest boat

For every blocked control, the server returned the player outside to `X=-4.500000`, unmounted, and outside the protected interval.

For every allowed control, the full mounted root/passenger graph entered the protected interval and remained mounted. The deterministic fixture disables gravity and living-entity AI to prevent test drift.

### Artifact hashes

- TransportGraphGuard JAR: `7b1fef7c15e3d41b79175fb40cda6a3adebe5c91cfdab54c6f9aee01598a0462`.
- TransportFixture JAR: `a137c31d7a51faf2ce4dabb1e95ad33badb2709cb6af82ef0d94388bf2d6c69f`.

## Known translation behavior

ViaBackwards/Mineflayer may log partial `entity_teleport` packet decode warnings while the server state remains correct. Treat the server snapshot as authoritative and the client warning as transport diagnostics.

## Production integration boundary

The laboratory relation map defaults to ENEMY for reproducibility. A production deployment must use a real relation-provider adapter and must not infer relations from player-controlled input.

Temporary allow tokens must be short-lived, server-issued, audited, and scoped to a specific transition purpose.

## Next defensive research queue

1. Cross-world passenger graph transfers through nether and end portals.
2. Nested passengers and multiple player passengers.
3. Chunk unload/reload during rollback and quarantine.
4. Piston, slime, honey, water-current, and wind-charge server pushes into protected geometry.
5. Pose transitions during server-created displacement.
6. Regenerating-block rewrites while entities overlap wall planes.
7. PacketEvents pre-Sakura rate limits and stale translated packet drains.
8. Consolidate SurfaceGuard, DismountAnchorGuard, RatchetGuard, and TransportGraphGuard into one production-oriented plugin only after the full matrix stays green.

## Release gate

No PhaseLab defense is production-ready until:

- all exact-runtime negative controls remain outside;
- all intended positive controls still work;
- server snapshots, not client coordinates, provide every verdict;
- no player or root vehicle remains in collision;
- no passenger graph becomes orphaned;
- rollback remains correct across at least one chunk unload/reload cycle;
- telemetry records the trigger, anchor, root entity, passengers, and final state.
