# MountLab SteerFlip 1.21.11

A client-side Fabric lab harness for reproducing mounted control-item timing on pigs and striders.

## Safety boundary

The mod activates only in singleplayer, localhost, `.local`, RFC1918 IPv4, loopback, or private/link-local IPv6 lab servers. It does not cancel corrections/passenger packets, spam interactions, inject vehicle movement, or bypass claim permissions.

## Controls

- Hold `W`, then press `P`: start/stop a trial while mounted
- `O`: cycle swap interval 1/2/3 ticks
- `K`: cycle max swaps 4/6/8/10/12/16
- `L`: cycle horizontal collision-delta stop threshold 0/0.02/0.04/0.08/0.12

The mod alternates between the correct control stick and another hotbar slot. It stops at the configured **horizontal overlap increase** or exact swap count, locks the control stick, and scores whether the mount remains coupled for 20 ticks.

## Hardening in 1.1

- No first-swap double-send on the start tick
- No per-tick disk writes during the timing-critical trial
- Floor/ceiling contacts excluded from wall-overlap detection
- Baseline collision is subtracted before thresholding
- Exact pure-Java planner with randomized schedule stress tests
- Aborts on screen open, control-item movement, W release, context loss, or timeout
- Retained results include player/vehicle coupling error rather than attachment alone

CSV files are written under `.minecraft/mountlab/` when a trial finishes.
