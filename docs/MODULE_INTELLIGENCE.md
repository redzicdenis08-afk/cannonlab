# CannonLab module intelligence

CannonLab treats a proven cannon as an evidence-bearing machine, not a pile of blocks to redraw from memory. The module-intelligence layer exists to preserve that machine while making bounded, reviewable changes.

## Static module map

`scripts/cannon-module-map.py` starts from decoded Sponge or Litematica geometry. It identifies same-facing dispenser banks with support-gap clustering, assigns nearby functional components to the nearest bank, and groups remaining functional islands with the same conservative support-gap rule.

The report includes:

- immutable source SHA-256
- bank-centered and unseeded modules
- exact component coordinates and canonical signatures
- controls, repeater delays, directional links, and type counts
- exact translated module families
- repeated x, y, and z functional slices
- shared-component ambiguities
- face-connected subcomponent counts and support-gap bridge risk
- module coupling candidates from shared ownership, face adjacency, and directional endpoints
- conservative static role candidates

Volatile saved properties such as redstone power are removed only from signatures. The original block states remain in the source and other audit outputs.

Static grouping does not prove runtime ownership. A nearby repeater can feed multiple banks, a shared redstone spine can cross inferred module bounds, and fluid or support cells can be spatially separated from the mechanism they serve.

## Exact cross-cannon comparison

`scripts/compare-cannon-modules.py` compares two module maps.

An exact match requires identical canonical block states at identical relative coordinates after translation. These matches are safe candidates for a shared geometric core. They are not automatically safe to transplant because their external inputs, neighboring blocks, timings, and server mechanics can still differ.

Near matches are ranked using:

- block-type multiset overlap
- dimension similarity
- dispenser-count similarity
- component-count similarity
- module kind
- dispenser facing

Near matches are diagnostic leads only. They cannot be used as preservation proof.

### Partial translated cores

`scripts/compare-cannon-cores.py` handles the case where a real shared lower machine or timing spine survives but extra banks and attachments cause the inferred whole-module boundaries to diverge.

It searches for intact local functional-neighborhood signatures, votes on integer translations, and then measures exact canonical-state overlap for functional and non-air cells. A shared-core candidate must clear all of these gates:

- enough exact functional cells
- enough support-connected functional cells
- enough non-dispenser functional cells
- enough mechanism categories among wiring, timing, motion, controls, fluids, and falling payload blocks

This prevents a translated rectangle of identical dispensers from being promoted into a proven shared cannon core. The report preserves that overlap as evidence while returning `shared_core_candidate=false`. A positive result still proves geometry only. Runtime phase and cannon-role equivalence require matched causal traces.

## Preservation gate

`scripts/cannon-preservation-check.py` compares every decoded non-air cell in a candidate against the exact reference. It fails closed when policy thresholds are exceeded.

The default `translate` alignment mode searches for one global integer translation using non-air bounds, functional bounds, and votes from matching critical block states. Candidates are scored by exact critical, functional, and non-air coverage. The chosen translation and competing candidates are included in the report. Translation handles harmless schematic-coordinate shifts; it does not permit rotation, reflection, scaling, or local deformation. `--alignment-mode exact` disables translation. Ambiguous best translations fail by default, and the minimum accepted alignment confidence defaults to `medium`.

Default policy:

- no source-dimension change
- at most 3 percent structural change
- at most 5 percent functional change
- at most one inferred module touched
- zero unexpected critical-component changes
- unchanged controls unless explicitly allowed
- unchanged dispenser-bank topology unless dispenser changes are explicitly allowed
- unchanged explicit block-entity position and ID topology
- no ambiguous translation unless explicitly allowed

The caller may name allowed block types and allowed module IDs. This makes the intended edit reviewable. A pass proves only policy compliance, not functionality.

## Runtime module trace

`scripts/analyze-module-trace.py` joins a module map to `causal-events.csv`.

Component events are assigned only by exact schematic-relative coordinate. Equal-distance shared components retain every candidate module instead of being silently assigned to one owner. Entity spawns are correlated to mapped dispense events using a configurable tick window and spatial radius. When a TNT UUID has exactly one candidate source module, later explosion events for that UUID are attributed to that module.

The output reports:

- component-event mapping coverage
- active modules and phase order
- same-tick module phase cohorts and inter-phase gaps
- dispense items and ticks
- redstone and piston activity
- correlated TNT and falling-block cohorts
- spawn position, velocity, fuse, and explosion position for unambiguous entities
- source-attributed entity and explosion cohorts grouped by tick
- unambiguous source-to-explosion chains
- unmapped and ambiguous evidence
- conservative runtime role candidates

The analyzer intentionally avoids definitive community subsystem names. `early-tnt-cohort-source-candidate` is evidence. `charge` is an interpretation that still requires full timing, motion, collision, and live-server proof.

## Unchanged-module runtime contract

`scripts/compare-module-traces.py` pairs exact translated modules using the dominant geometric translation, not module numbering. Repeated identical lanes are paired by minimum residual distance around that translation.

For every module outside the declared change set, the default contract compares:

- first and last activity ticks
- first dispense, piston, falling-block, and TNT ticks
- event counts and dispensed items
- correlated entity-type cohorts
- entity spawn positions and velocities
- fuse values
- explosion ticks and positions
- component-event, entity-source, shared-component, and joint-entity accounting coverage
- shared-component event cohorts and their tick distributions
- joint entity-source cohorts, including translated source dispenser identities and dispense timing
- ambiguous component-event counts without inventing one owner for shared evidence

Candidate entity, source-component, and explosion coordinates are transformed back into the reference module frame before comparison. This lets a padded or converted schematic pass without allowing real source, timing, fuse, trajectory, or impact drift. Runtime contract v3 permits ambiguity only when the ambiguous evidence is fully accounted for and its shared cohort remains unchanged. Unknown allowed-module IDs fail instead of being ignored.

## Repair-family ranking

`scripts/analyze-repair-family.py` compares multiple bounded repair variants against one exact reference and its run summary. It deduplicates mirrored run summaries by `run_id`, rejects conflicting duplicates and mismatched target, distance, layer, bounds, arena, and regeneration contracts, then uses three evidence stages: run metrics for every candidate, exact geometry for the strongest metric-screened candidates, and causal replay for the strongest bounded geometry candidates. Configurable geometry and runtime budgets make large experiment archives practical without promoting missing evidence. Candidates skipped by either stage remain visible and explicitly non-promotable. The final report exposes metric, geometry, and final scores, identifies the Pareto front only among runtime-tested candidates, and separates a clean bounded repair from a performance win that damages unrelated modules.

A candidate is not promotion-ready unless it has completed runtime evidence, passes the scenario contract, meets survival and target-retention thresholds, reduces self-damage, stays within the structural-change budget, and preserves protected module behavior.

`scripts/extend-repair-family-runtime.py` consumes an existing tournament report and adds causal replay to a requested runtime-rank window. It reuses the prior metric and geometry evidence, skips ranks already tested unless explicitly requested, and fails closed when the report has no eligible candidates. This is the fast path for expanding ranks 9–12, 13–16, and later windows without repeating the static tournament.

## Required workflow for advanced edits

1. Hash and map the exact proven reference.
2. Run the reference unchanged and collect a causal trace.
3. Build its runtime module phase report.
4. Compare related proven designs to find exact shared geometry.
5. Declare one allowed module and the allowed block types.
6. Produce the candidate from the reference, never from a fresh blank schematic.
7. Run the preservation gate.
8. Re-run the same scenario and compare causal traces.
9. Rank the repair family across repeated runs and reject collateral runtime drift.
10. Run defense, endurance, alignment, and self-damage gates.
11. Use a small live ExtremeCraft calibration or canary before an EC-ready claim.

Public Paper or Sakura success remains local evidence. Private ExtremeCraft configuration, patches, plugins, anti-lag behavior, durable blocks, regeneration, fluid handling, TNT restrictions, and FAWE limits can still change the result.