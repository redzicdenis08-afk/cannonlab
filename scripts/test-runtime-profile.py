#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "scripts" / "apply-runtime-profile.py"
AUDIT = ROOT / "scripts" / "audit-ec-parity.py"
PROFILE = ROOT / "profiles" / "extremecraft-observed.yml"
OBSERVATIONS = ROOT / "calibration" / "extremecraft-field-observations.yml"


def run(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([sys.executable, *args], text=True, capture_output=True)
    if result.returncode != expected:
        raise AssertionError(
            f"command failed ({result.returncode}, expected {expected}): {args}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cannonlab-profile-") as temporary:
        root = Path(temporary)
        server = root / "server"
        manifest = root / "manifest.json"
        sakura_path = server / "config" / "sakura-world-defaults.yml"
        sakura_path.parent.mkdir(parents=True, exist_ok=True)
        sakura_path.write_text(
            "_version: 12\n"
            "cannons:\n"
            "  hidden-stale-setting: true\n"
            "  merge-level: STRICT\n"
            "environment:\n"
            "  allow-water-in-the-nether: false\n",
            encoding="utf-8",
        )
        run(str(APPLY), str(PROFILE), "--server-root", str(server), "--manifest-out", str(manifest))

        sakura = yaml.safe_load(sakura_path.read_text(encoding="utf-8"))
        cannons = sakura["cannons"]
        assert "hidden-stale-setting" not in cannons
        assert sakura["environment"]["allow-water-in-the-nether"] is False
        assert cannons["merge-level"] == "NONE"
        assert cannons["load-chunks"] is False
        assert cannons["mechanics"]["tnt-spread"] == "Y"
        assert cannons["mechanics"]["mechanics-target"]["mechanic-version"] == "1.20.0"
        assert cannons["explosion"]["durable-materials"]["obsidian"]["durability"] == 4

        plugin = yaml.safe_load((server / "plugins" / "CannonLab" / "config.yml").read_text(encoding="utf-8"))
        assert plugin["limits"]["dispensers-per-chunk"] == 160
        assert plugin["parity-profile"]["id"] == "extremecraft-observed-2026-07-24"
        assert plugin["parity-profile"]["unknowns"]

        manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
        assert len(manifest_value["profile_sha256"]) == 64
        assert manifest_value["evidence_grade"] == "mixed"

        audit_out = root / "audit.json"
        run(str(AUDIT), str(PROFILE), str(OBSERVATIONS), "--json-out", str(audit_out), "--require-no-mismatch")
        audit = json.loads(audit_out.read_text(encoding="utf-8"))
        assert audit["matched_count"] == 7
        assert audit["mismatched_count"] == 0
        assert audit["unsupported_count"] == 0
        assert audit["open_probe_count"] >= 7

        mutated = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
        mutated["cannonlab"]["limits"]["dispensers-per-chunk"] = 128
        mutated_path = root / "mutated.yml"
        mutated_path.write_text(yaml.safe_dump(mutated, sort_keys=False), encoding="utf-8")
        failed = run(
            str(AUDIT),
            str(mutated_path),
            str(OBSERVATIONS),
            "--require-no-mismatch",
            expected=2,
        )
        mismatch = json.loads(failed.stdout)
        assert mismatch["mismatched_count"] == 1
        assert mismatch["mismatched"][0]["id"] == "dispenser-cap-per-chunk"

    print("runtime profile tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
