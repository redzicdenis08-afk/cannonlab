# CannonLab general-intelligence implementation queue

The catalog and planner can now describe most studied modern cannon families. `scripts/cannon-operator.py` now binds the general plan, architecture policy, and Cannon Forge staging into one fail-closed operator manifest. The shared runtime and construction layer still need the capabilities below before broad automatic repair can be promoted.

## P0: explicit pre-fire control states

Scenario requirements:

- ordered lever/button actions relative to cannon origin
- requested final state for each control
- settle delay after each action
- state verification before dispenser fill
- state snapshot written to the shot evidence pack
- native final button press kept separate from mode preparation

Acceptance:

- Rev-Worm can apply master plus both REV/NUKE levers before fill
- Asser candidates can record exact Nuke, OSRB, SlabBust, Bypass and Double Tap combinations
- wrong or missing state fails before the cannon is loaded

## P0: archetype-specific payload mode

Supported values:

- `falling-block-required`
- `tnt-only`
- `archetype-selectable`

Acceptance:

- Rev-Worm TNT-only diagnostics do not fail because falling blocks are absent
- hybrid, overstack and OSRB scenarios still require their falling payload
- a candidate cannot silently switch payload mode between shots
- payload mode appears in manifests, scenario integrity and assertion reports

## P0: output corridor and repeatability

Scenario requirements:

- one or more 3D corridor boxes or waypoint planes
- required entity types
- entry and exit direction
- minimum displacement along the intended axis
- maximum lateral/vertical error
- maximum angular spread
- minimum percentage of repeated shots using the same dominant direction
- minimum safe return distance from cannon bounds

Acceptance:

- straight, leftshoot, reverse, worm, midair and counter outputs can use different contracts
- random external blasts cannot pass
- three-cohort activation without corridor travel cannot pass as a worm
- a leftshoot must prove the correct side and bounded angle

## Implemented: bounded variant search

`scripts/cannon-variant-search.py` now enumerates the full declared Cartesian search without random sampling. It applies `cannon-mutator.py` to every candidate, preserves the parent hash, records each mutation plan, and ranks static preservation/placement pressure separately from runtime performance.

The search may change only declared variables such as:

- one repeater delay
- one cohort pulse offset
- one bank split location
- one stopper or splitter coordinate
- one guider coordinate
- one controlled payload ratio

It must never randomly flatten or regenerate the machine.

Each generated candidate now receives:

- parent hash
- mutation description
- preservation report
- chunk audit
- a runtime-scorecard slot using predeclared metrics
- deterministic weighted ranking after all required metrics exist

Current hard rejection includes:

- changed modules exceed the budget
- reference core preservation fails
- diagnostic assists are used for promotion
- target benefit improves only by increasing self-damage
- output becomes less repeatable

`scripts/cannon-variant-scorecard.py` now extracts conservative metrics from supplied CannonLab run summaries. Benefit metrics use the worst repeated shot, self-damage uses the worst shot, dispenser survival uses the minimum ratio, and missing telemetry remains missing so ranking fails closed. A small result-map file still explicitly binds each variant to its run summaries, preventing accidental cross-candidate evidence mixing.


## Implemented: MCP exposure

The main `mcp-server/server.py` now exposes bounded wrappers for:

- general catalog/runtime/operator audit
- family and specialization planning
- symptom-driven diagnostic ranking
- operator preparation
- operator dry-run and explicit local execution
- bounded mutation
- deterministic variant generation and ranking
- private corpus regression

MCP tools must call the same scripts used by CI. Do not duplicate a second looser implementation inside the server.

## Implemented: real schematic mutation

`scripts/cannon-mutator.py` writes a new Sponge v2 schematic and supports only declared transformations:

- repeater-delay change at an exact coordinate
- exact block-state replacement without deleting tile entities
- translated bounded regions with collision checks and preserved block-entity NBT

Every mutation produces a new file, parent hash, block-level diff, preservation report, EC160 audit, and deterministic rollback record. More specialized semantic operations such as symmetric bank splitting should be added only after the mapped region and interface contract are proven.


## Integration order

1. Merge active runtime and parity lanes without overwriting their evidence work.
2. Add pre-fire control states.
3. Add payload mode.
4. Add output corridor assertions.
5. Re-run the full private reference corpus through `private-corpus-regression.py`.
6. Run local campaigns for the generated Nuke timing sweep and extract its scorecard.
7. Promote one reduced family at a time, beginning with calibration and a clean shared core.
