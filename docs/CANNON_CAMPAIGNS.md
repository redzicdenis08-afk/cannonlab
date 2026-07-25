# Staged cannon campaigns

CannonLab campaigns separate candidate delivery, cheap static rejection, bounded runtime testing and evidence preservation.

## Modes

- `plan`: validate the campaign and render the exact intended work without running static or runtime tests.
- `static`: deliver candidates and perform format, hash, EC160, placement and scenario-integrity gates.
- `execute`: run static gates, build the plugin once and test only the bounded runtime survivors.

Primary entry points:

- `scripts/run-cannon-campaign.py`
- `profiles/campaigns/staged-campaign-template-v1.json`
- `profiles/campaigns/module-proof-request-template-v1.json`
- `scripts/plan-cannon-module-campaign.py`

## Required properties

A campaign must:

- bind every candidate to an exact SHA-256;
- copy every verified candidate into the campaign output before testing;
- expose static, runtime-budget, build, runtime and promotion statuses separately;
- preserve stdout, stderr and CannonLab artifacts for failed candidates;
- use identical target, distance, bounds, regeneration and evidence contracts when ranking a family;
- stop downstream module composition when a dependency has not passed its requested evidence level;
- preserve public-Sakura and private-ExtremeCraft evidence labels separately.

## Truth boundary

A campaign plan is not a shot. Static survivors are not runtime winners. Local runtime winners are not private ExtremeCraft-ready. The campaign runner is a bounded evidence funnel, not a capability generator.