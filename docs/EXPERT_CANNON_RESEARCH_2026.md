# Expert Cannon Research 2026

This document records the July 2026 source audit behind CannonLab's expert-physics and EC160 architecture work. It is a technical learning map, not a claim that CannonLab or any candidate cannon is automatically ExtremeCraft-ready.

Machine-readable source metadata and evidence boundaries live in `docs/research/cannon-expert-sources.json`.

## Truth hierarchy

Use this order when claims conflict:

1. Exact candidate/reference schematic bytes and hashes.
2. Repeatable CannonLab runtime traces from the exact file and real control input.
3. Source-audited Minecraft or fork implementation code.
4. Pinned public Sakura/Paper runtime fingerprints.
5. Recorded live ExtremeCraft canaries.
6. Community tutorials, showcases and terminology.
7. Memory, filenames and visual guesses.

A community name is useful search vocabulary. It is not subsystem proof. A sign saying `OSRB`, `Nuke`, `ByPass`, `Double Tap` or `SlabBust` proves only that the builder used that label.

## Corrections to the initial research claims

### AsyncTNT is useful, but not an authority

The inspected AsyncTNT revision is `e1198cd3db220daad2bd5ed7ac0d8a73bb4d89fc`, dated 2026-06-30. It was not updated "yesterday" at inspection time. Its README warns that it is still buggy and in active development.

Use it for implementation-level motion constants, explosion traversal, entity impulse, version-profile questions and fork-divergence tests. Do not use it as proof that its runtime is identical to vanilla, pinned Sakura or private ExtremeCraft.

### The Moonrise early-fuse claim is unproven for the target

A historical Folia/Moonrise report described TNT exploding early in one environment. That does not prove pinned Sakura 26.1.2 or current ExtremeCraft has the same behavior. CannonLab must measure fuse age, explosion age and position directly and compare them to the independent reference model.

### There is no universal hammer-to-sand ratio

No inspected primary source established one universal `hammer:sand approximately 1:1.11` law. Required power depends on explosion exposure, entity alignment, render order, payload distribution, range, water, collision behavior, server patches and intended mode. Ratios are candidate-specific calibration results until reproduced across controlled sweeps.

### CannonLib solves narrower expert problems

CannonLib is a real technical cannoning library. Its inspected surface solves differential basket angle counting, target-to-basket TNT count search using measured efficiency, ROM bit encoding for known designs, explosion vectors and slime-bounce timing search. It does not build a complete 384 OSRB, infer redstone modules, solve EC160 architecture or emulate private server plugins.

## Source-audited physics layer

The modern reference profile implemented by `scripts/cannon_physics_reference.py` uses this source-audited empty-space sequence.

### TNT per tick

1. Apply gravity.
2. Resolve movement/collision.
3. Apply drag.
4. Apply ground horizontal and vertical response when grounded.
5. Decrement fuse.
6. Detonate when the profile condition is met.
7. Apply water-current push only when the entity remains alive.

Modern numeric profile:

- gravity: `0.04`
- drag: `0.98`
- grounded horizontal multiplier: `0.7`
- grounded vertical multiplier: `-0.5`
- water-current scale for TNT: `0.014`

### Falling block per tick

1. Apply gravity.
2. Resolve movement/collision.
3. Apply ground response.
4. Apply drag.
5. Increase age.

The inspected implementation does not apply fluid push to falling blocks. This matters to hybrid design because TNT and falling payload can diverge inside water even when they entered with similar velocities.

### Explosion geometry

The inspected modern explosion implementation uses 1,352 surface rays from a 16 by 16 by 16 boundary grid. Entity impulse depends on distance, exposure and knockback resistance. The practical consequence is that TNT count alone is not power. Exposure, center position, water contact, collision phase and entity order determine how much useful velocity reaches each payload entity.

### Why the independent oracle matters

Comparing two server traces says when they diverged. Comparing a trace to an independent motion oracle can diagnose why.

The current oracle can distinguish likely fuse/tick-phase drift, gravity-order drift, missing or extra water push, drag drift, collision/axis resolution and unmodelled fork effects.

On a real 79-sample CannonLab TNT trace, the oracle matched free flight until tick 32, then identified the Y-axis collision where vertical velocity was clamped. Fuse drift remained zero. This is the intended evidence level: a measured cause, not "the trajectory looks off."

## Expert architecture vocabulary

The definitions below are working engineering descriptions derived from community explanations plus decoded/runtime evidence. They remain server-sensitive.

### 384 stacker

`384` is a community payload or stack-size label, not a total-dispenser count. A 384-class cannon can combine power, one-shot sand, hammer, slab-bust, roof, nuke, nuke hammer, adjust/basket and optional OSRB, backstack, bypass, anti-patch, double-tap or reverse packages.

The current private `2s_384_Nuke.schem` contains 530 dispensers. The decoded Leftshot reference contains 1,231.

### One-power or OOE/OE stacking

Community explanations describe sand rendered before the hammer, with one power package completing the stack interaction. Render order can make a basic one-power setup incompatible with slab-bust because slab-bust TNT may end above the completed stack instead of below it. The lab must measure spawn order, wall arrival order and final stacking behavior rather than encoding one fixed timing.

### Overstack

Community explanations describe overstacking as using hammer swing, overstack sand, an overstack hammer and often a stopper to send material above barrel height and restack it downward.

The win condition is not "sand went upward." The intended material must rise above the normal line, pause or redirect at the required alignment, restack at planned wall coordinates, preserve useful nuke exposure and repeat without clipping or self-damage.

### OSRB

Treat `OSRB` as a community mode label until exact semantics are proven from the candidate trace.

The inspected explanations describe a family of overstack/re-stack workflows that rebuild sand after a top portion has been destroyed. Two broad patterns appear:

1. A separate scatter destroys the top of the stack, then OSRB sand and an OSRB hammer restack it.
2. A combined hammer/scatter performs more than one role on mechanics that permit it.

One source explicitly warns that a single-hammer method did not work on a particular server. Therefore OSRB is not a portable recipe. CannonLab should verify original stack placement, top opening, OSRB sand spawn, OSRB hammer/scatter explosion, restack coordinate, optional overstack interaction and final nuke rewing.

### Nuke and rewing

In large stackers, `nuke` is not synonymous with "many TNT entities." The observed architecture often separates nuke, nuke hammer, rewing/scatter and final dry-stack explosion packages. Rewing can redirect the nuke hammer downward after an overstack/OSRB interaction so the nuke receives useful exposure inside the dry stack.

Runtime proof must identify source dispensers, spawn cohort, explosion cohort, wall position and target effect for every package.


### Slab-bust

A slab-bust package attempts to explode below or inside the falling stack before the sand settles as blocks, clearing slab or low-obstruction cells and allowing the stack/hybrid sequence to continue.

Older tutorials rely heavily on within-tick activation order, comparator/repeater ordering and tunneling behavior. Modern promotion requires exact spawn order, exact explosion age, target-relative Y position, slab destruction before sand settlement and repeatability across at least ten shots.

### Worm or horizontal tunnel stacker

Community worm explanations describe a repeating two-stage idea:

1. Place or maintain a horizontal sand line.
2. Tunnel through that line and immediately restack it farther forward.

Reported package vocabulary includes horizontal stacking sand, tunnel TNT, reverse power, hammer/nuke and height-setting sand. One described order is tunnel TNT, reverse, sand, hammer, then horizontal stacking sand. Treat this as a source-specific hypothesis, not a universal order.

The real worm contract is progression: the lane advances by the intended distance, the prior lane opens, the new lane restacks, reverse/hybrid alignment survives and cumulative drift stays bounded.

### Reverse and rev-hybrid

Reverse modules redirect a payload or sand/TNT package vertically or backward relative to its original travel. Reverse timing must be proven from the entity velocity sign change and correlated source explosion. A north/south panel, slime assembly or label is not enough.

### Leftshot

Leftshot is an output specialization attached to the large shared Asser-family core in the decoded reference corpus. Static comparison proves a large common core with Nuke Force, but clean left-shot output was not reproduced under the tested public Sakura profile.

The module contract must prove which upper/output bank differs, the first lateral velocity-producing explosion, intended lateral wall contact, unchanged lower-core timing and repeatable output.

### Bypass, double-tap, anti-patch and backstack

These names describe intended target interactions, not implementation standards.

- `bypass`: candidate mode intended to avoid or route around a defense layer.
- `double-tap`: candidate mode intended to deliver a second coordinated impact or package.
- `anti-patch` / AP: in one inspected operator guide, a mode intended to remove straight-line dry patches.
- `backstack`: a mode intended to stack behind or into regen/source structures; one guide uses it to attack lava-source rows while disabling nuke.

Each mode needs its own target course and causal contract. Turning on a labeled lever is not a pass.

## EC160 architecture findings

### Alignment comes before redesign

The per-chunk rule depends on the cannon's X/Z placement residue. The same geometry can be legal or illegal depending on the player's paste-origin frame.

The new advisor scans all 256 residues and reports legal residues, maximum dispensers per chunk, chunk distribution, contributing banks, placement fragility, opposing-bank pairs and segmentation scaffolds only when alignment is insufficient.

### Current private 2s 384 Nuke

Static result:

- 530 dispensers,
- 2 safe residues out of 256,
- best schematic minimum-corner residue: X `7`, Z `5`,
- best player `//paste` residue after `WEOffsetZ=-17`: X `7`, Z `6`,
- best maximum: 155 dispensers in one chunk,
- best distribution: 155, 126, 125 and 124,
- placement fragility: extreme,
- current source DataVersion: 4556,
- separate block-entity pressure remains unproven for EC.

Correct conclusion: this candidate does not require immediate dispenser-bank deletion or flattening. It requires exact placement documentation, target-version validation and a reduced-risk field canary. A one-block paste-origin mistake can make it illegal.

### Leftshot reference

Static result:

- 1,231 dispensers,
- 0 safe residues out of 256,
- best maximum: 347 dispensers in one chunk,
- 27 inferred banks,
- five probable opposing-bank pairs.

Correct conclusion: alignment cannot save it. A valid EC160 reconstruction must distribute paired banks across more chunk columns while preserving facing, vertical coordinates, compression symmetry and cohort timing.

## What elite cannon work actually requires

A top-tier workflow is a closed evidence loop:

1. Decode exact geometry and controls.
2. Identify banks and repeated translated modules.
3. Record real source-to-entity-to-explosion cohorts.
4. Compare free-flight motion to an independent physics oracle.
5. Prove collision, water and explosion phases.
6. Define the archetype's wall-level win condition.
7. Change one bounded variable.
8. Preserve untouched module traces.
9. Run dry, watered, regen, filter, slab, hotdog, pillar and endurance courses as appropriate.
10. Calibrate against pinned Sakura.
11. Run reduced-risk live EC canaries.
12. Promote only the level earned.

## Current capability rating

After this upgrade, CannonLab has a stronger expert-analysis layer, but "10/10 cannoner" remains unearned.

Current strengths:

- exact file and NBT forensics,
- causal runtime telemetry,
- independent motion and impulse diagnosis,
- all-offset EC160 placement analysis,
- reference-preserving repair gates,
- shared-core and module comparison,
- archetype-specific research vocabulary.

Remaining blockers:

- exact live EC physics fingerprint,
- clean shared Asser-core output,
- EC160 reconstruction with unchanged cohort timing,
- repeatable modern OSRB/nuke/slab-bust/worm contracts,
- successful live watered-regen and long-buffer canaries.

The target is not knowing more cannon words. The target is producing a candidate whose geometry, timing, flight, wall interaction, survival and repeated live behavior are all evidenced.
