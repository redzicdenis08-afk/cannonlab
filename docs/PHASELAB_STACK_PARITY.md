# PhaseLab private-stack parity

PhaseLab's current exact reference runtime proves behavior on pinned public Sakura 26.1.2 with ViaVersion and ViaBackwards 5.9.0. Those source/JAR identities are reference-lab evidence, not proof that the live server uses byte-identical Sakura or Via builds. PhaseLab does **not** yet prove parity with the full private server stack.

## Current observed stack

The canonical observed profile is `profiles/phaselab/extremecraft-plugin-stack-observed-v1.json`.

Confirmed or strongly identified:

- Sakura 26.1.2
- ViaVersion and ViaBackwards are required by the current translated-client lab, but their live versions are unknown; 5.9.0 is only the pinned reference-lab pair
- Velocity, exact version unknown
- FactionsUUID, exact version unknown
- AuraSkills, exact version unknown
- ExcellentEnchants, likely 5.4.3 but not confirmed
- FactionsUUIDPlus
- Vault
- NoCheatEnforcer
- CustomEnchantsHook
- AdditionalFeatures
- UserManager
- PaperIntegration
- ServerManager

FactionsUUID 4.6.1 is preserved only as a documentation-version candidate. It is not treated as proof of the live server build.

The public Sakura commit and hash are preserved under `backend.reference_runtime`. The live backend hash remains unlocked until an actual live export is supplied, because a private Sakura patch can retain the same visible version while changing behavior.

## Why random downloads are forbidden

Movement, teleport, vehicle, inventory, enchant, skill and claim behavior can change by plugin version, load order, private patch and configuration. Installing a convenient current release would create an approximate server while falsely labelling it identical.

Several observed names also appear to be custom/private plugins. PhaseLab cannot reconstruct those from public plugin pages.

Any additional readable plugin JAR found in the live export is treated as a parity blocker during inventory and automatically added as a required hash-locked component when the first live lock is created. Extra JARs cannot silently ride along. `PhaseLabStackProbe` is the sole ignored diagnostic identity so temporarily installing the exporter does not contaminate the target stack.

## Exact workflow

1. Export the live backend `plugins/` JARs into a private local folder. Do not commit them.
2. Export the exact Velocity JAR and Sakura backend JAR.
3. Run the inventory against the observed profile:

```text
python scripts/phaselab_stack_audit.py \
  --manifest profiles/phaselab/extremecraft-plugin-stack-observed-v1.json \
  --plugins-dir C:/private/live-export/plugins \
  --server-jar C:/private/live-export/server.jar \
  --proxy-jar C:/private/live-export/velocity.jar \
  --configs-dir C:/private/live-export/configs \
  --output plugin-stack-export/inventory.json
```

The first run is expected to return evidence code `2` because unknown target versions are deliberately unlocked.

4. Lock only an actual live-server export:

```text
python scripts/phaselab_stack_audit.py \
  --manifest profiles/phaselab/extremecraft-plugin-stack-observed-v1.json \
  --plugins-dir C:/private/live-export/plugins \
  --server-jar C:/private/live-export/server.jar \
  --proxy-jar C:/private/live-export/velocity.jar \
  --configs-dir C:/private/live-export/configs \
  --output plugin-stack-export/lock-run.json \
  --lock-output plugin-stack-export/extremecraft-live-lock.json \
  --source-label live-server-export
```

5. Verify and stage the locked stack into an isolated runtime:

```text
python scripts/phaselab_stack_audit.py \
  --manifest plugin-stack-export/extremecraft-live-lock.json \
  --plugins-dir C:/private/live-export/plugins \
  --server-jar C:/private/live-export/server.jar \
  --proxy-jar C:/private/live-export/velocity.jar \
  --configs-dir C:/private/live-export/configs \
  --output plugin-stack-export/verified.json \
  --stage-dir phaselab-runtime-local/plugins \
  --stage-config-dir phaselab-runtime-local/configs
```

Staging refuses any missing, ambiguous, version-mismatched or hash-mismatched required plugin, backend, proxy, or configuration fingerprint. Configuration contents are never printed; only relative paths, sizes and SHA-256 evidence are recorded.

Or assemble the complete verified private runtime in one command after the lock exists:

```text
python scripts/prepare_phaselab_private_runtime.py \
  --manifest plugin-stack-export/extremecraft-live-lock.json \
  --plugins-dir C:/private/live-export/plugins \
  --server-jar C:/private/live-export/server.jar \
  --proxy-jar C:/private/live-export/velocity.jar \
  --configs-dir C:/private/live-export/configs \
  --runtime-root phaselab-runtime-local
```

That command copies no files until every identity gate passes and writes `runtime-identity.json` as the assembly receipt. It will only replace a non-empty runtime directory carrying its own `.phaselab-runtime-root` marker; an unrelated or manually populated directory is refused instead of deleted. Direct `--stage-dir` and `--stage-config-dir` targets must be empty, preventing stale JARs or configs from contaminating the clone.

## In-server export probe

`phaselab-stack-probe` is an OP-only diagnostic plugin. `/phasestack export` writes server identity, loaded plugin metadata and accessible JAR SHA-256 hashes to `plugins/PhaseLabStackProbe/stack-export.json` without reading or exporting configuration values.

The probe is an inventory aid. A local runtime is still not identical until the exported JARs, proxy, backend and relevant configurations are copied and verified.
