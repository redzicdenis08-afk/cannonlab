# CannonLab cannon archetypes

This directory turns community names such as Rev-Worm, OSRB, leftshoot, force and efficient nuke into fail-closed machine contracts.

An archetype is not a schematic recipe. It records:

- exact reference hashes where available;
- static geometry that must survive reconstruction;
- controls and activation ordering;
- dispenser-cohort fingerprints;
- required payload and trajectory evidence;
- family-specific forbidden shortcuts;
- current evidence ceiling;
- EC160 redistribution constraints.

## Commands

List the registry:

```powershell
python scripts/cannon-archetype-engine.py list
```

Inspect the Rev-Worm contract:

```powershell
python scripts/cannon-archetype-engine.py inspect rev-worm-383-v4
```

Audit whether the current lab can support and promote that family:

```powershell
python scripts/cannon-archetype-engine.py audit --archetype rev-worm-383-v4
```

Create a reconstruction experiment plan from the registered private reference hash:

```powershell
python scripts/cannon-archetype-engine.py plan rev-worm-383-v4 `
  --reference-sha 6e23d2868c309b203d74003573a4707105a39f6822a3a5e715d0bb9ab71d7eda `
  --lifecycle diagnostic-prototype `
  --job rev-worm-baseline
```

Verify a runtime causal trace against the known 537/336/144 dispenser fingerprint:

```powershell
python scripts/cannon-archetype-engine.py verify-cohorts rev-worm-383-v4 `
  output/path/to/causal-events.csv
```

A cohort PASS proves only that the registered activation fingerprint occurred. It does not prove a clean worm output, target contact, cannon survival or live ExtremeCraft readiness.

## Current Rev-Worm result

The current capability audit reports:

- base analysis readiness: yes;
- local-candidate promotion readiness: no;
- current evidence ceiling: diagnostic prototype.

The missing promotion capabilities are documented in `UPGRADE_BACKLOG.md`.

## Privacy boundary

The registry contains hashes and derived contracts, not private cannon binaries. Do not publish private schematics or Litematics without Denis's explicit approval.
