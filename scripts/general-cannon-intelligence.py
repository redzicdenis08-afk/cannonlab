#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "knowledge" / "cannon-intelligence" / "catalog.json"
CAPABILITIES_PATH = ROOT / "knowledge" / "cannon-intelligence" / "runtime-capabilities.json"
ONTOLOGY_PATH = ROOT / "knowledge" / "cannon-concepts.jsonl"
COVERAGE_PATH = ROOT / "knowledge" / "research" / "concept-coverage.json"

LIFECYCLES = ("diagnostic-prototype", "local-candidate", "ec-ready")
LIFECYCLE_RANK = {name: index for index, name in enumerate(LIFECYCLES)}
EVIDENCE_RANK = {
    "unknown": 0,
    "single-source-community": 1,
    "multi-source-community": 2,
    "static-reference": 3,
    "local-runtime": 4,
    "field-reported": 5,
    "field-verified": 6,
}

COVERAGE_KEY_BY_ID = {
    "hybrid": "hybrid",
    "overstack": "overstack",
    "osrb": "osrb",
    "efficient-nuke": "efficient_nuke",
    "webbust-nuke": "webbust",
    "pseudo-nuke": "pseudo_nuke",
    "push-nuke": "push_nuke",
    "up-down-nuke": "up_down",
    "left-right-shoot": "leftshoot",
    "reverse-hybrid": "rev_hybrid",
    "worm-route": "worm",
    "midair-or-l-stack": "midair",
    "slab-bust": "slab_bust",
    "tunnel-effect": "tunnel",
    "anti-patch": "anti_patch",
    "bypass": "bypass",
    "double-tap": "double_tap",
    "alien-probe": "alien_probe",
    "hammered-stacker": "hammer",
    "hammerless-stacker": "hammerless",
    "anti-gravity-stacker": "384",
    "force-or-counter": "force",
    "asser-multiwave": "asser",
    "rev-worm": "worm",
}

SPECIALIZATION_PAYLOAD = {
    "hybrid": "falling-block-required",
    "overstack": "falling-block-required",
    "osrb": "falling-block-required",
    "efficient-nuke": "tnt-package",
    "webbust-nuke": "tnt-package",
    "pseudo-nuke": "falling-block-coupled",
    "push-nuke": "unknown",
    "up-down-nuke": "tnt-package",
    "left-right-shoot": "archetype-selectable",
    "reverse-hybrid": "falling-block-required",
    "worm-route": "tnt-or-payload-by-reference",
    "midair-or-l-stack": "archetype-selectable",
    "slab-bust": "tnt-package",
    "tunnel-effect": "tnt-package",
    "anti-patch": "tnt-package",
    "bypass": "archetype-selectable",
    "double-tap": "archetype-selectable",
    "alien-probe": "unknown",
}

FAILURE_HINTS = {
    "regen wins": ["osrb", "hybrid", "double-tap"],
    "sand one block wrong": ["osrb", "overstack", "hammered-stacker", "hammerless-stacker"],
    "wrong side": ["left-right-shoot", "reverse-hybrid"],
    "backboard return": ["left-right-shoot", "reverse-hybrid"],
    "slab remains": ["slab-bust"],
    "short nuke": ["efficient-nuke", "pseudo-nuke", "webbust-nuke"],
    "missing stage": ["efficient-nuke", "worm-route", "rev-worm"],
    "stall": ["worm-route", "rev-worm"],
    "payload high": ["hammered-stacker", "hammerless-stacker", "slab-bust"],
    "payload low": ["hammered-stacker", "hammerless-stacker", "slab-bust"],
    "packages merge": ["double-tap", "webbust-nuke", "left-right-shoot"],
    "self damage": ["hammered-stacker", "hammerless-stacker", "asser-multiwave", "rev-worm", "force-or-counter"],
    "variable direction": ["rev-worm", "left-right-shoot", "force-or-counter"],
    "unembedded explosion": ["hybrid", "osrb"],
    "partial stack": ["hammered-stacker", "hammerless-stacker", "overstack"],
    "no reset": ["hammerless-stacker", "rev-worm", "double-tap"],
}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_catalog() -> dict[str, Any]:
    payload = read_json(CATALOG_PATH)
    if payload.get("schema") != "cannonlab-general-cannon-catalog-v1":
        raise ValueError("unsupported cannon catalog schema")
    return payload


def load_capabilities() -> dict[str, Any]:
    payload = read_json(CAPABILITIES_PATH)
    if payload.get("schema") != "cannonlab-general-runtime-capabilities-v1":
        raise ValueError("unsupported runtime capability schema")
    return payload


def load_ontology() -> dict[str, dict[str, Any]]:
    if not ONTOLOGY_PATH.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw in ONTOLOGY_PATH.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        item = json.loads(raw)
        concept_id = item.get("id")
        if concept_id:
            result[str(concept_id)] = item
    return result


def load_coverage() -> dict[str, Any]:
    return read_json(COVERAGE_PATH) if COVERAGE_PATH.is_file() else {}


def index_catalog(catalog: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    families = {str(item["id"]): item for item in catalog.get("families", [])}
    specializations = {str(item["id"]): item for item in catalog.get("specializations", [])}
    return families, specializations


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def iter_text_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        return
    excluded_names = {
        "general-cannon-intelligence.py",
        "cannon-archetype-engine.py",
        "test-general-cannon-intelligence.py",
        "test-cannon-archetype-engine.py",
    }
    for candidate in path.rglob("*"):
        if "__pycache__" in candidate.parts or candidate.name in excluded_names or candidate.name.startswith("test-"):
            continue
        if candidate.is_file() and candidate.suffix.lower() in {
            ".py", ".java", ".kt", ".kts", ".md", ".yml", ".yaml", ".json", ".ps1", ".sh"
        }:
            yield candidate


def safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def capability_check(check: dict[str, Any]) -> tuple[bool, str]:
    kind = str(check.get("type", ""))
    if kind == "file":
        path = ROOT / str(check.get("path", ""))
        return path.is_file(), str(path.relative_to(ROOT)) if path.exists() else f"missing:{check.get('path')}"
    if kind == "any-file":
        paths = [ROOT / str(raw) for raw in check.get("paths", [])]
        existing = [str(path.relative_to(ROOT)) for path in paths if path.is_file()]
        return bool(existing), ",".join(existing) if existing else "none-of-files-present"
    if kind in {"any-token", "all-token", "none-token"}:
        path = ROOT / str(check.get("path", ""))
        text = safe_text(path)
        tokens = [str(token) for token in check.get("tokens", [])]
        if kind == "any-token":
            hits = [token for token in tokens if token in text]
            return bool(hits), f"hits={hits}"
        if kind == "all-token":
            missing = [token for token in tokens if token not in text]
            return not missing, f"missing={missing}"
        hits = [token for token in tokens if token in text]
        return not hits, f"forbidden-hits={hits}"
    if kind == "any-token-anywhere":
        tokens = [str(token) for token in check.get("tokens", [])]
        found: dict[str, list[str]] = defaultdict(list)
        for raw_path in check.get("paths", []):
            for file in iter_text_files(ROOT / str(raw_path)):
                text = safe_text(file)
                for token in tokens:
                    if token in text:
                        found[token].append(str(file.relative_to(ROOT)))
        return bool(found), f"hits={dict(found)}" if found else "no-token-hit"
    return False, f"unsupported-check-type:{kind}"


def audit_runtime() -> dict[str, Any]:
    payload = load_capabilities()
    return audit_capability_collection(
        payload.get("capabilities", []),
        schema="cannonlab-general-runtime-audit-v1",
        lifecycles=LIFECYCLES,
    )


def audit_capability_collection(
    capabilities: list[dict[str, Any]],
    *,
    schema: str,
    lifecycles: tuple[str, ...],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for capability in capabilities:
        check_results = []
        for check in capability.get("checks", []):
            passed, detail = capability_check(check)
            check_results.append({"passed": passed, "detail": detail, "check": check})
        passed = bool(check_results) and all(item["passed"] for item in check_results)
        rows.append({
            "id": capability["id"],
            "status": "PASS" if passed else "MISSING",
            "required_for": capability.get("required_for", []),
            "checks": check_results,
        })
    by_id = {row["id"]: row for row in rows}
    readiness: dict[str, Any] = {}
    for lifecycle in lifecycles:
        required = [row for row in rows if lifecycle in row["required_for"]]
        missing = [row["id"] for row in required if row["status"] != "PASS"]
        readiness[lifecycle] = {
            "status": "PASS" if not missing else "PARTIAL",
            "required": len(required),
            "passing": len(required) - len(missing),
            "missing": missing,
        }
    return {
        "schema": schema,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "capabilities": rows,
        "by_id": by_id,
        "readiness": readiness,
    }


def audit_operator_integration() -> dict[str, Any]:
    payload = load_capabilities()
    return audit_capability_collection(
        payload.get("operator_capabilities", []),
        schema="cannonlab-general-operator-audit-v1",
        lifecycles=("operator-ready",),
    )


def build_audit(require: str | None = None) -> dict[str, Any]:
    catalog_audit = validate_catalog(load_catalog())
    runtime_audit = audit_runtime()
    operator_audit = audit_operator_integration()

    if catalog_audit["status"] != "PASS":
        status = "FAIL"
    elif require:
        if require == "operator-ready":
            required_status = operator_audit["readiness"][require]["status"]
        else:
            required_status = runtime_audit["readiness"][require]["status"]
        status = "PASS" if required_status == "PASS" else "BLOCKED"
    else:
        fully_ready = (
            runtime_audit["readiness"]["ec-ready"]["status"] == "PASS"
            and operator_audit["readiness"]["operator-ready"]["status"] == "PASS"
        )
        diagnostic_ready = runtime_audit["readiness"]["diagnostic-prototype"]["status"] == "PASS"
        status = "PASS" if fully_ready else ("PARTIAL" if diagnostic_ready else "FAIL")

    return {
        "schema": "cannonlab-general-intelligence-audit-v2",
        "status": status,
        "required_level": require,
        "truth_boundary": (
            "Catalog validity, runtime capability, operator integration, local proof, and live ExtremeCraft proof "
            "are separate gates. A PARTIAL audit must never be described as fully automatic or EC-ready."
        ),
        "catalog": catalog_audit,
        "runtime": runtime_audit,
        "operator": operator_audit,
    }


def validate_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    families = catalog.get("families", [])
    specializations = catalog.get("specializations", [])
    interfaces = set(catalog.get("module_interfaces", {}).keys())
    evidence_order = set(catalog.get("evidence_order", []))

    def error(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    def warning(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    ids: list[str] = []
    for collection_name, collection in (("family", families), ("specialization", specializations)):
        for index, item in enumerate(collection):
            if not isinstance(item, dict):
                error("invalid-item", f"{collection_name}[{index}] must be an object")
                continue
            item_id = str(item.get("id", "")).strip()
            if not item_id:
                error("missing-id", f"{collection_name}[{index}] has no id")
                continue
            ids.append(item_id)
            evidence = str(item.get("evidence", "unknown"))
            if evidence not in evidence_order:
                error("invalid-evidence", f"{item_id} uses unsupported evidence {evidence}")
            if collection_name == "family":
                if not item.get("required_modules"):
                    error("missing-required-modules", f"{item_id} has no required_modules")
                if not item.get("runtime_contract"):
                    error("missing-runtime-contract", f"{item_id} has no runtime_contract")
            else:
                if not item.get("requires"):
                    error("missing-specialization-inputs", f"{item_id} has no requires")
                if not item.get("acceptance"):
                    error("missing-specialization-acceptance", f"{item_id} has no acceptance")
                if item.get("output") == "unknown-until-proven" and item.get("acceptance") != ["do-not-invent"]:
                    error("unknown-output-promotion", f"{item_id} must fail closed")
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        error("duplicate-id", f"duplicate catalog ids: {duplicates}")

    universal = catalog.get("universal_physics_contract", {})
    if len(universal.get("required_layers", [])) < 6:
        error("weak-universal-contract", "universal physics contract is missing major layers")
    if len(universal.get("required_edge_fields", [])) < 8:
        error("weak-edge-contract", "impulse edge contract is incomplete")
    if not interfaces:
        error("missing-interfaces", "module interface registry is empty")

    ontology = load_ontology()
    coverage = load_coverage()
    for item_id in ids:
        key = COVERAGE_KEY_BY_ID.get(item_id)
        if key and key not in coverage:
            warning("coverage-key-missing", f"{item_id} maps to missing research coverage key {key}")
    if not ontology:
        warning("ontology-missing", "cannon ontology unavailable")

    return {
        "schema": "cannonlab-general-catalog-audit-v1",
        "status": "PASS" if not errors else "FAIL",
        "catalog": str(CATALOG_PATH.relative_to(ROOT)),
        "family_count": len(families),
        "specialization_count": len(specializations),
        "interface_count": len(interfaces),
        "defense_contract_count": len(catalog.get("defense_contracts", [])),
        "errors": errors,
        "warnings": warnings,
    }


def evidence_summary(item_id: str, item: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    key = COVERAGE_KEY_BY_ID.get(item_id)
    source_count = None
    if key and isinstance(coverage.get(key), dict):
        source_count = coverage[key].get("source_count")
    count = int(source_count or 0)
    if count >= 5:
        community_strength = "strong-multi-source"
    elif count >= 2:
        community_strength = "multi-source"
    elif count == 1:
        community_strength = "single-source"
    else:
        community_strength = "none"
    return {
        "declared_evidence": item.get("evidence", "unknown"),
        "research_key": key,
        "community_source_count": count,
        "community_strength": community_strength,
        "reference_hash_count": len(item.get("reference_hashes", [])),
    }


def lifecycle_exceeds_ceiling(item: dict[str, Any], lifecycle: str) -> bool:
    ceiling = str(item.get("promotion_ceiling", "diagnostic-prototype"))
    if ceiling == "local-candidate-after-runtime-proof":
        ceiling = "local-candidate"
    if ceiling in {"field-calibration-only", "module-diagnostic"}:
        ceiling = "diagnostic-prototype"
    return LIFECYCLE_RANK[lifecycle] > LIFECYCLE_RANK.get(ceiling, 0)


def compatibility_blockers(base: dict[str, Any], specializations: list[dict[str, Any]]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    base_id = str(base["id"])
    payload_mode = str(base.get("payload_mode", "unknown"))
    ids = [str(item["id"]) for item in specializations]

    if base_id == "compact-calibration-stacker" and ids:
        blockers.append({"code": "calibration-scope", "message": "compact calibration architecture cannot inherit advanced raid claims"})
    if base_id == "rev-worm":
        falling_required = [item_id for item_id in ids if SPECIALIZATION_PAYLOAD.get(item_id) in {"falling-block-required", "falling-block-coupled"}]
        if falling_required:
            blockers.append({
                "code": "worm-payload-interface-unproven",
                "message": f"rev-worm tested mode is TNT-only; falling-payload specializations require a proven interface: {falling_required}",
            })
        if "left-right-shoot" in ids:
            blockers.append({"code": "axis-interface-unproven", "message": "north/south worm route cannot inherit Asser-style lateral output without corridor proof"})
    if base_id == "asser-multiwave" and "worm-route" in ids:
        blockers.append({"code": "family-mix-unproven", "message": "Asser east/west multi-wave and Rev-Worm surface routing require an explicit interface experiment"})
    if payload_mode.startswith("tnt-only"):
        for item_id in ids:
            if SPECIALIZATION_PAYLOAD.get(item_id) == "falling-block-required":
                blockers.append({"code": "payload-mode-mismatch", "message": f"{item_id} requires falling payload but base declares {payload_mode}"})
    if "osrb" in ids and "efficient-nuke" in ids:
        blockers.append({"code": "ooe-composition-proof", "message": "OSRB plus efficient nuke requires a measured shared entity-order contract, not independent module passes"})
    if "double-tap" in ids and len(ids) > 3:
        blockers.append({"code": "complexity-budget", "message": "double-tap with more than two other specializations exceeds the default bounded-composition budget"})
    if "push-nuke" in ids or "alien-probe" in ids:
        blockers.append({"code": "unresolved-terminology", "message": "unresolved community label requires a builder definition and working reference before composition"})
    return blockers


def build_plan(base_id: str, specialization_ids: list[str], lifecycle: str) -> dict[str, Any]:
    catalog = load_catalog()
    families, specialization_index = index_catalog(catalog)
    if base_id not in families:
        raise ValueError(f"unknown base architecture: {base_id}")
    unknown = [item_id for item_id in specialization_ids if item_id not in specialization_index]
    if unknown:
        raise ValueError(f"unknown specializations: {unknown}")
    base = families[base_id]
    specializations = [specialization_index[item_id] for item_id in specialization_ids]
    coverage = load_coverage()
    runtime = audit_runtime()
    blockers = compatibility_blockers(base, specializations)

    if lifecycle_exceeds_ceiling(base, lifecycle):
        blockers.append({
            "code": "base-evidence-ceiling",
            "message": f"{base_id} current evidence ceiling is {base.get('promotion_ceiling')}",
        })
    for item in specializations:
        if lifecycle != "diagnostic-prototype" and EVIDENCE_RANK.get(str(item.get("evidence", "unknown")), 0) < EVIDENCE_RANK["multi-source-community"]:
            blockers.append({
                "code": "weak-specialization-evidence",
                "message": f"{item['id']} lacks enough evidence for promotion beyond diagnostic work",
            })
        if item.get("output") == "unknown-until-proven":
            blockers.append({"code": "unknown-specialization-output", "message": f"{item['id']} output is unresolved"})

    runtime_readiness = runtime["readiness"][lifecycle]
    for missing in runtime_readiness["missing"]:
        blockers.append({"code": "missing-runtime-capability", "message": missing})

    phases: list[dict[str, Any]] = [
        {
            "id": "source-intake",
            "goal": "Preserve exact binaries and hashes, decode without mutation, and identify real controls.",
            "evidence": ["source-hash", "format", "data-version", "all-256-offsets", "control-map"],
        },
        {
            "id": "baseline-grammar",
            "goal": "Reproduce one native-control shot and map exact dispenser, piston, entity and explosion order.",
            "evidence": ["causal-events", "entity-telemetry", "cohort-fingerprint", "self-damage", "output-vector"],
        },
        {
            "id": "module-isolation",
            "goal": "Prove every claimed module by a physical input/output edge and a removal or timing counterfactual.",
            "evidence": ["module-runtime-trace", "impulse-edges", "counterfactual", "reset-state"],
        },
        {
            "id": "bounded-composition",
            "goal": "Add one specialization at a time while preserving untouched stage traces.",
            "evidence": ["declared-variable", "preservation-report", "before-after-trajectory", "interface-bindings"],
        },
        {
            "id": "defense-campaign",
            "goal": "Pass only defenses relevant to the declared capability, including repeated survival.",
            "evidence": ["target-scoped-breach", "regen-timing", "continuation", "endurance"],
        },
        {
            "id": "ec160-redesign",
            "goal": "Redistribute banks across chunk columns while preserving cohort timing, symmetry and output.",
            "evidence": ["all-offset-audit", "cohort-equivalence", "trajectory-equivalence", "chunk-column-counts"],
        },
    ]
    if lifecycle == "ec-ready":
        phases.append({
            "id": "live-ec-canary",
            "goal": "Run reduced-charge live ExtremeCraft calibration before any full field claim.",
            "evidence": ["paste-coordinate", "mode-states", "native-button", "field-video-or-log", "survival", "target-effect"],
        })

    specialization_plans = []
    for item in specializations:
        specialization_plans.append({
            "id": item["id"],
            "requires": item.get("requires", []),
            "output": item.get("output"),
            "acceptance": item.get("acceptance", []),
            "evidence": evidence_summary(str(item["id"]), item, coverage),
        })

    return {
        "schema": "cannonlab-general-build-plan-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": catalog["truth_boundary"],
        "base": {
            "id": base_id,
            "title": base.get("title"),
            "payload_mode": base.get("payload_mode"),
            "required_modules": base.get("required_modules", []),
            "runtime_contract": base.get("runtime_contract", []),
            "evidence": evidence_summary(base_id, base, coverage),
        },
        "specializations": specialization_plans,
        "requested_lifecycle": lifecycle,
        "runtime_readiness": runtime_readiness,
        "blockers": blockers,
        "phases": phases,
        "promotion_rule": "A plan authorizes experiments only. Promotion requires the generated evidence and cannot exceed the weakest base, specialization, runtime or field gate.",
    }


def research_gaps() -> dict[str, Any]:
    catalog = load_catalog()
    families, specializations = index_catalog(catalog)
    coverage = load_coverage()
    rows = []
    for item_id, item in {**families, **specializations}.items():
        evidence = evidence_summary(item_id, item, coverage)
        score = 0
        reasons = []
        declared = str(item.get("evidence", "unknown"))
        if declared == "unknown":
            score += 100
            reasons.append("declared-output-or-mechanism-unknown")
        elif declared == "single-source-community":
            score += 60
            reasons.append("single-source-community")
        elif declared == "multi-source-community":
            score += 30
            reasons.append("community-only-no-local-proof")
        elif declared == "static-reference":
            score += 20
            reasons.append("reference-shape-without-clean-output")
        if evidence["community_source_count"] == 0:
            score += 50
            reasons.append("zero-transcript-corpus-sources")
        elif evidence["community_source_count"] == 1:
            score += 25
            reasons.append("only-one-corpus-source")
        if item.get("output") == "unknown-until-proven":
            score += 100
            reasons.append("output-unknown")
        if str(item.get("promotion_ceiling", "")).startswith("diagnostic"):
            score += 15
            reasons.append("diagnostic-ceiling")
        rows.append({
            "id": item_id,
            "kind": item.get("kind"),
            "priority_score": score,
            "reasons": reasons,
            "evidence": evidence,
            "next_evidence": next_evidence_for(item),
        })
    rows.sort(key=lambda row: (-row["priority_score"], row["id"]))
    return {
        "schema": "cannonlab-general-research-gaps-v1",
        "status": "PASS",
        "items": rows,
    }


def next_evidence_for(item: dict[str, Any]) -> list[str]:
    declared = str(item.get("evidence", "unknown"))
    if item.get("output") == "unknown-until-proven" or declared == "unknown":
        return ["builder-definition", "working-reference-binary", "firing-video", "distinguishing-causal-trace"]
    if declared in {"single-source-community", "multi-source-community"}:
        return ["second-independent-source", "reference-binary", "module-isolation-runtime", "failure-counterfactual"]
    if declared == "static-reference":
        return ["native-control-clean-shot", "stable-output-vector", "module-causal-attribution", "repeatability"]
    if declared == "local-runtime":
        return ["defense-specific-acceptance", "endurance", "reduced-live-ec-canary"]
    return ["keep-field-evidence-versioned"]


def diagnose(symptoms: list[str]) -> dict[str, Any]:
    catalog = load_catalog()
    families, specializations = index_catalog(catalog)
    candidates = {**families, **specializations}
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)
    normalized = [normalize_text(item) for item in symptoms]

    for symptom in normalized:
        for hint, ids in FAILURE_HINTS.items():
            normalized_hint = normalize_text(hint)
            if normalized_hint in symptom or symptom in normalized_hint:
                for item_id in ids:
                    scores[item_id] += 4
                    evidence[item_id].append(f"matched-known-hint:{hint}")
        for item_id, item in candidates.items():
            for signature in item.get("failure_signatures", []):
                normalized_signature = normalize_text(str(signature))
                if normalized_signature in symptom or symptom in normalized_signature:
                    scores[item_id] += 6
                    evidence[item_id].append(f"matched-catalog-signature:{signature}")
            searchable = " ".join(str(value) for value in item.get("acceptance", []))
            for token in symptom.split():
                if len(token) >= 5 and token in normalize_text(searchable):
                    scores[item_id] += 1

    ranked = []
    for item_id, score in scores.most_common():
        item = candidates.get(item_id, {})
        ranked.append({
            "id": item_id,
            "kind": item.get("kind"),
            "score": score,
            "evidence": evidence[item_id],
            "next_checks": diagnostic_checks(item_id),
        })
    return {
        "schema": "cannonlab-general-diagnosis-v1",
        "status": "PASS" if ranked else "NO_MATCH",
        "symptoms": symptoms,
        "ranked_candidates": ranked,
        "truth_boundary": "This ranks experiment targets. It does not identify a module from symptoms alone.",
    }


def diagnostic_checks(item_id: str) -> list[str]:
    common = ["compare-native-control-timeline", "inspect-cohort-counts-and-facings", "compare-entity-trajectory", "measure-self-damage"]
    extra = {
        "osrb": ["measure-first-regen-tick", "locate-one-shot-sand", "verify-follow-up-before-restore"],
        "hybrid": ["count-embedded-vs-unembedded-explosions", "measure-sand-tnt-overlap"],
        "left-right-shoot": ["measure-lateral-vector", "check-splitter-timing", "check-backboard-return-distance"],
        "reverse-hybrid": ["locate-trajectory-sign-change", "verify-backboard-coordinate"],
        "rev-worm": ["verify-537-336-144-relative-cohorts", "trace-piston-slime-order", "measure-route-waypoints"],
        "worm-route": ["measure-waypoint-order", "find-stall-stage", "verify-terminal-transition"],
        "efficient-nuke": ["plot-vertical-explosion-centers", "find-missing-game-tick-cohort"],
        "slab-bust": ["measure-slab-height-contact", "check-stack-after-slab-impact"],
        "double-tap": ["separate-impact-clusters", "measure-inter-impact-delay", "verify-reset-window"],
    }
    return common + extra.get(item_id, [])


def matrix() -> dict[str, Any]:
    catalog = load_catalog()
    families, specializations = index_catalog(catalog)
    coverage = load_coverage()
    runtime = audit_runtime()
    rows = []
    for item_id, item in {**families, **specializations}.items():
        evidence = evidence_summary(item_id, item, coverage)
        rows.append({
            "id": item_id,
            "kind": item.get("kind"),
            "declared_evidence": evidence["declared_evidence"],
            "community_sources": evidence["community_source_count"],
            "reference_hashes": evidence["reference_hash_count"],
            "promotion_ceiling": item.get("promotion_ceiling", "inherits-base-and-runtime"),
            "output": item.get("output", "base-architecture"),
        })
    rows.sort(key=lambda row: (str(row["kind"]), row["id"]))
    return {
        "schema": "cannonlab-general-capability-matrix-v1",
        "status": "PASS",
        "rows": rows,
        "runtime_readiness": runtime["readiness"],
    }


def write_json(payload: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2) + "\n"
    if output:
        path = Path(output)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description="General evidence-first intelligence for modern factions cannons")
    parser.add_argument("--json-out", default="")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser(
        "audit",
        help="Validate catalog, runtime capabilities, and operator integration",
    )
    audit_parser.add_argument(
        "--require",
        choices=[*LIFECYCLES, "operator-ready"],
        default="",
        help="Fail closed unless the requested readiness level passes",
    )
    subparsers.add_parser("matrix", help="Print the general cannon family and specialization matrix")
    subparsers.add_parser("gaps", help="Rank terminology and runtime evidence gaps")

    plan = subparsers.add_parser("plan", help="Build a fail-closed experiment plan")
    plan.add_argument("--base", required=True)
    plan.add_argument("--specialization", action="append", default=[])
    plan.add_argument("--lifecycle", choices=LIFECYCLES, default="diagnostic-prototype")

    diagnose_parser = subparsers.add_parser("diagnose", help="Rank likely experiment targets from failure symptoms")
    diagnose_parser.add_argument("--symptom", action="append", required=True)

    args = parser.parse_args()
    if args.command == "audit":
        payload = build_audit(args.require or None)
    elif args.command == "matrix":
        payload = matrix()
    elif args.command == "gaps":
        payload = research_gaps()
    elif args.command == "plan":
        payload = build_plan(args.base, args.specialization, args.lifecycle)
    else:
        payload = diagnose(args.symptom)
    write_json(payload, args.json_out or None)
    if payload.get("status") in {"FAIL", "BLOCKED"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
