#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "knowledge" / "archetypes" / "registry.json"
DEFAULT_OUTPUT_ROOT = ROOT / "archetype-jobs"


class ArchetypeError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArchetypeError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ArchetypeError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArchetypeError(f"expected object in {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not slug:
        raise ArchetypeError("empty job name")
    return slug[:80]


def resolve_inside(path: str | Path, *, roots: Iterable[Path], must_exist: bool = True) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    allowed = [root.resolve() for root in roots]
    if not any(candidate.is_relative_to(root) for root in allowed):
        raise ArchetypeError(f"path escapes allowed roots: {path}")
    if must_exist and not candidate.exists():
        raise ArchetypeError(f"path does not exist: {candidate}")
    return candidate


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_registry(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != "cannonlab-archetype-registry-v1":
        raise ArchetypeError("unsupported archetype registry schema")
    archetypes = payload.get("archetypes")
    if not isinstance(archetypes, list) or not archetypes:
        raise ArchetypeError("archetype registry is empty")
    ids: set[str] = set()
    for index, archetype in enumerate(archetypes):
        if not isinstance(archetype, dict):
            raise ArchetypeError(f"archetypes[{index}] is not an object")
        archetype_id = str(archetype.get("id", "")).strip()
        if not archetype_id:
            raise ArchetypeError(f"archetypes[{index}] has no id")
        if archetype_id in ids:
            raise ArchetypeError(f"duplicate archetype id: {archetype_id}")
        ids.add(archetype_id)
    return payload


def archetype_by_id(registry: dict[str, Any], archetype_id: str) -> dict[str, Any]:
    for archetype in registry["archetypes"]:
        if archetype.get("id") == archetype_id:
            return archetype
    available = ", ".join(sorted(str(item.get("id")) for item in registry["archetypes"]))
    raise ArchetypeError(f"unknown archetype {archetype_id!r}; available: {available}")


@dataclass(frozen=True)
class CapabilityProbe:
    capability_id: str
    description: str
    status: str
    evidence: list[str]
    missing: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability_id,
            "description": self.description,
            "status": self.status,
            "evidence": self.evidence,
            "missing": self.missing,
        }


def file_contains(relative: str, *needles: str) -> tuple[bool, list[str]]:
    path = ROOT / relative
    if not path.is_file():
        return False, [f"missing:{relative}"]
    text = read_text(path)
    missing = [needle for needle in needles if needle not in text]
    return not missing, missing


def any_file_contains(relative: str, needles: Iterable[str]) -> tuple[bool, list[str]]:
    path = ROOT / relative
    if not path.is_file():
        return False, [f"missing:{relative}"]
    text = read_text(path)
    if any(needle in text for needle in needles):
        return True, []
    return False, [f"none-of:{','.join(needles)}"]


def capability_probe(
    capability_id: str,
    description: str,
    checks: list[tuple[str, bool, list[str]]],
    *,
    partial_ok: bool = False,
) -> CapabilityProbe:
    evidence = [label for label, passed, _ in checks if passed]
    missing: list[str] = []
    for label, passed, details in checks:
        if not passed:
            missing.append(label)
            missing.extend(details)
    if not missing:
        status = "PASS"
    elif partial_ok and evidence:
        status = "PARTIAL"
    else:
        status = "MISSING"
    return CapabilityProbe(capability_id, description, status, evidence, missing)


def audit_capabilities() -> dict[str, Any]:
    probes: list[CapabilityProbe] = []

    negative_test = (ROOT / "scripts" / "test-negative-litematic.py").is_file()
    signed_decode, signed_decode_missing = any_file_contains(
        "scripts/schem-audit.py",
        ["signed", "region minimum", "region_min", "min_corner", "negative"],
    )
    probes.append(capability_probe(
        "negative-litematic-coordinate-safety",
        "Negative signed Litematica regions decode without mirroring packed states.",
        [
            ("negative-litematic-regression-test", negative_test, [] if negative_test else ["scripts/test-negative-litematic.py"]),
            ("signed-region-decoder", signed_decode, signed_decode_missing),
        ],
        partial_ok=True,
    ))

    settle, settle_missing = file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java",
        "settleBeforeFillTicks",
        "fillToFireTicks",
    )
    controller_settle, controller_settle_missing = file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java",
        "settleBeforeFillTicks",
        "fillToFireTicks",
    )
    probes.append(capability_probe(
        "empty-settle-fill-fire",
        "Paste empty, settle, fill, delay, then fire.",
        [
            ("scenario-fields", settle, settle_missing),
            ("controller-implementation", controller_settle, controller_settle_missing),
        ],
        partial_ok=True,
    ))

    button_mode, button_missing = any_file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java",
        ["FireMode.BUTTON", "case BUTTON", "pressButton"],
    )
    probes.append(capability_probe(
        "native-button-fire",
        "Use the real button path instead of replacing nearby blocks with power sources.",
        [("button-fire-implementation", button_mode, button_missing)],
    ))

    scenario_mode_actions, scenario_mode_missing = any_file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java",
        ["preFireActions", "modeStates", "mode-states", "pre-fire-actions", "controlStates"],
    )
    controller_mode_actions, controller_mode_missing = any_file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java",
        ["preFireActions", "modeStates", "applyMode", "controlStates"],
    )
    probes.append(capability_probe(
        "explicit-pre-fire-mode-actions",
        "Apply and record exact lever/button mode states before filling and firing.",
        [
            ("scenario-mode-action-schema", scenario_mode_actions, scenario_mode_missing),
            ("controller-mode-action-application", controller_mode_actions, controller_mode_missing),
        ],
        partial_ok=True,
    ))

    causal_csv, causal_missing = file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/ShotRecorder.java",
        "causal-events.csv",
        "DISPENSE",
        "block_data=",
    )
    module_trace = (ROOT / "scripts" / "analyze-module-trace.py").is_file()
    probes.append(capability_probe(
        "dispenser-cohort-tracing",
        "Record exact dispenser ticks, positions, items and facing states for cohort fingerprints.",
        [
            ("causal-dispense-csv", causal_csv, causal_missing),
            ("module-trace-analyzer", module_trace, [] if module_trace else ["scripts/analyze-module-trace.py"]),
        ],
        partial_ok=True,
    ))

    entity_trace, entity_missing = file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/ShotRecorder.java",
        "entity_uuid",
        "vx,vy,vz",
        "fuse",
    )
    trajectory_compare = (ROOT / "scripts" / "compare-entity-trajectories.py").is_file()
    probes.append(capability_probe(
        "entity-trajectory-tracing",
        "Track TNT/falling entities per tick and compare trajectories.",
        [
            ("entity-telemetry", entity_trace, entity_missing),
            ("trajectory-comparator", trajectory_compare, [] if trajectory_compare else ["scripts/compare-entity-trajectories.py"]),
        ],
        partial_ok=True,
    ))

    acceptance_source = read_text(ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java")
    output_contract_needles = [
        "minLateralDisplacement",
        "min-lateral-displacement",
        "outputCorridor",
        "output-corridor",
        "dominantOutputDirection",
        "directionRepeatability",
    ]
    output_contract = any(needle in acceptance_source for needle in output_contract_needles)
    probes.append(capability_probe(
        "output-corridor-acceptance",
        "Fail or pass a worm/leftshoot based on stable directional output, not explosion count.",
        [("archetype-output-contract", output_contract, [] if output_contract else output_contract_needles)],
    ))

    forge_text = read_text(ROOT / "scripts" / "cannon-forge.py")
    archetype_payload = (
        "--archetype" in forge_text
        or "falling_payload_required" in forge_text
        or "payload-contract" in forge_text
    )
    hardcoded_payload = "acceptance_block(require_payload=True" in forge_text
    payload_ok = archetype_payload and not hardcoded_payload
    probes.append(capability_probe(
        "archetype-specific-payload-acceptance",
        "Allow TNT-only worm modes while requiring falling payload for sand/hybrid families.",
        [
            ("archetype-payload-selector", archetype_payload, [] if archetype_payload else ["no archetype payload selector in cannon-forge.py"]),
            ("no-global-falling-payload-assumption", not hardcoded_payload, [] if not hardcoded_payload else ["cannon-forge.py hardcodes require_payload=True"]),
        ],
        partial_ok=True,
    ))

    self_damage, self_damage_missing = file_contains(
        "src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java",
        "maxSelfDamageBlocks",
        "maxCannonMissingBlocks",
        "minRemainingDispenserRatio",
    )
    probes.append(capability_probe(
        "cannon-integrity-contract",
        "Measure self-damage, missing blocks and surviving dispenser ratio.",
        [("integrity-acceptance-fields", self_damage, self_damage_missing)],
    ))

    alignment = (ROOT / "scripts" / "paste-alignment-audit.py").is_file()
    probes.append(capability_probe(
        "ec160-all-offset-audit",
        "Scan all 256 X/Z offsets for per-chunk-column dispenser pressure.",
        [("paste-alignment-audit", alignment, [] if alignment else ["scripts/paste-alignment-audit.py"])],
    ))

    impulse_validator = (ROOT / "scripts" / "validate-cannon-architecture.py").is_file()
    impulse_policy = (ROOT / "policy" / "modern-cannon-architecture-policy.json").is_file()
    probes.append(capability_probe(
        "impulse-graph-policy",
        "Require an explicit multi-stage physical impulse graph before promotion.",
        [
            ("architecture-validator", impulse_validator, [] if impulse_validator else ["scripts/validate-cannon-architecture.py"]),
            ("architecture-policy", impulse_policy, [] if impulse_policy else ["policy/modern-cannon-architecture-policy.json"]),
        ],
        partial_ok=True,
    ))

    registry = (ROOT / "knowledge" / "source-registry.json").is_file()
    preservation = (ROOT / "scripts" / "cannon-preservation-check.py").is_file()
    probes.append(capability_probe(
        "reference-first-private-source-workflow",
        "Use exact hashes and preservation budgets without publishing private binaries.",
        [
            ("source-registry", registry, [] if registry else ["knowledge/source-registry.json"]),
            ("preservation-check", preservation, [] if preservation else ["scripts/cannon-preservation-check.py"]),
        ],
        partial_ok=True,
    ))

    result = {
        "schema": "cannonlab-archetype-capability-audit-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(probe.status == "PASS" for probe in probes) else "PARTIAL",
        "capabilities": [probe.as_dict() for probe in probes],
    }
    result["missing_capabilities"] = [
        probe.capability_id for probe in probes if probe.status != "PASS"
    ]
    return result


def capability_map(report: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("status"))
        for item in report.get("capabilities", [])
        if isinstance(item, dict)
    }


BASE_REQUIRED_CAPABILITIES = [
    "negative-litematic-coordinate-safety",
    "empty-settle-fill-fire",
    "native-button-fire",
    "dispenser-cohort-tracing",
    "entity-trajectory-tracing",
    "cannon-integrity-contract",
    "ec160-all-offset-audit",
    "reference-first-private-source-workflow",
]

PROMOTION_REQUIRED_CAPABILITIES = [
    "explicit-pre-fire-mode-actions",
    "output-corridor-acceptance",
    "archetype-specific-payload-acceptance",
    "impulse-graph-policy",
]


def lifecycle_rank(lifecycle: str) -> int:
    ranks = {
        "analysis-only": 0,
        "diagnostic-prototype": 1,
        "local-candidate": 2,
        "ec-ready": 3,
    }
    if lifecycle not in ranks:
        raise ArchetypeError(f"unsupported lifecycle: {lifecycle}")
    return ranks[lifecycle]


def ordered_stage_ids(archetype: dict[str, Any]) -> list[str]:
    stages = archetype.get("stage_contract") or []
    return [str(stage.get("id")) for stage in stages if isinstance(stage, dict) and stage.get("id")]


def architecture_template(archetype: dict[str, Any], lifecycle: str, reference_sha: str) -> dict[str, Any]:
    stages = []
    for raw in archetype.get("stage_contract") or []:
        if not isinstance(raw, dict):
            continue
        evidence = str(raw.get("role_evidence", "unknown"))
        role_status = "confirmed" if evidence in {"local-runtime", "field-verified"} else "hypothesis"
        stages.append({
            "id": raw.get("id"),
            "role": raw.get("role"),
            "role_evidence": "runtime" if evidence == "local-runtime" else "static" if evidence == "static-reference" else "unknown",
            "role_status": role_status,
            "runtime_evidence": "REQUIRED_PATH" if role_status == "confirmed" else "",
        })

    edges = []
    ids = [str(stage.get("id")) for stage in stages if stage.get("id")]
    for source, target in zip(ids, ids[1:]):
        edges.append({
            "from": source,
            "to": target,
            "mechanism": "unknown",
            "status": "hypothesis",
            "runtime_evidence": "REQUIRED_BEFORE_PROMOTION",
        })

    return {
        "schema": "cannonlab-architecture-manifest-v1",
        "intent": "modern-raid",
        "lifecycle": lifecycle,
        "source": {
            "mode": "reference-repair",
            "candidate": "REQUIRED_CANDIDATE_PATH",
            "candidate_sha256": "REQUIRED_CANDIDATE_SHA256",
            "references": [{"sha256": reference_sha, "path": "PRIVATE_REFERENCE_PATH"}],
        },
        "claims": [],
        "architecture": {
            "archetype": archetype.get("id"),
            "stages": stages,
            "impulse_edges": edges,
            "warning": "Sequential stages are listed, but edge mechanisms remain unknown until entity-level causal evidence proves them.",
        },
        "change_budget": {
            "declared_variable": "REQUIRED_SINGLE_CAUSAL_VARIABLE",
            "modules_touched": 1,
            "override_approved": False,
            "override_reason": "",
        },
        "runtime": {
            "native_redstone": True,
            "direct_dispense": False,
            "forced_velocity": False,
            "tnt_probe": False,
            "simulated_durability": False,
            "suppressed_paste_side_effects": False,
            "acceptance_report": "REQUIRED_FOR_LOCAL_CANDIDATE",
        },
        "extremecraft": {
            "field_verified": False,
            "live_canary_report": "REQUIRED_FOR_EC_READY",
        },
    }


def experiment_plan(archetype: dict[str, Any]) -> list[dict[str, Any]]:
    archetype_id = str(archetype.get("id"))
    common = [
        {
            "phase": 1,
            "name": "immutable-intake",
            "success": [
                "source hash matches an allowed private reference hash",
                "signed-region decode and block-entity placement pass",
                "all 256 chunk offsets are audited",
            ],
        },
        {
            "phase": 2,
            "name": "empty-settle-mode-fill-fire",
            "success": [
                "paste while dispensers are empty",
                "settle while empty",
                "apply and record exact mode states",
                "fill after settling",
                "fire through native control",
            ],
        },
        {
            "phase": 3,
            "name": "causal-fingerprint",
            "success": [
                "cohort timing and facing contract passes",
                "piston and motion events are mapped",
                "every major TNT cohort has trajectory telemetry",
            ],
        },
    ]
    if archetype_id == "rev-worm-383-v4":
        common.extend([
            {
                "phase": 4,
                "name": "output-corridor-discovery",
                "success": [
                    "one dominant output direction exists",
                    "a measurable TNT cohort exits the cannon corridor",
                    "the output does not return toward the cannon",
                    "direction and displacement repeat across at least five clean shots",
                ],
            },
            {
                "phase": 5,
                "name": "one-variable-trajectory-sweep",
                "success": [
                    "change only one mode/timing/alignment variable per family",
                    "untouched cohort fingerprint remains within contract",
                    "self-damage does not increase beyond the declared budget",
                ],
            },
            {
                "phase": 6,
                "name": "ec160-bank-redistribution",
                "success": [
                    "split one symmetric bank pair at a time",
                    "every X/Z chunk column is at or below 160 dispensers",
                    "cohort counts, facings and relative tick offsets remain intact",
                    "stable output corridor survives redistribution",
                ],
            },
            {
                "phase": 7,
                "name": "reduced-live-ec-canary",
                "success": [
                    "Sponge v2 DataVersion 3465 paste succeeds",
                    "real mode controls and button activate",
                    "reduced charge exits in the predicted direction",
                    "cannon survives",
                ],
            },
        ])
    else:
        common.append({
            "phase": 4,
            "name": "archetype-specific-output-contract",
            "success": list(archetype.get("required_runtime_metrics") or archetype.get("required_features") or []),
        })
    return common


def build_plan(
    registry: dict[str, Any],
    archetype: dict[str, Any],
    lifecycle: str,
    reference_sha: str,
    capability_report: dict[str, Any],
    *,
    field_canary_report: Path | None,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    known_hashes = {str(value).lower() for value in archetype.get("reference_hashes") or []}
    if known_hashes and reference_sha.lower() not in known_hashes:
        blockers.append({
            "code": "reference-hash-mismatch",
            "message": f"reference hash {reference_sha} is not registered for {archetype.get('id')}",
        })
    if not reference_sha:
        blockers.append({"code": "missing-reference-hash", "message": "an exact reference hash is mandatory"})

    capability_status = capability_map(capability_report)
    required = list(BASE_REQUIRED_CAPABILITIES)
    if lifecycle_rank(lifecycle) >= lifecycle_rank("local-candidate"):
        required.extend(PROMOTION_REQUIRED_CAPABILITIES)
    for capability_id in required:
        if capability_status.get(capability_id) != "PASS":
            blockers.append({
                "code": "missing-capability",
                "message": f"{capability_id} is {capability_status.get(capability_id, 'UNKNOWN')}",
            })

    ceiling = str(archetype.get("promotion_ceiling", "analysis-only"))
    if lifecycle_rank(lifecycle) > lifecycle_rank(ceiling if ceiling in {"analysis-only", "diagnostic-prototype", "local-candidate", "ec-ready"} else "diagnostic-prototype"):
        blockers.append({
            "code": "archetype-evidence-ceiling",
            "message": f"requested lifecycle {lifecycle} exceeds current archetype ceiling {ceiling}: {archetype.get('promotion_ceiling_reason', '')}",
        })

    if lifecycle == "ec-ready":
        if field_canary_report is None:
            blockers.append({"code": "missing-live-ec-canary", "message": "EC-ready requires a live canary report"})
        else:
            try:
                canary = load_json(field_canary_report)
            except ArchetypeError as exc:
                blockers.append({"code": "invalid-live-ec-canary", "message": str(exc)})
            else:
                if str(canary.get("status", "")).upper() != "PASS" or canary.get("field_verified") is not True:
                    blockers.append({"code": "failed-live-ec-canary", "message": "live canary must PASS with field_verified=true"})

    if lifecycle == "diagnostic-prototype":
        warnings.append({
            "code": "diagnostic-only",
            "message": "A PASS plan authorizes experiments only. It does not authorize a working, one-shot or EC-ready claim.",
        })

    return {
        "schema": "cannonlab-archetype-plan-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "archetype": archetype,
        "requested_lifecycle": lifecycle,
        "reference_sha256": reference_sha,
        "blockers": blockers,
        "warnings": warnings,
        "capability_audit": capability_report,
        "architecture_manifest_template": architecture_template(archetype, lifecycle, reference_sha),
        "experiment_plan": experiment_plan(archetype),
        "truth_boundary": registry.get("truth_boundary"),
    }


def plan_markdown(plan: dict[str, Any]) -> str:
    archetype = plan["archetype"]
    lines = [
        f"# {archetype.get('title', archetype.get('id'))}",
        "",
        f"Gate: **{plan['status']}**",
        "",
        f"Requested lifecycle: `{plan['requested_lifecycle']}`",
        "",
        f"Reference SHA-256: `{plan['reference_sha256']}`",
        "",
        "## Truth boundary",
        "",
        str(plan.get("truth_boundary", "")),
        "",
    ]
    if plan["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- `{item['code']}`: {item['message']}" for item in plan["blockers"])
        lines.append("")
    lines.extend(["## Experiment phases", ""])
    for phase in plan["experiment_plan"]:
        lines.append(f"### {phase['phase']}. {phase['name']}")
        lines.append("")
        lines.extend(f"- {item}" for item in phase.get("success", []))
        lines.append("")
    lines.extend([
        "## Hard rule",
        "",
        "Do not generate a blank-canvas modern cannon from this plan. Start from the exact private reference, preserve its causal interfaces, and mutate one proved variable at a time.",
        "",
    ])
    return "\n".join(lines)


def extract_facing(details: str) -> str:
    match = re.search(r"(?:^|[,\[])facing=([a-z_]+)", details.lower())
    return match.group(1) if match else "unknown"


def load_dispense_cohorts(path: Path) -> dict[int, dict[str, Any]]:
    cohorts: dict[int, dict[str, Any]] = defaultdict(lambda: {"count": 0, "facings": Counter()})
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"tick", "event", "item", "details"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ArchetypeError(f"causal CSV missing columns: {sorted(required - set(reader.fieldnames or []))}")
        for row in reader:
            if row.get("event") != "DISPENSE":
                continue
            item = str(row.get("item", "")).upper()
            if item not in {"TNT", "MINECART_TNT", "TNT_MINECART"}:
                continue
            try:
                tick = int(float(str(row.get("tick", "0"))))
            except ValueError:
                continue
            cohort = cohorts[tick]
            cohort["count"] += 1
            cohort["facings"][extract_facing(str(row.get("details", "")))] += 1
    return {
        tick: {"count": value["count"], "facings": dict(value["facings"])}
        for tick, value in cohorts.items()
    }


def score_cohort(actual: dict[str, Any], expected: dict[str, Any]) -> int:
    score = abs(int(actual.get("count", 0)) - int(expected.get("count", 0)))
    actual_facings = actual.get("facings") or {}
    expected_facings = expected.get("facing_counts") or {}
    for facing in set(actual_facings) | set(expected_facings):
        if facing == "unknown" and facing not in expected_facings:
            continue
        score += abs(int(actual_facings.get(facing, 0)) - int(expected_facings.get(facing, 0)))
    return score


def verify_cohorts(archetype: dict[str, Any], causal_csv: Path, tick_tolerance: int, count_tolerance: int) -> dict[str, Any]:
    contract = archetype.get("cohort_contract")
    if not isinstance(contract, dict):
        raise ArchetypeError(f"archetype {archetype.get('id')} has no cohort contract")
    expected = contract.get("cohorts")
    if not isinstance(expected, list) or not expected:
        raise ArchetypeError("cohort contract is empty")
    actual = load_dispense_cohorts(causal_csv)
    if not actual:
        return {
            "schema": "cannonlab-archetype-cohort-verdict-v1",
            "status": "FAIL",
            "archetype": archetype.get("id"),
            "causal_csv": str(causal_csv),
            "reason": "no TNT dispense events",
        }

    anchor_candidates = sorted(actual)
    best: dict[str, Any] | None = None
    for anchor_tick in anchor_candidates:
        matches = []
        total_score = 0
        for expected_cohort in expected:
            target_tick = anchor_tick + int(expected_cohort.get("tick_offset", 0))
            nearby = [tick for tick in actual if abs(tick - target_tick) <= tick_tolerance]
            if not nearby:
                match = {
                    "id": expected_cohort.get("id"),
                    "expected_tick": target_tick,
                    "actual_tick": None,
                    "expected": expected_cohort,
                    "actual": {"count": 0, "facings": {}},
                    "score": 10_000,
                }
            else:
                chosen = min(nearby, key=lambda tick: (score_cohort(actual[tick], expected_cohort), abs(tick - target_tick), tick))
                match = {
                    "id": expected_cohort.get("id"),
                    "expected_tick": target_tick,
                    "actual_tick": chosen,
                    "expected": expected_cohort,
                    "actual": actual[chosen],
                    "score": score_cohort(actual[chosen], expected_cohort),
                }
            total_score += int(match["score"])
            matches.append(match)
        candidate = {"anchor_tick": anchor_tick, "score": total_score, "matches": matches}
        if best is None or (candidate["score"], candidate["anchor_tick"]) < (best["score"], best["anchor_tick"]):
            best = candidate

    assert best is not None
    failures = []
    for match in best["matches"]:
        if match["actual_tick"] is None:
            failures.append(f"missing cohort {match['id']}")
            continue
        expected_count = int(match["expected"].get("count", 0))
        actual_count = int(match["actual"].get("count", 0))
        if abs(actual_count - expected_count) > count_tolerance:
            failures.append(f"{match['id']} count {actual_count} != {expected_count}±{count_tolerance}")
        for facing, expected_count_facing in (match["expected"].get("facing_counts") or {}).items():
            actual_count_facing = int((match["actual"].get("facings") or {}).get(facing, 0))
            if abs(actual_count_facing - int(expected_count_facing)) > count_tolerance:
                failures.append(
                    f"{match['id']} facing {facing} {actual_count_facing} != {expected_count_facing}±{count_tolerance}"
                )

    return {
        "schema": "cannonlab-archetype-cohort-verdict-v1",
        "status": "PASS" if not failures else "FAIL",
        "archetype": archetype.get("id"),
        "causal_csv": str(causal_csv),
        "causal_csv_sha256": sha256(causal_csv),
        "tick_tolerance": tick_tolerance,
        "count_tolerance": count_tolerance,
        "best_match": best,
        "failures": failures,
        "truth_boundary": "A PASS proves the registered dispenser activation fingerprint only. It does not prove a clean worm, wall contact or ExtremeCraft readiness.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence-first CannonLab archetype planner and cohort verifier")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered cannon archetypes")

    inspect_parser = subparsers.add_parser("inspect", help="Print one archetype contract")
    inspect_parser.add_argument("archetype")

    audit_parser = subparsers.add_parser("audit", help="Audit CannonLab capabilities needed by archetypes")
    audit_parser.add_argument("--archetype", default="")
    audit_parser.add_argument("--json-out", default="")

    plan_parser = subparsers.add_parser("plan", help="Create a fail-closed reconstruction plan")
    plan_parser.add_argument("archetype")
    plan_parser.add_argument("--reference-sha", required=True)
    plan_parser.add_argument(
        "--lifecycle",
        choices=["analysis-only", "diagnostic-prototype", "local-candidate", "ec-ready"],
        default="diagnostic-prototype",
    )
    plan_parser.add_argument("--job", default="")
    plan_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    plan_parser.add_argument("--field-canary-report", default="")

    cohort_parser = subparsers.add_parser("verify-cohorts", help="Verify a causal-events.csv against an archetype fingerprint")
    cohort_parser.add_argument("archetype")
    cohort_parser.add_argument("causal_csv")
    cohort_parser.add_argument("--tick-tolerance", type=int, default=0)
    cohort_parser.add_argument("--count-tolerance", type=int, default=0)
    cohort_parser.add_argument("--json-out", default="")

    args = parser.parse_args()
    registry_path = resolve_inside(args.registry, roots=[ROOT], must_exist=True)
    registry = load_registry(registry_path)

    if args.command == "list":
        print(json.dumps({
            "schema": registry["schema"],
            "truth_boundary": registry.get("truth_boundary"),
            "archetypes": [
                {
                    "id": item.get("id"),
                    "family": item.get("family"),
                    "status": item.get("status"),
                    "promotion_ceiling": item.get("promotion_ceiling"),
                }
                for item in registry["archetypes"]
            ],
        }, indent=2))
        return

    archetype = archetype_by_id(registry, args.archetype) if getattr(args, "archetype", "") else None

    if args.command == "inspect":
        print(json.dumps(archetype, indent=2))
        return

    if args.command == "audit":
        report = audit_capabilities()
        if archetype is not None:
            status_map = capability_map(report)
            report["archetype"] = archetype.get("id")
            report["base_ready"] = all(status_map.get(item) == "PASS" for item in BASE_REQUIRED_CAPABILITIES)
            report["promotion_ready"] = all(
                status_map.get(item) == "PASS"
                for item in BASE_REQUIRED_CAPABILITIES + PROMOTION_REQUIRED_CAPABILITIES
            )
        if args.json_out:
            out = resolve_inside(args.json_out, roots=[ROOT], must_exist=False)
            write_json(out, report)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report.get("status") == "PASS" else 2)

    if args.command == "plan":
        report = audit_capabilities()
        field_canary = (
            resolve_inside(args.field_canary_report, roots=[ROOT, ROOT.parents[1] / "output"], must_exist=True)
            if args.field_canary_report
            else None
        )
        plan = build_plan(
            registry,
            archetype,
            args.lifecycle,
            args.reference_sha,
            report,
            field_canary_report=field_canary,
        )
        output_root = resolve_inside(args.output_dir, roots=[ROOT], must_exist=False)
        job = slugify(args.job or f"{args.archetype}-{args.lifecycle}")
        job_dir = output_root / job
        job_dir.mkdir(parents=True, exist_ok=True)
        write_json(job_dir / "plan.json", plan)
        write_json(job_dir / "architecture-manifest.template.json", plan["architecture_manifest_template"])
        (job_dir / "PLAN.md").write_text(plan_markdown(plan), encoding="utf-8", newline="\n")
        result = {
            "status": plan["status"],
            "job_dir": str(job_dir.relative_to(ROOT)),
            "blockers": plan["blockers"],
            "promotion_ceiling": archetype.get("promotion_ceiling"),
        }
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if plan["status"] == "PASS" else 2)

    if args.command == "verify-cohorts":
        if args.tick_tolerance < 0 or args.count_tolerance < 0:
            parser.error("tolerances must be non-negative")
        causal_csv = resolve_inside(args.causal_csv, roots=[ROOT, ROOT.parents[1] / "output"], must_exist=True)
        verdict = verify_cohorts(archetype, causal_csv, args.tick_tolerance, args.count_tolerance)
        if args.json_out:
            out = resolve_inside(args.json_out, roots=[ROOT, ROOT.parents[1] / "output"], must_exist=False)
            write_json(out, verdict)
        print(json.dumps(verdict, indent=2))
        raise SystemExit(0 if verdict["status"] == "PASS" else 2)


if __name__ == "__main__":
    try:
        main()
    except ArchetypeError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2))
        raise SystemExit(2)
