#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
DEFAULT_OUTPUT_ROOT = WORKSPACE_ROOT / "output"
DEFAULT_POLICY = ROOT / "policy" / "modern-cannon-architecture-policy.json"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ManifestError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ManifestError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"expected JSON object in {path}")
    return payload


def report_pass(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "")).upper()
    if status == "PASS":
        return True
    for key in (
        "passed",
        "contract_pass",
        "contract_passed",
        "acceptance_contract_pass",
        "one_shot_contract_pass",
    ):
        if payload.get(key) is True:
            return True
    return False


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def resolve_path(
    raw: Any,
    *,
    repo_root: Path,
    output_root: Path,
    label: str,
    required: bool,
    errors: list[dict[str, str]],
) -> Path | None:
    if raw is None or raw == "":
        if required:
            errors.append({"code": "missing_evidence_path", "message": f"{label} is required"})
        return None
    if not isinstance(raw, str):
        errors.append({"code": "invalid_evidence_path", "message": f"{label} must be a string path"})
        return None

    path = Path(raw)
    if not path.is_absolute():
        if path.parts and path.parts[0].lower() == "output":
            path = output_root.parent / path
        else:
            path = repo_root / path
    path = path.resolve()

    allowed = (repo_root.resolve(), output_root.resolve())
    if not any(path == root or path.is_relative_to(root) for root in allowed):
        errors.append(
            {
                "code": "evidence_path_escape",
                "message": f"{label} escapes CannonLab repository/output roots: {raw}",
            }
        )
        return None
    if not path.is_file():
        errors.append({"code": "missing_evidence_file", "message": f"{label} does not exist: {path}"})
        return None
    return path


def load_evidence_report(
    raw: Any,
    *,
    repo_root: Path,
    output_root: Path,
    label: str,
    required: bool,
    errors: list[dict[str, str]],
) -> tuple[Path | None, dict[str, Any] | None]:
    path = resolve_path(
        raw,
        repo_root=repo_root,
        output_root=output_root,
        label=label,
        required=required,
        errors=errors,
    )
    if path is None:
        return None, None
    try:
        return path, read_json(path)
    except ManifestError as exc:
        errors.append({"code": "invalid_evidence_json", "message": f"{label}: {exc}"})
        return path, None


def validate_manifest(
    manifest: dict[str, Any],
    policy: dict[str, Any],
    *,
    repo_root: Path,
    output_root: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    def fail(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if manifest.get("schema") != "cannonlab-architecture-manifest-v1":
        fail("unsupported_manifest_schema", "manifest.schema must be cannonlab-architecture-manifest-v1")

    if policy.get("schema") != "cannonlab-modern-architecture-policy-v1":
        raise ManifestError("unsupported policy schema")

    rules = as_dict(policy.get("rules"))
    candidate = as_dict(manifest.get("candidate"))
    source = as_dict(manifest.get("source"))
    architecture = as_dict(manifest.get("architecture"))
    runtime = as_dict(manifest.get("runtime"))
    ec = as_dict(manifest.get("extremecraft"))
    change_budget = as_dict(manifest.get("change_budget"))

    intent = str(candidate.get("intent", ""))
    lifecycle = str(candidate.get("lifecycle", ""))
    claims = [str(item) for item in as_list(candidate.get("claims"))]
    source_mode = str(source.get("mode", ""))

    allowed_intents = set(map(str, as_list(policy.get("allowed_intents"))))
    allowed_lifecycles = list(map(str, as_list(policy.get("allowed_lifecycles"))))
    allowed_source_modes = set(map(str, as_list(policy.get("allowed_source_modes"))))
    allowed_claims = set(map(str, as_list(policy.get("allowed_claims"))))
    lifecycle_rank = {name: index for index, name in enumerate(allowed_lifecycles)}

    if intent not in allowed_intents:
        fail("invalid_intent", f"candidate.intent must be one of {sorted(allowed_intents)}")
    if lifecycle not in lifecycle_rank:
        fail("invalid_lifecycle", f"candidate.lifecycle must be one of {allowed_lifecycles}")
    if source_mode not in allowed_source_modes:
        fail("invalid_source_mode", f"source.mode must be one of {sorted(allowed_source_modes)}")
    invalid_claims = sorted(set(claims) - allowed_claims)
    if invalid_claims:
        fail("invalid_claims", f"unsupported candidate claims: {invalid_claims}")

    candidate_path = resolve_path(
        candidate.get("file"),
        repo_root=repo_root,
        output_root=output_root,
        label="candidate.file",
        required=True,
        errors=errors,
    )
    check("candidate-file", candidate_path is not None, "candidate file exists inside an allowed root")

    is_modern = intent == "modern-raid"
    is_diagnostic = intent == "diagnostic-prototype" or lifecycle == "diagnostic-prototype"
    local_rank = lifecycle_rank.get("local-candidate", 2)
    current_rank = lifecycle_rank.get(lifecycle, -1)
    promoted_local = current_rank >= local_rank

    if is_diagnostic:
        if lifecycle != "diagnostic-prototype":
            fail("diagnostic_lifecycle_mismatch", "diagnostic-prototype intent must use diagnostic-prototype lifecycle")
        non_diagnostic_claims = sorted(set(claims) - {"diagnostic"})
        if non_diagnostic_claims:
            fail(
                "diagnostic_claim_inflation",
                f"diagnostic prototypes may claim only diagnostic, not {non_diagnostic_claims}",
            )

    reference_hashes = [str(item) for item in as_list(source.get("reference_sha256"))]
    bad_hashes = [value for value in reference_hashes if not SHA256_RE.fullmatch(value)]
    if bad_hashes:
        fail("invalid_reference_hash", "every source.reference_sha256 value must be a 64-character hex digest")

    if is_modern and rules.get("modern_raid_requires_reference", True) and not reference_hashes:
        fail("modern_raid_missing_reference", "modern-raid candidates require at least one exact reference SHA-256")
    if is_modern and rules.get("modern_raid_forbids_from_scratch", True) and source_mode == "from-scratch":
        fail("modern_raid_from_scratch_forbidden", "from-scratch geometry cannot be labeled modern-raid")
    check(
        "reference-first",
        (not is_modern) or (bool(reference_hashes) and source_mode in {"reference-repair", "bounded-variant"}),
        "modern raid work begins from an exact decoded reference",
    )

    geometry_required = is_modern and bool(rules.get("modern_raid_requires_geometry_profile_pass", True))
    geometry_path, geometry_report = load_evidence_report(
        source.get("geometry_profile"),
        repo_root=repo_root,
        output_root=output_root,
        label="source.geometry_profile",
        required=geometry_required,
        errors=errors,
    )
    geometry_pass = geometry_report is not None and report_pass(geometry_report)
    morphology_verdict = ""
    if geometry_report is not None:
        morphology_verdict = str(
            as_dict(as_dict(geometry_report.get("candidate")).get("modern_raid_morphology")).get("verdict", "")
        ).upper()
    morphology_pass = morphology_verdict == "PASS"
    if geometry_required and geometry_report is not None and not geometry_pass:
        fail("geometry_profile_failed", "modern-raid geometry profile did not pass")
    if is_modern and rules.get("modern_raid_requires_morphology_pass", True) and geometry_report is not None and not morphology_pass:
        fail("flat_morphology_rejected", "modern-raid candidate failed the three-dimensional anti-pancake morphology gate")
    check("geometry-profile", (not geometry_required) or geometry_pass, f"geometry profile: {geometry_path}")
    check("anti-pancake-morphology", (not is_modern) or morphology_pass, f"morphology verdict={morphology_verdict or 'missing'}")

    preservation_required = is_modern and bool(rules.get("modern_raid_requires_preservation_pass", True))
    preservation_path, preservation_report = load_evidence_report(
        source.get("preservation_report"),
        repo_root=repo_root,
        output_root=output_root,
        label="source.preservation_report",
        required=preservation_required,
        errors=errors,
    )
    preservation_pass = preservation_report is not None and report_pass(preservation_report)
    if preservation_required and preservation_report is not None and not preservation_pass:
        fail("preservation_failed", "reference preservation report did not pass")
    check("reference-preservation", (not preservation_required) or preservation_pass, f"preservation report: {preservation_path}")

    stages = as_list(architecture.get("stages"))
    edges = as_list(architecture.get("impulse_edges"))
    min_stages = int(rules.get("minimum_stages", 2))
    min_edges = int(rules.get("minimum_impulse_edges", 1))
    requires_impulse_model = intent in {"modern-raid", "diagnostic-prototype"}
    if requires_impulse_model and len(stages) < min_stages:
        fail("insufficient_architecture_stages", f"architecture requires at least {min_stages} stages")
    if requires_impulse_model and len(edges) < min_edges:
        fail("insufficient_impulse_edges", f"architecture requires at least {min_edges} physical impulse edges")

    allowed_role_evidence = set(map(str, as_list(policy.get("allowed_role_evidence"))))
    allowed_role_status = set(map(str, as_list(policy.get("allowed_role_status"))))
    stage_ids: list[str] = []
    for index, raw_stage in enumerate(stages):
        if not isinstance(raw_stage, dict):
            fail("invalid_stage", f"architecture.stages[{index}] must be an object")
            continue
        stage_id = str(raw_stage.get("id", "")).strip()
        if not stage_id:
            fail("missing_stage_id", f"architecture.stages[{index}] has no id")
            continue
        if stage_id in stage_ids:
            fail("duplicate_stage_id", f"duplicate stage id: {stage_id}")
        stage_ids.append(stage_id)

        role_evidence = str(raw_stage.get("role_evidence", "unknown"))
        role_status = str(raw_stage.get("role_status", "unknown"))
        if role_evidence not in allowed_role_evidence:
            fail("invalid_role_evidence", f"stage {stage_id} has unsupported role_evidence={role_evidence}")
        if role_status not in allowed_role_status:
            fail("invalid_role_status", f"stage {stage_id} has unsupported role_status={role_status}")
        if (
            rules.get("confirmed_role_requires_runtime_or_field", True)
            and role_status == "confirmed"
            and role_evidence not in {"runtime", "field"}
        ):
            fail(
                "static_role_promotion_forbidden",
                f"stage {stage_id} is confirmed from {role_evidence}; confirmed roles require runtime or field evidence",
            )
        if role_status == "confirmed" and role_evidence in {"runtime", "field"}:
            resolve_path(
                raw_stage.get("runtime_evidence"),
                repo_root=repo_root,
                output_root=output_root,
                label=f"stage {stage_id} runtime_evidence",
                required=True,
                errors=errors,
            )

    allowed_mechanisms = set(map(str, as_list(policy.get("allowed_edge_mechanisms"))))
    allowed_edge_status = set(map(str, as_list(policy.get("allowed_edge_status"))))
    explosion_push_count = 0
    verified_edges = 0
    for index, raw_edge in enumerate(edges):
        if not isinstance(raw_edge, dict):
            fail("invalid_impulse_edge", f"architecture.impulse_edges[{index}] must be an object")
            continue
        source_id = str(raw_edge.get("from", "")).strip()
        target_id = str(raw_edge.get("to", "")).strip()
        mechanism = str(raw_edge.get("mechanism", "unknown"))
        status = str(raw_edge.get("status", "unknown"))
        if source_id not in stage_ids:
            fail("unknown_edge_source", f"impulse edge {index} references unknown source stage {source_id!r}")
        if target_id not in stage_ids:
            fail("unknown_edge_target", f"impulse edge {index} references unknown target stage {target_id!r}")
        if source_id and source_id == target_id:
            fail("self_impulse_edge", f"impulse edge {index} cannot push a stage into itself")
        if mechanism not in allowed_mechanisms:
            fail("invalid_edge_mechanism", f"impulse edge {index} has unsupported mechanism={mechanism}")
        if status not in allowed_edge_status:
            fail("invalid_edge_status", f"impulse edge {index} has unsupported status={status}")
        if mechanism == "explosion-push":
            explosion_push_count += 1
        if status == "verified":
            verified_edges += 1
        if promoted_local:
            if rules.get("local_candidate_requires_verified_edges", True) and status != "verified":
                fail("unverified_promoted_edge", f"promoted candidate edge {source_id}->{target_id} is not verified")
            if mechanism == "unknown":
                fail("unknown_promoted_mechanism", f"promoted candidate edge {source_id}->{target_id} has unknown mechanism")
            resolve_path(
                raw_edge.get("runtime_evidence"),
                repo_root=repo_root,
                output_root=output_root,
                label=f"impulse edge {source_id}->{target_id} runtime_evidence",
                required=True,
                errors=errors,
            )

    if is_modern and rules.get("require_explosion_push_edge", True) and explosion_push_count < 1:
        fail("missing_explosion_push", "modern-raid architecture must identify at least one TNT explosion-push edge")
    check(
        "impulse-chain",
        (not requires_impulse_model) or (len(stages) >= min_stages and len(edges) >= min_edges),
        f"stages={len(stages)} edges={len(edges)} required={requires_impulse_model}",
    )
    check("explosion-push", (not is_modern) or explosion_push_count >= 1, f"explosion-push edges={explosion_push_count}")
    check("promoted-edge-evidence", (not promoted_local) or verified_edges == len(edges), f"verified edges={verified_edges}/{len(edges)}")

    declared_variable = str(change_budget.get("declared_variable", "")).strip()
    modules_touched_raw = change_budget.get("modules_touched", 0)
    try:
        modules_touched = int(modules_touched_raw)
    except (TypeError, ValueError):
        modules_touched = -1
        fail("invalid_modules_touched", "change_budget.modules_touched must be a non-negative integer")
    if modules_touched < 0:
        fail("invalid_modules_touched", "change_budget.modules_touched must be a non-negative integer")
    if is_modern and not declared_variable:
        fail("undeclared_change_variable", "modern-raid repair must declare the one causal variable being changed")
    max_modules = int(rules.get("default_max_modules_touched", 1))
    if modules_touched > max_modules and rules.get("multi_module_change_requires_override", True):
        override = change_budget.get("override_approved") is True
        reason = str(change_budget.get("override_reason", "")).strip()
        if not override or not reason:
            fail(
                "unbounded_multi_module_change",
                f"touching {modules_touched} modules exceeds the default budget of {max_modules} without an approved reason",
            )
        else:
            warn("multi_module_override", f"approved broad edit touches {modules_touched} modules: {reason}")
    check("bounded-change", modules_touched <= max_modules or change_budget.get("override_approved") is True, f"modules touched={modules_touched}")

    acceptance_required = promoted_local or bool(set(claims) & set(map(str, as_list(policy.get("promotion_claims")))))
    acceptance_path, acceptance_report = load_evidence_report(
        runtime.get("acceptance_report"),
        repo_root=repo_root,
        output_root=output_root,
        label="runtime.acceptance_report",
        required=acceptance_required,
        errors=errors,
    )
    acceptance_pass = acceptance_report is not None and report_pass(acceptance_report)
    if acceptance_required and acceptance_report is not None and not acceptance_pass:
        fail("acceptance_failed", "runtime acceptance report did not pass")

    if promoted_local:
        if rules.get("local_candidate_requires_native_redstone", True) and runtime.get("native_redstone") is not True:
            fail("native_redstone_required", "local candidates must fire through their real native-redstone control path")
        assists = {
            "direct_dispense": rules.get("local_candidate_forbids_direct_dispense", True),
            "forced_velocity": rules.get("local_candidate_forbids_forced_velocity", True),
            "tnt_probe": rules.get("local_candidate_forbids_tnt_probe", True),
            "simulated_durability": rules.get("local_candidate_forbids_simulated_durability", True),
            "suppressed_paste_side_effects": rules.get(
                "local_candidate_forbids_suppressed_paste_side_effects", True
            ),
        }
        for key, forbidden in assists.items():
            if forbidden and runtime.get(key) is True:
                fail("diagnostic_assist_promotion", f"{key} is diagnostic-only and cannot promote a local candidate")
        if rules.get("local_candidate_requires_acceptance_pass", True) and not acceptance_pass:
            fail("acceptance_required", "local candidate requires a passing runtime acceptance report")
    check("native-redstone", (not promoted_local) or runtime.get("native_redstone") is True, "native redstone promotion gate")
    check("acceptance-contract", (not acceptance_required) or acceptance_pass, f"acceptance report: {acceptance_path}")

    promotion_claims = set(map(str, as_list(policy.get("promotion_claims"))))
    claimed_promotions = sorted(set(claims) & promotion_claims)
    if claimed_promotions and not promoted_local:
        fail("claim_exceeds_lifecycle", f"claims {claimed_promotions} require local-candidate lifecycle or stronger")
    if "local-runtime" in claims and not promoted_local:
        fail("local_runtime_claim_without_candidate", "local-runtime claim requires local-candidate lifecycle or stronger")
    if "one-shot" in claims and rules.get("one_shot_claim_requires_explicit_contract", True):
        explicit_one_shot = acceptance_report is not None and (
            acceptance_report.get("one_shot_contract_pass") is True
            or acceptance_report.get("shots_to_breach") == 1
        )
        if not explicit_one_shot:
            fail(
                "one_shot_contract_required",
                "one-shot claim requires one_shot_contract_pass=true or shots_to_breach=1 in the acceptance report",
            )

    ec_promotion = lifecycle == "ec-ready" or "ec-ready" in claims
    live_canary_path, live_canary_report = load_evidence_report(
        ec.get("live_canary_report"),
        repo_root=repo_root,
        output_root=output_root,
        label="extremecraft.live_canary_report",
        required=ec_promotion,
        errors=errors,
    )
    live_canary_pass = live_canary_report is not None and report_pass(live_canary_report)
    if ec_promotion:
        if rules.get("ec_ready_requires_field_verified", True) and ec.get("field_verified") is not True:
            fail("ec_field_verification_required", "EC-ready requires explicit field_verified=true")
        if rules.get("ec_ready_requires_live_canary_pass", True) and not live_canary_pass:
            fail("ec_live_canary_required", "EC-ready requires a passing live ExtremeCraft canary report")
        if lifecycle != "ec-ready":
            fail("ec_claim_lifecycle_mismatch", "ec-ready claim requires ec-ready lifecycle")
    check("extremecraft-boundary", (not ec_promotion) or (ec.get("field_verified") is True and live_canary_pass), f"live canary: {live_canary_path}")

    if geometry_report is not None and geometry_report.get("intent") not in {None, "", intent}:
        warn(
            "geometry_intent_mismatch",
            f"geometry profile intent={geometry_report.get('intent')} differs from manifest intent={intent}",
        )
    if preservation_report is not None and source_mode == "from-scratch":
        warn("unused_preservation_report", "from-scratch diagnostic prototype supplied a preservation report")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "schema": "cannonlab-architecture-policy-result-v1",
        "manifest": str(manifest_path) if manifest_path else None,
        "policy": policy.get("schema"),
        "candidate": {
            "file": str(candidate_path) if candidate_path else candidate.get("file"),
            "intent": intent,
            "lifecycle": lifecycle,
            "claims": claims,
            "source_mode": source_mode,
        },
        "evidence": {
            "geometry_profile": str(geometry_path) if geometry_path else None,
            "preservation_report": str(preservation_path) if preservation_path else None,
            "acceptance_report": str(acceptance_path) if acceptance_path else None,
            "live_canary_report": str(live_canary_path) if live_canary_path else None,
        },
        "architecture": {
            "stage_count": len(stages),
            "impulse_edge_count": len(edges),
            "explosion_push_edges": explosion_push_count,
            "verified_edges": verified_edges,
        },
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "truth_boundary": (
            "A policy pass proves evidence completeness and claim discipline. It does not independently prove the cannon works, "
            "matches private ExtremeCraft mechanics, or deserves an unrecorded community subsystem label."
        ),
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a CannonLab modern-cannon architecture manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--json-out", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = args.manifest.resolve()
    policy_path = args.policy.resolve()
    repo_root = args.repo_root.resolve()
    output_root = args.output_root.resolve()
    try:
        manifest = read_json(manifest_path)
        policy = read_json(policy_path)
        result = validate_manifest(
            manifest,
            policy,
            repo_root=repo_root,
            output_root=output_root,
            manifest_path=manifest_path,
        )
    except ManifestError as exc:
        result = {
            "status": "INVALID",
            "schema": "cannonlab-architecture-policy-result-v1",
            "manifest": str(manifest_path),
            "errors": [{"code": "invalid_input", "message": str(exc)}],
            "warnings": [],
        }
        exit_code = 1
    else:
        exit_code = 0 if result["status"] == "PASS" else 2

    rendered = json.dumps(result, indent=2, sort_keys=False)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
