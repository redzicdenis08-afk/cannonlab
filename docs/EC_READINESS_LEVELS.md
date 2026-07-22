# ExtremeCraft readiness levels

CannonLab uses evidence levels so a successful explosion is never confused with a raid-ready cannon.

## 0. Intake pass

Required evidence:

- source file decodes without truncation or palette errors
- exact block geometry is preserved through any Litematica to Sponge v2 conversion
- every dispenser and block entity is counted
- the intended paste alignment is below the configured dispenser cap
- the separate block-entity pressure is reported without inventing an ExtremeCraft limit
- redstone support and obvious structural failures pass static audit

This proves the file can enter the laboratory. It does not prove that it fires.

## 1. Circuit pass

Required evidence:

- the real button, lever, or configured fire input activates the cannon
- causal telemetry records redstone, dispenser, piston, TNT/falling-block creation and explosions
- component coordinates are relative to the actual schematic paste origin
- expected firing cohorts repeat across at least ten shots
- no unexplained preparation or telemetry errors occur

This proves the circuit executes on the selected local runtime. It does not prove useful range or defense penetration.

## 2. Local physics pass

Required evidence:

- Paper and pinned public Sakura tests agree within explicit tolerances where parity matters
- TNT fuse continuity, launch timing, travel and explosion position pass
- falling-block payload behavior is recorded when the design uses sand or concrete powder
- target-impact convergence is measured, not eyeballed
- cannon self-damage is within the candidate's declared limit
- repeated shots reset cleanly without leaked entities or reused state

This proves the design is mechanically coherent under public local physics.

## 3. Local defense pass

Required evidence:

- the candidate is tested against the relevant dry, watered, filter, slab-filter, hotdog, pillar and regen stages
- mixed courses use `target.stages`, not separate toy fixtures presented as one raid
- each stage records its own geometry and regeneration schedule in `target-course.json`
- the intended range, target height and wall-course depth are represented
- per-shot penetration, target peak damage, deepest global layer, regeneration and self-damage gates pass
- at least one serious endurance run uses the candidate cannon rather than the four-dispenser plumbing fixture

The included `ec-15chunk-gauntlet-template.yml` is a configurable stress template. It is not an assertion that ExtremeCraft uses that exact wall order or regeneration timing.

## 4. EC calibration pass

Required evidence:

- every black-box probe in `scripts/audit-ec-calibration.py` has a valid live evidence file
- evidence was captured on ExtremeCraft Cannoning with confirmed chunk-corner paste origin
- fuse, dispenser spread, water flow, falling-block behavior, high-speed survival, durable blocks/regen, redstone timing and paste limits are all covered
- the evidence auditor returns `ec_calibrated: true`
- local fingerprint tolerances are updated from those measurements, one mechanic at a time

Public Sakura similarity is strong evidence but cannot replace this level.

## 5. EC canary pass

Required evidence:

- a reduced-risk version of the actual candidate is pasted at the intended chunk alignment
- `/p tntfill` and the normal field firing method are used
- timing, flight, payload, self-survival and target contact match the local prediction
- repeated canary shots are consistent
- no dispenser or FAWE block-entity limit is exceeded

## 6. EC ready

A candidate may be labeled `ec-ready` only when the full intended configuration passes live at the intended:

- dispenser distribution and chunk alignment
- cannon height and target Y
- payload size and fire rate
- range and wall-course depth
- defense type and regeneration timing
- repeated-shot count

Every exported candidate should ship with:

- exact schematic SHA-256
- static audit JSON
- structural map JSON
- scenario YAML
- `target-course.json`
- causal quality report
- Paper and Sakura fingerprints
- EC evidence references
- explicit readiness level

Anything below level 6 must keep its lower label. Green CI is not permission to rename a plumbing probe into a raid cannon.
