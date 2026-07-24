#!/usr/bin/env python3
"""Apply a declared CannonLab parity profile to a prepared server.

The profile is evidence, not a claim of live server parity. The script writes the
requested Sakura cannon settings, CannonLab limits/metadata, and a deterministic
manifest that is copied beside runtime artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Profile does not exist: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a YAML mapping: {path}")
    return value


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_sakura(profile: dict[str, Any]) -> dict[str, Any]:
    sakura = profile.get("sakura", {})
    if not isinstance(sakura, dict):
        raise SystemExit("profile.sakura must be a mapping")
    cannons = sakura.get("cannons", {})
    if not isinstance(cannons, dict):
        raise SystemExit("profile.sakura.cannons must be a mapping")
    cannons = json.loads(json.dumps(cannons))
    mechanics = cannons.get("mechanics", {})
    if mechanics:
        if not isinstance(mechanics, dict):
            raise SystemExit("profile.sakura.cannons.mechanics must be a mapping")
        mechanic_version = mechanics.pop("mechanic-version", None)
        server_type = mechanics.pop("server-type", None)
        if mechanic_version is not None or server_type is not None:
            target = mechanics.setdefault("mechanics-target", {})
            if mechanic_version is not None:
                target["mechanic-version"] = mechanic_version
            if server_type is not None:
                target["server-type"] = server_type
    return {"cannons": cannons}


def read_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=120)
    path.write_text(text, encoding="utf-8", newline="\n")


def require_profile(profile: dict[str, Any]) -> None:
    required = ["schema-version", "id", "label", "evidence-grade", "server", "sakura", "cannonlab", "unknowns"]
    missing = [key for key in required if key not in profile]
    if missing:
        raise SystemExit("Profile missing required keys: " + ", ".join(missing))
    if profile["schema-version"] != 1:
        raise SystemExit(f"Unsupported profile schema-version: {profile['schema-version']}")
    unknowns = profile.get("unknowns")
    if not isinstance(unknowns, list):
        raise SystemExit("profile.unknowns must be a list, including an empty list for a closed profile")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    parser.add_argument("--server-root", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path)
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    server_root = args.server_root.resolve()
    profile = load_yaml(profile_path)
    require_profile(profile)

    sakura_path = server_root / "config" / "sakura-world-defaults.yml"
    sakura_current = read_mapping(sakura_path)
    if "_version" not in sakura_current:
        sakura_current["_version"] = 12
    sakura_requested = normalize_sakura(profile)
    # Cannon parity must not inherit stale machine-local cannon settings. Keep
    # unrelated world sections, but replace the entire cannon section from the
    # dated profile.
    sakura_effective = dict(sakura_current)
    sakura_effective["cannons"] = sakura_requested["cannons"]
    write_yaml(sakura_path, sakura_effective)

    plugin_data = server_root / "plugins" / "CannonLab"
    plugin_config_path = plugin_data / "config.yml"
    plugin_config = read_mapping(plugin_config_path)
    cannonlab = profile.get("cannonlab", {})
    limits = cannonlab.get("limits", {}) if isinstance(cannonlab, dict) else {}
    dispenser_limit = limits.get("dispensers-per-chunk", 160)
    if not isinstance(dispenser_limit, int) or dispenser_limit < 1:
        raise SystemExit("cannonlab.limits.dispensers-per-chunk must be a positive integer")
    plugin_overlay = {
        "limits": {"dispensers-per-chunk": dispenser_limit},
        "parity-profile": {
            "id": str(profile["id"]),
            "label": str(profile["label"]),
            "evidence-grade": str(profile["evidence-grade"]),
            "source-file": profile_path.name,
            "unknowns": [str(item) for item in profile.get("unknowns", [])],
        },
    }
    write_yaml(plugin_config_path, deep_merge(plugin_config, plugin_overlay))

    active_profile = plugin_data / "profiles" / "active.yml"
    active_profile.parent.mkdir(parents=True, exist_ok=True)
    active_profile.write_bytes(profile_path.read_bytes())

    raw = profile_path.read_bytes()
    manifest = {
        "schema_version": 1,
        "profile_id": str(profile["id"]),
        "profile_label": str(profile["label"]),
        "evidence_grade": str(profile["evidence-grade"]),
        "profile_sha256": hashlib.sha256(raw).hexdigest(),
        "profile_path": str(profile_path),
        "server_root": str(server_root),
        "sakura_config_path": str(sakura_path),
        "cannonlab_config_path": str(plugin_config_path),
        "requested": {
            "server": profile.get("server", {}),
            "sakura": sakura_requested,
            "cannonlab": cannonlab,
        },
        "unknowns": profile.get("unknowns", []),
        "truth_boundary": profile.get("truth-boundary", []),
    }
    manifest_out = args.manifest_out or (plugin_data / "profiles" / "active-manifest.json")
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
