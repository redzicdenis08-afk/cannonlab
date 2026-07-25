#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("verify-sakura-cannon-contract.py")
    spec = importlib.util.spec_from_file_location("verify_sakura_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_source(root: Path) -> None:
    files = {
        "gradle.properties": "version=26.1.2\nmcVersion=26.1.2\n",
        "sakura-server/src/main/java/me/samsuik/sakura/configuration/WorldConfiguration.java": "\n".join([
            "public MergeLevel mergeLevel = MergeLevel.LENIENT;",
            "public boolean loadChunks = false;",
            "public boolean forcePositionUpdates;",
            "map.put(Blocks.OBSIDIAN, new DurableMaterial(4, x, true));",
            "public Duration durableMaterialsExpiration = Duration.of(\"1m\");",
            "public TNTSpread tntSpread = TNTSpread.ALL;",
            "public boolean tntFlowsInWater = true;",
            "public boolean fallingBlockParity = false;",
            "public MinecraftMechanicsTarget mechanicsTarget = MinecraftMechanicsTarget.latest();",
            "public boolean brokenPaperExplosionBehaviour = false;",
        ]),
        "sakura-server/minecraft-patches/sources/net/minecraft/world/entity/item/PrimedTnt.java.patch": "\n".join([
            "this.cannonEntity = true",
            "case NONE -> this.setDeltaMovement(0.0, 0.0, 0.0);",
            "tntFlowsInWater",
            "remove max tnt per tick",
        ]),
        "sakura-server/minecraft-patches/features/0004-Optimise-cannon-entity-movement.patch": "movement.lengthSqr() >= 12.0\ncollideAxisScan\n",
        "sakura-api/src/main/java/me/samsuik/sakura/mechanics/MinecraftMechanicsTarget.java": "record MinecraftMechanicsTarget\nLATEST = new MinecraftMechanicsTarget(MechanicVersion.LATEST, ServerType.PAPER)\n",
        "sakura-server/src/main/java/me/samsuik/sakura/command/subcommand/MechanicCommand.java": "Mechanic Version\nHeight Parity\nTnt Spread\nTnt Flow\nRedstone Implementation\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main() -> None:
    module = load_module()
    contract_path = Path(__file__).parents[1] / "profiles/parity/sakura-26.1.2-cannon-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert module.verify_contract(contract) == []

    broken = json.loads(json.dumps(contract))
    broken["source"]["minecraft_runtime_version"] = "1.20.1"
    errors = module.verify_contract(broken)
    assert any("runtime version" in error for error in errors), errors

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_source(root)
        assert module.check_source_root(contract, root) == []
        (root / "gradle.properties").write_text("version=26.1.2\nmcVersion=1.20.1\n", encoding="utf-8")
        errors = module.check_source_root(contract, root)
        assert "gradle mcVersion mismatch" in errors, errors

    print("verify-sakura-cannon-contract: 3 regression groups passed")


if __name__ == "__main__":
    main()
