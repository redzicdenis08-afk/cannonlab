# Advanced Cannon Intelligence Research

Verified: 2026-07-24

## Purpose

CannonLab must learn advanced factions cannoning from evidence, not filenames, screenshots, labels, or one lucky shot.

The target is a closed loop:

1. decode an exact schematic;
2. identify authored ratio and architecture constraints;
3. capture source-accounted redstone, TNT and falling-block traces;
4. construct an impulse and collision graph;
5. reproduce the exact defense contract;
6. change one bounded module;
7. replay and compare untouched modules;
8. validate the exact candidate through a small live ExtremeCraft canary.

No local Paper/Sakura result is private ExtremeCraft proof.

## High-value findings

### A 384 is a payload contract, not a dispenser-count claim

The strongest public ratio evidence found is in `Samsuik/CannonLibrary` at commit
`9146378dd96d685a181b6a9b836e0ee9a1141f64`.

Its public `0.7 384 osrb 1 above barrel` example contains:

| Cohort | Amount | Authored timing |
| --- | ---: | ---: |
| Sand power | unspecified power | 0.0 |
| Hybrid sand 1 | 2 | 6.3 |
| Reverse TNT | 10 | 7.1 |
| Hybrid sand 2 | 1 | 7.3 |
| Hammer | 561 | 8.1 |
| Main sand | 381 | 8.3 |
| OSRB sand | 9 | 8.3 |
| OSRB hammer | 31 | 9.1 |
| Scatter | 6 | 15 |

The base stack accounts exactly:

`381 main sand + 2 hybrid sand + 1 hybrid sand = 384`

The nine OSRB sand entities are an attachment payload, not part of the base 384 accounting.

A second public `1.2s 384 4os-osrb`-derived example preserves open and ranged timing
tokens such as `10+`, `4-8`, and `16-17`. Its upstream comment says OSRB was removed.
CannonLab therefore stores it as a derived, incomplete ratio rather than silently
normalizing it into a supposedly exact 384 profile.

Sources:

- `Samsuik/CannonLibrary/examples/.../OSRBClippingExample.java`
- `Samsuik/CannonLibrary/examples/.../CannonRatioExample.java`
- `Samsuik/CannonLibrary/examples/.../Simple384Stacker.java`
- <https://github.com/Samsuik/CannonLibrary>

### Fractional ratio timing is not automatically a real tick measurement

Public ratio simulators use decimal timing to preserve ordering between entities and
falling blocks. A token such as `8.3` must remain authored ordering evidence until an
exact schematic trace maps it to real server events.

CannonLab must never perform a blind conversion such as:

- decimal ratio value to redstone repeater delay;
- ratio tick to Minecraft game tick;
- cycle label such as `0.7s` to every internal phase;
- public simulator phase to private ExtremeCraft phase.

The ratio audit therefore preserves exact, fractional, ranged and open-ended tokens.

### Full redstone geometry and ratio simulation solve different problems

A ratio simulator can answer whether an authored entity schedule is physically
plausible against a wall. It cannot prove:

- the schematic produces those entities;
- observer and piston chains activate in that order;
- dispensers survive and refill;
- private server limits do not remove or reorder entities;
- the exact cannon clips, restacks or regens correctly.

CannonLab's schematic runtime remains the promotion authority. Ratio profiles become
constraints and expected cohorts, not replacements for a real firing trace.

### The missing center is an impulse graph

The canonical TNT mechanics archive exposes the useful source-level structure:

- explosion exposure determines entity push;
- push direction comes from explosion-to-entity position;
- movement applies gravity, drag, collision and ground response each tick;
- TNT fuse and entity order affect where later explosions occur.

CannonLab already records positions, velocities, fuses, explosions and source
dispensers. The next intelligence layer should connect those events into edges:

`source explosion -> affected entity -> velocity delta -> collision -> later explosion/impact`

Every edge should include:

- source entity and source dispenser cohort;
- pre- and post-event velocity;
- predicted and observed delta;
- exposure and distance if reproducible;
- collision cells and axis order;
- confidence and ambiguity;
- downstream target effect.

Source-level reference:

- <https://gist.github.com/tryashtar/2120988ad9afbc8f786df1f9a57a1a5b>

### Private-server parity is a vector, not one version number

Modern cannon behavior can change through independent patches. AsyncTNT publicly
documents four well-known fork-style switches:

1. zero horizontal TNT spawn kick;
2. fixed 80-tick fuse;
3. deterministic dispenser/redstone direction order;
4. stabilized east-west collision resolution.

It also warns that it is still under active development. These options are useful as
named hypotheses and test fixtures, not proof of what ExtremeCraft uses.

CannonLab must fingerprint each dimension separately and compare raw distributions.
The machine-readable contract lives at:

`profiles/parity/extremecraft-private-parity-required-v1.json`

Sources:

- <https://github.com/owengregson/AsyncTNT>
- `owengregson/AsyncTNT/core/src/main/resources/config.yml`

## Architecture ontology

The machine-readable ontology at
`profiles/archetypes/advanced-cannon-ontology-v1.json` covers:

- power, compression, reverse, hybrid, hammer, stopper, scatter, guider/barrel;
- 384 stackers;
- OSRB and one-shot families;
- nuke variants;
- slab bust and drop bust;
- left/right shooting and splitter fusion;
- double tap;
- anti-patch and webbust;
- anti-gravity;
- cubic;
- midair;
- worms/snakes;
- probes;
- adjustable cannons.

These are search and classification terms. None become confirmed runtime roles from
shape alone.

Community guides and current server rule pages are useful for discovering vocabulary,
defense types and legality boundaries. They are not sufficient for exact timings or
private-server mechanics.

Reference vocabulary:

- MCLabs cannoning guide: <https://labs-mc.com/wiki/Snowman%27s_In-depth_guide_for_cannoning_in_1.12.2>
- Minecraft TNT cannon tutorial: <https://minecraft.wiki/w/Tutorial:TNT_cannons>
- Mineage Factions rules: <https://store.mineage.net/rules-factions>
- ExtremeCraft rules and cannoning pages: <https://www.extremecraft.net/rules/>

## Required implementation sequence

### P0: Authored ratio intelligence

Implemented by this change:

- ratio profile schema;
- conservative parser;
- exact/range/open timing preservation;
- role tags;
- base-stack accounting;
- overlap cohorts;
- profile comparison;
- fail-closed validation;
- public 0.7 OSRB and 1.2 derived 384 profiles.

### P1: Explosion-to-entity impulse graph

Add a runtime analyzer that:

1. indexes every TNT and falling-block state by UUID and tick;
2. joins each explosion to candidate affected entities;
3. computes observed velocity deltas;
4. recreates expected push under the selected physics model;
5. records collision and fluid interactions;
6. links the entity to its final explosion or block conversion;
7. emits the first divergent edge between reference and candidate.

Acceptance must include synthetic exact-answer fixtures and real CannonLab traces.

### P2: Parity fingerprint matrix

Build minimal paired scenarios for every dimension in the parity profile:

- vanilla versus zero spawn kick;
- random versus fixed fuse;
- normal versus deterministic redstone order;
- mirrored collision resolution;
- dry versus water motion;
- increasing synchronized explosion cohorts;
- chunk and region boundary travel;
- piston/observer chains under load;
- OSRB clip and restack wet/dry;
- durable and regen state machines.

Store distributions, not only pass/fail booleans.

### P3: Corpus-backed role promotion

For each private or public reference cannon, preserve:

- cryptographic file hash;
- source/version;
- exact input controls;
- paste point and WE offset;
- authored ratio when known;
- static module map;
- causal trace;
- impulse graph;
- target manifest;
- successful and failed shots;
- live-server evidence label.

A role is promoted only after multiple references show the same causal behavior.

### P4: Constraint-driven repair search

The repair engine should mutate only declared controls:

- repeater/comparator delay;
- cohort amount;
- module translation inside a bounded envelope;
- barrel/guider cell;
- hammer/restack offset;
- declared attachment enablement.

Candidate generation must be driven by the first divergent impulse edge. Random broad
geometry generation remains blocked.

### P5: Live ExtremeCraft learning loop

The smallest safe live test produces the highest-value measurement:

1. select one unknown parity dimension;
2. create a minimal non-destructive fixture;
3. publish exact paste point and workflow;
4. record raw output and date;
5. compare against local hypotheses;
6. update only that dimension;
7. then test the exact reference cannon;
8. then test one bounded repair.

Never upload credentials, automate gameplay, or label a design EC-ready from a
Cannoning-world result alone when Factions parity remains disputed.

## Immediate reference baseline

The first serious baseline should remain:

1. exact 0.7 public 384 OSRB ratio profile;
2. exact private Nuke/Leftshot schematic intake;
3. one clean local shot with complete source accounting;
4. impulse graph;
5. EC160 paste-point proof;
6. exact wet/dry OSRB clip canary;
7. only then a bounded EC canary schematic.

This path teaches CannonLab why a cannon works. Building another ungrounded flat
candidate would only generate prettier failure.
