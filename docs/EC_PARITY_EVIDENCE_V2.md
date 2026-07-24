# ExtremeCraft Parity Evidence v2

Verified: 2026-07-24

## Why v2 exists

The original calibration auditor checked eight broad probe names and minimum sample counts.
That was useful for rejecting an empty folder, but it could not prove that the files belonged
to the stated fixture, that raw captures were unchanged, or that independent cannon mechanics
had actually been measured.

Parity is now treated as a 16-dimension vector, not one `Sakura 26.1.2` checkbox.

The machine-readable contracts are:

- `profiles/parity/extremecraft-private-parity-required-v1.json`: what must be learned;
- `profiles/parity/extremecraft-evidence-rules-v1.json`: exact evidence and sample requirements;
- `scripts/audit-ec-calibration.py`: fail-closed pack validation and limited classification.

## Required dimensions

A complete v2 pack covers:

1. TNT horizontal spawn kick;
2. TNT fuse distribution;
3. dispenser activation order;
4. collision axis behavior;
5. TNT motion in water;
6. velocity and despawn limits;
7. explosion batching and per-tick limits;
8. falling-block ticking and collision;
9. piston chains and observer updates;
10. chunk loading and boundary continuity;
11. dispenser-per-chunk limits;
12. FAWE block-entity limits;
13. material durability hit contracts;
14. regeneration algorithm;
15. OSRB clipping and restacking;
16. the complete paste-empty, settle, fill, real-input workflow.

Each dimension has its own minimum sample count, required fields, required comparison labels,
and optional automatic classifier.

## Evidence file shape

Every v2 JSON file is one dimension:

```json
{
  "schema_version": 2,
  "kind": "ec-parity-evidence",
  "dimension": "tnt.fuse.distribution",
  "server": "ExtremeCraft Cannoning",
  "server_date": "2026-07-24",
  "captured_at": "2026-07-24T01:23:45Z",
  "client_version": "1.21.11",
  "fixture": {
    "path": "fixtures/single-dispenser-fuse.schem",
    "sha256": "<64 lowercase hex characters>"
  },
  "paste_origin": {"x": 0, "y": 100, "z": 0},
  "player_chunk_offset": {"x": 0, "z": 0},
  "chunk_origin_confirmed": true,
  "workflow": {
    "paste_empty": true,
    "settle_ticks": 120,
    "fill_after_settle": true,
    "real_input": true
  },
  "raw_artifacts": [
    {
      "path": "raw/fuse-run-001.csv",
      "sha256": "<64 lowercase hex characters>"
    }
  ],
  "samples": [
    {
      "sample_id": "fuse-0001",
      "spawn_tick": 100,
      "explosion_tick": 179,
      "initial_fuse": 79
    }
  ]
}
```

Files may split one dimension across multiple captures. Sample IDs must remain unique across
the whole evidence directory.

## Hash and path rules

By default, the auditor verifies the SHA-256 of every fixture and raw artifact. Referenced
paths must resolve inside the evidence directory. Missing files, changed bytes, path traversal,
or malformed hashes invalidate the evidence file.

`--skip-hash-verification` exists only for inspecting incomplete historical packs. A report
created with that flag does not contain the normal hash-backed guarantee.

The auditor also rejects secret-like JSON keys such as passwords, tokens, sessions, cookies,
authorization headers and Minecraft sessions. Evidence packs must contain observations, never
credentials.

## Run the auditor

```powershell
python scripts/audit-ec-calibration.py evidence/extremecraft-2026-07-24 `
  --json-out lab-artifacts/ec-parity-v2.json
```

Exit codes:

- `0`: all 16 dimensions are complete and every file is internally valid;
- `2`: incomplete or invalid evidence;
- uncaught input/config errors fail the command.

Important report fields:

- `valid_dimension_count`
- `coverage_ratio`
- `missing_dimensions`
- `dimension_reports`
- `files`
- `legacy_compatibility`
- `truth_boundary`

## Automatic classifications

The auditor currently derives only outcomes that can be calculated without inventing cannon
semantics:

- horizontal kick: zero or nonzero;
- fuse lifetime: fixed or distributed;
- redstone sequence: fixed or variable;
- explosion processing: no observed cap, batched, or missing;
- paste thresholds: highest passing count and lowest failing count.

Other dimensions remain `not-automatically-classified` even when their evidence is complete.
They require explicit analysis against local hypothesis runs.

A submitted `claimed_classification` must agree with any automatic classification. A conflict
invalidates the dimension.

## Legacy compatibility

Old eight-probe files still parse so existing CI and historical packs fail closed instead of
crashing. They are reported under `legacy_compatibility` and continue to populate top-level
`missing_probes`.

Legacy evidence never promotes a v2 dimension and can never produce `ec_calibrated=true`.

## Promotion boundary

A v2 `PASS` proves:

- all 16 declared evidence contracts are represented;
- fixture and raw-artifact hashes match;
- paths remain inside the pack;
- sample counts, fields, labels and identities are internally valid;
- supported derived classifications are consistent.

A v2 `PASS` does not independently prove that the operator measured ExtremeCraft correctly,
that private mechanics did not change after the captured server date, or that one full cannon
is raid-ready. Exact reference and candidate schematics still need their own live field canaries.
