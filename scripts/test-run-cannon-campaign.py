#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = load_script("staged_cannon_campaign", ROOT / "scripts" / "run-cannon-campaign.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_candidate(root: Path, name: str, *, mutate: bool = False) -> Path:
    source = ROOT / "cannons" / "probe-one-dispenser.schem.b64"
    raw = base64.b64decode(source.read_bytes())
    if mutate:
        raw += b"x"
    path = root / f"{name}.schem"
    path.write_bytes(raw)
    return path


def manifest(
    path: Path,
    candidates: list[Path],
    *,
    max_runtime_candidates: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "synthetic-campaign",
        "candidates": [
            {
                "id": f"candidate-{index + 1}",
                "path": relative(candidate),
                "sha256": digest(candidate),
                "priority": 100 - index,
            }
            for index, candidate in enumerate(candidates)
        ],
        "stages": [
            {
                "id": "static",
                "type": "static",
                "required": True,
                "chunk_limit": 160,
                "expect_format": "sponge-v2",
            },
            {
                "id": "truth",
                "type": "scenario-integrity",
                "required": True,
                "scenario": "scenarios/probe-redstone-endurance.yml",
            },
            {
                "id": "runtime",
                "type": "runtime",
                "required": True,
                "scenario": "scenarios/probe-redstone-endurance.yml",
                "expected_shots": 1,
                "timeout_seconds": 60,
                "environment": {
                    "CANNONLAB_STRICT_SINGLE_TNT": "true",
                    "CANNONLAB_MIN_TNT_PER_SHOT": "1",
                    "CANNONLAB_MIN_EXPLOSIONS_PER_SHOT": "1",
                },
            },
        ],
        "policy": {
            "stop_on_required_failure": True,
            "max_runtime_candidates": max_runtime_candidates,
            "build_plugin": True,
            "build_timeout_seconds": 60,
        },
    }


class FakeRunner:
    def __init__(self, *, fail_static: bool = False, fail_runtime: bool = False) -> None:
        self.fail_static = fail_static
        self.fail_runtime = fail_runtime
        self.calls: list[dict[str, Any]] = []
        self.runtime_candidates: list[str] = []

    def __call__(
        self,
        command: list[str],
        cwd: Path,
        environment: dict[str, str] | None,
        timeout_seconds: int,
    ) -> Any:
        self.calls.append(
            {
                "command": list(command),
                "cwd": cwd,
                "environment": environment,
                "timeout_seconds": timeout_seconds,
            }
        )
        joined = " ".join(command)
        if "schem-audit.py" in joined and self.fail_static:
            return CAMPAIGN.CommandOutcome(2, json.dumps({"status": "FAIL"}), "", 0.01)
        if any(name in joined for name in (
            "schem-audit.py",
            "paste-alignment-audit.py",
            "scenario-integrity-audit.py",
        )):
            return CAMPAIGN.CommandOutcome(0, json.dumps({"status": "PASS"}), "", 0.01)
        if command and command[0] == "gradle":
            return CAMPAIGN.CommandOutcome(0, "built", "", 0.01)
        if command and command[0] == "bash" and command[-1].endswith("cloud-smoke.sh"):
            assert environment is not None
            scenario = ROOT / "scenarios" / environment["CANNONLAB_SCENARIO"]
            assert scenario.is_file(), scenario
            text = scenario.read_text(encoding="utf-8")
            match = re.search(r"(?m)^\s*file:\s*(\S+)\s*$", text)
            assert match, text
            runtime_name = match.group(1)
            candidate_asset = ROOT / "cannons" / f"{runtime_name}.b64"
            assert candidate_asset.is_file(), {
                "scenario": scenario,
                "runtime_name": runtime_name,
                "expected_asset": candidate_asset,
            }
            decoded = base64.b64decode(candidate_asset.read_bytes())
            self.runtime_candidates.append(hashlib.sha256(decoded).hexdigest())
            artifacts = ROOT / "lab-artifacts"
            if artifacts.exists():
                shutil.rmtree(artifacts)
            artifacts.mkdir(parents=True)
            (artifacts / "synthetic-runtime.txt").write_text(runtime_name + "\n", encoding="utf-8")
            return CAMPAIGN.CommandOutcome(
                2 if self.fail_runtime else 0,
                "runtime complete",
                "synthetic failure" if self.fail_runtime else "",
                0.02,
            )
        raise AssertionError(f"unexpected command: {command}")


def temp_workspace() -> tempfile.TemporaryDirectory[str]:
    (ROOT / "lab-artifacts").mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="campaign-test-", dir=ROOT / "lab-artifacts")


def assert_no_runtime_residue() -> None:
    assert not (ROOT / ".campaign-runtime.lock").exists()
    assert not list((ROOT / "cannons").glob("campaign-*.schem.b64"))
    assert not list((ROOT / "scenarios").glob("campaign-*.yml"))


def test_plan_delivers_candidate_before_any_execution() -> None:
    with temp_workspace() as raw:
        work = Path(raw)
        candidate = make_candidate(work, "candidate")
        manifest_path = work / "manifest.json"
        write_json(manifest_path, manifest(manifest_path, [candidate]))
        runner = FakeRunner()
        report = CAMPAIGN.run_campaign(
            manifest_path,
            work / "output",
            root=ROOT,
            mode="plan",
            runner=runner,
        )
        assert report["status"] == "PLAN", report
        assert not runner.calls, runner.calls
        row = report["candidates"][0]
        delivered = Path(row["delivery"]["path"])
        assert delivered.is_file()
        assert digest(delivered) == digest(candidate)
        assert row["delivery"]["delivered_before_testing"] is True
        assert all(stage["status"] == "PLANNED" for stage in row["stages"])


def test_static_failure_stops_runtime_but_keeps_schematic() -> None:
    with temp_workspace() as raw:
        work = Path(raw)
        candidate = make_candidate(work, "candidate")
        manifest_path = work / "manifest.json"
        write_json(manifest_path, manifest(manifest_path, [candidate]))
        runner = FakeRunner(fail_static=True)
        report = CAMPAIGN.run_campaign(
            manifest_path,
            work / "output",
            root=ROOT,
            mode="execute",
            runner=runner,
        )
        assert report["status"] == "FAIL", report
        row = report["candidates"][0]
        assert row["status"] == "DELIVERED_STATIC_FAIL", row
        assert Path(row["delivery"]["path"]).is_file()
        assert not any(call["command"][0] == "bash" for call in runner.calls)
        assert_no_runtime_residue()


def test_runtime_uses_exact_delivered_candidate_and_cleans_assets() -> None:
    with temp_workspace() as raw:
        work = Path(raw)
        candidate = make_candidate(work, "candidate")
        manifest_path = work / "manifest.json"
        write_json(manifest_path, manifest(manifest_path, [candidate]))
        runner = FakeRunner()
        report = CAMPAIGN.run_campaign(
            manifest_path,
            work / "output",
            root=ROOT,
            mode="execute",
            runner=runner,
        )
        assert report["status"] == "PASS", report
        row = report["candidates"][0]
        assert row["status"] == "DELIVERED_RUNTIME_PASS", row
        assert runner.runtime_candidates == [digest(candidate)]
        runtime = next(stage for stage in row["stages"] if stage["type"] == "runtime")
        evidence = Path(runtime["evidence_directory"])
        assert (evidence / "lab-artifacts" / "synthetic-runtime.txt").is_file()
        assert_no_runtime_residue()


def test_runtime_failure_still_returns_candidate_and_evidence() -> None:
    with temp_workspace() as raw:
        work = Path(raw)
        candidate = make_candidate(work, "candidate")
        manifest_path = work / "manifest.json"
        write_json(manifest_path, manifest(manifest_path, [candidate]))
        report = CAMPAIGN.run_campaign(
            manifest_path,
            work / "output",
            root=ROOT,
            mode="execute",
            runner=FakeRunner(fail_runtime=True),
        )
        assert report["status"] == "FAIL", report
        row = report["candidates"][0]
        assert row["status"] == "DELIVERED_RUNTIME_FAIL", row
        assert Path(row["delivery"]["path"]).is_file()
        runtime = next(stage for stage in row["stages"] if stage["type"] == "runtime")
        assert Path(runtime["evidence_directory"]).is_dir()
        assert_no_runtime_residue()


def test_runtime_budget_selects_priority_winner_only() -> None:
    with temp_workspace() as raw:
        work = Path(raw)
        first = make_candidate(work, "first")
        second = make_candidate(work, "second", mutate=True)
        manifest_path = work / "manifest.json"
        write_json(
            manifest_path,
            manifest(manifest_path, [first, second], max_runtime_candidates=1),
        )
        runner = FakeRunner()
        report = CAMPAIGN.run_campaign(
            manifest_path,
            work / "output",
            root=ROOT,
            mode="execute",
            runner=runner,
        )
        assert report["status"] == "PASS", report
        assert runner.runtime_candidates == [digest(first)], runner.runtime_candidates
        statuses = {row["id"]: row["status"] for row in report["candidates"]}
        assert statuses == {
            "candidate-1": "DELIVERED_RUNTIME_PASS",
            "candidate-2": "DELIVERED_RUNTIME_SKIPPED_BUDGET",
        }, statuses
        assert all(Path(row["delivery"]["path"]).is_file() for row in report["candidates"])
        assert_no_runtime_residue()


def test_hash_drift_fails_before_delivery() -> None:
    with temp_workspace() as raw:
        work = Path(raw)
        candidate = make_candidate(work, "candidate")
        payload = manifest(work / "manifest.json", [candidate])
        payload["candidates"][0]["sha256"] = "0" * 64
        manifest_path = work / "manifest.json"
        write_json(manifest_path, payload)
        try:
            CAMPAIGN.run_campaign(
                manifest_path,
                work / "output",
                root=ROOT,
                mode="plan",
                runner=FakeRunner(),
            )
        except CAMPAIGN.CampaignError as exc:
            assert "hash mismatch" in str(exc), exc
        else:
            raise AssertionError("hash drift unexpectedly passed")


def main() -> None:
    tests = [
        test_plan_delivers_candidate_before_any_execution,
        test_static_failure_stops_runtime_but_keeps_schematic,
        test_runtime_uses_exact_delivered_candidate_and_cleans_assets,
        test_runtime_failure_still_returns_candidate_and_evidence,
        test_runtime_budget_selects_priority_winner_only,
        test_hash_drift_fails_before_delivery,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} staged cannon campaign regressions passed.")


if __name__ == "__main__":
    main()
