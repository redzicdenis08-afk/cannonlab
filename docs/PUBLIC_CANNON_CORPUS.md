# Public cannon corpus intake

CannonLab can now ingest publicly downloadable cannon schematics without confusing public access with permission to re-host, without trusting mutable URLs, and without promoting old numeric block IDs into modern block states.

## Why this exists

Real cannon architecture is scattered across faction server pages, test-server communities, Discord attachments, and personal archives. A useful corpus must preserve exact bytes and provenance before CannonLab compares modules, timings, or claimed roles.

The intake contract therefore separates four things:

1. **Source claim**: what the publisher says the cannon does.
2. **Static observation**: what the schematic geometry actually contains.
3. **Local runtime evidence**: what CannonLab reproduces on pinned Paper or public Sakura.
4. **Field evidence**: what a player measures on the target server.

A filename such as `OSRB`, `Nuke`, or `Slabbust` is metadata, not proof.

## Included public source registry

`profiles/corpus/public-cannon-sources-v1.json` records six direct downloads published by CosmicReborn:

- Formal
- Pred
- Mboze
- Shakisha
- Raid Outpost QP
- L Stacker

The official source page credits Leepad, Phonis, and Tino. The page does not state a reusable license, so every entry is `fetch-only`. CannonLab may download and inspect the bytes, but the repository does not vendor the third-party schematic files.

The registry intentionally records the target jar as `unknown`. Server branding and attachment labels do not establish physics parity.

## Plan the intake

```bash
python scripts/fetch-public-cannon-corpus.py \
  profiles/corpus/public-cannon-sources-v1.json \
  --output-directory lab-artifacts/public-corpus \
  --mode plan \
  --json-out lab-artifacts/public-corpus-plan.json
```

Plan mode validates:

- HTTPS-only URLs
- explicit host allowlisting
- plain filenames
- accepted schematic extensions
- creator attribution
- claimed-capability metadata
- fetch-only repository policy
- optional exact SHA-256 pins

It performs no network request.

## First controlled fetch

The public files are currently unpinned. The first operator-reviewed fetch must explicitly accept the observed hashes and write a lock:

```bash
python scripts/fetch-public-cannon-corpus.py \
  profiles/corpus/public-cannon-sources-v1.json \
  --output-directory lab-artifacts/public-corpus \
  --mode fetch \
  --accept-new-hashes \
  --write-lock lab-artifacts/public-cannon-lock-v1.json \
  --json-out lab-artifacts/public-cannon-fetch.json
```

The downloader:

- limits each file to 64 MiB
- rejects HTTP
- rejects redirects outside the allowlist
- rejects empty files
- rejects HTML error/login pages disguised as downloads
- refuses to overwrite different cached bytes
- computes SHA-256 while streaming
- records the final URL, byte count, authors, source page, and redistribution policy
- dispatches the file to the matching static auditor

After human review, keep the generated lock in a trusted evidence location. Future fetches should omit `--accept-new-hashes` and pass the lock:

```bash
python scripts/fetch-public-cannon-corpus.py \
  profiles/corpus/public-cannon-sources-v1.json \
  --output-directory lab-artifacts/public-corpus-repeat \
  --mode fetch \
  --lock-file lab-artifacts/public-cannon-lock-v1.json \
  --write-lock lab-artifacts/public-cannon-lock-v1-repeat.json
```

A changed upstream file then fails instead of silently replacing the corpus member.

## Legacy `.schematic` audit

The CosmicReborn downloads use the old MCEdit/Schematica format. Run the standalone reader directly with:

```bash
python scripts/legacy-schematic-audit.py FORMAL.schematic \
  --chunk-limit 160 \
  --json-out FORMAL-legacy-audit.json
```

The reader supports gzip or raw NBT and validates:

- root compound integrity
- dimensions and volume
- `Blocks`, `Data`, and optional `AddBlocks`
- tile-entity coordinate integrity
- duplicate and out-of-bounds tile entities
- legacy block-ID counts
- dispenser coordinates
- all 256 X/Z chunk-local paste offsets
- the current field-reported EC160 dispenser limit

The reader is deliberately forensic. It does **not** automatically convert legacy numeric IDs into Sponge v2. A trustworthy conversion needs a declared source Minecraft version, a reviewed numeric-ID/data mapping, block-entity preservation, and a deterministic modern output audit. Guessing that mapping would create polished garbage.

## Runtime progression

A public corpus member should move through these evidence stages:

1. `SOURCE_FETCHED`
2. `HASH_PINNED`
3. `LEGACY_STATIC_AUDIT_ONLY` or modern static audit
4. reviewed conversion candidate, when required
5. exact module map and family comparison
6. bounded local activation test
7. source-accounted causal trace
8. staged Paper/public-Sakura campaign
9. live canary only after local evidence is coherent

No stage automatically grants the next one.

## Community discovery

OneShot Cannoning remains a useful place to locate creators, test-server jars, and publicly shared files. Discord or in-game schematic-shop files should be added only after recording:

- who supplied the file
- whether analysis and storage are permitted
- original attachment name
- exact SHA-256
- claimed jar/version
- claimed capabilities
- source message or page
- whether redistribution is allowed

Private, leaked, purchased, or faction-stolen cannons do not belong in the public corpus.

## Truth boundary

A public download is not an ExtremeCraft-ready cannon. A static OSRB-looking structure is not proven OSRB behavior. A pass on pinned public Sakura is local runtime evidence only. Private ExtremeCraft configuration, anti-lag, FAWE behavior, durability, regeneration, and TNT changes remain separate unknowns until measured.
