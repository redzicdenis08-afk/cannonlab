# PhaseLab Purple-Team Handoff 8.0

## Executive result

A fixed, non-adaptive vehicle packet profile now has a clean differential across the isolated PhaseLab runtimes:

- `127.0.0.1:25569` (Sakura + Grim, intentionally without RatchetGuard): **20/20 server-snapshot and far-side-witness verified mounted crossings**.
- `127.0.0.1:25568` (same defensive family with RatchetGuard): **0/20 crossings**, every final server snapshot stopped at X `0.450`, before the wall.

This is the red-team deliverable. Purple team has a repeatable failing target, a repeatable protected target, the exact packet grammar, and objective acceptance criteria.

## Exact reproducer profile

Arena coordinates used by the headless harness:

- start: X `0.20`, Y `65.00`, Z `0.01`
- wall: X `1.00` through `2.00`, six blocks high
- target: X `2.35`
- vehicle: bamboo raft
- packet cadence: one packet every 50 ms
- packet sequence: `+0.25` repeated eight times, then a final `+0.15`
- total attempted movement: `2.15` blocks
- packet type: vehicle movement only
- player fallback: not used in the successful mounted path
- success witness: server snapshot beyond the wall while mounted plus opening the far-side barrel

## Stress evidence

### Unguarded red-team runtime, port 25569

- trials: 20
- verified mounted crossings: 20
- far-side witnesses opened: 20
- final server X: `2.350` in every trial
- passenger detach trials: 0
- correction trials: 0

### Guarded regression runtime, port 25568

- trials: 20
- verified crossings: 0
- far-side witnesses opened: 0
- final server X: `0.450` in every trial
- passenger detach trials: 0
- correction trials observed by the translated bot: 0

The protected runtime blocks by keeping the authoritative root vehicle before the wall. The absence of a translated correction event must not be interpreted as acceptance.

## Field-stack mismatch from the player client

Four fresh field captures against the reported server stack showed a different enforcement path:

- first passenger detach arrived roughly 43 to 66 ms after the first vehicle packet
- player correction followed immediately
- no vehicle-correction packet was observed
- the ordinary later remount did not preserve vehicle movement
- three runs finished mounted with zero or negligible movement
- one run detached again after the remount and contained invalid post-detach player displacement

Therefore the local `25569` stack and the field stack are not parity-equivalent. The local weakness is reproducible, but the field stack contains an additional passenger-separation or movement-reconciliation layer.

## Purple-team patch invariants

The defense should preserve the behavior proven on port `25568`:

1. Capture the last valid outside root-vehicle anchor when the rider mounts.
2. Validate every requested vehicle destination against collision and protected-volume geometry.
3. Roll the root vehicle and every player passenger back atomically.
4. Clear vehicle and passenger velocity during rollback.
5. Do not rely only on passenger presence at the vehicle-move callback. Keep a short rider lifecycle watch after mount and detach.
6. Validate delayed player movement after ejection so stale mounted traffic cannot become ordinary player movement.
7. Emit one correlation ID covering requested vehicle position, root anchor, passenger graph, correction source, and final authoritative snapshot.

## Acceptance suite

A patch is accepted only when all conditions hold:

- 20/20 fixed-profile trials remain before X `1.00`
- zero mounted far-side snapshots
- zero far-side barrel witnesses
- zero delayed player-only escapes after detach
- the control runtime without the guard continues to reproduce the weakness
- a normal boat-driving control remains usable

## Client artifact

`phaselab-purple-handoff-8.0.0.jar` is a player-side Fabric 1.21.11 reproducer hard-locked to loopback ports `25568` and `25569`.

Controls:

- `P`: run or stop one fixed reproduction
- `O`: emergency abort

The client sends the exact fixed vehicle packet sequence above, performs no remount loop, contains no editable target allowlist, and writes CSV plus JSON results under:

`config/phaselab-purple-handoff/logs/`

A client verdict is supporting evidence only. The headless server snapshot and far-side witness remain the authoritative proof.
