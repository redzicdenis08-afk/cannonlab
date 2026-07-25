#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"unable to read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanError(f"expected JSON object in {path}")
    return payload


def build_plan(
    public_contract: dict[str, Any],
    private_contract: dict[str, Any],
    priority_catalog: dict[str, Any],
    maximum_risk: str | None = None,
) -> dict[str, Any]:
    if public_contract.get("id") != "sakura-26.1.2-cannon-contract":
        raise PlanError("unexpected public Sakura contract")
    if private_contract.get("id") != "extremecraft-private-parity-required-v1":
        raise PlanError("unexpected private parity contract")
    if priority_catalog.get("id") != "extremecraft-parity-probe-priorities-v1":
        raise PlanError("unexpected priority catalog")

    dimensions = {row["id"]: row for row in private_contract.get("dimensions", [])}
    catalog_rows = priority_catalog.get("probes", [])
    catalog_ids = [row["dimension"] for row in catalog_rows]
    if len(catalog_ids) != len(set(catalog_ids)):
        raise PlanError("duplicate catalog dimensions")
    missing = sorted(set(dimensions) - set(catalog_ids))
    unknown = sorted(set(catalog_ids) - set(dimensions))
    if missing or unknown:
        raise PlanError(f"catalog mismatch missing={missing} unknown={unknown}")

    risk_order = {
        "safe": 0,
        "safe-bounded": 1,
        "safe-calibration": 1,
        "field-operational": 2,
        "controlled-destructive": 3,
        "advanced-destructive": 4,
    }
    risk_limit = risk_order.get(maximum_risk, 99) if maximum_risk else 99
    stages: list[dict[str, Any]] = []
    for row in sorted(catalog_rows, key=lambda item: (-int(item["priority"]), item["dimension"])):
        dimension = dimensions[row["dimension"]]
        current_status = str(dimension.get("status", "unknown"))
        within_risk = risk_order.get(str(row["risk"]), 99) <= risk_limit
        stages.append({
            "order": len(stages) + 1,
            "dimension": row["dimension"],
            "priority": int(row["priority"]),
            "phase": row["phase"],
            "risk": row["risk"],
            "status": current_status,
            "action": "MEASURE" if within_risk and current_status not in {"measured", "field-verified"} else (
                "REUSE_EVIDENCE" if current_status in {"measured", "field-verified"} else "DEFER_RISK"
            ),
            "public_reference": {
                "contract": public_contract["id"],
                "probe": row["public_probe"],
                "baseline": row["public_baseline"],
            },
            "field_canary": dimension.get("canary"),
            "hypotheses": dimension.get("hypotheses", []),
            "required_evidence": dimension.get("required_evidence", []),
            "minimum_repeats": max(
                int(row.get("minimum_repeats", 1)),
                int(private_contract.get("promotion_gate", {}).get("minimum_repeat_count_per_stochastic_dimension", 1))
                if row["dimension"] in {
                    "tnt.spawn.horizontal_kick",
                    "tnt.fuse.distribution",
                    "redstone.dispenser.activation_order",
                }
                else int(row.get("minimum_repeats", 1)),
            ),
            "paired_comparison": row["paired_comparison"],
            "promotion_gate": {
                "raw_trace": True,
                "fixture_hash": True,
                "local_replay": True,
                "server_date": True,
            },
        })

    return {
        "schema_version": 1,
        "id": "cannon-parity-campaign-plan-v1",
        "public_contract": public_contract["id"],
        "private_contract": private_contract["id"],
        "stage_count": len(stages),
        "measure_now_count": sum(row["action"] == "MEASURE" for row in stages),
        "deferred_count": sum(row["action"] == "DEFER_RISK" for row in stages),
        "stages": stages,
        "truth_boundary": {
            "plan_is_measurement": False,
            "public_reference_is_private_parity": False,
            "completed_single_probe_proves_full_parity": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan paired public-Sakura and private-server parity probes.")
    parser.add_argument("public_contract", type=Path)
    parser.add_argument("private_contract", type=Path)
    parser.add_argument("priority_catalog", type=Path)
    parser.add_argument("--maximum-risk", choices=[
        "safe", "safe-bounded", "safe-calibration", "field-operational", "controlled-destructive", "advanced-destructive"
    ])
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_plan(
        read_object(args.public_contract),
        read_object(args.private_contract),
        read_object(args.priority_catalog),
        args.maximum_risk,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
