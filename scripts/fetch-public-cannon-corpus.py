#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class CorpusError(ValueError):
    pass


ALLOWED_EXTENSIONS = {".schematic", ".schem", ".litematic"}
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CorpusError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clean_identifier(raw: Any, label: str) -> str:
    value = str(raw or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not value or any(character not in allowed for character in value):
        raise CorpusError(f"{label} must use letters, digits, dot, dash, or underscore")
    return value


def validate_https_url(raw: Any, allowed_hosts: set[str], label: str) -> str:
    value = str(raw or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https":
        raise CorpusError(f"{label} must use https")
    host = (parsed.hostname or "").lower()
    if not host or host not in allowed_hosts:
        raise CorpusError(f"{label} host is not allowlisted: {host!r}")
    if parsed.username or parsed.password:
        raise CorpusError(f"{label} must not contain credentials")
    if parsed.fragment:
        raise CorpusError(f"{label} must not contain a fragment")
    return value


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if int(manifest.get("schema_version", 0)) != 1:
        raise CorpusError("corpus schema_version must equal 1")
    corpus_id = clean_identifier(manifest.get("id"), "corpus id")
    policy = manifest.get("policy") or {}
    if not isinstance(policy, dict):
        raise CorpusError("policy must be an object")
    raw_hosts = policy.get("allowed_hosts")
    if not isinstance(raw_hosts, list) or not raw_hosts:
        raise CorpusError("policy.allowed_hosts must be a non-empty list")
    allowed_hosts = {str(host).strip().lower() for host in raw_hosts if str(host).strip()}
    if len(allowed_hosts) != len(raw_hosts):
        raise CorpusError("policy.allowed_hosts contains duplicates or empty values")
    max_bytes = int(policy.get("max_bytes_per_file", DEFAULT_MAX_BYTES))
    if max_bytes <= 0 or max_bytes > 512 * 1024 * 1024:
        raise CorpusError("policy.max_bytes_per_file must be between 1 and 536870912")
    if str(policy.get("repository_storage", "")) != "fetch-only":
        raise CorpusError("policy.repository_storage must equal fetch-only")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CorpusError("corpus requires at least one source")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in sources:
        if not isinstance(raw, dict):
            raise CorpusError("every source must be an object")
        source_id = clean_identifier(raw.get("id"), "source id")
        if source_id in seen:
            raise CorpusError(f"duplicate source id: {source_id}")
        seen.add(source_id)
        filename = Path(str(raw.get("filename", "")).strip()).name
        if not filename or filename != str(raw.get("filename", "")).strip():
            raise CorpusError(f"source {source_id}: filename must be a plain basename")
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise CorpusError(f"source {source_id}: unsupported extension {extension!r}")
        download_url = validate_https_url(
            raw.get("download_url"), allowed_hosts, f"source {source_id} download_url"
        )
        source_page = validate_https_url(
            raw.get("source_page"), allowed_hosts, f"source {source_id} source_page"
        )
        authors = raw.get("authors")
        if not isinstance(authors, list) or not authors or any(
            not isinstance(author, str) or not author.strip() for author in authors
        ):
            raise CorpusError(f"source {source_id}: authors must be a non-empty string list")
        capabilities = raw.get("claimed_capabilities", [])
        if not isinstance(capabilities, list) or any(
            not isinstance(value, str) or not value.strip() for value in capabilities
        ):
            raise CorpusError(f"source {source_id}: claimed_capabilities must be a string list")
        if str(raw.get("redistribution", "")) != "fetch-only":
            raise CorpusError(f"source {source_id}: redistribution must equal fetch-only")
        if str(raw.get("license_status", "")) not in {
            "not-stated",
            "permission-stated",
            "open-license",
        }:
            raise CorpusError(
                f"source {source_id}: license_status must be not-stated, permission-stated, or open-license"
            )
        expected = raw.get("expected_sha256")
        if expected is not None:
            expected = str(expected).strip().lower()
            if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
                raise CorpusError(f"source {source_id}: expected_sha256 is invalid")
        normalized.append(
            {
                **raw,
                "id": source_id,
                "filename": filename,
                "download_url": download_url,
                "source_page": source_page,
                "authors": [author.strip() for author in authors],
                "claimed_capabilities": [value.strip() for value in capabilities],
                "expected_sha256": expected,
            }
        )
    return {
        "schema_version": 1,
        "id": corpus_id,
        "policy": {
            **policy,
            "allowed_hosts": sorted(allowed_hosts),
            "max_bytes_per_file": max_bytes,
        },
        "sources": normalized,
    }


def read_lock(path: Path | None, corpus_id: str) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"schema_version": 1, "corpus_id": corpus_id, "sources": {}}
    lock = read_json(path)
    if int(lock.get("schema_version", 0)) != 1:
        raise CorpusError("lock schema_version must equal 1")
    if str(lock.get("corpus_id", "")) != corpus_id:
        raise CorpusError("lock corpus_id does not match manifest")
    sources = lock.get("sources")
    if not isinstance(sources, dict):
        raise CorpusError("lock sources must be an object")
    return lock


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_html(prefix: bytes, content_type: str) -> bool:
    lowered_type = content_type.lower()
    if "text/html" in lowered_type or "application/xhtml" in lowered_type:
        return True
    sample = prefix.lstrip().lower()
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html")


def stream_response_to_file(response: Any, destination: Path, max_bytes: int) -> dict[str, Any]:
    content_type = str(response.headers.get("Content-Type", ""))
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise CorpusError("invalid Content-Length header") from exc
        if declared_bytes < 0 or declared_bytes > max_bytes:
            raise CorpusError(f"download Content-Length exceeds limit: {declared_bytes}")
    digest = hashlib.sha256()
    total = 0
    prefix = b""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        while True:
            chunk = response.read(min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise CorpusError(f"download exceeds {max_bytes} bytes")
            if len(prefix) < 1024:
                prefix += chunk[: 1024 - len(prefix)]
            digest.update(chunk)
            handle.write(chunk)
    if total == 0:
        raise CorpusError("download is empty")
    if sniff_html(prefix, content_type):
        raise CorpusError("download returned HTML instead of a schematic")
    return {
        "sha256": digest.hexdigest(),
        "bytes": total,
        "content_type": content_type or None,
    }


def download_source(source: dict[str, Any], destination: Path, allowed_hosts: set[str], max_bytes: int) -> dict[str, Any]:
    request = urllib.request.Request(
        source["download_url"],
        headers={
            "User-Agent": "CannonLab-Public-Corpus/1.0",
            "Accept": "application/octet-stream,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            final_url = response.geturl()
            validate_https_url(final_url, allowed_hosts, f"source {source['id']} redirect")
            streamed = stream_response_to_file(response, destination, max_bytes)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CorpusError(f"source {source['id']} download failed: {exc}") from exc
    return {**streamed, "final_url": final_url}


def expected_hash_for(source: dict[str, Any], lock: dict[str, Any]) -> str | None:
    manifest_hash = source.get("expected_sha256")
    locked = lock.get("sources", {}).get(source["id"])
    lock_hash = locked.get("sha256") if isinstance(locked, dict) else None
    if manifest_hash and lock_hash and manifest_hash != lock_hash:
        raise CorpusError(f"source {source['id']}: manifest and lock hashes disagree")
    return manifest_hash or lock_hash


def verify_or_record_hash(
    source: dict[str, Any],
    observed_sha256: str,
    expected_sha256: str | None,
    accept_new_hashes: bool,
) -> str:
    if expected_sha256 is None:
        if not accept_new_hashes:
            raise CorpusError(
                f"source {source['id']} is unpinned; rerun with --accept-new-hashes to create a lock"
            )
        return "NEW_HASH_ACCEPTED"
    if observed_sha256 != expected_sha256:
        raise CorpusError(
            f"source {source['id']} hash mismatch expected={expected_sha256} observed={observed_sha256}"
        )
    return "PINNED_HASH_VERIFIED"


def run_audit(repo_root: Path, source: dict[str, Any], file_path: Path, audit_path: Path, chunk_limit: int) -> dict[str, Any]:
    extension = file_path.suffix.lower()
    if extension == ".schematic":
        command = [
            sys.executable,
            str(repo_root / "scripts" / "legacy-schematic-audit.py"),
            str(file_path),
            "--chunk-limit",
            str(chunk_limit),
            "--json-out",
            str(audit_path),
        ]
    else:
        command = [
            sys.executable,
            str(repo_root / "scripts" / "schem-audit.py"),
            str(file_path),
            "--chunk-limit",
            str(chunk_limit),
            "--json-out",
            str(audit_path),
        ]
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    payload = None
    if audit_path.exists():
        try:
            payload = read_json(audit_path)
        except (OSError, json.JSONDecodeError, CorpusError):
            payload = None
    return {
        "command": command,
        "returncode": result.returncode,
        "status": payload.get("status") if isinstance(payload, dict) else "ERROR",
        "classification": payload.get("classification") if isinstance(payload, dict) else None,
        "report": str(audit_path) if audit_path.exists() else None,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def source_lock_row(source: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "sha256": result["sha256"],
        "bytes": result["bytes"],
        "filename": source["filename"],
        "download_url": source["download_url"],
        "source_page": source["source_page"],
        "authors": source["authors"],
        "redistribution": source["redistribution"],
    }


def run_corpus(
    manifest_path: Path,
    output_directory: Path,
    *,
    repo_root: Path,
    mode: str,
    lock_path: Path | None,
    write_lock_path: Path | None,
    accept_new_hashes: bool,
    skip_audit: bool,
) -> dict[str, Any]:
    if mode not in {"plan", "fetch"}:
        raise CorpusError("mode must be plan or fetch")
    manifest = validate_manifest(read_json(manifest_path))
    lock = read_lock(lock_path, manifest["id"])
    allowed_hosts = set(manifest["policy"]["allowed_hosts"])
    max_bytes = int(manifest["policy"]["max_bytes_per_file"])
    chunk_limit = int(manifest["policy"].get("chunk_limit", 160))
    if chunk_limit <= 0:
        raise CorpusError("policy.chunk_limit must be positive")
    corpus_root = output_directory / manifest["id"]
    files_root = corpus_root / "files"
    audits_root = corpus_root / "audits"
    corpus_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    new_lock = {"schema_version": 1, "corpus_id": manifest["id"], "sources": {}}
    for source in manifest["sources"]:
        expected = expected_hash_for(source, lock)
        row: dict[str, Any] = {
            "id": source["id"],
            "source_page": source["source_page"],
            "download_url": source["download_url"],
            "filename": source["filename"],
            "authors": source["authors"],
            "claimed_capabilities": source["claimed_capabilities"],
            "target_environment": source.get("target_environment"),
            "license_status": source["license_status"],
            "redistribution": source["redistribution"],
            "expected_sha256": expected,
            "status": "PLANNED" if mode == "plan" else "PENDING",
        }
        if mode == "plan":
            rows.append(row)
            continue

        final_path = files_root / source["id"] / source["filename"]
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"cannonlab-corpus-{source['id']}-") as temporary:
            temporary_path = Path(temporary) / source["filename"]
            downloaded = download_source(source, temporary_path, allowed_hosts, max_bytes)
            pin_status = verify_or_record_hash(
                source, downloaded["sha256"], expected, accept_new_hashes
            )
            if final_path.exists():
                existing_hash = sha256_file(final_path)
                if existing_hash != downloaded["sha256"]:
                    raise CorpusError(
                        f"source {source['id']}: refusing to overwrite different cached bytes"
                    )
            else:
                shutil.copy2(temporary_path, final_path)
        row.update(downloaded)
        row["pin_status"] = pin_status
        row["path"] = str(final_path)
        if skip_audit:
            row["audit"] = {"status": "SKIPPED"}
        else:
            audit_path = audits_root / f"{source['id']}.json"
            row["audit"] = run_audit(
                repo_root, source, final_path, audit_path, chunk_limit
            )
        row["status"] = "FETCHED"
        rows.append(row)
        new_lock["sources"][source["id"]] = source_lock_row(source, row)

    if mode == "fetch" and write_lock_path is not None:
        write_json(write_lock_path, new_lock)
    report = {
        "schema_version": 1,
        "status": "PLAN" if mode == "plan" else "PASS",
        "mode": mode,
        "corpus_id": manifest["id"],
        "manifest": str(manifest_path),
        "lock_input": str(lock_path) if lock_path else None,
        "lock_output": str(write_lock_path) if write_lock_path else None,
        "output_directory": str(corpus_root),
        "summary": {
            "source_count": len(rows),
            "fetched_count": sum(row["status"] == "FETCHED" for row in rows),
            "pinned_verified_count": sum(
                row.get("pin_status") == "PINNED_HASH_VERIFIED" for row in rows
            ),
            "new_hash_count": sum(
                row.get("pin_status") == "NEW_HASH_ACCEPTED" for row in rows
            ),
            "audit_completed_count": sum(
                isinstance(row.get("audit"), dict)
                and row["audit"].get("status") in {"PASS", "STATIC_FAIL"}
                for row in rows
            ),
        },
        "sources": rows,
        "truth_boundary": {
            "download_claims_are_source_metadata_not_lab_proof": True,
            "fetching_does_not_grant_redistribution_rights": True,
            "legacy_static_audit_proves_runtime_function": False,
            "local_runtime_pass_proves_private_extremecraft_parity": False,
            "ec_ready": False,
        },
    }
    write_json(corpus_root / "corpus-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a provenance-preserving public cannon corpus without vendoring third-party "
            "schematics into the repository"
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

    try:
        report = run_corpus(
            args.manifest.resolve(),
            args.output_directory.resolve(),
            repo_root=args.repo_root.resolve(),
            mode=args.mode,
            lock_path=args.lock_file.resolve() if args.lock_file else None,
            write_lock_path=args.write_lock.resolve() if args.write_lock else None,
            accept_new_hashes=args.accept_new_hashes,
            skip_audit=args.skip_audit,
        )
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError, CorpusError) as exc:
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
        write_json(args.json_out.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"PASS", "PLAN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
