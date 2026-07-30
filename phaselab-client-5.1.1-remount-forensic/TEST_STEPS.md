# PhaseLab 5.1.1 remount-forensic test

## Install

1. Remove every other PhaseLab JAR from the client `mods` folder.
2. Install only the 5.1.1 remount-forensic JAR and keep Fabric API installed.
3. Start Minecraft 1.21.11.
4. Join only the private server you own or are explicitly authorized to test.
5. If PhaseLab refuses the target, add the exact multiplayer-list address to:

```text
.minecraft/config/phaselab-remount-forensic/authorized-targets.txt
```

## Run

1. Use the same boat or bamboo raft for the entire attempt.
2. Mount it and face the intended test direction.
3. Press `P` once.
4. Do not touch movement controls while a pulse or quiet window is active.
5. If chat asks for a manual remount, right-click the **same vehicle once**.
6. Do not move during the one-second stable-mount check.
7. The probe stops after two attempted blocks. `O` aborts immediately.

## Report

Preserve the newest CSV from:

```text
.minecraft/config/phaselab-remount-forensic/
```

Also capture:

- the final authoritative server coordinate snapshot;
- whether the server reports the same vehicle or no vehicle;
- whether a far-side barrel or other server-originated witness opened;
- the exact PhaseLab final chat line;
- matching anti-cheat and passenger/vehicle logs.

## Verdict rule

Do not count an outside-map camera view, stable remount, missing correction packet, or `client-observed retained` value as a phase. The server snapshot plus far-side witness must agree.
