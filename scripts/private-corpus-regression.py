#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
AUDITOR = SCRIPTS / "audit-cannon-corpus.py"
REGRESSION_ROOT = ROOT / "corpus-regressions"
EXTENSIONS = {".schem", ".litematic"}


def allowed_path(raw: str | Path, *, directory: bool = False) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"path escapes CannonLab repository/output roots: {raw}")
    if directory and not path.is_dir():
        raise NotADirectoryError(path)
    if not directory and not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return value[:72] or "private-corpus"


def inventory(directory: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        rows.append({
            "relative_path": str(path.relative_to(directory)).replace("\\", "/"),
            "suffix": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    if not rows:
        raise ValueError(f"no .schem or .litematic files under {directory}")
    return rows


def compare_inventory(current: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    current_by_path = {str(row["relative_path"]): row for row in current}
    baseline_by_path = {str(row["relative_path"]): row for row in baseline}
    added = sorted(set(current_by_path) - set(baseline_by_path))
    removed = sorted(set(baseline_by_path) - set(current_by_path))
    changed = sorted(
        path for path in set(current_by_path) & set(baseline_by_path)
        if current_by_path[path].get("sha256") != baseline_by_path[path].get("sha256")
    )
    unchanged = sorted(
        path for path in set(current_by_path) & set(baseline_by_path)
        if current_by_path[path].get("sha256") == baseline_by_path[path].get("sha256")
    )
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
        "drift": bool(added or removed or changed),
    }


def run_structural_audit(directory: Path, output: Path, chunk_limit: int) -> tuple[int, dict[str, Any]]:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            str(directory),
            "--chunk-limit",
            str(chunk_limit),
            "--json-out",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=1200,
    )
    if output.is_file():
        report = json.loads(output.read_text(encoding="utf-8"))
    else:
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = {
                "status": "ERROR",
                "error": result.stderr[-3000:] or result.stdout[-3000:],
            }
    return result.returncode, report


def regression_job(
    directory_raw: str,
    *,
    job: str,
    chunk_limit: int,
    baseline_raw: str | None,
    require_unchanged_sources: bool,
) -> dict[str, Any]:
    directory = allowed_path(directory_raw, directory=True)
    slug = slugify(job or directory.name)
    job_dir = REGRESSION_ROOT / slug
    job_dir.mkdir(parents=True, exist_ok=True)
    current = inventory(directory)

    baseline_path: Path | None = None
    baseline_payload: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    if baseline_raw:
        baseline_path = allowed_path(baseline_raw)
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline_payload.get("schema") != "cannonlab-private-corpus-regression-v1":
            raise ValueError("unsupported baseline corpus manifest schema")
        comparison = compare_inventory(current, list(baseline_payload.get("sources", [])))

    structural_path = job_dir / "structural-report.json"
    audit_code, structural = run_structural_audit(directory, structural_path, chunk_limit)
    blockers: list[dict[str, str]] = []
    if audit_code != 0 or str(structural.get("status", "")).upper() in {"FAIL", "ERROR", "BLOCKED"}:
        blockers.append({
            "code": "structural-corpus-audit-failed",
            "message": f"audit-cannon-corpus exited {audit_code} with status {structural.get('status')}",
        })
    if require_unchanged_sources and comparison and comparison["drift"]:
        blockers.append({
            "code": "private-source-drift",
            "message": "private corpus filenames or SHA-256 hashes changed from the baseline",
        })

    payload = {
        "schema": "cannonlab-private-corpus-regression-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": (
            "This manifest records private source hashes and structural comparison only. It does not publish binaries, "
            "prove runtime behavior, or promote local results to ExtremeCraft."
        ),
        "job": slug,
        "source_directory": str(directory),
        "source_count": len(current),
        "sources": current,
        "baseline_manifest": str(baseline_path) if baseline_path else None,
        "source_comparison": comparison,
        "chunk_limit": chunk_limit,
        "structural_report": str(structural_path.relative_to(ROOT)).replace("\\", "/"),
        "structural_status": structural.get("status"),
        "blockers": blockers,
    }
    manifest = job_dir / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    payload["manifest"] = str(manifest.relative_to(ROOT)).replace("\\", "/")
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hash, structurally audit, and regression-check a private CannonLab corpus without publishing it"
    )
    parser.add_argument("directory")
    parser.add_argument("--job", default="")
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--baseline-manifest", default="")
    parser.add_argument("--require-unchanged-sources", action="store_true")
    args = parser.parse_args()
    if args.chunk_limit < 1:
        parser.error("chunk limit must be positive")
    result = regression_job(
        args.directory,
        job=args.job,
        chunk_limit=args.chunk_limit,
        baseline_raw=args.baseline_manifest or None,
        require_unchanged_sources=args.require_unchanged_sources,
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
