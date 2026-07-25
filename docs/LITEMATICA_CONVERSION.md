# Audited Litematica conversion

CannonLab accepts Litematica files as schematic inputs, but conversion is a serialization operation, not a physics proof.

## Required path

1. Audit the original `.litematic` with `scripts/schem-audit.py`.
2. Confirm region orientation, dimensions, palette states, block entities and every EC160 alignment.
3. Convert only compatible geometry to deterministic Sponge v2.
4. Re-audit the exact `.schem` output that will be pasted.
5. Run `scripts/paste-alignment-audit.py` to convert schematic-minimum offsets into the player's actual `//paste` frame.
6. Test the output through the same scenario and evidence gates used for native Sponge input.

Example:

```powershell
python scripts/schem-audit.py cannon.litematic `
  --chunk-limit 160 `
  --expect-format litematic `
  --convert-sponge-out cannon-ec.schem `
  --output-data-version 3465 `
  --allow-data-version-retag `
  --json-out litematic-audit.json

python scripts/schem-audit.py cannon-ec.schem `
  --chunk-limit 160 `
  --expect-format sponge-v2 `
  --json-out sponge-audit.json

python scripts/paste-alignment-audit.py cannon-ec.schem `
  --chunk-limit 160 `
  --json-out paste-alignment.json
```

## Truth boundary

`--allow-data-version-retag` changes the numeric DataVersion. It does not execute Mojang DataFixerUpper and does not prove that every state has identical runtime behavior. Conversion preserves compatible geometry and block entities; it does not prove controls, timing, cannon modules, server parity or target capability.