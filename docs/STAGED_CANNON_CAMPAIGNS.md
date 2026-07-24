# CannonLab Staged Cannon Campaigns

Verified: 2026-07-24

## Purpose

`run-cannon-campaign.py` closes the gap between generating a schematic and spending minutes on full server tests.

The campaign order is fixed:

`verify exact candidate bytes -> deliver every .schem -> cheap static gates -> scenario truth gate -> bounded runtime survivors -> preserve all evidence`

A candidate is copied to the campaign output before the first test. Static or runtime failure never removes it. This means an operator can inspect or manually test the best failed candidate instead of receiving nothing after a long run.

## Modes

- `plan`: verify hashes, deliver candidates, materialize exact scenarios, and show every planned stage without executing tools.
- `static`: run schematic, EC160 alignment, and scenario-integrity gates only.
- `execute`: run static gates, build CannonLab once, then send only the highest-priority bounded survivors through real `cloud-smoke.sh` runtime stages.

## Identity contract

Every candidate requires an exact SHA-256. Runtime stages create a unique temporary `.schem.b64` fixture and scenario whose `cannon.file` points to the same exact candidate bytes. A repository-level runtime lock prevents two campaigns from sharing CannonLab's global `.cloud-lab` and `lab-artifacts` directories.

Temporary runtime assets and the lock are removed in `finally`, including failed runtime commands. Evidence is copied into the campaign output before cleanup.

## Fail-fast behavior

Required static failure stops later stages for that candidate. Other candidates continue.

`policy.max_runtime_candidates` limits expensive runtime testing. Candidates outside the budget remain delivered and are labeled `DELIVERED_RUNTIME_SKIPPED_BUDGET`; they are not mislabeled as physics failures.

Statuses include:

- `DELIVERED_PLAN`
- `DELIVERED_STATIC_FAIL`
- `DELIVERED_STATIC_PASS`
- `DELIVERED_RUNTIME_BLOCKED_BUILD`
- `DELIVERED_RUNTIME_SKIPPED_BUDGET`
- `DELIVERED_RUNTIME_FAIL`
- `DELIVERED_RUNTIME_PASS`

## Usage

Plan a campaign:

```powershell
python scripts/run-cannon-campaign.py `
  profiles/campaigns/my-campaign.json `
  --output-directory lab-artifacts/campaigns `
  --mode plan
```

Run static gates:

```powershell
python scripts/run-cannon-campaign.py `
  profiles/campaigns/my-campaign.json `
  --output-directory lab-artifacts/campaigns `
  --mode static
```

Run the bounded runtime campaign:

```powershell
python scripts/run-cannon-campaign.py `
  profiles/campaigns/my-campaign.json `
  --output-directory lab-artifacts/campaigns `
  --mode execute
```

Each campaign writes:

- `candidates/<id>.schem`, copied before testing;
- materialized scenario files with the exact runtime cannon filename;
- per-candidate runtime stdout, stderr, and copied CannonLab artifacts;
- `campaign-report.json` with every gate, command, status, winner, and truth boundary.

## Runtime configuration

Runtime stages use existing `cloud-smoke.sh` assertions. Additional environment entries must begin with `CANNONLAB_`, for example:

```json
{
  "CANNONLAB_STRICT_SINGLE_TNT": "false",
  "CANNONLAB_MIN_TNT_PER_SHOT": "4",
  "CANNONLAB_MIN_EXPLOSIONS_PER_SHOT": "4",
  "CANNONLAB_MIN_TARGET_PEAK_DESTROYED": "1"
}
```

The scenario remains the primary machine contract. Environment assertions add external evidence gates; they do not rewrite the candidate.

## Truth boundary

A static pass is not physics proof. A Paper or public Sakura runtime pass is not private ExtremeCraft parity. Campaign winners remain local runtime candidates until live EC canaries verify the relevant parity dimensions and exact field workflow.
