# ExtremeCraft calibration contract

CannonLab must not assume that ExtremeCraft's private configuration is identical to the public Sakura defaults. The final calibration treats ExtremeCraft as a black box and matches only observed behavior.

## Rules

- Use a fresh Cannoning plot or an isolated safe test area.
- Paste every probe at a known chunk corner and record the exact origin.
- Use the same client protocol and server commands used for normal cannoning.
- Repeat each probe at least ten times when randomness is possible.
- Record raw coordinates, ticks, screenshots/video, dispenser counts, and outcomes.
- Never infer a mechanic from one large cannon failure. Test one variable at a time.
- Do not upload credentials, launcher tokens, session cookies, or private authentication data.

## Required live probes

### 1. Fuse clock

Fire one isolated TNT from a dispenser. Record the activation tick and explosion tick. CannonLab currently observes the first recorded fuse as 79 and a 79-tick entity-to-explosion lifetime on its pinned runtime. The ExtremeCraft result becomes the reference truth.

### 2. Dispenser launch spread

Fire the same isolated dispenser at least 20 times with no water or nearby TNT. Record the first measurable TNT position and velocity. This identifies random launch spread and any server-side dispenser patch.

### 3. Water flow

Place a TNT entity in a controlled source/flowing-water channel. Record its position and velocity every tick until detonation. Repeat with source water, each relevant flow level, and perpendicular flow directions.

### 4. Falling-block parity

Use a minimal sand or concrete-powder payload with known release timing. Record spawn tick, position, velocity, block state, landing behavior, and whether stacking/merging occurs.

### 5. High-speed survival and adjustment

Launch TNT and falling blocks at increasing velocities. Record clipping, despawn, adjustment, merge, and explosion outcomes. This fingerprints maximum adjustment distance, instant-fall limits, and anti-lag restrictions.

### 6. Durable blocks and regen

Test one controlled explosion against each relevant defense material and a minimal cobblestone/obsidian-style regen cell. Record damage count, replacement timing, fluid updates, and protected-height behavior.

### 7. Redstone timing

Run a short repeater chain containing one-, two-, three-, and four-tick delays. Record dispenser activation order and tick differences. This verifies whether server lag or redstone patches change the expected timing chain.

### 8. Chunk and paste limits

Test schematics with known dispenser distributions around the current user-reported 160-per-chunk boundary. Keep a separate 128-per-chunk case only as a conservative regression profile. Test block-entity pressure independently with gradually increasing known counts because the dispenser chunk cap and FAWE block-entity/NBT paste limit are separate constraints, and the exact FAWE threshold is not yet verified.

## Evidence format

Store each live measurement as JSON using this shape:

```json
{
  "server": "ExtremeCraft Cannoning",
  "captured_at": "ISO-8601 timestamp",
  "client_version": "1.21.11",
  "probe": "single-dispenser-fuse",
  "paste_origin": {"x": 0, "y": 100, "z": 0},
  "chunk_origin_confirmed": true,
  "samples": [
    {
      "shot": 1,
      "activation_tick": 0,
      "first_entity_tick": 1,
      "first_fuse": 79,
      "explosion_tick": 80,
      "spawn": {"x": 1.5, "y": 101.5, "z": 1.5},
      "velocity": {"x": 0.0, "y": 0.0, "z": 0.0}
    }
  ]
}
```

Raw video or screenshots remain supporting evidence. Derived values must never replace the original observations.

## Comparison

1. Convert the live samples into the same aggregate keys produced by `scripts/assert-results.py`.
2. Copy `calibration/fingerprint-rules.example.json` and set tolerances appropriate to each probe.
3. Run:

```text
python scripts/compare-fingerprints.py reference.json candidate.json rules.json
```

4. Change one Sakura/world/scenario setting at a time.
5. Rebuild and rerun until every required metric passes.

## Readiness decision

A cannon may be labeled `local-pass` after static audit and all relevant local scenarios pass. It may be labeled `ec-canary-pass` only after a small live shot reproduces the expected timing and flight behavior. It may be labeled `ec-ready` only after the full intended payload, target type, range, height, and chunk alignment have passed a live canary without exceeding paste or dispenser limits.

Public Sakura parity is strong evidence, not a substitute for this final calibration.
