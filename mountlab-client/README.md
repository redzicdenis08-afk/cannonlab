# MountLab SteerFlip 1.21.11

Client-side Fabric lab harness for reproducing mounted control-item timing on pigs and striders.

## Safety boundary

Activates only in singleplayer, localhost, `.local`, or RFC1918 private-IP servers. It does not cancel corrections/passenger packets, spam interactions, inject vehicle movement, or bypass claim permissions.

## Controls

- `P`: start/stop a trial while mounted
- `O`: cycle swap interval 1/2/3 ticks
- `K`: cycle max swaps 4/6/8/10/12/16
- `L`: cycle local collision stop threshold 0/0.02/0.04/0.08/0.12
- Hold `W` manually during the trial

The mod alternates between the correct control stick and another hotbar slot. It stops at the configured overlap threshold or swap count, locks the control stick, and scores whether the real client mount remains for 20 ticks.

CSV files are written under `.minecraft/mountlab/`.
