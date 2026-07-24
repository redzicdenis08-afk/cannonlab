---
name: cannon-forge
description: Build or repair modern factions cannons through reference-first reconstruction, deterministic wall campaigns, runtime telemetry and fail-closed promotion. Use whenever producing or modifying a .schem or .litematic for CannonLab or ExtremeCraft.
---

# Cannon Forge

This skill turns CannonLab from a collection of analysis tools into one mandatory build loop. Never hand a user a modern raid schematic before this loop has produced current evidence.

## Source order

1. Exact candidate and reference schematics.
2. `knowledge/source-registry.json` and its linked local sources.
3. Exact local causal traces and run summaries.
4. Pinned public Sakura results.
5. Recorded ExtremeCraft canaries.
6. Memory and historical community material only as background.

Add every useful guide, video transcript, forum post, field report or decoded cannon to the source registry with an evidence level and an explicit “never promote directly” boundary.

## Mandatory forge loop

1. Intake the candidate and strongest references with `fast_cannon_intake`.
2. Reject malformed files, illegal chunk distributions, fake-modern morphology and missing real controls.
3. Map modules and recover exact translated cores. Never infer roles from filenames.
4. Choose one runtime-confirmed reference or module as the edit base.
5. Declare one changed variable and a strict preservation budget.
6. Run `check_cannon_preservation` before runtime work.
7. Resolve the base plus specializations into an explicit payload contract. Unknown or conflicting payload interfaces fail closed.
8. Declare every required lever, repeater, comparator, piston, trapdoor, or dispenser mode state as a verified control state.
9. Stage a deterministic campaign with `scripts/cannon-forge.py stage`.
10. Run the one-shot `smoke` tier first. Stop immediately on payload, direction, target-contact, survival, control-state, or integrity failure.
11. Run the cumulative `qualify` tier only after smoke passes.
12. Run the `full` tier only for candidates that passed qualification. Resume exact passed stages instead of rerunning them.
13. Explain every shot, analyze breach evidence, enforce output-corridor repeatability, and compare untouched module traces.
14. Promote only the evidence level actually earned.

## Fast iteration funnel

The default operator run executes only the one-shot smoke gate. The generated campaign is deliberately tiered:

- `smoke`: one native shot for cheap rejection
- `qualify`: smoke plus short cumulative baseline/payload qualification
- `full`: every archetype-specific gauntlet and endurance contract

Use `--plan-only` before expensive work and use a wall-clock budget when exploring. Static intake runs independent tools concurrently and reuses content-addressed results. Variant search runs unique bounded mutations concurrently, deduplicates identical rendered changes, and caches exact mutation outcomes.

Runtime resume is valid only when candidate and scenario hashes, assertion arguments, analysis tools, plugin/server JARs, lab home, and `CANNONLAB_*` environment values match. A cache hit saves computation; it never raises the evidence level. Only a completed full campaign can earn the full local candidate verdict.

## Required stress campaign

Falling-block and hybrid candidates must pass all of these with native redstone or their real button:

- dry baseline
- watered payload overlap
- fast watered regeneration race
- mixed filter/hotdog/pillar course
- repeated watered endurance with survival and self-damage gates

TNT-only worm, nuke, force, or directional candidates use the archetype-specific dry campaign instead:

- dry baseline
- five-shot measured direction repeatability
- dry multilayer progression
- dry filter/pillar route gauntlet
- repeated dry endurance with survival and self-damage gates

TNT-only success must never be promoted into watered-defense capability. Every repeated scenario must pass the measured output corridor, dominant direction, angular spread, lateral center, and forward-distance consistency contract.

The campaign must paste empty, settle, fill, then fire. Direct dispenser triggering and forced velocity may diagnose a problem but cannot promote a field candidate.

## Design boundary

Do not freehand a “modern cannon” from dispenser rows, memory or abstract ratios. Rebuild around exact decoded reference geometry, preserve causal sequence, and make bounded variants. When no proven core exists, label the output `diagnostic prototype`.

## Completion evidence

A finished forge job contains:

- source and reference hashes
- static intake JSON
- module and preservation evidence
- generated scenario pack
- resolved archetype payload contract
- exact pre-fire control-state contract
- scenario-integrity reports
- per-scenario run artifacts
- assertion reports
- output-corridor reports for repeated scenarios
- causal traces and shot explanations
- local Paper/Sakura verdict
- live EC notes when claiming EC readiness

No evidence pack means no “working,” “fixed,” “one-shot,” or “EC-ready” claim.