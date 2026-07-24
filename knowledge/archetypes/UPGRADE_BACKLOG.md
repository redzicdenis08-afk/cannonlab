# CannonLab archetype upgrade backlog

## Honest current verdict

CannonLab can decode, audit, trace and plan a Rev-Worm experiment. It cannot yet honestly claim automatic working-worm generation.

The current capability audit finds three promotion blockers:

1. no explicit pre-fire mode-action system;
2. no output-corridor and direction-repeatability acceptance contract;
3. Cannon Forge globally assumes serious cannons require falling payload.

The tested Rev-Worm REV/NUKE mode produced zero falling blocks, so a global falling-payload requirement is wrong for this family.

## P0: exact pre-fire mode actions

Observer-heavy, mode-gated cannons need controls set after empty settling and before TNT fill.

Required scenario shape:

```yaml
cannon:
  pre-fire-actions:
    - phase: after-empty-settle
      type: set-lever
      position: {x: 5, y: 12, z: 13}
      state: on
      verify: true
      settle-ticks: 4
```

Initial action types should stay narrow: `set-lever`, `press-button`, `set-trapdoor`, `set-fence-gate`, and `verify-block-state`. Do not begin with arbitrary commands or redstone-block replacement.

Required order:

1. paste with dispensers empty;
2. settle while empty;
3. apply each native control action;
4. verify the resulting state;
5. wait its settle window;
6. fill dispensers;
7. wait fill-to-fire delay;
8. press the real input.

Required causal events: `CONTROL_STATE_APPLIED`, `CONTROL_STATE_VERIFIED`, and `CONTROL_STATE_FAILED`, including relative position, requested state, observed state, phase and sequence.

A field-candidate scenario must fail before fill if a control is missing, has the wrong type, cannot be applied natively, or does not reach the requested state.

## P0: output-corridor acceptance

Explosion count and generic forward distance cannot prove a worm or leftshoot. These families require a stable entity-output vector and safe separation from the cannon.

```yaml
acceptance:
  output-contract:
    enabled: true
    entity-types: [tnt]
    corridor-min: {x: -4, y: -3, z: -4}
    corridor-max: {x: 4, y: 8, z: 4}
    discovery-mode: dominant-direction
    expected-direction: any
    min-entities-exiting-corridor: 1
    min-displacement: 8.0
    max-return-distance-toward-cannon: 1.5
    max-angular-spread-degrees: 12.0
    min-consistent-shots: 5
    max-direction-outliers: 0
```

`expected-direction: any` is diagnostic only. Promotion requires a locked direction established by a prior clean family.

Per entity, record first corridor exit, displacement, dominant axis/sign, return toward cannon, angle against the dominant vector, fuse continuity and explosion point. Per shot, record exit count, dominant vector, median displacement, spread, return violations, target contact and self-damage. Across shots, record direction mode, vector variance, displacement variance, outliers and clean-shot streak.

A worm cannot become `local-candidate` unless exact mode controls pass, the registered cohort fingerprint passes, at least five shots leave through one locked direction, none return dangerously toward the cannon, and cannon integrity passes.

## P0: archetype-specific payload contracts

Add a payload enum:

```text
ANY
TNT_ONLY
FALLING_REQUIRED
HYBRID_REQUIRED
```

- `ANY`: diagnostic plumbing only.
- `TNT_ONLY`: TNT trajectory/output required; falling blocks optional.
- `FALLING_REQUIRED`: falling payload and target overlap required.
- `HYBRID_REQUIRED`: falling payload plus source-attributed embedded TNT impact required.

Defaults:

- Rev-Worm tested REV/NUKE mode: `TNT_ONLY`.
- Asser OSRB/Nuke/Leftshot: `HYBRID_REQUIRED` until a specific mode proves otherwise.
- Basic calibration: `ANY` or explicitly `TNT_ONLY`, calibration lifecycle only.
- Reaper partial module: module-output contract, not full-cannon payload contract.

Forge must select this from the archetype registry rather than hardcode `require_payload=True`.

## P1: archetype-aware Forge integration

After the P0 runtime contracts exist, Forge should accept:

```powershell
python scripts/cannon-forge.py stage candidate.schem `
  --archetype rev-worm-383-v4 `
  --reference private-reference.litematic `
  --fire-input 4,11,13
```

Forge must verify the reference hash, select payload/output contracts, include mode actions, run cohort verification, enforce the archetype evidence ceiling, and store the archetype-registry hash in every job manifest. `--archetype` must never become a decorative filename label.

## P1: one-variable mutation families

Each mutation packet must contain parent hash, reference hash, one causal variable, touched module IDs, expected unaffected cohort fingerprint, expected trajectory effect, preservation report, runtime comparison and rollback candidate.

Initial Rev-Worm sweeps:

1. mode-state combinations;
2. native fire-input equivalence;
3. output-direction discovery;
4. one evidence-selected timing site at a time;
5. one symmetric bank-pair redistribution at a time for EC160.

Never sweep unknown repeaters across the whole machine.

## P1: EC160 redistribution planner

Plan around symmetric bank pairs and cohort interfaces, not individual dispensers. Every move must report source/destination chunk columns, before/after counts, facing preservation, panel shape, corridor width, wire/repeater delta, observer order delta, piston/slime interface delta, predicted cohort membership and modules touched.

“Move 144 dispensers into another chunk” is not a sufficient redesign plan.

## Definition of real Rev-Worm support

CannonLab can claim Rev-Worm construction support only after it has:

- exact private-reference intake and hashing;
- correct negative-size Litematica decoding;
- explicit mode actions and evidence;
- exact 537/336/144 cohort verification;
- TNT-only payload mode;
- output-corridor discovery and locked-direction acceptance;
- five-shot repeatability;
- self-damage and survival gates;
- symmetric EC160 redistribution planning;
- local public-Sakura output proof;
- reduced live ExtremeCraft canary before EC-ready promotion.

Until then, the truthful wording is: **CannonLab can deeply analyze and plan a Rev-Worm reconstruction, but cannot automatically produce a proven working worm yet.**
