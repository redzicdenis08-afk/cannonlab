# Cannon Intelligence Skill

Use this workflow for modern factions cannons, Sponge schematics, Litematics, Sakura/Paper runtime traces, and ExtremeCraft calibration.

## Non-negotiable truth levels

1. `geometry-confirmed`: directly decoded from the file.
2. `runtime-confirmed`: observed in repeatable local telemetry.
3. `sakura-local-pass`: passed the intended scenario on pinned public Sakura.
4. `ec-canary-pass`: a small live ExtremeCraft test matched expected timing and flight.
5. `ec-ready`: full payload, range, target, height, paste and chunk alignment passed live.

Never collapse these levels.

## Required workflow

1. Run `inspect_cannon`.
2. Reject malformed formats, unsupported redstone, illegal chunk distributions, or unexplained block-entity pressure.
3. Read the static functional map. Describe shapes and connectivity only.
4. Run the cannon through real redstone, not direct dispenser activation, when judging its actual firing circuit.
5. Run `explain_shot` on every shot.
6. Compare at least ten repeatable shots before calling timing stable.
7. Correlate dispenser cohorts, entity-spawn cohorts, piston cohorts and explosion ticks.
8. Assign cannon roles only when the causal trace supports them.
9. Test one variable at a time.
10. Preserve failed shots and their evidence.

## Language discipline

Allowed:

- “A 21x41 south-facing dispenser panel is geometry-confirmed.”
- “This 384-TNT cohort fires 18 ticks before the falling-block cohort.”
- “The bank is a charge candidate because its TNT cohort precedes acceleration.”

Not allowed:

- “The filename says OSRB, therefore this is the OSRB bank.”
- “It looks like a hammer.”
- “It should work on ExtremeCraft.”
- “Local Sakura proves EC.”

## ExtremeCraft profile

- Current user-reported dispenser limit: 160 per X/Z chunk column.
- Keep 128 as an optional conservative regression threshold only.
- The FAWE block-entity/NBT paste limit is separate and currently unverified.
- Empty dispenser inventories are intentional because `/p tntfill` fills them.
- Sponge v2, DataVersion 3465 is the field-verified paste target.
- Chunk alignment must be recorded for every paste.
- `/schemdb` and `/mechanic` are not valid recommendations for this project.

## Design rule

Do not generate a “modern cannon” by arranging flat dispenser rows from abstract theory. Start from runtime-confirmed modules or a proven imported design, preserve its causal sequence, then solve EC chunk and paste constraints around it.

## Completion evidence

A cannon task is not complete until the repository contains:

- source schematic and SHA-256
- static audit JSON
- functional map JSON
- scenario YAML
- causal trace CSV
- causal explanation JSON/Markdown
- repeatability results
- Sakura result
- EC canary notes where applicable
