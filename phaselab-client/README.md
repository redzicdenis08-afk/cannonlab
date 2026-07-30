# PhaseLab Red Team Client 5.5

Fabric 1.21.11 client for authorized PhaseLab Sakura + Grim red-team testing.

Active probes now run on the multiplayer server you are directly connected to.
Only use them on servers you own or are explicitly authorized to test.

## Proven one-wall probe

The local headless lab found a Bamboo Raft-specific one-plane crossing that did
not reproduce with oak boats, chest boats, horses, camels, pigs, striders, or
happy ghasts.

1. Join the private server you are authorized to test.
2. Place a bamboo raft with its center about `0.8` blocks before a one-block
   wall.
3. Mount the raft.
4. Look horizontally and directly through the wall.
5. Press `R` once and keep your hands off movement controls.
6. While still mounted on the far side, open the far-side witness.
7. Dismount normally only after the witness opens.

`R` sends a bounded `2.15`-block route using `0.25`-block vehicle steps at one
packet per tick. `O` aborts immediately. `P` retains the older bounded
diagnostic ladder.

## Current evidence boundary

- Verified: one solid plane, six blocks high, four of four server-authoritative
  mounted entries, four of four far-side barrel witnesses, zero vehicle
  corrections, zero passenger resets.
- Failed: two-block and five-block solid depth.
- Not yet verified: real-player clean dismount, water/lava/regen depth, long
  claim course, or the private production plugin stack.

Logs are written under:

```text
.minecraft/config/phaselab-verifier/
```

## Build

```text
gradle -p phaselab-client clean build --stacktrace --console=plain
```
