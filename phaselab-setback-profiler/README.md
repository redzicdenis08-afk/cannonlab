# PhaseLab Setback Profiler

Passive server-side evidence collector for authorized Minecraft test servers. It never sends, cancels, rewrites, delays, suppresses, or replays movement packets.

## Why this exists

A PhaseLab client profile can behave differently on clean Sakura and on a stack containing GrimAC or custom enforcement plugins. This profiler records the authoritative server timeline and provides bounded Grim permission controls so the rejecting layer can be identified without guessing from client visuals.

## Verified parity result

Local parity stack:

- Sakura `26.1.2-DEV-HEAD@63f35d7`
- GrimAC `2.3.74-7ae1d8f`
- ViaVersion and ViaBackwards `5.9.0`
- Client test shape matching PhaseLab P-down profile: one vehicle move packet at `Y - 0.25`

Observed server-side result:

- `baseline`: `VehicleExitEvent` and `PlayerTeleportEvent` with cause `DISMOUNT` 5 ticks after the marked packet.
- `grim.nomodifypacket`: the same authoritative eject 7 ticks after the marked packet.
- `grim.nosetback`: no eject inside the 30-tick probe window; target vehicle Y was retained.
- `grim.disabled`: no eject inside the probe window; target vehicle Y was retained.

That isolates this exact instant dismount to Grim's setback path. It does not prove behavior for a private `NoCheatEnforcer` build or a different Grim configuration.

## Install

Build or copy `PhaseLab-SetbackProfiler-1.0.0.jar` into the owned test server's `plugins` folder, then restart.

## Commands

```text
/phaseprofile arm <player>
/phaseprofile mode <player> <baseline|nosetback|nomodifypacket|disabled|exempt>
/phaseprofile mark <player> [label]
/phaseprofile status <player>
/phaseprofile stop <player>
```

Use `mark` immediately before one small, identical probe. The classification window lasts 30 server ticks. Later manual resets are logged as `VEHICLE_EXIT_OUTSIDE_TRIAL_WINDOW` and cannot poison the probe verdict.

Suggested A/B order:

```text
/phaseprofile arm Denis
/phaseprofile mode Denis baseline
/phaseprofile mark Denis p-down-baseline

/phaseprofile mode Denis nosetback
/phaseprofile mark Denis p-down-nosetback

/phaseprofile mode Denis nomodifypacket
/phaseprofile mark Denis p-down-nomodifypacket

/phaseprofile mode Denis disabled
/phaseprofile mark Denis p-down-disabled

/phaseprofile stop Denis
```

Logs are written to:

```text
plugins/PhaseLabSetbackProfiler/sessions/*.jsonl
```

## Interpretation

- Baseline ejects while `nosetback` retains the mount: Grim's setback action is responsible.
- Baseline and `nosetback` eject while `nomodifypacket` retains it: packet cancellation or modification is the differentiator.
- Only `disabled` retains it: a Grim check is responsible, beyond its ordinary setback action.
- `disabled` still ejects: the first authoritative eject is outside Grim, such as a custom claim, enforcement, or vehicle listener.

`exempt` is available as a final control, but Grim can require a rejoin when full exemption registration changes. Prefer `disabled` for a live A/B.

## Build verification

`manual-build.ps1` compiles against the cached Paper 26.1.2 API, packages the plugin, then runs a deterministic classifier self-test. A valid build ends with:

```text
SELF_TEST_PASS
```

## Boundary

This project is defensive telemetry and regression tooling for a server you own or are authorized to test. It is not an anti-cheat bypass and contains no client packet mutator or live-server evasion route.
