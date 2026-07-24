# Modern cannon architecture policy

This directory contains fail-closed rules for generating, repairing, testing, and promoting modern factions cannons.

The policy exists to prevent a recurring failure mode: replacing a real three-dimensional impulse machine with a visually tidy but physically meaningless flat dispenser layout.

## Non-negotiable design rules

1. **Reference first.** A modern raid cannon must begin from decoded reference geometry or a bounded variant of a proven reference. Blank-canvas builds are diagnostic prototypes only.
2. **Preserve the physical machine.** Redstone schedules the shot, but TNT cohorts, sand, hybrid payloads, hammers, splitters, stoppers, guiders, pistons, fluids, and chambers form the actual machine.
3. **Model impulse transfer.** Every serious candidate must declare stages and directed edges showing which stage physically pushes, redirects, aligns, or transfers the next stage.
4. **Reject flat morphology.** A modern raid candidate must pass CannonLab's geometry-profile morphology gate. This is necessary but never sufficient.
5. **Do not name roles from shape or filenames.** Static geometry may produce a role candidate. A confirmed role needs runtime or field evidence.
6. **Change one bounded variable.** Reference repairs should touch one declared module or one causal variable by default. Broader edits need an explicit reviewed override.
7. **No assisted promotion.** Direct dispenser triggering, forced entity velocity, TNT probes, simulated durability, or hidden paste assistance may diagnose a mechanism but cannot promote the cannon.
8. **Require native redstone evidence.** A local candidate must fire from its real control through normal redstone and pass acceptance, survival, payload, trajectory, and breach gates.
9. **Do not inflate claims.** Explosion, activation, TNT travel, or static resemblance alone cannot justify `working`, `fixed`, `one-shot`, or `EC-ready`.
10. **ExtremeCraft requires ExtremeCraft evidence.** Public Sakura or Paper proves only local behavior. `EC-ready` requires a passing live canary and an explicit field-verification record.

## Machine-checkable manifest

Validate a candidate architecture manifest with:

```powershell
python scripts/validate-cannon-architecture.py path/to/architecture-manifest.json
```

The validator checks:

- source mode and reference hashes
- geometry-profile and anti-pancake morphology verdicts
- preservation evidence
- stage and impulse-edge topology
- role-evidence honesty
- change budget
- runtime-assist exclusions
- acceptance evidence
- claim level
- live ExtremeCraft evidence for EC promotion

The validator is additive. It does not rewrite schematics, alter CannonLab runtime behavior, or guess subsystem roles. It blocks unsupported promotion and explains every failure.

## Minimal manifest shape

```json
{
  "schema": "cannonlab-architecture-manifest-v1",
  "candidate": {
    "file": "cannons/example.schem",
    "intent": "modern-raid",
    "lifecycle": "local-candidate",
    "claims": ["local-runtime"]
  },
  "source": {
    "mode": "reference-repair",
    "reference_sha256": ["<64 lowercase hex characters>"],
    "geometry_profile": "output/job/geometry-profile.json",
    "preservation_report": "output/job/preservation.json"
  },
  "architecture": {
    "stages": [
      {
        "id": "power",
        "role": "power",
        "role_status": "confirmed",
        "role_evidence": "runtime",
        "runtime_evidence": "output/job/module-trace.json"
      },
      {
        "id": "payload",
        "role": "payload-package",
        "role_status": "confirmed",
        "role_evidence": "runtime",
        "runtime_evidence": "output/job/module-trace.json"
      }
    ],
    "impulse_edges": [
      {
        "from": "power",
        "to": "payload",
        "mechanism": "explosion-push",
        "status": "verified",
        "expected_axis": "forward",
        "runtime_evidence": "output/job/impulse-edge.json"
      }
    ]
  },
  "change_budget": {
    "declared_variable": "one repeater delay in the mapped timing module",
    "modules_touched": 1,
    "override_approved": false,
    "override_reason": ""
  },
  "runtime": {
    "native_redstone": true,
    "direct_dispense": false,
    "forced_velocity": false,
    "tnt_probe": false,
    "acceptance_report": "output/job/assertion.json"
  },
  "extremecraft": {
    "field_verified": false,
    "live_canary_report": null
  }
}
```
