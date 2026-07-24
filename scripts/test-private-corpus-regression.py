#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "private-corpus-regression.py"
SPEC = importlib.util.spec_from_file_location("private_corpus_regression", SCRIPT)
assert SPEC and SPEC.loader
regression = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = regression
SPEC.loader.exec_module(regression)


class PrivateCorpusRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.corpus = self.root / "corpus"
        self.corpus.mkdir()
        (self.corpus / "a.schem").write_bytes(b"a")
        (self.corpus / "b.litematic").write_bytes(b"b")
        self.originals = {
            "ROOT": regression.ROOT,
            "OUTPUT_ROOT": regression.OUTPUT_ROOT,
            "SCRIPTS": regression.SCRIPTS,
            "AUDITOR": regression.AUDITOR,
            "REGRESSION_ROOT": regression.REGRESSION_ROOT,
        }
        regression.ROOT = self.root
        regression.OUTPUT_ROOT = self.output
        regression.SCRIPTS = self.root / "scripts"
        regression.SCRIPTS.mkdir()
        regression.AUDITOR = regression.SCRIPTS / "audit-cannon-corpus.py"
        regression.AUDITOR.write_text("# fixture\n", encoding="utf-8")
        regression.REGRESSION_ROOT = self.root / "corpus-regressions"
        self.addCleanup(self.restore)

    def restore(self) -> None:
        for name, value in self.originals.items():
            setattr(regression, name, value)

    def test_inventory_hashes_only_supported_files(self) -> None:
        (self.corpus / "ignore.txt").write_text("x", encoding="utf-8")
        rows = regression.inventory(self.corpus)
        self.assertEqual([row["relative_path"] for row in rows], ["a.schem", "b.litematic"])
        self.assertTrue(all(len(row["sha256"]) == 64 for row in rows))

    def test_inventory_requires_cannon_files(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(ValueError):
            regression.inventory(empty)

    def test_compare_inventory_detects_added_removed_and_changed(self) -> None:
        baseline = [
            {"relative_path": "a.schem", "sha256": "old"},
            {"relative_path": "removed.schem", "sha256": "same"},
        ]
        current = [
            {"relative_path": "a.schem", "sha256": "new"},
            {"relative_path": "added.schem", "sha256": "same"},
        ]
        result = regression.compare_inventory(current, baseline)
        self.assertEqual(result["changed"], ["a.schem"])
        self.assertEqual(result["added"], ["added.schem"])
        self.assertEqual(result["removed"], ["removed.schem"])
        self.assertTrue(result["drift"])

    def test_regression_job_records_hashes_and_structural_report(self) -> None:
        with mock.patch.object(regression, "run_structural_audit", return_value=(0, {"status": "PASS"})):
            result = regression.regression_job(
                str(self.corpus), job="corpus-test", chunk_limit=160,
                baseline_raw=None, require_unchanged_sources=False,
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source_count"], 2)
        self.assertTrue((regression.REGRESSION_ROOT / "corpus-test" / "manifest.json").is_file())
        self.assertIn("does not publish binaries", result["truth_boundary"])

    def test_require_unchanged_sources_blocks_drift(self) -> None:
        baseline = self.root / "baseline.json"
        baseline.write_text(json.dumps({
            "schema": "cannonlab-private-corpus-regression-v1",
            "sources": [{"relative_path": "a.schem", "sha256": "wrong"}],
        }), encoding="utf-8")
        with mock.patch.object(regression, "run_structural_audit", return_value=(0, {"status": "PASS"})):
            result = regression.regression_job(
                str(self.corpus), job="drift", chunk_limit=160,
                baseline_raw=str(baseline), require_unchanged_sources=True,
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("private-source-drift", {item["code"] for item in result["blockers"]})

    def test_structural_audit_failure_blocks(self) -> None:
        with mock.patch.object(regression, "run_structural_audit", return_value=(2, {"status": "FAIL"})):
            result = regression.regression_job(
                str(self.corpus), job="fail", chunk_limit=160,
                baseline_raw=None, require_unchanged_sources=False,
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("structural-corpus-audit-failed", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
