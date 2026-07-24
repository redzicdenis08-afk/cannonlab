#!/usr/bin/env python3
"""Inventory the exact Bukkit-family plugin JAR stack used by a lab run."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import yaml


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def descriptor(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            descriptor_name = next((name for name in ("paper-plugin.yml", "plugin.yml") if name in names), None)
            if descriptor_name is None:
                return {}, "no plugin.yml or paper-plugin.yml"
            raw = archive.read(descriptor_name).decode("utf-8", errors="replace")
            value = yaml.safe_load(raw)
            if not isinstance(value, dict):
                return {}, f"{descriptor_name} is not a mapping"
            selected = {
                "descriptor": descriptor_name,
                "name": value.get("name"),
                "version": value.get("version"),
                "main": value.get("main"),
                "api_version": value.get("api-version"),
                "depend": value.get("depend", []),
                "softdepend": value.get("softdepend", []),
                "loadbefore": value.get("loadbefore", []),
            }
            return selected, None
    except (OSError, zipfile.BadZipFile) as exc:
        return {}, f"unreadable jar: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugins-dir", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    plugins_dir = args.plugins_dir.resolve()
    if not plugins_dir.is_dir():
        raise SystemExit(f"Plugin directory does not exist: {plugins_dir}")

    plugins: list[dict[str, Any]] = []
    for jar in sorted(plugins_dir.glob("*.jar"), key=lambda path: path.name.lower()):
        metadata, error = descriptor(jar)
        row: dict[str, Any] = {
            "file": jar.name,
            "size_bytes": jar.stat().st_size,
            "sha256": sha256(jar),
            **metadata,
        }
        if error:
            row["descriptor_error"] = error
        plugins.append(row)

    aggregate = hashlib.sha256()
    for plugin in plugins:
        aggregate.update(plugin["file"].encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(plugin["sha256"].encode("ascii"))
        aggregate.update(b"\n")

    report = {
        "schema_version": 1,
        "plugins_dir": str(plugins_dir),
        "plugin_count": len(plugins),
        "stack_sha256": aggregate.hexdigest(),
        "plugins": plugins,
        "warning": "Matching plugin names or public versions does not prove matching private configuration or patches.",
    }
    text = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
