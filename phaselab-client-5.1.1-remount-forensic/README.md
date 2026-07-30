# PhaseLab Remount Forensic 5.1.1

A bounded Fabric 1.21.11 diagnostic derived from the exact PhaseLab Pulse 5.1 source.

This build exists to investigate the server lifecycle observed in Denis's screenshots:

1. a short vehicle pulse is sent;
2. the server detaches the rider;
3. PhaseLab waits silently;
4. one normal remount interaction is attempted;
5. the operator may right-click the same vehicle once if needed;
6. the mount must remain stable for twenty ticks;
7. the next pulse begins from the currently tracked same-UUID vehicle.

## What changed from 5.1.0

- Passenger detach is treated as a reconciliation state rather than an immediate terminal failure.
- The original vehicle UUID and entity ID are retained so the client can rebind if Minecraft replaces the local entity object after remount.
- A missing vehicle receives a forty-tick tracker-refresh window during reconciliation instead of immediately printing `Vehicle disappeared`.
- `noPhysics` is enabled only while constructing each movement packet and is restored immediately. The old build left it enabled during reconciliation, which could create a convincing local outside-map clip without server-retained movement.
- Passenger detach and attach packets are recorded separately from player and vehicle corrections.
- The client says `client-observed retained`, never `server-retained`; only server snapshots and far-side witnesses prove acceptance.
- The run is bounded to two attempted blocks.
- Evidence logging and target authorization fail closed.

## Authorization

Singleplayer and loopback addresses are permitted automatically. For another private server you own or are explicitly authorized to test, add the exact multiplayer-list address to:

```text
.minecraft/config/phaselab-remount-forensic/authorized-targets.txt
```

## Keys

- `P`: start or stop the bounded remount probe.
- `O`: emergency abort.

## Evidence

Logs are written to:

```text
.minecraft/config/phaselab-remount-forensic/
```

A camera clip or a stable remount is not success. Preserve the CSV and pair it with an authoritative server coordinate snapshot and a far-side interaction witness.
