# CannonLab Evidence-Backed Synthesis Planner

Verified: 2026-07-24

## Purpose

CannonLab can already decode, audit, trace, compare, stress and reject cannon schematics. This planner adds the missing conservative synthesis layer:

`evidenced module registry -> capability request graph -> declared-port placement -> EC160 scan -> deterministic Sponge v2 candidate`

It is deliberately not a free-form block generator. It never assigns hammer, OSRB, nuke, leftshot, charge or payload roles from a filename, visual shape or dispenser count. A capability is usable only when the registry explicitly declares it with an evidence level that satisfies the request.

## What it does

- verifies every source module by exact SHA-256 before planning;
- decodes source geometry through CannonLab's existing `schem-audit.py`;
- requires explicit capability evidence for every requested node;
- connects modules only through named input/output ports;
- requires matching media, compatible contracts and opposed directions for adjacent ports;
- uses integer translation only, with no rotation, reflection, scaling or geometry warping;
- rejects unexpected block overlap and block-entity overlap;
- fails closed on non-empty inventories or block entities that the minimal Sponge writer cannot preserve losslessly;
- scans the assembled dispenser coordinates across all 256 X/Z chunk offsets;
- enforces the current field-reported EC limit of 160 dispensers per chunk by default;
- ranks valid assemblies by evidence strength, safe-alignment count, chunk margin and compactness;
- optionally compiles the strongest plan into deterministic Sponge v2 / DataVersion 3465;
- reloads the compiled output and verifies exact occupied geometry and block-entity positions.

## Registry contract

Each component must declare:

- stable `id` and `version`;
- overall evidence level and concrete evidence sources;
- capability claims with their own evidence levels;
- exact schematic path, SHA-256 and DataVersion;
- named ports with kind, medium, position, direction and optional contract fields;
- whether the same component may be reused in one assembly;
- source metadata.

Evidence levels are ordered:

1. `unknown`
2. `inference`
3. `static`
4. `local-runtime`
5. `field-reported`
6. `field-verified`

A capability claim cannot have stronger evidence than the component itself.

## Request graph

A request describes logical nodes and exact edges rather than raw blocks.

```json
{
  "schema_version": 1,
  "id": "ec160-baseline",
  "min_evidence": "local-runtime",
  "root_node": "control",
  "nodes": [
    {"id": "control", "requires": ["control-spine"]},
    {"id": "charge", "requires": ["charge-cohort"]},
    {"id": "payload", "requires": ["payload-interface"]}
  ],
  "edges": [
    {
      "from": {"node": "control", "port": "signal-out"},
      "to": {"node": "charge", "port": "signal-in"},
      "connection": "adjacent"
    },
    {
      "from": {"node": "charge", "port": "entity-out"},
      "to": {"node": "payload", "port": "entity-in"},
      "connection": "adjacent"
    }
  ],
  "constraints": {
    "chunk_limit": 160,
    "min_safe_alignments": 1,
    "max_dimensions": [128, 128, 128],
    "allow_identical_overlap": false,
    "require_lossless_block_entities": true
  }
}
```

## Usage

Plan without writing a schematic:

```powershell
python scripts/cannon-synthesis-planner.py `
  profiles/synthesis/my-registry.json `
  profiles/synthesis/my-request.json `
  --json-out lab-artifacts/synthesis/plan.json
```

Compile the strongest valid plan:

```powershell
python scripts/cannon-synthesis-planner.py `
  profiles/synthesis/my-registry.json `
  profiles/synthesis/my-request.json `
  --compile-best lab-artifacts/synthesis/candidate.schem `
  --json-out lab-artifacts/synthesis/plan.json
```

The output is an `ASSEMBLY_CANDIDATE_ONLY`. It still requires:

1. source-module preservation checks;
2. real input activation;
3. causal trace and source accounting;
4. impulse-graph comparison;
5. target, range, survival and self-damage contracts;
6. a controlled live ExtremeCraft canary before any EC-ready claim.

## Why the compiler is intentionally strict

Cannon modules often contain dispenser block entities that are safe to rewrite as empty because `/p tntfill` is the verified field workflow. Other block entities may contain inventories, signs, custom NBT or plugin-sensitive data. The planner rejects those by default rather than silently stripping them.

The first production registry should therefore start with exact, isolated modules whose block-entity contract is understood:

- field-verified pocket cannon control/physics spine;
- source-accounted Nuke/Leftshot shared lower core after one clean local shot;
- exact charge cohorts;
- exact payload or sand interfaces;
- barrel/guider modules;
- attachments only after their causal roles are promoted from repeated evidence.

## Current boundary

This planner makes synthesis deterministic and evidence-driven. It does not solve private ExtremeCraft physics, infer undocumented subsystem semantics, automatically route arbitrary redstone, or prove a compiled candidate works. Public Paper/Sakura runtime and live EC measurements remain the promotion authorities.
