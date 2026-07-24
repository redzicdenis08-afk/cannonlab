#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
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
AUDITOR = load_script(
    "native_durability_result_auditor",
    ROOT / "scripts" / "assert-native-durability-result.py",
)


def write_summary(root: Path, shot: dict[str, Any], *, effective_mode: str = "NATIVE") -> None:
    run = root / "run"
    run.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": "synthetic-native-durability",
        "finish_reason": "complete",
        "shots_requested": 1,
        "shots_completed": 1,
        "durability": {
            "configured_mode": "AUTO",
            "effective_mode": effective_mode,
        },
        "shots": [shot],
    }
    (run / "run-summary.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def shot(**overrides: Any) -> dict[str, Any]:
    payload = {
        "shot": 1,
        "contract_pass": True,
        "error": None,
        "target_blocks_destroyed": 1,
        "target_peak_destroyed": 0,
        "target_ever_destroyed": 0,
        "max_layer_breached": 0,
    }
    payload.update(overrides)
    return payload


def audit(root: Path, *, min_layer: int = 1) -> dict[str, Any]:
    return AUDITOR.audit_results(
        root,
        expected_shots=1,
        min_final_destroyed=1,
        min_effective_peak_destroyed=1,
        min_effective_layer_breached=min_layer,
    )


def test_late_final_break_reconciles_one_layer() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        write_summary(root, shot())
        report = audit(root)
        assert report["status"] == "PASS", report
        assert report["reconciliation_count"] == 1, report
        result = report["shots"][0]
        assert result["reported"]["target_peak_destroyed"] == 0, result
        assert result["reported"]["max_layer_breached"] == 0, result
        assert result["effective_lower_bounds"]["target_peak_destroyed"] == 1, result
        assert result["effective_lower_bounds"]["target_ever_destroyed"] == 1, result
        assert result["effective_lower_bounds"]["max_layer_breached"] == 1, result
        assert report["truth_boundary"]["final_state_infers_layers_beyond_first"] is False


def test_final_state_does_not_infer_two_layers() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        write_summary(root, shot())
        report = audit(root, min_layer=2)
        assert report["status"] == "FAIL", report
        assert any("effective_max_layer_breached=1 below 2" in row for row in report["failures"])


def test_no_final_break_stays_failed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        write_summary(root, shot(target_blocks_destroyed=0))
        report = audit(root)
        assert report["status"] == "FAIL", report
        assert report["reconciliation_count"] == 0, report


def test_observed_metrics_need_no_reconciliation() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        write_summary(
            root,
            shot(
                target_blocks_destroyed=1,
                target_peak_destroyed=3,
                target_ever_destroyed=4,
                max_layer_breached=2,
            ),
        )
        report = audit(root, min_layer=2)
        assert report["status"] == "PASS", report
        assert report["reconciliation_count"] == 0, report


def test_non_native_mode_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        write_summary(root, shot(), effective_mode="SIMULATE")
        report = audit(root)
        assert report["status"] == "FAIL", report
        assert any("effective_mode='SIMULATE'" in row for row in report["failures"])


def main() -> None:
    tests = [
        test_late_final_break_reconciles_one_layer,
        test_final_state_does_not_infer_two_layers,
        test_no_final_break_stays_failed,
        test_observed_metrics_need_no_reconciliation,
        test_non_native_mode_fails,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} native durability reconciliation regressions passed.")


if __name__ == "__main__":
    main()
