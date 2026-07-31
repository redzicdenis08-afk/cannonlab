# PhaseLab Persistent Animal 9.0.0

Single-mount persistent stream for pigs / horses / donkeys / mules.

Designed for factions claim rules: mount only in wilderness, never remount inside claim.

## Rules
- Mount once in wilderness.
- Press P.
- Client streams small absolute vehicle packets only.
- Any passenger detach or vehicle correction = hard abort.
- No remount logic exists.
- Stay mounted until far-side or abort (O).

## Profile
- Step: 0.10
- Pace: every 2 ticks
- Max distance: 12.0 blocks
- Packet-only, absolute targets from mount start
- noPhysics scoped to packet construction only

## Build
```
gradle -p phaselab-persistent-animal-9.0.0 remapJar --offline --no-daemon
```

Authorized targets only (loopback auto, others via config).
