#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


class CampaignError(ValueError):
    pass


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


CommandRunner = Callable[[list[str], Path, dict[str, str] | None, int], CommandOutcome]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CampaignError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_repo_path(root: Path, raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise CampaignError(f"path escapes CannonLab repository: {raw}")
    if must_exist and not path.exists():
        raise CampaignError(f"path does not exist: {path}")
    return path


def default_runner(
    command: list[str],
    cwd: Path,
    environment: dict[str, str] | None,
    timeout_seconds: int,
) -> CommandOutcome:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandOutcome(
            result.returncode,
            result.stdout,
            result.stderr,
            round(time.monotonic() - started, 6),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandOutcome(
            124,
            stdout,
            stderr + f"\ncommand timed out after {timeout_seconds}s",
            round(time.monotonic() - started, 6),
        )


def parse_json_stdout(outcome: CommandOutcome) -> dict[str, Any] | None:
    try:
        payload = json.loads(outcome.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def clean_identifier(raw: Any, label: str) -> str:
    value = str(raw or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not value or any(character not in allowed for character in value):
        raise CampaignError(f"{label} must use letters, digits, dot, dash, or underscore")
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    if int(manifest.get("schema_version", 0)) != 1:
        raise CampaignError("campaign schema_version must equal 1")
    clean_identifier(manifest.get("id"), "campaign id")
    candidates = manifest.get("candidates")
    stages = manifest.get("stages")
    if not isinstance(candidates, list) or not candidates:
        raise CampaignError("campaign requires at least one candidate")
    if not isinstance(stages, list) or not stages:
        raise CampaignError("campaign requires at least one stage")

    candidate_ids: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict):
            raise CampaignError("every candidate must be an object")
        candidate_id = clean_identifier(row.get("id"), "candidate id")
        if candidate_id in candidate_ids:
            raise CampaignError(f"duplicate candidate id: {candidate_id}")
        candidate_ids.add(candidate_id)
        if not str(row.get("path", "")).strip():
            raise CampaignError(f"candidate {candidate_id}: path is required")
        if len(str(row.get("sha256", "")).strip()) != 64:
            raise CampaignError(f"candidate {candidate_id}: exact SHA-256 is required")

    stage_ids: set[str] = set()
    runtime_seen = False
    for row in stages:
        if not isinstance(row, dict):
            raise CampaignError("every stage must be an object")
        stage_id = clean_identifier(row.get("id"), "stage id")
        if stage_id in stage_ids:
            raise CampaignError(f"duplicate stage id: {stage_id}")
        stage_ids.add(stage_id)
        stage_type = str(row.get("type", "")).strip()
        if stage_type not in {"static", "scenario-integrity", "runtime"}:
            raise CampaignError(f"stage {stage_id}: unsupported type {stage_type!r}")
        if stage_type == "runtime":
            runtime_seen = True
            if not str(row.get("scenario", "")).strip():
                raise CampaignError(f"runtime stage {stage_id}: scenario is required")
        elif runtime_seen:
            raise CampaignError("all static/scenario stages must appear before runtime stages")

    policy = manifest.get("policy") or {}
    if not isinstance(policy, dict):
        raise CampaignError("campaign policy must be an object")
    if int(policy.get("max_runtime_candidates", 1)) < 0:
        raise CampaignError("policy.max_runtime_candidates cannot be negative")


def candidate_rows(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in manifest["candidates"]:
        candidate_id = clean_identifier(raw["id"], "candidate id")
        source = resolve_repo_path(root, str(raw["path"]))
        if source.suffix.lower() != ".schem":
            raise CampaignError(f"candidate {candidate_id}: only .schem files are accepted")
        expected = str(raw["sha256"]).lower()
        actual = sha256_file(source)
        if actual != expected:
            raise CampaignError(
                f"candidate {candidate_id}: hash mismatch expected={expected} actual={actual}"
            )
        rows.append(
            {
                "id": candidate_id,
                "source": source,
                "sha256": actual,
                "priority": int(raw.get("priority", 0)),
                "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            }
        )
    rows.sort(key=lambda row: (-int(row["priority"]), str(row["id"])))
    return rows


def deliver_candidate(candidate: dict[str, Any], output_root: Path) -> dict[str, Any]:
    destination = output_root / "candidates" / f"{candidate['id']}.schem"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate["source"], destination)
    copied_hash = sha256_file(destination)
    if copied_hash != candidate["sha256"]:
        raise CampaignError(f"candidate delivery hash mismatch: {candidate['id']}")
    return {
        "path": str(destination),
        "sha256": copied_hash,
        "bytes": destination.stat().st_size,
        "delivered_before_testing": True,
    }


def command_record(
    command: list[str], outcome: CommandOutcome, payload: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "command": command,
        "returncode": outcome.returncode,
        "duration_seconds": outcome.duration_seconds,
        "stdout_tail": outcome.stdout[-4000:],
        "stderr_tail": outcome.stderr[-4000:],
        "json": payload,
    }


def outcome_passed(outcome: CommandOutcome, payload: dict[str, Any] | None) -> bool:
    return (
        outcome.returncode == 0
        and payload is not None
        and str(payload.get("status", "PASS")).upper() not in {"FAIL", "ERROR"}
    )


def run_static_stage(
    root: Path,
    candidate: dict[str, Any],
    stage: dict[str, Any],
    runner: CommandRunner,
) -> dict[str, Any]:
    chunk_limit = int(stage.get("chunk_limit", 160))
    if chunk_limit <= 0:
        raise CampaignError(f"stage {stage['id']}: chunk_limit must be positive")
    audit = [
        sys.executable,
        str(root / "scripts" / "schem-audit.py"),
        str(candidate["source"]),
        "--chunk-limit",
        str(chunk_limit),
    ]
    if stage.get("expect_format"):
        audit += ["--expect-format", str(stage["expect_format"])]
    alignment = [
        sys.executable,
        str(root / "scripts" / "paste-alignment-audit.py"),
        str(candidate["source"]),
        "--chunk-limit",
        str(chunk_limit),
    ]
    commands: list[dict[str, Any]] = []
    passed = True
    for command in (audit, alignment):
        outcome = runner(command, root, None, int(stage.get("timeout_seconds", 180)))
        payload = parse_json_stdout(outcome)
        commands.append(command_record(command, outcome, payload))
        passed = passed and outcome_passed(outcome, payload)
        if not passed:
            break
    return {
        "id": stage["id"],
        "type": "static",
        "required": bool(stage.get("required", True)),
        "status": "PASS" if passed else "FAIL",
        "commands": commands,
    }


def replace_scenario_cannon_file(text: str, runtime_name: str) -> str:
    lines = text.splitlines()
    cannon_indent: int | None = None
    replacements = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if stripped == "cannon:":
            cannon_indent = indent
            continue
        if cannon_indent is None:
            continue
        if stripped and indent <= cannon_indent:
            cannon_indent = None
            continue
        if stripped.startswith("file:"):
            lines[index] = " " * indent + f"file: {runtime_name}"
            replacements += 1
            cannon_indent = None
    if replacements != 1:
        raise CampaignError(
            f"scenario template must contain exactly one cannon.file entry, found {replacements}"
        )
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def runtime_token(candidate: dict[str, Any], stage: dict[str, Any]) -> str:
    return hashlib.sha256(
        f"{candidate['id']}:{candidate['sha256']}:{stage['id']}".encode("utf-8")
    ).hexdigest()[:20]


def materialize_scenario(
    root: Path,
    candidate: dict[str, Any],
    stage: dict[str, Any],
    output_root: Path,
) -> tuple[Path, str]:
    template = resolve_repo_path(root, str(stage["scenario"]))
    runtime_name = f"campaign-{runtime_token(candidate, stage)}.schem"
    rendered = replace_scenario_cannon_file(template.read_text(encoding="utf-8"), runtime_name)
    destination = output_root / "materialized-scenarios" / candidate["id"] / f"{stage['id']}.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return destination, runtime_name


def run_scenario_integrity_stage(
    root: Path,
    candidate: dict[str, Any],
    stage: dict[str, Any],
    output_root: Path,
    runner: CommandRunner,
) -> dict[str, Any]:
    scenario, runtime_name = materialize_scenario(root, candidate, stage, output_root)
    command = [
        sys.executable,
        str(root / "scripts" / "scenario-integrity-audit.py"),
        str(scenario),
    ]
    if bool(stage.get("require_field_candidate", False)):
        command.append("--require-field-candidate")
    if bool(stage.get("require_readiness", False)):
        command.append("--require-readiness")
    outcome = runner(command, root, None, int(stage.get("timeout_seconds", 180)))
    payload = parse_json_stdout(outcome)
    return {
        "id": stage["id"],
        "type": "scenario-integrity",
        "required": bool(stage.get("required", True)),
        "status": "PASS" if outcome_passed(outcome, payload) else "FAIL",
        "scenario": str(scenario),
        "runtime_cannon_name": runtime_name,
        "commands": [command_record(command, outcome, payload)],
    }


def runtime_environment(stage: dict[str, Any], scenario_name: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["CANNONLAB_SCENARIO"] = scenario_name
    environment["CANNONLAB_EXPECTED_SHOTS"] = str(int(stage.get("expected_shots", 1)))
    environment["CANNONLAB_TIMEOUT_SECONDS"] = str(int(stage.get("timeout_seconds", 600)))
    extra = stage.get("environment") or {}
    if not isinstance(extra, dict):
        raise CampaignError(f"runtime stage {stage['id']}: environment must be an object")
    for key, value in extra.items():
        if not isinstance(key, str) or not key.startswith("CANNONLAB_"):
            raise CampaignError(f"runtime environment key must start with CANNONLAB_: {key!r}")
        environment[key] = str(value)
    return environment


def acquire_runtime_lock(root: Path) -> Path:
    lock = root / ".campaign-runtime.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise CampaignError(
            f"another campaign runtime owns {lock}; remove it only after proving no campaign is running"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()}\n")
    return lock


def run_runtime_stage(
    root: Path,
    candidate: dict[str, Any],
    stage: dict[str, Any],
    output_root: Path,
    runner: CommandRunner,
) -> dict[str, Any]:
    materialized, runtime_name = materialize_scenario(root, candidate, stage, output_root)
    token = runtime_token(candidate, stage)
    cannon_asset = root / "cannons" / f"{runtime_name}.b64"
    scenario_asset = root / "scenarios" / f"campaign-{token}.yml"
    lock = acquire_runtime_lock(root)
    try:
        if cannon_asset.exists() or scenario_asset.exists():
            raise CampaignError("campaign runtime asset collision")
        scenario_asset.write_text(materialized.read_text(encoding="utf-8"), encoding="utf-8")
        cannon_asset.write_bytes(base64.b64encode(candidate["source"].read_bytes()))
        command = ["bash", str(root / "scripts" / "cloud-smoke.sh")]
        environment = runtime_environment(stage, scenario_asset.name)
        outcome = runner(
            command,
            root,
            environment,
            int(stage.get("timeout_seconds", 600)) + 90,
        )
        stage_root = output_root / "runtime" / candidate["id"] / str(stage["id"])
        stage_root.mkdir(parents=True, exist_ok=True)
        (stage_root / "command.stdout.log").write_text(outcome.stdout, encoding="utf-8")
        (stage_root / "command.stderr.log").write_text(outcome.stderr, encoding="utf-8")
        artifact_source = root / "lab-artifacts"
        artifact_destination = stage_root / "lab-artifacts"
        if artifact_source.is_dir():
            if artifact_destination.exists():
                shutil.rmtree(artifact_destination)
            shutil.copytree(artifact_source, artifact_destination)
        return {
            "id": stage["id"],
            "type": "runtime",
            "required": bool(stage.get("required", True)),
            "status": "PASS" if outcome.returncode == 0 else "FAIL",
            "scenario": str(materialized),
            "runtime_cannon_name": runtime_name,
            "runtime_candidate_sha256": candidate["sha256"],
            "evidence_directory": str(stage_root),
            "commands": [command_record(command, outcome, None)],
        }
    finally:
        for path in (cannon_asset, scenario_asset, lock):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def planned_stage(
    root: Path,
    candidate: dict[str, Any],
    stage: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": stage["id"],
        "type": stage["type"],
        "required": bool(stage.get("required", True)),
        "status": "PLANNED",
    }
    if stage["type"] in {"scenario-integrity", "runtime"}:
        scenario, runtime_name = materialize_scenario(root, candidate, stage, output_root)
        row["scenario"] = str(scenario)
        row["runtime_cannon_name"] = runtime_name
    return row


def required_failure(stages: Iterable[dict[str, Any]]) -> bool:
    return any(
        bool(stage.get("required", True)) and stage.get("status") == "FAIL"
        for stage in stages
    )


def build_plugin(root: Path, runner: CommandRunner, timeout_seconds: int) -> dict[str, Any]:
    command = ["gradle", "clean", "build", "--stacktrace"]
    outcome = runner(command, root, None, timeout_seconds)
    return {
        "status": "PASS" if outcome.returncode == 0 else "FAIL",
        "command": command_record(command, outcome, None),
    }


def run_campaign(
    manifest_path: Path,
    output_root: Path,
    *,
    root: Path,
    mode: str,
    runner: CommandRunner = default_runner,
) -> dict[str, Any]:
    if mode not in {"plan", "static", "execute"}:
        raise CampaignError("mode must be plan, static, or execute")
    root = root.resolve()
    manifest_path = resolve_repo_path(root, manifest_path)
    output_root = resolve_repo_path(root, output_root, must_exist=False)
    manifest = read_json(manifest_path)
    validate_manifest(manifest)
    campaign_id = clean_identifier(manifest["id"], "campaign id")
    campaign_root = output_root / campaign_id
    report_path = campaign_root / "campaign-report.json"
    if report_path.exists():
        raise CampaignError(f"campaign output already contains a report: {report_path}")
    campaign_root.mkdir(parents=True, exist_ok=True)

    candidates = candidate_rows(root, manifest)
    static_stages = [stage for stage in manifest["stages"] if stage["type"] != "runtime"]
    runtime_stages = [stage for stage in manifest["stages"] if stage["type"] == "runtime"]
    policy = manifest.get("policy") or {}
    stop_required = bool(policy.get("stop_on_required_failure", True))
    max_runtime = int(policy.get("max_runtime_candidates", 1))

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        row = {
            "id": candidate["id"],
            "priority": candidate["priority"],
            "source": str(candidate["source"]),
            "sha256": candidate["sha256"],
            "metadata": candidate["metadata"],
            "delivery": deliver_candidate(candidate, campaign_root),
            "stages": [],
            "status": "DELIVERED",
        }
        for stage in static_stages:
            if mode == "plan":
                stage_result = planned_stage(root, candidate, stage, campaign_root)
            elif stage["type"] == "static":
                stage_result = run_static_stage(root, candidate, stage, runner)
            else:
                stage_result = run_scenario_integrity_stage(
                    root, candidate, stage, campaign_root, runner
                )
            row["stages"].append(stage_result)
            if mode != "plan" and stop_required and required_failure(row["stages"]):
                break
        if mode == "plan":
            row["status"] = "DELIVERED_PLAN"
        elif required_failure(row["stages"]):
            row["status"] = "DELIVERED_STATIC_FAIL"
        else:
            row["status"] = "DELIVERED_STATIC_PASS"
        results.append(row)

    build = None
    if mode == "plan":
        by_id = {candidate["id"]: candidate for candidate in candidates}
        for row in results:
            for stage in runtime_stages:
                row["stages"].append(
                    planned_stage(root, by_id[row["id"]], stage, campaign_root)
                )
    elif mode == "execute" and runtime_stages:
        eligible = [row for row in results if row["status"] == "DELIVERED_STATIC_PASS"]
        selected_ids = {row["id"] for row in eligible[:max_runtime]}
        if bool(policy.get("build_plugin", True)) and selected_ids:
            build = build_plugin(root, runner, int(policy.get("build_timeout_seconds", 600)))
            if build["status"] != "PASS":
                for row in eligible:
                    if row["id"] in selected_ids:
                        row["status"] = "DELIVERED_RUNTIME_BLOCKED_BUILD"
                selected_ids = set()
        by_id = {candidate["id"]: candidate for candidate in candidates}
        for row in results:
            if row["status"] != "DELIVERED_STATIC_PASS":
                continue
            if row["id"] not in selected_ids:
                row["status"] = "DELIVERED_RUNTIME_SKIPPED_BUDGET"
                continue
            candidate = by_id[row["id"]]
            for stage in runtime_stages:
                row["stages"].append(
                    run_runtime_stage(root, candidate, stage, campaign_root, runner)
                )
                if stop_required and required_failure(row["stages"]):
                    break
            row["status"] = (
                "DELIVERED_RUNTIME_FAIL"
                if required_failure(row["stages"])
                else "DELIVERED_RUNTIME_PASS"
            )

    if mode == "plan":
        status = "PLAN"
        promoted: list[dict[str, Any]] = []
    elif mode == "static" or not runtime_stages:
        promoted = [row for row in results if row["status"] == "DELIVERED_STATIC_PASS"]
        status = "PASS" if promoted else "FAIL"
    else:
        promoted = [row for row in results if row["status"] == "DELIVERED_RUNTIME_PASS"]
        status = "PASS" if promoted else "FAIL"

    report = {
        "schema_version": 1,
        "status": status,
        "mode": mode,
        "campaign_id": campaign_id,
        "manifest": str(manifest_path),
        "output_directory": str(campaign_root),
        "build": build,
        "summary": {
            "candidate_count": len(results),
            "delivered_count": sum(
                bool(row["delivery"]["delivered_before_testing"]) for row in results
            ),
            "static_pass_count": sum(
                row["status"]
                in {
                    "DELIVERED_STATIC_PASS",
                    "DELIVERED_RUNTIME_PASS",
                    "DELIVERED_RUNTIME_FAIL",
                    "DELIVERED_RUNTIME_SKIPPED_BUDGET",
                    "DELIVERED_RUNTIME_BLOCKED_BUILD",
                }
                for row in results
            ),
            "runtime_pass_count": sum(
                row["status"] == "DELIVERED_RUNTIME_PASS" for row in results
            ),
            "runtime_fail_count": sum(
                row["status"] == "DELIVERED_RUNTIME_FAIL" for row in results
            ),
            "runtime_budget": max_runtime,
        },
        "candidates": results,
        "promotion": {
            "status": (
                "LOCAL_RUNTIME_CANDIDATE"
                if status == "PASS" and mode == "execute" and runtime_stages
                else "NO_RUNTIME_PROMOTION"
            ),
            "winner_ids": [row["id"] for row in promoted],
        },
        "truth_boundary": {
            "candidate_is_exported_even_when_a_gate_fails": True,
            "static_pass_proves_runtime_function": False,
            "local_runtime_pass_proves_private_extremecraft_parity": False,
            "runtime_budget_skip_marks_candidate_failed": False,
            "ec_ready": False,
        },
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deliver every cannon candidate first, reject cheap failures early, and run only a bounded "
            "set through real CannonLab runtime stages"
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=("plan", "static", "execute"), default="plan")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    try:
        report = run_campaign(
            args.manifest,
            args.output_directory,
            root=args.repo_root,
            mode=args.mode,
        )
    except (OSError, json.JSONDecodeError, CampaignError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
    if args.json_out:
        write_json(
            resolve_repo_path(args.repo_root.resolve(), args.json_out, must_exist=False),
            report,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"PASS", "PLAN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
