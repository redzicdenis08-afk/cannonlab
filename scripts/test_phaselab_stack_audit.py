#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("phaselab_stack_audit.py")
SPEC = importlib.util.spec_from_file_location("phaselab_stack_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_plugin(path: Path, name: str, version: str, main: str = "test.Main") -> None:
    with zipfile.ZipFile(path, "w") as jar:
        jar.writestr("plugin.yml", f"name: {name}\nversion: {version}\nmain: {main}\napi-version: '1.21'\n")


def base_manifest() -> dict:
    return {
        "profile_id": "test",
        "backend": {"jar_sha256": None},
        "proxy": {"jar_sha256": None, "required_for_full_parity": True},
        "configuration": {
            "required_for_full_parity": True,
            "tree_sha256": None,
            "file_count": None,
        },
        "translation_plugins": [],
        "plugins": [
            {"id": "factionsuuid", "aliases": ["FactionsUUID"], "required": True,
             "version": {"exact": None}, "sha256": None},
            {"id": "auraskills", "aliases": ["AuraSkills"], "required": True,
             "version": {"exact": None}, "sha256": None},
        ],
        "lock_policy": {"required_source_label": "live-server-export"},
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plugins = root / "plugins"
        plugins.mkdir()
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(base_manifest()), encoding="utf-8")

        make_plugin(plugins / "FactionsUUID-4.6.1.jar", "FactionsUUID", "4.6.1")
        make_plugin(plugins / "FactionsUUIDPlus-1.0.0.jar", "FactionsUUIDPlus", "1.0.0")
        report = MODULE.run_audit(manifest_path, plugins)
        assert "missing_required:auraskills" in report["full_stack_blockers"]
        factions_row = next(
            row for row in report["plugin_comparison"]["plugins"] if row["id"] == "factionsuuid"
        )
        assert factions_row["status"] == "UNLOCKED_TARGET"
        assert factions_row["actual"]["name"] == "FactionsUUID"

        make_plugin(plugins / "AuraSkills-2.3.0.jar", "AuraSkills", "2.3.0")
        server_jar = root / "server.jar"
        proxy_jar = root / "velocity.jar"
        configs = root / "configs"
        server_jar.write_bytes(b"exact-test-backend")
        proxy_jar.write_bytes(b"exact-test-proxy")
        (configs / "plugins" / "FactionsUUID").mkdir(parents=True)
        (configs / "plugins" / "FactionsUUID" / "config.yml").write_text(
            "claims: true\n", encoding="utf-8"
        )
        (configs / "logs").mkdir()
        (configs / "logs" / "ignored.json").write_text("{}", encoding="utf-8")
        report = MODULE.run_audit(manifest_path, plugins, server_jar, proxy_jar, configs)
        assert report["plugin_comparison"]["status"] == "NOT_IDENTICAL"
        assert any(blocker.startswith("unlocked_target:") for blocker in report["full_stack_blockers"])
        assert report["configuration"]["file_count"] == 1

        source = json.loads(manifest_path.read_text(encoding="utf-8"))
        locked = MODULE.build_locked_manifest(
            source,
            report["plugin_comparison"],
            "live-server-export",
            report["backend"],
            report["proxy"],
            report["configuration"],
        )
        locked_path = root / "locked.json"
        locked_path.write_text(json.dumps(locked), encoding="utf-8")
        assert any(
            plugin.get("discovered_from_live_export")
            and plugin["aliases"] == ["FactionsUUIDPlus"]
            for plugin in locked["plugins"]
        )
        locked_report = MODULE.run_audit(locked_path, plugins, server_jar, proxy_jar, configs)
        assert locked_report["plugin_comparison"]["status"] == "PLUGIN_STACK_EXACT"
        assert locked_report["status"] == "FULL_STACK_EXACT"

        stage = root / "stage"
        copied = MODULE.stage_verified_plugins(locked_report["plugin_comparison"], stage)
        assert len(copied) == 3
        assert sorted(path.name for path in stage.glob("*.jar")) == [
            "AuraSkills-2.3.0.jar",
            "FactionsUUID-4.6.1.jar",
            "FactionsUUIDPlus-1.0.0.jar",
        ]
        config_stage = root / "config-stage"
        config_copied = MODULE.stage_verified_configs(locked_report["configuration"], configs, config_stage)
        assert len(config_copied) == 1
        assert (config_stage / "plugins" / "FactionsUUID" / "config.yml").is_file()

        with zipfile.ZipFile(plugins / "AuraSkills-2.3.0.jar", "a") as jar:
            jar.writestr("tamper.txt", "changed")
        tampered = MODULE.run_audit(locked_path, plugins, server_jar, proxy_jar, configs)
        assert "hash_mismatch:auraskills" in tampered["full_stack_blockers"]

        (configs / "plugins" / "FactionsUUID" / "config.yml").write_text(
            "claims: false\n", encoding="utf-8"
        )
        config_tampered = MODULE.run_audit(locked_path, plugins, server_jar, proxy_jar, configs)
        assert "configuration:fingerprint_mismatch" in config_tampered["full_stack_blockers"]

        try:
            MODULE.build_locked_manifest(
                locked,
                locked_report["plugin_comparison"],
                "live-server-export",
                locked_report["backend"],
                locked_report["proxy"],
                locked_report["configuration"],
            )
        except ValueError as exc:
            assert "already locked" in str(exc)
        else:
            raise AssertionError("Already locked manifest was overwritten")

    print("PhaseLab stack audit regressions passed: 10")


if __name__ == "__main__":
    main()
