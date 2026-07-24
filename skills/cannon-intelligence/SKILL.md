# Cannon Intelligence Skill

Use this workflow for modern factions cannons, Sponge schematics, Litematics, Sakura/Paper runtime traces, and ExtremeCraft calibration.

## Non-negotiable truth levels

1. `geometry-confirmed`: directly decoded from the file.
2. `runtime-confirmed`: observed in repeatable local telemetry.
3. `sakura-local-pass`: passed the intended scenario on pinned public Sakura.
4. `ec-canary-pass`: a small live ExtremeCraft test matched expected timing and flight.
5. `ec-ready`: full payload, range, target, height, paste and chunk alignment passed live.

Never collapse these levels.

## Fast default workflow

1. Use `fast_cannon_intake` once. Pass the candidate plus the strongest real reference cannons available.
2. Read `ec160_architecture`. If any legal residue exists, document exact placement before attempting a bank redesign.
3. For a format-only or quick upload task, use `prepare_reference_cannon`; do not redesign the cannon.
4. If `modern_raid_morphology` fails, reject the candidate immediately. Do not spend runtime hours proving a flat toy fires.
5. Start edits from a decoded proven reference. Preserve its exact block-state geometry and causal sequence until one measured variable is intentionally changed.
6. Run real redstone only after static structure, chunk alignment, block entities, control input, and morphology pass.
7. Test the narrow changed module first, then the whole cannon.
8. Return the `.schem` and the smallest honest evidence summary. Do not narrate every internal step.

## Required deep workflow

1. Run `inspect_cannon` or `fast_cannon_intake`.
2. Reject malformed formats, unsupported redstone, illegal chunk distributions, unexplained block-entity pressure, or fake-modern morphology.
3. Read the static functional map. Describe shapes and connectivity only.
4. Run the cannon through real redstone, not direct dispenser activation, when judging its actual firing circuit.
5. Run `explain_shot` on every shot.
6. Compare at least ten repeatable shots before calling timing stable.
7. Run `compare_reference_physics` on representative TNT and falling-block entities. Separate normal collision from fuse, drag, gravity, water-push or fork drift.
8. Correlate dispenser cohorts, entity-spawn cohorts, piston cohorts and explosion ticks.
9. Assign cannon roles only when the causal trace supports them.
10. Treat community ratios and names as hypotheses unless reproduced on the exact target profile.
11. Test one variable at a time.
12. Preserve failed shots and their evidence.

## Anti-pancake gate

For `intent=modern-raid`, the candidate must show all of the following before expensive runtime work:

- at least 16 blocks of functional vertical depth
- at least 8 dispenser Y layers
- observer logic
- piston logic
- a multi-delay repeater network
- water protection
- a real button or lever
- at least 8 functional block types
- at least one legal X/Z alignment under the configured chunk limit

These thresholds are structural rejection gates, not proof that a cannon works. Use `intent=calibration` for small field-calibration cannons.

## Language discipline

Allowed:

- “A 21x41 south-facing dispenser panel is geometry-confirmed.”
- “This 384-TNT cohort fires 18 ticks before the falling-block cohort.”
- “The bank is a charge candidate because its TNT cohort precedes acceleration.”
- “This candidate fails modern morphology because it has one dispenser layer and no observers.”

Not allowed:

- “The filename says OSRB, therefore this is the OSRB bank.”
- “It looks like a hammer.”
- “It should work on ExtremeCraft.”
- “Local Sakura proves EC.”
- “A flat dispenser tray is a modern cannon because it fires TNT.”

## ExtremeCraft profile

- Current user-reported dispenser limit: 160 per X/Z chunk column.
- Keep 128 as an optional conservative regression threshold only.
- The FAWE block-entity/NBT paste limit is separate and currently unverified.
- Empty dispenser inventories are intentional because `/p tntfill` fills them.
- Sponge v2, DataVersion 3465 is the field-verified paste target.
- Chunk alignment must be recorded for every paste.
- Scan all 256 residues before changing geometry. A placement-fragile legal cannon is not the same problem as a 0/256 cannon.
- When 0/256, segment paired opposing banks symmetrically and re-prove transport timing. Do not move only one compression panel.
- Paste empty, settle, fill, then use the real control input.
- `/schemdb` and `/mechanic` are not valid recommendations for this project.

## Design rule

Do not generate a “modern cannon” by arranging flat dispenser rows from abstract theory. Start from runtime-confirmed modules or a proven imported design, preserve its causal sequence, then solve EC chunk and paste constraints around it.

When no proven module exists, the honest output is a diagnostic prototype, not a raid cannon.

## Completion evidence

A cannon task is not complete until the repository contains:

- source schematic and SHA-256
- static audit JSON
- geometry profile JSON
- functional map JSON
- scenario YAML
- causal trace CSV
- causal explanation JSON or Markdown
- EC160 architecture/advisor report
- reference-physics comparison for representative TNT and falling-block trajectories
- repeatability results
- Sakura result
- EC canary notes where applicable
