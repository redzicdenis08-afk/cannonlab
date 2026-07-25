# ExtremeCraft fifteen-chunk regeneration raid program

Verified: 2026-07-25

## Objective

The long-term objective is an evidence-backed CannonLab process capable of producing and validating a legal cannon for a measured ExtremeCraft defense course commonly described as a fifteen-chunk buffer with regeneration defenses.

This is a research and qualification program, not a claim that a qualifying cannon currently exists.

## The five distances and counts that must stay separate

1. **Buffer depth in chunks** describes the claimed or permitted defensive region.
2. **Exact muzzle-to-first-target distance in blocks** controls the first flight solution.
3. **Exact muzzle-to-core distance in blocks** describes the deepest intended target plane.
4. **Regeneration depth in chunks** describes how much of the course actually regenerates.
5. **Wall-group count** determines the number of successful target interactions required.

Fifteen chunks must never be automatically converted into a 240-block shot. The cannon may be placed outside claims, the first defense may begin at a different position, the base core has its own dimensions, and multiple wall groups can exist inside one chunk. Every distance and count must be measured from the exact raid lane.

## Current evidence state

The official ExtremeCraft Cannoning page confirms a dedicated practice environment and current convenience commands such as `/p tntfill` and `/bonetool`. It says Cannoning behavior is designed to closely match Factions, which is useful but weaker than proof of exact private configuration.

Official historical ExtremeCraft updates mention TNT chunk loading and several cannon-mechanics choices. Those statements are valuable hypotheses, but they must be revalidated against the current map and private configuration.

Player suggestions repeatedly discuss fifteen-chunk buffers, eight chunks of regeneration, one- or two-second cannon intervals, velocity-based TNT removal and OSRB compatibility. These are community signals on the official site, not published current rules. CannonLab uses them to select probes, never to fill unknown configuration fields.

The authority-ranked source registry is `research/sources/extremecraft-raid-sources-v1.json`.

## Core proof graph

A general fifteen-chunk regeneration program requires at least:

1. charge force;
2. distinct payload;
3. guider or realignment;
4. held sand release;
5. hammer;
6. sand compression;
7. hybrid payload-sand fusion;
8. slab or filter preparation where present;
9. one-shot cycle composition.

Scatter, double tap, reverse, left/right shot, OSRB and nuke are conditional branches. They are selected only when the measured defense requires them and the current server rule profile permits them.

A larger TNT cohort cannot replace an unproven guider, hammer, compression stage or hybrid interaction.

## Qualification ladder

### 1. Private mechanics fingerprint

Complete the sixteen-dimension paired public-Sakura and ExtremeCraft profile. Priority unknowns include spawn kick, fuse distribution, activation ordering, collision axis behavior, water motion, velocity/removal limits, explosion batching, falling blocks, piston/observer behavior, chunk crossing, EC160 enforcement, FAWE block-entity limits, durability, regeneration, OSRB behavior and the full field workflow.

### 2. Raid-lane survey

Record exact coordinates for:

- cannon paste point and muzzle;
- first target plane;
- every defense-family transition;
- regen start and end;
- core target plane;
- target heights and lateral lane;
- chunk boundaries and player position.

### 3. Module fixtures

Prove each core module independently with source-accounted traces. The candidate must stop at the first failed dependency rather than composing downstream modules around it.

### 4. Single external watered cell

Break one external durable target cell with measured payload-sand overlap, correct lane, durability hits and cannon survival.

### 5. One-chunk defense course

Qualify one exact chunk of the measured defense family. Scattered damage cannot be combined into a fake lane.

### 6. Three-chunk transition course

Test transitions among the measured regen, filter, slab-filter, hotdog and pillar geometry.

### 7. Exact regeneration-depth course

Run the current measured regen depth against the observed replacement order, delay, interval and cap.

### 8. Full fifteen-chunk course

Use the measured wall-group count and actual distances. Passing range alone earns no credit for wall progression.

### 9. One-paste endurance

Repeat the complete firing cycle on one physical cannon with bounded timing/trajectory variance, no hidden rebuilding and accepted dispenser survival.

### 10. Controlled field canary

Replay the exact hashed schematic, paste point, settle/fill timeline, controls and target contract in a low-risk ExtremeCraft test. Local success remains local until this stage.

## Throughput model

The planner calculates theoretical throughput only when these values are supplied:

- measured wall-group count;
- measured shots per wall group;
- permitted and stable fire interval;
- reload/refill overhead per shot.

The calculation deliberately does not use buffer depth as wall count. It also excludes live patching and unknown regeneration unless those behaviors are separately measured. Therefore a theoretical time budget is a scheduling estimate, not proof that a raid completes.

## Usage

```bash
python scripts/plan-extremecraft-raid-program.py \
  profiles/grammar/modern-factions-cannon-grammar-v1.json \
  profiles/parity/extremecraft-private-parity-required-v1.json \
  profiles/raid/extremecraft-15-chunk-regen-objective-v1.json \
  --json-out raid-program.json
```

The canonical profile intentionally returns `BLOCKED`. Fill unknown fields only from dated field evidence and promote module levels only from the existing evidence ladder.

## Truth boundary

A complete program input means the objective is specified well enough to execute research. It does not prove geometry, runtime success, private parity, field readiness or a completed raid.
