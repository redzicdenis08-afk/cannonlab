# ExtremeCraft Parity Lab

CannonLab cannot honestly clone an unknown private server stack. This layer instead makes every cannon test declare exactly which public Sakura settings, field observations, command shims, limits, and unknowns produced the result.

## Current candidate profile

`profiles/extremecraft-observed.yml` is the closest reproducible candidate as of 2026-07-24. It combines pinned public Sakura 26.1.2, the 1.20.0 Paper mechanics target, merge level NONE, TNT spread Y, TNT flowing in water, public Sakura durable materials, the 160-dispenser-per-chunk cap, and the Sponge v2 / DataVersion 3465 workflow.

It is evidence grade `mixed`, not field parity. A result produced by this profile is labeled `local-runtime-candidate` until a matching live calibration is recorded.

## One-command run

```powershell
$env:CANNONLAB_ACCEPT_EULA = 'TRUE'
$env:CANNONLAB_SAKURA_JAR = 'C:\path\to\sakura-26.1.2.jar'
$env:CANNONLAB_CORPUS_DIR = 'C:\path\to\private-cannons'

.\scripts\run-ec-lab.ps1 `
  -Scenario my-cannon-ec-defense-gauntlet.yml `
  -LabHome C:\CannonLab-EC
```

Every run writes a profile manifest and embeds the profile ID, evidence grade, and SHA-256 into `run-summary.json`. A runtime result without that identity is unprofiled and must not be compared with profiled evidence.

The exact plugin directory is inventoried as `plugin-stack.json`. Each JAR gets a SHA-256 and parsed Bukkit/Paper descriptor, while `run-summary.json` carries the aggregate stack hash. Optional compatibility plugins can be mounted through `CANNONLAB_PLUGIN_DIR`; binaries remain outside git.

## Generate the same gauntlet for every cannon

```powershell
py scripts\make-ec-scenario-pack.py 2s_384_Nuke.schem `
  --output-dir scenarios\generated\2s-384-nuke `
  --origin 7,0,5 `
  --fire-input 7,2,12 `
  --fire-mode button `
  --direction west `
  --distance 939 `
  --y-offset -48 `
  --lateral-offset -63
```

The generator creates dry baseline, native durable watered obsidian, fast hotdog regeneration, filter, slab filter, pillars, and a mixed defense gauntlet. Use the same pack for Nuke, OSRB, leftshot, hammerless, slab-bust, bypass, double-tap, and future cannons. Tighten contracts after a clean baseline. Never lower contracts merely to turn a red run green.

## Field workflow shims

The isolated server exposes familiar manual commands:

- `/p tntfill`: fills all loaded dispensers with TNT
- `/p gui`: toggles manual explosions while no automated run is active
- `/bonetool`: places sand, places obsidian while sneaking, and removes blocks on left-click
- WorldEdit or FAWE remains responsible for `//paste`

These are CannonLab-compatible shims, not copies of ExtremeCraft private plugins.

## Durability truth

Public Sakura native durability is preferred on Sakura runs. CannonLab simulation is a fallback for Paper or controlled tests.

Dry and watered obsidian are separate tests. Four dry TNT hits should break candidate-profile obsidian. Four naked TNT explosions against a water shield should not automatically count as useful wall hits. A real cannon must deliver sand or another verified dewatering/stacking payload before a watered-wall breach is credited. This prevents nearby explosions from being promoted into fake wall damage.

## Parity audit

```powershell
py scripts\audit-ec-parity.py `
  profiles\extremecraft-observed.yml `
  calibration\extremecraft-field-observations.yml `
  --json-out parity-audit.json `
  --require-no-mismatch
```

Current declared coverage is seven matching facts and seven open probe families. Candidate status means no known mismatch, not exact parity.

## Evidence ladder

1. `static`: geometry and NBT only
2. `lab-assisted-diagnostic`: controlled probes or injected conditions
3. `local-runtime`: native circuit on a declared Paper/Sakura profile
4. `local-runtime-candidate`: EC candidate profile plus real defense contract
5. `field-reported`: live player report
6. `field-verified`: measured ExtremeCraft canary with retained evidence

Only the final level establishes ExtremeCraft readiness. Filenames, signs, local explosions, CI, or profile similarity cannot.

## Next calibration order

1. TNT spread variance
2. merge level and merged momentum
3. durable-material expiration
4. FAWE block-entity paste cap
5. regen replacement timestamps
6. chunk-ticket behavior
7. leftshot and adjust restrictions
8. repeated same-world firing without repaste

Record each live observation in `calibration/extremecraft-field-observations.yml`, audit it, then create a new dated profile. Never silently mutate an old evidence profile.
