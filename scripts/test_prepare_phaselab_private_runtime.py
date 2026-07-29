#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import zipfile
from pathlib import Path


SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))

AUDIT_SPEC = importlib.util.spec_from_file_location(
    "phaselab_stack_audit", SCRIPTS / "phaselab_stack_audit.py"
)
assert AUDIT_SPEC and AUDIT_SPEC.loader
AUDIT = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules["phaselab_stack_audit"] = AUDIT
AUDIT_SPEC.loader.exec_module(AUDIT)

PREP_SPEC = importlib.util.spec_from_file_location(
    "prepare_phaselab_private_runtime", SCRIPTS / "prepare_phaselab_private_runtime.py"
)
assert PREP_SPEC and PREP_SPEC.loader
PREP = importlib.util.module_from_spec(PREP_SPEC)
PREP_SPEC.loader.exec_module(PREP)


def make_plugin(path: Path, name: str, version: str) -> None:
    with zipfile.ZipFile(path, "w") as jar:
        jar.writestr(
            "plugin.yml",
            f"name: {name}\nversion: {version}\nmain: test.{name}\napi-version: '1.21'\n",
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plugins = root / "plugins"
        configs = root / "configs"
        plugins.mkdir()
        configs.mkdir()
        make_plugin(plugins / "FactionsUUID.jar", "FactionsUUID", "4.6.1")
        (configs / "plugins" / "FactionsUUID").mkdir(parents=True)
        (configs / "plugins" / "FactionsUUID" / "config.yml").write_text(
            "claims: true\n", encoding="utf-8"
        )
        server = root / "server.jar"
        proxy = root / "velocity.jar"
        server.write_bytes(b"backend")
        proxy.write_bytes(b"proxy")

        profile = {
            "profile_id": "runtime-test",
            "backend": {"jar_sha256": None},
            "proxy": {"jar_sha256": None, "required_for_full_parity": True},
            "configuration": {
                "required_for_full_parity": True,
                "tree_sha256": None,
                "file_count": None,
            },
            "translation_plugins": [],
            "plugins": [{
                "id": "factionsuuid",
                "aliases": ["FactionsUUID"],
                "required": True,
                "version": {"exact": None},
                "sha256": None,
            }],
            "lock_policy": {"required_source_label": "live-server-export"},
        }
        observed = root / "observed.json"
        observed.write_text(json.dumps(profile), encoding="utf-8")
        audit = AUDIT.run_audit(observed, plugins, server, proxy, configs)
        locked = AUDIT.build_locked_manifest(
            profile,
            audit["plugin_comparison"],
            "live-server-export",
            audit["backend"],
            audit["proxy"],
            audit["configuration"],
        )
        lock_path = root / "locked.json"
        lock_path.write_text(json.dumps(locked), encoding="utf-8")

        runtime = root / "runtime"
        identity = PREP.prepare_runtime(lock_path, plugins, server, proxy, configs, runtime)
        assert identity["status"] == "FULL_STACK_EXACT"
        assert identity["plugin_count"] == 1
        assert (runtime / "backend" / "server.jar").read_bytes() == b"backend"
        assert (runtime / "proxy" / "velocity.jar").read_bytes() == b"proxy"
        assert (runtime / "backend" / "plugins" / "FactionsUUID.jar").is_file()
        assert (runtime / "configs" / "plugins" / "FactionsUUID" / "config.yml").is_file()
        assert (runtime / "runtime-identity.json").is_file()
        assert (runtime / PREP.RUNTIME_MARKER).is_file()

        unsafe_runtime = root / "not-a-phaselab-runtime"
        unsafe_runtime.mkdir()
        (unsafe_runtime / "keep.txt").write_text("do not delete", encoding="utf-8")
        try:
            PREP.prepare_runtime(
                lock_path, plugins, server, proxy, configs, unsafe_runtime
            )
        except ValueError as exc:
            assert "unmarked runtime directory" in str(exc)
        else:
            raise AssertionError("Unmarked non-empty runtime directory was deleted")
        assert (unsafe_runtime / "keep.txt").read_text(encoding="utf-8") == "do not delete"

        (configs / "plugins" / "FactionsUUID" / "config.yml").write_text(
            "claims: false\n", encoding="utf-8"
        )
        try:
            PREP.prepare_runtime(lock_path, plugins, server, proxy, configs, runtime)
        except ValueError as exc:
            assert "parity blockers" in str(exc)
        else:
            raise AssertionError("Tampered configuration unexpectedly staged")

    print("PhaseLab private runtime preparation regressions passed: 3")


if __name__ == "__main__":
    main()
