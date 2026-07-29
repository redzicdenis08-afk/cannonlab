#!/usr/bin/env python3
"""Fail-closed PhaseLab plugin-stack inventory, lock, verification, and staging.

This tool never downloads or guesses plugin versions. It inventories operator-supplied
JARs, can lock a profile only when explicitly labelled as a live-server export, and
stages files only after exact version/hash verification.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


EVIDENCE_FAILURE = 2
DEFAULT_CONFIG_EXTENSIONS = {".yml", ".yaml", ".json", ".conf", ".toml", ".properties"}
DEFAULT_EXCLUDED_CONFIG_DIRS = {
    "logs", "cache", ".cache", "backups", "world", "playerdata", "stats", "advancements"
}


def normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_configs(directory: Path | None, expected: dict[str, Any]) -> dict[str, Any]:
    if directory is None:
        return {"status": "NOT_SUPPLIED", "expected": expected}
    if not directory.is_dir():
        raise FileNotFoundError(f"Configuration directory does not exist: {directory}")

    extensions = {
        str(value).lower() for value in expected.get("included_extensions", DEFAULT_CONFIG_EXTENSIONS)
    }
    excluded = {
        str(value).lower() for value in expected.get("excluded_directories", DEFAULT_EXCLUDED_CONFIG_DIRS)
    }
    files: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        relative = path.relative_to(directory)
        if any(part.lower() in excluded for part in relative.parts[:-1]):
            continue
        files.append({
            "relative_path": relative.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    tree = hashlib.sha256()
    for item in files:
        tree.update(item["relative_path"].encode("utf-8"))
        tree.update(b"\0")
        tree.update(item["sha256"].encode("ascii"))
        tree.update(b"\n")
    actual_tree = tree.hexdigest()
    expected_tree = expected.get("tree_sha256")
    expected_count = expected.get("file_count")
    if expected_tree is None or expected_count is None:
        status = "UNLOCKED_TARGET"
    elif actual_tree.lower() != str(expected_tree).lower() or len(files) != int(expected_count):
        status = "FINGERPRINT_MISMATCH"
    else:
        status = "EXACT_MATCH"
    return {
        "status": status,
        "path": str(directory.resolve()),
        "tree_sha256": actual_tree,
        "file_count": len(files),
        "files": files,
        "expected": expected,
    }


def parse_simple_yaml(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        if not raw_line or raw_line[0].isspace() or raw_line.lstrip().startswith("#"):
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("'\"")
        if key in {"name", "version", "main", "api-version", "id"}:
            parsed[key] = value
    return parsed


def inspect_jar(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "filename": path.name,
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "metadata_source": None,
        "name": None,
        "id": None,
        "version": None,
        "main": None,
        "api_version": None,
        "read_error": None,
    }
    try:
        with zipfile.ZipFile(path) as jar:
            names = set(jar.namelist())
            for descriptor in ("plugin.yml", "paper-plugin.yml", "bungee.yml"):
                if descriptor not in names:
                    continue
                data = parse_simple_yaml(jar.read(descriptor).decode("utf-8", errors="replace"))
                result.update({
                    "metadata_source": descriptor,
                    "name": data.get("name"),
                    "id": data.get("id"),
                    "version": data.get("version"),
                    "main": data.get("main"),
                    "api_version": data.get("api-version"),
                })
                break
            if result["metadata_source"] is None and "velocity-plugin.json" in names:
                data = json.loads(jar.read("velocity-plugin.json").decode("utf-8"))
                result.update({
                    "metadata_source": "velocity-plugin.json",
                    "name": data.get("name") or data.get("id"),
                    "id": data.get("id"),
                    "version": data.get("version"),
                    "main": data.get("main"),
                })
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        result["read_error"] = f"{type(exc).__name__}: {exc}"
    return result


def scan_plugin_dir(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Plugin directory does not exist: {directory}")
    return [inspect_jar(path) for path in sorted(directory.glob("*.jar"), key=lambda p: p.name.lower())]


def all_expected_plugins(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(manifest.get("translation_plugins", [])) + list(manifest.get("plugins", []))


def descriptor_keys(jar: dict[str, Any]) -> set[str]:
    keys = {
        normalize(jar.get("name")),
        normalize(jar.get("id")),
    }
    return {key for key in keys if key}


def match_expected(expected: dict[str, Any], jars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aliases = {normalize(expected.get("id"))}
    aliases.update(normalize(alias) for alias in expected.get("aliases", []))
    aliases.discard("")

    descriptor_matches = [jar for jar in jars if aliases & descriptor_keys(jar)]
    if descriptor_matches:
        return descriptor_matches

    # Filename fallback is only used when a JAR has no readable descriptor. This
    # prevents FactionsUUID from also claiming a valid FactionsUUIDPlus JAR.
    filename_matches: list[dict[str, Any]] = []
    for jar in jars:
        if jar.get("metadata_source") is not None:
            continue
        stem = normalize(Path(jar["filename"]).stem)
        if any(stem.startswith(alias) for alias in aliases if len(alias) >= 4):
            filename_matches.append(jar)
    return filename_matches


def compare_plugins(manifest: dict[str, Any], jars: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    claimed_paths: set[str] = set()
    blockers: list[str] = []
    matched_by_id: dict[str, dict[str, Any]] = {}

    for expected in all_expected_plugins(manifest):
        matches = match_expected(expected, jars)
        row: dict[str, Any] = {
            "id": expected["id"],
            "required": bool(expected.get("required", False)),
            "aliases": expected.get("aliases", []),
            "expected_version": expected.get("version", {}).get("exact"),
            "expected_sha256": expected.get("sha256"),
            "status": None,
            "actual": None,
        }
        if not matches:
            row["status"] = "MISSING" if row["required"] else "ABSENT_OPTIONAL"
            if row["required"]:
                blockers.append(f"missing_required:{expected['id']}")
        elif len(matches) > 1:
            row["status"] = "AMBIGUOUS"
            row["matches"] = matches
            blockers.append(f"ambiguous_match:{expected['id']}")
        else:
            actual = matches[0]
            claimed_paths.add(actual["path"])
            matched_by_id[expected["id"]] = actual
            row["actual"] = actual
            if actual.get("read_error"):
                row["status"] = "UNREADABLE_JAR"
                blockers.append(f"unreadable_jar:{expected['id']}")
            elif row["expected_version"] is None or row["expected_sha256"] is None:
                row["status"] = "UNLOCKED_TARGET"
                blockers.append(f"unlocked_target:{expected['id']}")
            elif str(actual.get("version")) != str(row["expected_version"]):
                row["status"] = "VERSION_MISMATCH"
                blockers.append(f"version_mismatch:{expected['id']}")
            elif actual["sha256"].lower() != str(row["expected_sha256"]).lower():
                row["status"] = "HASH_MISMATCH"
                blockers.append(f"hash_mismatch:{expected['id']}")
            else:
                row["status"] = "EXACT_MATCH"
        rows.append(row)

    unclaimed = [jar for jar in jars if jar["path"] not in claimed_paths]
    ignored_aliases = {
        normalize(value)
        for value in manifest.get("lock_policy", {}).get("ignored_plugin_aliases", [])
    }
    ignored_jars: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []
    for jar in unclaimed:
        if ignored_aliases & descriptor_keys(jar):
            ignored_jars.append(jar)
        else:
            extras.append(jar)
            blockers.append(f"unexpected_plugin:{jar['filename']}")
    return {
        "status": "PLUGIN_STACK_EXACT" if not blockers else "NOT_IDENTICAL",
        "blockers": blockers,
        "plugins": rows,
        "extra_jars": extras,
        "ignored_jars": ignored_jars,
        "matched_by_id": matched_by_id,
    }


def inspect_runtime_jar(path: Path | None, expected: dict[str, Any], label: str) -> dict[str, Any]:
    if path is None:
        return {"label": label, "status": "NOT_SUPPLIED", "expected": expected}
    actual_hash = sha256_file(path)
    expected_hash = expected.get("jar_sha256")
    if expected_hash is None:
        status = "UNLOCKED_TARGET"
    elif actual_hash.lower() == str(expected_hash).lower():
        status = "EXACT_MATCH"
    else:
        status = "HASH_MISMATCH"
    return {
        "label": label,
        "status": status,
        "path": str(path.resolve()),
        "filename": path.name,
        "sha256": actual_hash,
        "expected": expected,
    }


def build_locked_manifest(
    manifest: dict[str, Any],
    comparison: dict[str, Any],
    source_label: str,
    backend: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if manifest.get("locked"):
        raise ValueError("Refusing to overwrite an already locked manifest")
    required_label = manifest.get("lock_policy", {}).get("required_source_label", "live-server-export")
    if source_label != required_label:
        raise ValueError(f"Lock source must be exactly {required_label!r}, got {source_label!r}")
    invalid_required = [
        row for row in comparison["plugins"]
        if row["required"] and row["status"] not in {"UNLOCKED_TARGET", "EXACT_MATCH"}
    ]
    if invalid_required:
        details = ", ".join(f"{row['id']}={row['status']}" for row in invalid_required)
        raise ValueError(f"Cannot lock invalid plugin export: {details}")

    if backend is None or backend.get("status") == "NOT_SUPPLIED":
        raise ValueError("Cannot lock full parity without the live backend JAR")
    if backend.get("status") == "HASH_MISMATCH":
        raise ValueError("Live backend JAR does not match the already pinned backend hash")
    proxy_required = manifest.get("proxy", {}).get("required_for_full_parity", False)
    if proxy_required and (proxy is None or proxy.get("status") == "NOT_SUPPLIED"):
        raise ValueError("Cannot lock full parity without the live Velocity JAR")
    if proxy is not None and proxy.get("status") == "HASH_MISMATCH":
        raise ValueError("Live proxy JAR does not match the already locked proxy hash")
    config_required = manifest.get("configuration", {}).get("required_for_full_parity", False)
    if config_required and (configuration is None or configuration.get("status") == "NOT_SUPPLIED"):
        raise ValueError("Cannot lock full parity without the live configuration export")
    if configuration is not None and configuration.get("status") == "FINGERPRINT_MISMATCH":
        raise ValueError("Live configuration export does not match the already locked fingerprint")

    locked = copy.deepcopy(manifest)
    by_id = comparison["matched_by_id"]
    for expected in all_expected_plugins(locked):
        actual = by_id.get(expected["id"])
        if actual is None:
            continue
        if not actual.get("version"):
            raise ValueError(f"Cannot lock {expected['id']}: JAR descriptor has no version")
        expected.setdefault("version", {})["exact"] = str(actual["version"])
        expected["version"]["status"] = "locked-from-live-server-export"
        expected["sha256"] = actual["sha256"]
        expected["locked_filename"] = actual["filename"]
        expected["metadata_source"] = actual.get("metadata_source")
        expected["main"] = actual.get("main")
    known_ids = {normalize(item.get("id")) for item in all_expected_plugins(locked)}
    for actual in comparison.get("extra_jars", []):
        if actual.get("read_error") or not actual.get("metadata_source"):
            raise ValueError(
                f"Cannot lock unexpected JAR without a readable plugin descriptor: {actual['filename']}"
            )
        if not actual.get("version"):
            raise ValueError(f"Cannot lock unexpected plugin without a version: {actual['filename']}")
        discovered_id = normalize(actual.get("id") or actual.get("name") or Path(actual["filename"]).stem)
        if not discovered_id or discovered_id in known_ids:
            raise ValueError(f"Unexpected plugin has duplicate/invalid identity: {actual['filename']}")
        locked.setdefault("plugins", []).append({
            "id": discovered_id,
            "aliases": [actual.get("name") or Path(actual["filename"]).stem],
            "required": True,
            "version": {
                "exact": str(actual["version"]),
                "status": "discovered-and-locked-from-live-server-export",
            },
            "sha256": actual["sha256"],
            "locked_filename": actual["filename"],
            "metadata_source": actual.get("metadata_source"),
            "main": actual.get("main"),
            "discovered_from_live_export": True,
        })
        known_ids.add(discovered_id)
    locked.setdefault("backend", {})["jar_sha256"] = backend["sha256"]
    locked["backend"]["locked_filename"] = backend["filename"]
    if proxy is not None and proxy.get("status") != "NOT_SUPPLIED":
        locked.setdefault("proxy", {})["jar_sha256"] = proxy["sha256"]
        locked["proxy"]["locked_filename"] = proxy["filename"]
        locked["proxy"]["status"] = "locked-from-live-server-export"
    if configuration is not None and configuration.get("status") != "NOT_SUPPLIED":
        locked.setdefault("configuration", {})["tree_sha256"] = configuration["tree_sha256"]
        locked["configuration"]["file_count"] = configuration["file_count"]
        locked["configuration"]["status"] = "locked-from-live-server-export"
    locked["evidence_level"] = "operator-supplied-live-export-lock"
    locked["lock_source"] = source_label
    locked["locked"] = True
    return locked


def stage_verified_plugins(comparison: dict[str, Any], destination: Path) -> list[str]:
    non_exact = [row for row in comparison["plugins"] if row["required"] and row["status"] != "EXACT_MATCH"]
    if non_exact:
        raise ValueError("Refusing to stage because required plugins are not exact matches")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Refusing to stage into non-empty plugin directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for row in comparison["plugins"]:
        actual = row.get("actual")
        if actual is None:
            continue
        source = Path(actual["path"])
        target = destination / source.name
        shutil.copy2(source, target)
        if sha256_file(target) != actual["sha256"]:
            raise IOError(f"Hash changed while staging {source.name}")
        copied.append(str(target.resolve()))
    return copied


def stage_verified_configs(configuration: dict[str, Any], source_root: Path, destination: Path) -> list[str]:
    if configuration.get("status") != "EXACT_MATCH":
        raise ValueError("Refusing to stage configurations because their fingerprint is not exact")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Refusing to stage into non-empty configuration directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for item in configuration.get("files", []):
        relative = Path(item["relative_path"])
        source = source_root / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha256_file(target) != item["sha256"]:
            raise IOError(f"Hash changed while staging configuration {relative.as_posix()}")
        copied.append(str(target.resolve()))
    return copied


def run_audit(
    manifest_path: Path,
    plugins_dir: Path,
    server_jar: Path | None = None,
    proxy_jar: Path | None = None,
    configs_dir: Path | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jars = scan_plugin_dir(plugins_dir)
    comparison = compare_plugins(manifest, jars)
    backend = inspect_runtime_jar(server_jar, manifest.get("backend", {}), "backend")
    proxy_expected = {
        "jar_sha256": manifest.get("proxy", {}).get("jar_sha256"),
        **manifest.get("proxy", {}),
    }
    proxy = inspect_runtime_jar(proxy_jar, proxy_expected, "proxy")
    configuration = fingerprint_configs(configs_dir, manifest.get("configuration", {}))
    full_blockers = list(comparison["blockers"])
    if backend["status"] != "EXACT_MATCH":
        full_blockers.append(f"backend:{backend['status'].lower()}")
    if manifest.get("proxy", {}).get("required_for_full_parity", False) and proxy["status"] != "EXACT_MATCH":
        full_blockers.append(f"proxy:{proxy['status'].lower()}")
    if (manifest.get("configuration", {}).get("required_for_full_parity", False)
            and configuration["status"] != "EXACT_MATCH"):
        full_blockers.append(f"configuration:{configuration['status'].lower()}")
    return {
        "schema_version": 1,
        "profile_id": manifest.get("profile_id"),
        "status": "FULL_STACK_EXACT" if not full_blockers else "NOT_IDENTICAL",
        "full_stack_blockers": full_blockers,
        "plugin_comparison": comparison,
        "backend": backend,
        "proxy": proxy,
        "configuration": configuration,
        "inventory": jars,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plugins-dir", type=Path, required=True)
    parser.add_argument("--server-jar", type=Path)
    parser.add_argument("--proxy-jar", type=Path)
    parser.add_argument("--configs-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock-output", type=Path)
    parser.add_argument("--source-label")
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--stage-config-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = run_audit(
            args.manifest, args.plugins_dir, args.server_jar, args.proxy_jar, args.configs_dir
        )
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.lock_output:
            locked = build_locked_manifest(
                manifest,
                report["plugin_comparison"],
                args.source_label or "",
                report["backend"],
                report["proxy"],
                report["configuration"],
            )
            args.lock_output.parent.mkdir(parents=True, exist_ok=True)
            args.lock_output.write_text(json.dumps(locked, indent=2) + "\n", encoding="utf-8")
            report["lock_output"] = str(args.lock_output.resolve())
        if args.stage_dir:
            report["staged_plugins"] = stage_verified_plugins(report["plugin_comparison"], args.stage_dir)
        if args.stage_config_dir:
            if args.configs_dir is None:
                raise ValueError("--stage-config-dir requires --configs-dir")
            report["staged_configs"] = stage_verified_configs(
                report["configuration"], args.configs_dir, args.stage_config_dir
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": report["status"],
            "blockers": report["full_stack_blockers"],
            "output": str(args.output.resolve()),
            "lock_output": report.get("lock_output"),
            "staged_count": len(report.get("staged_plugins", [])),
            "staged_config_count": len(report.get("staged_configs", [])),
        }, indent=2))
        if args.lock_output:
            return 0
        return 0 if report["status"] == "FULL_STACK_EXACT" else EVIDENCE_FAILURE
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
