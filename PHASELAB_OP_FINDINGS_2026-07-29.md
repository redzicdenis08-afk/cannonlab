# PhaseLab High-Impact Findings — 2026-07-29

## Scope

Exact authorized approximation:

- Sakura 26.1.2 (`63f35d74e0fbe6bcd76c58494c01c1632c83010d`)
- Java 25
- FactionsUUID 4.6.1 candidate
- AuraSkills 2.3.12
- ExcellentEnchants 5.4.3
- NightCore 2.15.2
- ViaVersion / ViaBackwards 5.9.0
- Vault 1.7.3

These findings are exact-runtime for this tested stack. They are not proof that a live server has identical private plugin jars, configuration, or patches.

## Confirmed

### Repeatable cursed grindstone XP

- Surface: AuraSkills + ExcellentEnchants event ordering.
- Result: same Sharpness V + `curse_of_fragility` sword paid Enchanting XP repeatedly while the result click was cancelled and the input survived.
- Three consecutive gains: `116`, `16`, `237.6` XP.
- Exact exploit run: `30418729460`.
- Exact guard run: `30419935986`.
- Guard result: three clicks, zero XP gain, item preserved.

### Enemy-claim crafter storage theft

- Surface: FactionsUUID 4.6.1 omits `CRAFTER` from protected container classification.
- Result: attacker opened a crafter in the verified victim claim and shift-clicked `27` netherite blocks.
- Victim storage: `27 -> 0`.
- Attacker inventory: `0 -> 27`.
- Exact exploit run: `30422169586`.
- Exploit artifact digest: `sha256:b321d162a6ee747f26e650010df63664bbc9c6a480e2db94338e32e7ae6a386b`.

### Enemy-claim decorated-pot projectile storage release

- Surface: FactionsUUID ignores projectile `EntityChangeBlockEvent` for decorated pots.
- Result: attacker-owned arrow changed the victim pot `DECORATED_POT -> AIR`; the event was not cancelled and the stored stack was released.
- Stored netherite released: `64` blocks.
- Exact exploit run: `30422566989`.
- Exploit artifact digest: `sha256:b7ef0c38a1da66315f809bb321203eb67b6683e89ba1bf8d7326fae5fc004547`.

## Proven Guard

Module: `phaselab-modern-container-guard`

Behavior:

- Adds `CRAFTER` and `DECORATED_POT` to FactionsUUID's runtime container cache and backing names.
- Cancels player-owned projectile destruction of non-empty decorated pots.

Exact guard regression:

- Commit: `9f2dd4d`
- Run: `30424355393`
- Claims verified: `true`
- Crafter theft: `rejected`; victim kept `27`, attacker got `0`.
- Pot theft: `rejected`; change event cancelled, pot kept `64`, zero drops.
- Artifact digest: `sha256:dd2f750f30b99484b388534b96f0ad05780c6491aa67a3b70f8165f64b3c7050`.
- Guard JAR SHA-256: `c5b20e2a56594660f79a54c53ba949ff91454b4e60705d61f775c654a05291c9`.

## Rejected or Low Impact on This Stack

- AuraSkills Treecapitator / Terraform enemy-claim block crossing: rejected.
- ExcellentEnchants Treefeller / Tunnel / Blast Mining enemy-claim crossing: rejected.
- Piston payload into victim claim: rejected after claim geometry correction.
- Cancelled end-portal creation dupe: rejected.
- Five-cycle AuraSkills brewing amplifier: rejected; five BrewEvents and fifteen extracted potions produced zero XP on the final take.
- Attacker hopper feeding victim chest: observed, but not theft or duplication.
- Cross-claim double-chest merge: rejected.

## Active Follow-ups

- Bamboo chest raft storage interaction, exact rerun with sneak-right-click.
- Mannequin equipment interaction in a victim claim.
- Server-created displacement phase matrix: wind charge, pose transition, dismount, and chunk rollback families.