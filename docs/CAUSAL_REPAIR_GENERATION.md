# CannonLab Causal Bounded Repair Generation

Verified: 2026-07-24

## Purpose

CannonLab can identify the first entity or impulse divergence and rank completed repair runs, but those tools still need a disciplined candidate source. `generate-causal-repair-family.py` turns one first-divergence report into a small deterministic family of predeclared edits.

The loop is:

`reference hash -> first divergence -> matching reviewed controls -> bounded combinations -> deterministic .schem -> EC160 scan -> preservation gate -> runtime tournament`

The generator never performs random geometry generation, broad redstone rewrites or automatic subsystem-role guesses.

## Repair policy

A policy is tied to one exact reference SHA-256. Every control declares:

- stable control ID;
- supported mutation kind;
- exact owning module ID;
- exact schematic-relative positions;
- finite allowed values or states;
- exact divergence kinds that may activate it;
- causal justification explaining why the control belongs in the search.

Current safe mutation kinds:

### `repeater-delay`

Changes the `delay` property of one exact repeater or a declared repeater cohort. Values must be integers from 1 through 4. Facing, locking, powered state and every other property remain unchanged.

### `block-state-choice`

Chooses among exact reviewed block states at one position, or a cohort only when `apply_same_state_to_cohort=true`. Block-type changes fail unless `allow_type_change=true`, and the preservation gate still judges the resulting edit.

## Divergence routing

The generator reads `first_divergence.kind` from either the top level or `comparison.first_divergence`. A control runs only when its `divergence_kinds` contains that exact kind or the explicit wildcard `*`.

This routing is a search permission, not proof that the control will repair the problem. A policy should be built from source-accounted module traces, impulse edges and reviewed cannon knowledge. When no declared control matches, generation fails instead of inventing a fix.

## Ownership and search bounds

Each control position must belong to its declared current module. Shared positions fail unless the policy explicitly sets `allow_shared_position=true`.

Search limits are hard bounded:

- `max_controls_per_candidate`: 1 to 3;
- `max_candidates`: 1 to 256;
- finite values for every control;
- deterministic control and variant order;
- conflicting edits to the same coordinate are rejected;
- duplicate output geometry is deduplicated by SHA-256.

The default useful workflow is one control per candidate. Two-control combinations are appropriate only when the causal trace shows a coupled timing cohort.

## Candidate gates

Every generated candidate must:

1. round-trip exact occupied geometry and block-entity positions;
2. retain the source DataVersion and dimensions;
3. use only empty dispenser/dropper block entities that the deterministic writer can preserve;
4. have at least one safe alignment under the configured dispenser-per-chunk limit;
5. pass `cannon-preservation-check.py` with allowed types and modules derived from its exact declared controls.

Failed candidates are removed from the accepted family and reported with their EC160 or preservation failure.

## Usage

```powershell
python scripts/generate-causal-repair-family.py `
  private/reference.schem `
  lab-artifacts/reference-vs-candidate/impulse-comparison.json `
  profiles/repairs/reference-repair-policy.json `
  --output-directory lab-artifacts/repair-family `
  --json-out lab-artifacts/repair-family.json
```

The output directory contains:

- one `.schem` per accepted candidate;
- one `.candidate.json` manifest per candidate;
- `repair-family.json` with the complete family and rejection evidence.

## Runtime promotion

Generated candidates are `STATIC_REPAIR_CANDIDATE_ONLY`. The generator deliberately does not declare a winner.

For each candidate:

1. run the exact same scenario, target, range, initialization and shot count as the reference;
2. capture `events.csv`, `causal-events.csv`, integrity snapshots and run summary;
3. build module and impulse comparisons;
4. place candidate result directories under one family directory;
5. run `analyze-repair-family.py` to rank performance and protected-module drift;
6. promote only a runtime-tested Pareto candidate;
7. complete a controlled live ExtremeCraft canary before any EC-ready claim.

This closes the intended loop from the first measured physics divergence to bounded evidence-producing repair attempts, without turning an LLM guess into a giant uncontrolled rebuild.
