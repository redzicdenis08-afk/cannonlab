# PhaseLab ExtremeCraft Campaign 6.3

Player-only Fabric 1.21.11 black-box campaign runner hard-locked to `extremecraft.net:25565`.

## Controls

- `F5`: cycle the six bounded campaign profiles.
- `F11`: start the selected campaign or abort immediately.
- Existing `F6` / `F12` geometry-aware single-scenario controls remain available.

The default campaign is `FULL_PRESSURE_MATRIX`.

## Campaign profiles

- `FULL_PRESSURE_MATRIX`: staged continuous pressure, fast and medium pulses, bounded steering oscillation, forward/back reversal, and final forward pressure.
- `PULSE_STRESS`: three pulse densities in one bounded run.
- `STEERING_STRESS`: forward pressure with fast, medium, and slow left/right oscillation windows.
- `BRAKE_REVERSAL`: repeated forward pressure and bounded reverse braking.
- `FORWARD_BACK_STRESS`: alternating forward/back windows at three rates.
- `IDLE_CONTROL`: mounted control with no automated movement.

## Setup

1. Remove older PhaseLab JARs and install the v6.3 JAR with Fabric API.
2. Join `extremecraft.net` on Minecraft 1.21.11.
3. Mount the test boat or vehicle.
4. Center it on the lowest solid wall block and aim at that vertical face.
5. Press `F11` once and do not touch movement keys.

The campaign rejects non-collidable targets, invalid height, and poor alignment. Every run is capped at 360 ticks and 24 blocks of observed travel.

## Evidence

```text
.minecraft/PHASELAB_CAMPAIGN_LATEST.csv
.minecraft/PHASELAB_CAMPAIGN_SUMMARY.txt
.minecraft/config/phaselab/campaign-v6.3-<run>.csv
```

`CAMPAIGN_CANDIDATE` is client-observed evidence that the tracked vehicle remained beyond the selected wall plane inside the selected block corridor. It still requires visual and server-persistence confirmation before treating it as a real phase.

The campaign changes only ordinary forward, back, left, and right key states. It does not construct movement packets or directly modify coordinates, velocity, collision, bounding boxes, or server state.
