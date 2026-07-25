# CannonLab cannon grammar and Sakura parity contract

Verified: 2026-07-25

## Why the old scratch-build approach failed

The rejected twenty-block one-stacker search proved range without proving cannon architecture. It eventually launched payload TNT beyond the requested corridor, but the payload lane diverged, sand never fused with the payload at the target, and the muzzle lost dispensers. Adding more charge or changing one shared delay could not repair those independent failures.

CannonLab now treats cannoning as a staged causal system instead of a block-count problem. A candidate is not a cannon merely because it contains dispensers, TNT, water and sand. It must prove each required module and the interfaces between those modules.

## The three-version model

Every run must record three independent identities:

1. **Schematic serialization version.** ExtremeCraft accepts Sponge v2 schematics written with DataVersion 3465. This controls block-state encoding and compatibility of the pasted file.
2. **Server runtime version.** The pinned public laboratory runtime is Sakura 26.1.2 on Minecraft 26.1.2, built from exact source commit `63f35d74e0fbe6bcd76c58494c01c1632c83010d`.
3. **Cannon mechanics target.** Sakura can emulate a separately selected Minecraft mechanics version and server family. Its public default is `latest+paper`, but the private ExtremeCraft value is unknown.

DataVersion 3465 must never be promoted into a claim that the server uses Minecraft 1.20.1 physics.

## Exact pinned public Sakura defaults

The contract in `profiles/parity/sakura-26.1.2-cannon-contract.json` records the source-backed public defaults that materially affect cannon behavior. Important examples include:

- TNT spread defaults to `ALL`.
- TNT can flow in water by default.
- falling-block parity is disabled by default.
- cannon entity merging is `LENIENT`.
- TNT and sand are affected by bubble columns.
- moving entities use Sakura's cannon collision path, including an axis scan for sufficiently large movement.
- chunk loading for cannon entities is disabled by default.
- obsidian is a four-hit durable material with a one-minute expiration window.
- waterlogged blocks are not destroyed by explosions by default.
- dispenser item choice is randomized by default.
- sand inside moving pistons may despawn by default.

These are public defaults, not verified private ExtremeCraft settings. CannonLab therefore requires behavioral probes rather than assuming the private server kept them unchanged.

## Required parity probes

A server profile is incomplete until it measures at least these behaviors:

- mechanics target and server family;
- TNT initial spread distribution;
- TNT motion in flowing water;
- falling-block height parity;
- high-speed collision and axis ordering;
- entity-link or merge behavior for coincident cannon entities;
- bubble-column effects on TNT and sand;
- unloaded-chunk flight behavior;
- obsidian durability and hit-expiration timing;
- waterlogged-block explosion behavior;
- whether fluids break redstone;
- dispenser item-selection behavior.

The private server does not expose Sakura's normal `/mechanic` report, so CannonLab must infer these fields with controlled experiments and label each result with its evidence source.

## Evidence-gated module grammar

The machine-readable grammar is in `profiles/grammar/modern-factions-cannon-grammar-v1.json`.

A modern factions cannon may use these modules:

- **charge force:** protected explosion volume and a measured coupling line into the payload;
- **payload:** a distinct TNT cohort with a target-plane crossing, lane error and fuse error;
- **guider / realignment:** repeatable control of lateral and vertical trajectory;
- **slab bust / drop bust:** a separately attributed target-preparation stage;
- **sand release:** a proven held-to-falling transition at the commanded tick;
- **hammer:** a measured explosion-to-sand vertical impulse;
- **sand compression:** measured reduction in cohort spread and a resulting stack;
- **hybrid fusion:** payload explosion while sand occupies the interaction volume;
- **scatter:** a declared target-cluster pattern after lineup is already proven;
- **one-shot cycle:** ordered composition of preparation, stack, hammer and hybrid stages;
- **double tap:** two distinct target interactions, not merely two button pulses;
- **reverse and left/right shot:** measured direction changes with server restrictions recorded;
- **OSRB, nuke, bypass and pseudo:** source-defined variants whose names do not prove behavior.

The order is not universal geometry. It is a proof graph. A design cannot skip a dependency by adding more TNT.

## Causal failure classifier

`scripts/classify-cannon-run.py` consumes a CannonLab `run-summary.json` and the corresponding per-shot `events.csv` traces. It separates charge and payload cohorts and reports the first measurable failure category, including:

- payload missing, short range, lane divergence or incorrect fuse;
- sand not released, short range or lane divergence;
- absent payload-sand fusion;
- target untouched or durability never hit;
- cannon self-damage and dispenser loss.

This prevents the catch-all diagnosis “ticks are off.” For example, a payload that crosses the target X coordinate ten blocks off the intended Z lane is a guider/realignment failure. Fuse tuning is downstream and must not be attempted first.

## Promotion ladder

1. **STATIC:** format, bounds, EC160 alignment, declared controls and interfaces.
2. **LOCAL_CAUSAL:** every required module has trace-backed causal evidence in the pinned public runtime.
3. **LOCAL_ENDURANCE:** repeated one-paste firing survives and maintains bounded variance.
4. **FIELD_CANARY:** a controlled low-risk ExtremeCraft test reproduces the expected stages.
5. **FIELD_READY:** repeated field evidence covers the intended defense class and server rules.

No filename, screenshot, explosion count, CI check or public-Sakura pass can skip this ladder.

## Research-source policy

`research/sources/cannon-community-sources-v1.json` separates source code, official documentation, community rules and community vocabulary. Source code is authoritative for the pinned public runtime. Community material is valuable for module names, architecture patterns and server-rule examples, but it does not prove private ExtremeCraft mechanics. Third-party schematic files remain fetch-only unless their license permits redistribution.

## Immediate engineering direction

Future synthesis should start from a source-backed architecture specimen or a promoted module, not another scratch monolith. CannonLab should first reproduce a clean charge-to-payload coupling, then prove a guider, held sand release, hammer and hybrid overlap as independent experiments. Only after those gates pass should it assemble a one-button wall course.
