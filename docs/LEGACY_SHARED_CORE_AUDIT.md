# Legacy Formal/Pred shared static audit

CannonLab now distinguishes four increasingly strict questions when comparing the pinned public Formal and Pred legacy schematics:

1. Do they use similar local construction vocabulary?
2. Can one whole schematic be aligned to the other with one rigid transform?
3. Which aligned functional blocks also preserve reviewed legacy metadata such as facing and repeater delay?
4. Which metadata-equivalent regions remain connected when exact shared support blocks are included, and where do source-specific boundaries remain?

None of these questions proves cannon function.

## Pinned inputs

The source files remain fetch-only and are identified by exact SHA-256:

- Formal: `510abf89ca04e7219aa3fd3f002b28c31b9462c37b9eac82843019391df5c8ae`
- Pred: `9e13c77fbab9c1037d314bb6d96cf363244f257f17ef5e161137d34366324763`

The pinned global transform rotates Pred 270 degrees around Y and translates it by `[-649, 0, 357]`. It performs no reflection, scaling, or local warping.

## Metadata-aware overlap

The global kind-only alignment contained 2,731 same-kind functional positions. The metadata-aware pass retained 2,693:

- 2,693 proven canonical-token equivalents
- 9 metadata conflicts
- 29 unresolved rotated controls or torches
- 67 kind conflicts at occupied functional positions

Saved powered and unpowered forms are normalized only where CannonLab already has an explicit legacy rule. Unsupported directional metadata remains unresolved instead of being guessed.

## Component and support-shell checks

The 2,693 proven positions split into 67 face-connected functional regions with at least eight blocks. None was face-closed in both sources.

A bounded support-shell pass may add only exact, explicitly rotation-invariant shared support blocks. It cannot consume functional continuation, one-sided blocks, conflicts, directional support, or unreviewed legacy IDs. All 67 regions remained open.

## Shared assembly closure

The assembly pass merges proven functional regions through exact shared support. It produced ten assemblies containing at least eight proven functional blocks.

The largest is a 3,939-node shared spine:

- 1,803 functional blocks
- 2,136 support blocks
- 559 dispensers
- best EC160 pressure of 153
- only two legal X/Z offsets
- substantial conflicting, unresolved, and one-sided boundary evidence

It is useful architecture evidence, not an extraction candidate.

## Near-closed review candidates

Two assemblies have only small source-specific boundaries and no boundary conflict or unresolved metadata. The label `NEAR_CLOSED_STATIC_REVIEW_CANDIDATE` means “inspect next,” not “safe module.”

### ASSEMBLY-002

- 273 functional blocks
- 265 exact shared support blocks
- 118 dispensers
- all 256 EC160 offsets legal
- eight unique source-specific boundary positions
- two paired boundary-shape hypotheses at Y spans 13–14 and 17–18

### ASSEMBLY-007

- 44 functional blocks
- 41 exact shared support blocks
- 12 dispensers
- all 256 EC160 offsets legal
- four unique source-specific boundary positions
- one paired boundary-shape hypothesis at Y span 21–22

For all three pairs, Formal exposes the attachment on the west face while globally aligned Pred exposes it on the south face. Each pattern contains one signal-bearing block and one support or unmapped block.

This supports a variant connector-placement hypothesis. It does not establish input/output direction, timing, role, or standalone behavior.

## Commands

Metadata-aware shared regions:

```bash
python scripts/legacy-shared-core-audit.py \
  --first-id formal --first FORMAL.schematic \
  --second-id pred --second PRED.schematic \
  --turns 3 --translation=-649,0,357 \
  --chunk-limit 160 --minimum-component-size 8
```

Bounded shared support envelopes:

```bash
python scripts/legacy-shared-core-envelope.py \
  --first-id formal --first FORMAL.schematic \
  --second-id pred --second PRED.schematic \
  --turns 3 --translation=-649,0,357
```

Complete shared assemblies:

```bash
python scripts/legacy-shared-assembly-audit.py \
  --first-id formal --first FORMAL.schematic \
  --second-id pred --second PRED.schematic \
  --turns 3 --translation=-649,0,357 \
  --chunk-limit 160
```

Boundary port hypotheses:

```bash
python scripts/infer-legacy-shared-ports.py \
  formal-pred-shared-assemblies.json
```

## Evidence progression

Before either review candidate can become a synthesis component, CannonLab still requires:

1. reviewed legacy-to-modern block-state conversion;
2. explicit connector direction and timing from causal runtime evidence;
3. standalone activation evidence;
4. source-accounted TNT, payload, and damage phases;
5. live ExtremeCraft canary evidence before any EC-ready claim.

The compact captured evidence is stored in:

```text
evidence/public-corpus/cosmicreborn-formal-pred-shared-static-v1.json
```

## Truth boundary

Static repetition, EC160 legality, a small boundary, or a matched connector shape does not prove a working cannon module. Public Sakura results would remain local evidence only. Private ExtremeCraft mechanics, durability, regeneration, anti-lag behavior, FAWE behavior, and TNT changes remain separate unknowns.
