# PhaseLab 5.1 remount forensics

Date: 2026-07-30

## Trigger

A real-player screenshot showed PhaseLab Pulse 5.1 entering this sequence:

1. one short boat pulse;
2. server rider/vehicle separation;
3. one automatic remount interaction;
4. manual right-click fallback on the same vehicle;
5. twenty-tick stable-mount validation;
6. termination with `Vehicle disappeared`.

A later verifier build terminated immediately on authoritative passenger detach and therefore could not investigate this lifecycle.

## Exact artifact recovered

Three byte-identical copies of the original client were found in the workspace.

- version: `5.1.0`
- bytes: `34337`
- SHA-256: `57433d85ec5985dca7c4ea40db420d728f7ce2aac16c653db26e6de4e47bf7cc`
- source project: `output/phaselab-client-5.1-pulse/phaselab-client/`

## Exact 5.1 grammar

- Boat forward pulse: `1.00` block.
- Step: `0.25` block.
- Rate: one movement packet per client tick.
- Post-pulse settle: ten ticks.
- Separation quiet window: eight ticks.
- Automatic remount: one normal interaction.
- Automatic result wait: twelve ticks.
- Manual fallback timeout: 120 ticks.
- Stable-remount requirement: twenty ticks.
- Maximum reconciliation attempts per pulse: three.

After a stable remount, the next pulse anchor was reset to the current client vehicle position.

## Root-cause findings

### Why the newer verifier stopped immediately

It promoted the first authoritative passenger detach to a terminal result. That classification is useful for evidence but removes the old client's most interesting state transition: detach, wait, remount, stabilize, and continue.

### Why 5.1 could show an outside-map visual

The original client set the vehicle's local `noPhysics` flag when the run began and restored it only when the entire run stopped. It therefore remained enabled during correction, detach, remount, and stabilization. The vehicle object was also moved locally before each packet. This can preserve a visually dramatic local vehicle/camera position while the server rejects or corrects the rider.

### Why `Vehicle disappeared` appeared after remount

The client retained one Java entity-object reference. A server passenger update or tracker replacement can leave that object marked removed while another local object represents the same server vehicle. The client did not recover by UUID or entity ID, so it terminated even when a same-vehicle remount had just occurred.

### Why `accepted pulse` was not authoritative

The client counted a pulse after a stable local remount and calculated retained progress from the client vehicle object's position. It had no server-coordinate witness. Stable remount and server acceptance are different claims.

## Preserved field-log verdict

Twenty original `pulse-vehicle-v5.1` CSV sessions were recovered from `PHASELAB_LOGS/`.

- Several sessions reached `PULSE_ACCEPTED_AFTER_STABLE_REMOUNT`.
- Most final rows still reported accepted distance `0.00`.
- Some sessions recorded 20 to 48 player-correction events.
- Vehicle-correction events were generally zero.
- Later outside-map-looking sessions still ended with accepted distance `0.00`.

The logs prove a repeatable detach/remount/correction lifecycle. They do not by themselves prove a server-authoritative phase.

## Loopback reconstruction

A loopback-only harness was added at:

`phaselab-harness/pulse-remount-forensics.js`

Results on the isolated `127.0.0.1:25569` runtime:

- Bamboo raft in the permissive claim fixture retained only shallow positions around X `0.104` to `0.203`; no far-side witness opened.
- Oak-boat profiles detached and normal remount failed.
- Strict-mode bamboo control detached and failed remount, finishing outside the claim.
- No deep server-witness-verified remount ratchet was reproduced.

## 5.1.1 forensic design

The isolated derivative preserves the useful remount sequence but adds:

- two-block attempted-distance cap;
- same-UUID and entity-ID tracker recovery;
- forty-tick missing-tracker grace during reconciliation;
- explicit passenger detach/attach telemetry;
- per-packet-only `noPhysics` scope;
- fail-closed evidence logging;
- explicit target authorization;
- `client-observed retained` terminology;
- server snapshot and far-side witness as the only success authority.
