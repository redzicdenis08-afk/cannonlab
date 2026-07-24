# Adversarial public-cannon corpus self-test

This report records the July 24, 2026 red-team pass performed after the first public cannon corpus and legacy-family mapper were merged.

## Why the second pass was necessary

The original pipeline passed its normal regression suite and successfully audited six pinned CosmicReborn schematics. That did not justify calling the system fully hardened. Happy-path tests did not exercise malicious NBT allocation patterns, incomplete audit subprocesses, or the difference between locally recurring construction motifs and one globally aligned cannon structure.

The second pass deliberately searched for counterexamples rather than additional green badges.

## Defects found and fixed

### Unsafe NBT collection handling

The legacy reader accepted a `TAG_List` with `TAG_End` as the child type and a positive length. Since a `TAG_End` payload consumes zero bytes, a hostile file could request a very large Python list without needing a correspondingly large input.

The reader now:

- permits `TAG_End` only for an empty list;
- applies separate limits to lists, byte arrays, int arrays, long arrays, compounds, and nesting depth;
- checks fixed-width collections against the bytes actually remaining before allocating or iterating;
- rejects impossible collection lengths before materialization.

### Inexact `AddBlocks` validation

The original legacy audit rejected a short `AddBlocks` array but accepted an oversized one. The format now requires the exact nibble-array length implied by the schematic volume.

### Weak tile-entity integrity

Duplicate and out-of-bounds tile entities were reported, but a tile entity placed on air did not make the static audit fail. The v2 audit records tile-entity IDs, underlying legacy block IDs, an explicit integrity status, and fails static integrity when issues are present.

### Audit failure hidden by corpus success

The base fetcher could finish downloading files and report overall `PASS` even when an individual static auditor returned `ERROR`. The strict wrapper now requires every requested audit to produce a report with `PASS` or `STATIC_FAIL`, a recognized process exit, and a verified hash. Any missing or errored audit fails the corpus and removes the newly written lock.

### Local motif similarity overstated

The earlier Formal/Pred result of `0.911054` is a multiset comparison of independently rotation-normalized local motifs. It proves that the two schematics share a large amount of local construction vocabulary. It does not prove that one rotation and translation aligns the entire machine.

A separate comparator now chooses one bounded global transform from four Y-axis rotations and translation votes, then measures whole-map exact-kind overlap.

For Formal and Pred, the strongest single transform produced:

| Metric | Result |
|---|---:|
| Rotation | 270 degrees around Y |
| Translation | `[-649, 0, 357]` |
| Exact functional-kind overlap | 2,731 components |
| Whole-map exact-kind Jaccard | 0.569077 |
| Formal coverage | 0.710643 |
| Pred coverage | 0.740711 |
| Kind conflicts at occupied overlap | 67 |
| Conflict ratio at occupied overlap | 0.023946 |
| Largest face-connected exact overlap | 302 components |
| Confidence | static-medium |

The defensible conclusion is that Formal and Pred contain a large globally aligned static structure and are strong architecture relatives. They are not established as identical cannons, simple rotated copies, or runtime-equivalent designs.

## Adversarial regressions

The CI suite now proves that:

- a non-empty `TAG_End` list is rejected before allocation;
- an impossible million-element fixed-width list is rejected using remaining-byte preflight;
- oversized `AddBlocks` fails;
- a tile entity on air fails integrity;
- an audit `ERROR`, missing report, or failed process makes strict corpus intake fail;
- a completed EC160 `STATIC_FAIL` is preserved as valid static evidence rather than confused with a parser failure;
- local motif bags can score `1.0` while the one-transform global score correctly falls to `0.333333` when repeated modules are rearranged;
- reflections are not promoted to rigid rotation matches;
- attachments reduce whole-structure similarity without erasing the aligned core;
- repeated panels remain within the bounded candidate budget.

The hostile fixtures run under a 768 MiB virtual-memory limit.

## Fresh live-corpus rerun

Workflow run `30114438511` re-downloaded all six exact pinned sources, verified all hashes, completed all six v2 audits, produced local and global architecture reports, removed the raw third-party schematics, proved the raw-file directory was absent, and uploaded derived evidence only.

All six files retained zero tile-entity integrity issues and remained illegal at every EC160 alignment. This consistency supports the static measurements but does not add runtime evidence.

The compact global result is pinned at:

```text
evidence/public-corpus/cosmicreborn-global-alignment-v1.json
```

## Remaining uncertainty

This hardening improves parser safety, evidence integrity, and architectural inference. It does not establish:

- correct legacy-to-modern block-state conversion;
- working firing controls;
- charge, hammer, booster, payload, OSRB, nuke, leftshot, or slab-bust roles;
- timing phases or TNT trajectories;
- Paper or public-Sakura runtime success;
- private ExtremeCraft parity;
- a serious EC-ready cannon.

The next justified step is bounded extraction of the globally aligned Formal/Pred overlap, followed by reviewed conversion and runtime tracing. The unmatched portions must remain visible rather than being flattened into a fictional universal core.
