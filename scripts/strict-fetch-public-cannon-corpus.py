#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


class StrictFetchError(ValueError):
    pass


def load_fetcher() -> Any:
    script = Path(__file__).resolve().with_name("fetch-public-cannon-corpus.py")
    spec = importlib.util.spec_from_file_location("cannonlab_fetch_public_corpus", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_fetch_report(
    report: dict[str, Any],
    *,
    mode: str,
    skip_audit: bool,
) -> dict[str, Any]:
    value = dict(report)
    rows = value.get("sources")
    failures: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        failures.append({"issue": "sources_missing_or_not_list"})
        rows = []

    if mode == "plan":
        if value.get("status") != "PLAN":
            failures.append({"issue": "plan_status_not_plan", "status": value.get("status")})
        for row in rows:
            if not isinstance(row, dict) or row.get("status") != "PLANNED":
                failures.append(
                    {
                        "issue": "source_not_planned",
                        "source": row.get("id") if isinstance(row, dict) else None,
                    }
                )
    else:
        for row in rows:
            if not isinstance(row, dict):
                failures.append({"issue": "source_row_not_object"})
                continue
            source_id = row.get("id")
            if row.get("status") != "FETCHED":
                failures.append(
                    {
                        "issue": "source_not_fetched",
                        "source": source_id,
                        "status": row.get("status"),
                    }
                )
            pin_status = row.get("pin_status")
            if pin_status not in {"PINNED_HASH_VERIFIED", "NEW_HASH_ACCEPTED"}:
                failures.append(
                    {
                        "issue": "source_hash_not_verified",
                        "source": source_id,
                        "pin_status": pin_status,
                    }
                )
            audit = row.get("audit")
            if skip_audit:
                if not isinstance(audit, dict) or audit.get("status") != "SKIPPED":
                    failures.append(
                        {
                            "issue": "audit_not_explicitly_skipped",
                            "source": source_id,
                        }
                    )
                continue
            if not isinstance(audit, dict):
                failures.append({"issue": "audit_missing", "source": source_id})
                continue
            audit_status = audit.get("status")
            audit_returncode = audit.get("returncode")
            if audit_status not in {"PASS", "STATIC_FAIL"}:
                failures.append(
                    {
                        "issue": "audit_not_completed",
                        "source": source_id,
                        "audit_status": audit_status,
                        "audit_returncode": audit_returncode,
                    }
                )
            if not audit.get("report"):
                failures.append({"issue": "audit_report_missing", "source": source_id})
            if not isinstance(audit_returncode, int):
                failures.append(
                    {
                        "issue": "audit_returncode_missing",
                        "source": source_id,
                    }
                )
            elif audit_returncode not in {0, 3}:
                failures.append(
                    {
                        "issue": "audit_process_failed",
                        "source": source_id,
                        "audit_returncode": audit_returncode,
                    }
                )

    expected_count = None
    summary = value.get("summary")
    if isinstance(summary, dict):
        expected_count = summary.get("source_count")
    if isinstance(expected_count, int) and expected_count != len(rows):
        failures.append(
            {
                "issue": "summary_source_count_mismatch",
                "summary": expected_count,
                "actual": len(rows),
            }
        )

    value["strict_validation"] = {
        "status": "PASS" if not failures else "FAIL",
        "failure_count": len(failures),
        "failures": failures,
        "audit_required": mode == "fetch" and not skip_audit,
    }
    if failures:
        value["status"] = "FAIL"
    value.setdefault("truth_boundary", {})
    value["truth_boundary"]["strict_fetch_validation_passed"] = not failures
    value["truth_boundary"]["ec_ready"] = False
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run public cannon corpus intake and fail closed unless every source is hash-verified "
            "and every requested audit produced a complete PASS or STATIC_FAIL report"
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=("plan", "fetch"), default="plan")
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--write-lock", type=Path)
    parser.add_argument("--accept-new-hashes", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    fetcher = load_fetcher()
    try:
        report = fetcher.run_corpus(
            args.manifest.resolve(),
            args.output_directory.resolve(),
            repo_root=args.repo_root.resolve(),
            mode=args.mode,
            lock_path=args.lock_file.resolve() if args.lock_file else None,
            write_lock_path=args.write_lock.resolve() if args.write_lock else None,
            accept_new_hashes=args.accept_new_hashes,
            skip_audit=args.skip_audit,
        )
        report = validate_fetch_report(
            report,
            mode=args.mode,
            skip_audit=args.skip_audit,
        )
        if report.get("status") == "FAIL" and args.write_lock:
            try:
                args.write_lock.resolve().unlink()
            except FileNotFoundError:
                pass
        corpus_id = report.get("corpus_id")
        if isinstance(corpus_id, str) and corpus_id:
            write_json(
                args.output_directory.resolve() / corpus_id / "corpus-report.json",
                report,
            )
    except (OSError, json.JSONDecodeError, StrictFetchError, ValueError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "strict_validation": {
                "status": "FAIL",
                "failure_count": 1,
                "failures": [{"issue": "strict_fetch_exception", "detail": str(exc)}],
            },
            "truth_boundary": {
                "strict_fetch_validation_passed": False,
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
        if args.write_lock:
            try:
                args.write_lock.resolve().unlink()
            except FileNotFoundError:
                pass

    if args.json_out:
        write_json(args.json_out.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"PASS", "PLAN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
