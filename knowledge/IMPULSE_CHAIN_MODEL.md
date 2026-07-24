# CannonLab impulse-chain model

## Core rule

A serious factions cannon is not a flat redstone drawing. It is a three-dimensional staged physics machine.

Separate TNT and falling-block cohorts occupy real chambers. One explosion changes the position, velocity, or alignment of another cohort. That moved cohort then becomes the input to the next stage. The cannon is therefore best represented as a directed impulse chain rather than a pile of nearby components.

The user's reference diagram is the intended mental model: grouped TNT packages act from different sides and heights, arrows represent the resulting impulse, and the central package is moved into the next position or phase. A production cannon scales this idea into large power banks, compression, hammers, splitters, stoppers, nukes, OSRB, leftshoot, reverse, and related modules.

## Canonical stage record

Every proposed stage must have all of these fields:

- **source cohort**: exact dispensers or already moving TNT entities responsible for the impulse
- **recipient cohort**: TNT, sand, concrete, or another payload that should be moved
- **spawn contract**: source tick, recipient tick, and same-tick entity order where relevant
- **explosion contract**: fuse, explosion tick, and explosion center
- **geometry contract**: relative source and recipient positions at explosion
- **impulse vector**: expected horizontal and vertical velocity change
- **entry condition**: where the recipient must be before the stage acts
- **exit condition**: where and how fast the recipient must leave for the next stage
- **failure signature**: the measurable symptom when the contract is wrong

A stage with no named recipient and no measurable impulse is not understood, even if its redstone activates.

## Example causal chain

A modern shot may contain a chain resembling:

1. Sand compression releases a falling-block cohort.
2. A stopper or alignment stage positions that cohort.
3. A hammer or shared-power stage pushes it vertically into a stack.
4. Main power launches the stacked package forward.
5. A splitter separates or offsets TNT and sand for the required angle.
6. A leftshoot, reverse, midair, or secondary force stage redirects the package.
7. Hybrid, slab-bust, OSRB, nuke, bypass, anti-patch, or double-tap cohorts execute at the wall.

Not every cannon uses every stage, and hammerless designs can merge several effects into one shared explosion. The chain still exists physically and must still be measured.

## Morphology rule

Generated or repaired candidates must preserve actual three-dimensional cannon morphology:

- distinct TNT banks and blast chambers
- water protection where explosions occur inside the cannon
- payload shafts, guider paths, alignment cells, and transition points
- vertical and lateral separation between physical stages
- support blocks and redstone arranged around the mechanism, not substituted for it
- enough space for TNT and falling blocks to exist, move, and collide without clipping the cannon

A broad flat slab of dispensers and redstone is rejected unless a proven reference genuinely uses that geometry and runtime evidence confirms the complete impulse chain.

## CannonLab evidence model

CannonLab should infer a directed graph from runtime telemetry:

- node: source-attributed TNT or falling-block cohort
- edge: a statistically and physically plausible velocity change in another cohort after the source explosion
- edge attributes: tick gap, distance, direction, velocity delta, confidence, and repeated-shot consistency
- stage boundary: stable cluster of nodes and edges performing one physical effect

The graph must distinguish:

- wiring activation from physical effect
- proximity from causation
- same-tick order from ordinary delay
- propulsion from stopping, splitting, alignment, or vertical stacking
- a successful local stage from live ExtremeCraft parity

## Acceptance gates

A candidate is not promoted merely because it fires or explodes. For every required stage:

- the intended source cohort must spawn
- the intended recipient must be present in the correct chamber
- the source must explode in the expected relative position
- the recipient must receive a velocity change in the expected direction and range
- the recipient must enter the next stage's accepted position and timing window
- the relationship must repeat across multiple clean shots
- cannon integrity must remain within the configured loss limits

The whole shot passes only when the complete required impulse chain reaches the target and satisfies the named breach contract.

## Design boundary

Community labels such as `384`, `OSRB`, `hammerless`, `force`, `asser`, `leftshot`, or `nuke` are not substitutes for this graph. They are hypotheses about a collection of stages. The mechanism is considered understood only after its directed impulse chain is reconstructed from geometry and runtime evidence.
