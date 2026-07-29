#!/usr/bin/env python3
"""Assemble an isolated PhaseLab runtime from an already locked live-server export.

No components are downloaded. The command fails unless backend, proxy, every required
plugin, and the configuration tree exactly match the supplied lock manifest.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import phaselab_stack_audit as stack_audit


RUNTIME_MARKER = ".phaselab-runtime-root"


def reset_runtime_root(runtime_root: Path) -> Path:
    resolved = runtime_root.resolve()
    anchor = Path(resolved.anchor)
    if resolved == anchor or len(resolved.parts) < 3:
        raise ValueError(f"Unsafe runtime root: {resolved}")
    if resolved.exists():
        entries = list(resolved.iterdir())
        marker = resolved / RUNTIME_MARKER
        if entries and not marker.is_file():
            raise ValueError(
                f"Refusing to delete non-empty unmarked runtime directory: {resolved}"
            )
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=False)
    (resolved / RUNTIME_MARKER).write_text(
        "Managed only by prepare_phaselab_private_runtime.py\n", encoding="utf-8"
    )
    return resolved


def copy_verified(source: Path, destination: Path, expected_sha256: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    actual = stack_audit.sha256_file(destination)
    if actual.lower() != expected_sha256.lower():
        raise IOError(f"Hash changed while staging {source.name}")
    return actual


def prepare_runtime(
    manifest_path: Path,
    plugins_dir: Path,
    server_jar: Path,
    proxy_jar: Path,
    configs_dir: Path,
    runtime_root: Path,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("locked"):
        raise ValueError("Runtime assembly requires a locked live-export manifest")

    report = stack_audit.run_audit(
        manifest_path, plugins_dir, server_jar, proxy_jar, configs_dir
    )
    if report["status"] != "FULL_STACK_EXACT":
        raise ValueError(
            "Runtime assembly refused; parity blockers: "
            + ", ".join(report["full_stack_blockers"])
        )

    runtime_root = reset_runtime_root(runtime_root)
    backend_plugins = runtime_root / "backend" / "plugins"
    staged_plugins = stack_audit.stage_verified_plugins(
        report["plugin_comparison"], backend_plugins
    )
    staged_configs = stack_audit.stage_verified_configs(
        report["configuration"], configs_dir, runtime_root / "configs"
    )
    backend_hash = copy_verified(
        server_jar, runtime_root / "backend" / "server.jar", report["backend"]["sha256"]
    )
    proxy_hash = copy_verified(
        proxy_jar, runtime_root / "proxy" / "velocity.jar", report["proxy"]["sha256"]
    )

    identity = {
        "schema_version": 1,
        "status": "FULL_STACK_EXACT",
        "source_profile_id": report.get("profile_id"),
        "lock_manifest": str(manifest_path.resolve()),
        "runtime_marker": RUNTIME_MARKER,
        "backend": {
            "relative_path": "backend/server.jar",
            "sha256": backend_hash,
        },
        "proxy": {
            "relative_path": "proxy/velocity.jar",
            "sha256": proxy_hash,
        },
        "plugin_count": len(staged_plugins),
        "plugins": [
            str(Path(path).relative_to(runtime_root).as_posix()) for path in staged_plugins
        ],
        "configuration": {
            "tree_sha256": report["configuration"]["tree_sha256"],
            "file_count": len(staged_configs),
            "root": "configs",
        },
    }
    identity_path = runtime_root / "runtime-identity.json"
    identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return identity


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plugins-dir", type=Path, required=True)
    parser.add_argument("--server-jar", type=Path, required=True)
    parser.add_argument("--proxy-jar", type=Path, required=True)
    parser.add_argument("--configs-dir", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        identity = prepare_runtime(
            args.manifest,
            args.plugins_dir,
            args.server_jar,
            args.proxy_jar,
            args.configs_dir,
            args.runtime_root,
        )
        print(json.dumps(identity, indent=2))
        return 0
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
