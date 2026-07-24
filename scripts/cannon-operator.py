#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
OUTPUT_ROOT = WORKSPACE_ROOT / "output"
SCRIPTS = ROOT / "scripts"
OPERATOR_JOBS = ROOT / "operator-jobs"
GENERAL_ENGINE = SCRIPTS / "general-cannon-intelligence.py"
ARCHITECTURE_VALIDATOR = SCRIPTS / "validate-cannon-architecture.py"
CANNON_FORGE = SCRIPTS / "cannon-forge.py"
CANNON_MUTATOR = SCRIPTS / "cannon-mutator.py"
GEOMETRY_PROFILE = SCRIPTS / "cannon-geometry-profile.py"
FORGE_RUNNER = SCRIPTS / "run-forge-campaign.ps1"


def load_general_engine() -> Any:
    spec = importlib.util.spec_from_file_location("cannonlab_general_intelligence", GENERAL_ENGINE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {GENERAL_ENGINE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def slugify(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not value:
        raise ValueError("job name produced an empty slug")
    return value[:72]


def allowed_input(raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"path escapes CannonLab repository/output roots: {raw}")
    if must_exist and not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(command: list[str], *, timeout: int = 900) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"non-JSON command output ({result.returncode}): {' '.join(command)}\n"
            f"stdout={result.stdout[-3000:]}\nstderr={result.stderr[-3000:]}"
        ) from exc
    payload["_exit_code"] = result.returncode
    if result.returncode not in {0, 2}:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout={result.stdout[-3000:]}\nstderr={result.stderr[-3000:]}"
        )
    return payload


def failed(payload: dict[str, Any]) -> bool:
    return payload.get("_exit_code") == 2 or str(payload.get("status", "")).upper() in {
        "FAIL",
        "BLOCKED",
        "INVALID",
    }


def relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def canonical_json_object(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("expected a valid JSON object") from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def prepare_effective_architecture_manifest(
    original_path: Path,
    *,
    source_candidate: Path,
    candidate: Path,
    mutation: dict[str, Any],
    references: list[Path],
    args: argparse.Namespace,
    slug: str,
) -> tuple[Path, dict[str, Any], list[dict[str, str]]]:
    """Bind the architecture manifest to the exact candidate instead of trusting a stale path."""
    payload = read_json(original_path)
    candidate_section = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    blockers: list[dict[str, str]] = []
    raw_candidate = candidate_section.get("file")
    try:
        manifest_candidate = allowed_input(raw_candidate) if raw_candidate else None
    except (ValueError, FileNotFoundError) as exc:
        manifest_candidate = None
        blockers.append({
            "stage": "architecture-binding",
            "code": "architecture-candidate-invalid",
            "message": str(exc),
        })
    if manifest_candidate is None:
        blockers.append({
            "stage": "architecture-binding",
            "code": "architecture-candidate-missing",
            "message": "architecture manifest must name the exact source candidate",
        })
    elif manifest_candidate != source_candidate:
        blockers.append({
            "stage": "architecture-binding",
            "code": "architecture-candidate-mismatch",
            "message": f"manifest names {manifest_candidate}, operator source is {source_candidate}",
        })
    if str(candidate_section.get("intent", "")) != args.intent:
        blockers.append({
            "stage": "architecture-binding",
            "code": "architecture-intent-mismatch",
            "message": f"manifest intent must equal requested intent {args.intent}",
        })
    if str(candidate_section.get("lifecycle", "")) != args.lifecycle:
        blockers.append({
            "stage": "architecture-binding",
            "code": "architecture-lifecycle-mismatch",
            "message": f"manifest lifecycle must equal requested lifecycle {args.lifecycle}",
        })
    if blockers or candidate == source_candidate:
        return original_path, {"status": "UNCHANGED", "path": relative_or_absolute(original_path)}, blockers

    job_directory = OPERATOR_JOBS / slug
    job_directory.mkdir(parents=True, exist_ok=True)
    geometry_path = job_directory / "derived-geometry-profile.json"
    geometry_command = [
        sys.executable,
        str(GEOMETRY_PROFILE),
        str(candidate),
        "--intent",
        args.intent,
        "--chunk-limit",
        str(args.chunk_limit),
    ]
    seen_references: set[Path] = set()
    for reference in [source_candidate, *references]:
        if reference in seen_references:
            continue
        seen_references.add(reference)
        geometry_command += ["--reference", str(reference)]
    geometry = run_json(geometry_command, timeout=600)
    geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8", newline="\n")
    if failed(geometry):
        blockers.append({
            "stage": "architecture-binding",
            "code": "mutated-geometry-profile-failed",
            "message": "mutated candidate did not pass its requested geometry profile",
        })

    mutation_evidence_path = job_directory / "bounded-mutation-evidence.json"
    mutation_evidence_path.write_text(
        json.dumps(mutation, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    derived = copy.deepcopy(payload)
    derived_candidate = derived.setdefault("candidate", {})
    derived_candidate["file"] = relative_or_absolute(candidate)
    derived_candidate["candidate_sha256"] = sha256(candidate)
    derived_source = derived.setdefault("source", {})
    derived_source["mode"] = "bounded-variant"
    hashes = [str(item) for item in derived_source.get("reference_sha256", [])]
    for reference in [source_candidate, *references]:
        digest = sha256(reference)
        if digest not in hashes:
            hashes.append(digest)
    derived_source["reference_sha256"] = hashes
    derived_source["geometry_profile"] = relative_or_absolute(geometry_path)
    derived_source["preservation_report"] = relative_or_absolute(mutation_evidence_path)
    preservation_summary = (
        mutation.get("preservation", {}).get("summary", {})
        if isinstance(mutation.get("preservation"), dict)
        else {}
    )
    change_budget = derived.setdefault("change_budget", {})
    change_budget["declared_variable"] = str(
        mutation.get("declared_variable") or change_budget.get("declared_variable") or "bounded mutation"
    )
    change_budget["modules_touched"] = int(preservation_summary.get("modules_touched") or 0)
    change_budget["override_approved"] = False
    change_budget["override_reason"] = ""
    derived_path = job_directory / "architecture-derived.json"
    derived_path.write_text(json.dumps(derived, indent=2) + "\n", encoding="utf-8", newline="\n")
    return derived_path, {
        "status": "PASS" if not blockers else "BLOCKED",
        "path": relative_or_absolute(derived_path),
        "geometry_profile": relative_or_absolute(geometry_path),
        "mutation_evidence": relative_or_absolute(mutation_evidence_path),
    }, blockers


def architecture_command(manifest: Path) -> list[str]:
    return [
        sys.executable,
        str(ARCHITECTURE_VALIDATOR),
        str(manifest),
        "--repo-root",
        str(ROOT),
        "--output-root",
        str(OUTPUT_ROOT),
    ]


def forge_command(args: argparse.Namespace, candidate: Path, references: list[Path]) -> list[str]:
    command = [
        sys.executable,
        str(CANNON_FORGE),
        "stage",
        str(candidate),
        "--job",
        args.job,
        "--intent",
        args.intent,
        "--base",
        args.base,
        "--payload-mode",
        getattr(args, "payload_mode", "auto"),
        "--chunk-limit",
        str(args.chunk_limit),
        "--origin",
        args.origin,
        "--fire-input",
        args.fire_input,
        "--fire-mode",
        args.fire_mode,
        "--direction",
        args.direction,
        "--distance",
        str(args.distance),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--shots",
        str(args.shots),
    ]
    for specialization in args.specialization:
        command += ["--specialization", specialization]
    for control_state in getattr(args, "control_state_json", []):
        command += ["--control-state-json", control_state]
    for reference in references:
        command += ["--reference", str(reference)]
    return command


def write_operator_job(slug: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    directory = OPERATOR_JOBS / slug
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    runbook = directory / "RUNBOOK.md"
    forge_manifest = payload.get("forge", {}).get("manifest_path") or f"forge-jobs/{slug}/manifest.json"
    runbook.write_text(
        "# CannonLab operator runbook\n\n"
        f"Job: `{slug}`\n\n"
        f"Gate: **{payload['status']}**\n\n"
        "This job binds general cannon planning, architecture policy, and Cannon Forge into one fail-closed intake.\n\n"
        "Run the local campaign only when the gate is PASS:\n\n"
        "```powershell\n"
        "$env:CANNONLAB_ACCEPT_EULA='TRUE'\n"
        f"python scripts/cannon-operator.py run operator-jobs/{slug}/manifest.json --execute\n"
        "```\n\n"
        f"Underlying Forge manifest: `{forge_manifest}`\n\n"
        "Local runtime evidence is not live ExtremeCraft proof.\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest, runbook


def prepare_job(args: argparse.Namespace) -> dict[str, Any]:
    source_candidate = allowed_input(args.candidate)
    candidate = source_candidate
    architecture_manifest = allowed_input(args.architecture_manifest)
    effective_architecture_manifest = architecture_manifest
    references = [allowed_input(item) for item in args.reference]
    mutation_plan = allowed_input(args.mutation_plan) if args.mutation_plan else None
    slug = slugify(args.job or source_candidate.stem)
    args.job = slug

    engine = load_general_engine()
    plan = engine.build_plan(args.base, list(args.specialization), args.lifecycle)
    blockers: list[dict[str, str]] = []
    if plan.get("status") != "PASS":
        blockers.extend(
            {"stage": "general-plan", **item}
            for item in plan.get("blockers", [])
        )

    mutation: dict[str, Any] = {"status": "SKIPPED", "reason": "no-mutation-plan"}
    if not blockers and mutation_plan is not None:
        mutation = run_json([sys.executable, str(CANNON_MUTATOR), str(mutation_plan)], timeout=1200)
        if failed(mutation):
            blockers.append({
                "stage": "bounded-mutation",
                "code": "mutation-failed",
                "message": "bounded schematic mutation did not pass",
            })
        else:
            output_value = mutation.get("output", {}).get("path") if isinstance(mutation.get("output"), dict) else None
            if not output_value:
                blockers.append({
                    "stage": "bounded-mutation",
                    "code": "mutation-output-missing",
                    "message": "mutation result did not provide an output schematic",
                })
            else:
                candidate = allowed_input(str(output_value))

    architecture_binding: dict[str, Any] = {"status": "SKIPPED", "reason": "earlier-gate-blocked"}
    if not blockers:
        effective_architecture_manifest, architecture_binding, binding_blockers = prepare_effective_architecture_manifest(
            architecture_manifest,
            source_candidate=source_candidate,
            candidate=candidate,
            mutation=mutation,
            references=references,
            args=args,
            slug=slug,
        )
        blockers.extend(binding_blockers)

    architecture: dict[str, Any] = {"status": "SKIPPED", "reason": "earlier-gate-blocked"}
    forge: dict[str, Any] = {"status": "SKIPPED", "reason": "general-plan-or-architecture-blocked"}
    if not blockers:
        architecture = run_json(architecture_command(effective_architecture_manifest), timeout=300)
        if failed(architecture):
            blockers.append({
                "stage": "architecture-policy",
                "code": "architecture-policy-failed",
                "message": "architecture manifest did not pass the fail-closed policy",
            })

    if not blockers:
        forge = run_json(forge_command(args, candidate, references), timeout=1200)
        if failed(forge):
            blockers.append({
                "stage": "cannon-forge",
                "code": "forge-stage-failed",
                "message": "Cannon Forge static/scenario intake did not pass",
            })

    forge_manifest_path = ROOT / "forge-jobs" / slug / "manifest.json"
    payload: dict[str, Any] = {
        "schema": "cannonlab-operator-job-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "job": slug,
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": (
            "PASS authorizes the generated local campaign only. It is not proof that the cannon works, "
            "is one-shot, or is ExtremeCraft-ready."
        ),
        "requested": {
            "base": args.base,
            "specializations": list(args.specialization),
            "payload_mode": getattr(args, "payload_mode", "auto"),
            "control_states": [json.loads(value) for value in getattr(args, "control_state_json", [])],
            "lifecycle": args.lifecycle,
            "intent": args.intent,
        },
        "candidate": {
            "path": relative_or_absolute(candidate),
            "sha256": sha256(candidate),
        },
        "source_candidate": {
            "path": relative_or_absolute(source_candidate),
            "sha256": sha256(source_candidate),
        },
        "mutation_plan": (
            {"path": relative_or_absolute(mutation_plan), "sha256": sha256(mutation_plan)}
            if mutation_plan is not None
            else None
        ),
        "bounded_mutation": mutation,
        "references": [
            {"path": relative_or_absolute(path), "sha256": sha256(path)}
            for path in references
        ],
        "architecture_manifest": {
            "path": relative_or_absolute(architecture_manifest),
            "sha256": sha256(architecture_manifest),
        },
        "effective_architecture_manifest": {
            "path": relative_or_absolute(effective_architecture_manifest),
            "sha256": sha256(effective_architecture_manifest),
            "binding": architecture_binding,
        },
        "general_plan": plan,
        "architecture_policy": architecture,
        "forge": {
            "result": forge,
            "manifest_path": relative_or_absolute(forge_manifest_path),
        },
        "blockers": blockers,
        "next_command": (
            f"python scripts/cannon-operator.py run operator-jobs/{slug}/manifest.json --execute"
            if not blockers
            else None
        ),
    }
    manifest, runbook = write_operator_job(slug, payload)
    payload["operator_manifest"] = relative_or_absolute(manifest)
    payload["runbook"] = relative_or_absolute(runbook)
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload


def load_operator_manifest(raw: str | Path) -> tuple[Path, dict[str, Any]]:
    path = allowed_input(raw)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "cannonlab-operator-job-v1":
        raise ValueError("unsupported operator manifest schema")
    return path, payload


def powershell_executable() -> str:
    return "powershell" if sys.platform.startswith("win") else "pwsh"


def run_job(manifest_raw: str, *, execute: bool) -> dict[str, Any]:
    manifest_path, manifest = load_operator_manifest(manifest_raw)
    if manifest.get("status") != "PASS":
        return {
            "schema": "cannonlab-operator-run-v1",
            "status": "BLOCKED",
            "manifest": relative_or_absolute(manifest_path),
            "reason": "operator manifest gate is not PASS",
        }
    forge_manifest = allowed_input(manifest["forge"]["manifest_path"])
    command = [
        powershell_executable(),
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(FORGE_RUNNER),
        "-Manifest",
        str(forge_manifest),
    ]
    if not execute:
        return {
            "schema": "cannonlab-operator-run-v1",
            "status": "READY",
            "executed": False,
            "manifest": relative_or_absolute(manifest_path),
            "forge_manifest": relative_or_absolute(forge_manifest),
            "command": command,
            "truth_boundary": "Dry-run only. Pass --execute to start the local CannonLab campaign.",
        }
    result = subprocess.run(command, cwd=ROOT, text=True, check=False)
    return {
        "schema": "cannonlab-operator-run-v1",
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "executed": True,
        "exit_code": result.returncode,
        "manifest": relative_or_absolute(manifest_path),
        "forge_manifest": relative_or_absolute(forge_manifest),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One fail-closed CannonLab operator binding general planning, architecture policy, and Cannon Forge"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Plan, validate architecture, and stage a Forge campaign")
    prepare.add_argument("candidate")
    prepare.add_argument("--architecture-manifest", required=True)
    prepare.add_argument("--mutation-plan", default="", help="Optional reviewed bounded mutation plan applied before policy and Forge gates")
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--specialization", action="append", default=[])
    prepare.add_argument(
        "--payload-mode",
        choices=["auto", "falling-block-required", "tnt-only"],
        default="auto",
    )
    prepare.add_argument(
        "--control-state-json",
        action="append",
        type=canonical_json_object,
        default=[],
        help="Repeatable JSON control-state object passed to Cannon Forge",
    )
    prepare.add_argument("--lifecycle", choices=["diagnostic-prototype", "local-candidate", "ec-ready"], default="diagnostic-prototype")
    prepare.add_argument("--reference", action="append", default=[])
    prepare.add_argument("--job", default="")
    prepare.add_argument("--intent", choices=["calibration", "modern-raid"], default="modern-raid")
    prepare.add_argument("--chunk-limit", type=int, default=160)
    prepare.add_argument("--origin", default="0,0,0")
    prepare.add_argument("--fire-input", required=True)
    prepare.add_argument("--fire-mode", choices=["button", "redstone"], default="button")
    prepare.add_argument("--direction", choices=["north", "south", "east", "west"], default="north")
    prepare.add_argument("--distance", type=int, default=160)
    prepare.add_argument("--width", type=int, default=17)
    prepare.add_argument("--height", type=int, default=32)
    prepare.add_argument("--shots", type=int, default=10)

    run = subparsers.add_parser("run", help="Show or execute the staged local campaign")
    run.add_argument("manifest")
    run.add_argument("--execute", action="store_true")

    args = parser.parse_args()
    if args.command == "prepare":
        if min(args.chunk_limit, args.distance, args.width, args.height, args.shots) < 1:
            parser.error("chunk limit, distance, dimensions and shots must be positive")
        result = prepare_job(args)
    else:
        result = run_job(args.manifest, execute=args.execute)
    print(json.dumps(result, indent=2))
    if result.get("status") in {"FAIL", "BLOCKED"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
