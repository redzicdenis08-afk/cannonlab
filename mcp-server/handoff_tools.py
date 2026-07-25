from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def register_handoff_tools(mcp: Any, *, root: Path) -> tuple[str, ...]:
    """Register a structured repository handoff for fresh AI sessions."""

    @mcp.tool()
    def get_cannonlab_handoff(include_documents: bool = False) -> dict[str, Any]:
        """Return current CannonLab capabilities, proof limits and mandatory reading order."""
        agents_path = root / "AGENTS.md"
        start_path = root / "CANNONLAB_START_HERE.md"
        grammar_path = root / "profiles/grammar/modern-factions-cannon-grammar-v1.json"
        private_path = root / "profiles/parity/extremecraft-private-parity-required-v1.json"
        public_path = root / "profiles/parity/sakura-26.1.2-cannon-contract.json"
        priority_path = root / "profiles/parity/extremecraft-parity-probe-priorities-v1.json"

        required = [
            agents_path,
            start_path,
            grammar_path,
            private_path,
            public_path,
            priority_path,
        ]
        missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"CannonLab handoff is incomplete: {missing}")

        grammar = json.loads(grammar_path.read_text(encoding="utf-8"))
        private_profile = json.loads(private_path.read_text(encoding="utf-8"))
        public_contract = json.loads(public_path.read_text(encoding="utf-8"))
        priorities = json.loads(priority_path.read_text(encoding="utf-8"))

        result: dict[str, Any] = {
            "schema_version": 1,
            "mandatory_read_order": [
                "AGENTS.md",
                "CANNONLAB_START_HERE.md",
                "README.md",
                "docs/CANNON_GRAMMAR_AND_PARITY.md",
                "docs/CANNON_PARITY_CAMPAIGNS.md",
                "profiles/parity/extremecraft-private-parity-required-v1.json",
                "profiles/parity/sakura-26.1.2-cannon-contract.json",
                "profiles/grammar/modern-factions-cannon-grammar-v1.json",
                "docs/EXTREMECRAFT_CALIBRATION.md",
            ],
            "current_state": {
                "laboratory_is_serious_and_reproducible": True,
                "field_ready_advanced_extremecraft_cannon_exists": False,
                "private_extremecraft_parity_complete": False,
                "field_ready_watered_wall_one_stacker_exists": False,
                "fifteen_chunk_regen_raid_capability_proven": False,
                "failed_twenty_block_scratch_pr": 41,
                "failed_twenty_block_scratch_merged": False,
            },
            "identities": {
                "schematic_data_version": public_contract["source"]["schematic_data_version"],
                "public_runtime": public_contract["source"]["sakura_version"],
                "public_runtime_commit": public_contract["source"]["commit"],
                "private_mechanics_target": "unknown",
            },
            "counts": {
                "grammar_modules": len(grammar.get("modules", [])),
                "private_parity_dimensions": len(private_profile.get("dimensions", [])),
                "public_runtime_probes": len(public_contract.get("required_runtime_probes", [])),
                "paired_parity_priorities": len(priorities.get("probes", [])),
                "chunk_alignment_offsets": 256,
            },
            "required_first_actions": [
                "identify target profile, defense, distance and requested modules",
                "plan or inspect paired parity probes",
                "expand the module dependency proof campaign",
                "reuse only exact evidence meeting the requested promotion level",
                "classify the first causal failure before changing geometry",
            ],
            "forbidden_shortcuts": [
                "target embedded beside the cannon",
                "filename or community label treated as behavior proof",
                "public Sakura pass treated as private ExtremeCraft parity",
                "schematic DataVersion treated as runtime physics version",
                "more TNT used to mask missing guider, hammer, compression or fusion",
                "failed runtime candidate published as working",
            ],
            "truth_boundary": {
                "handoff_proves_runtime_function": False,
                "handoff_proves_private_extremecraft_parity": False,
                "handoff_proves_field_readiness": False,
                "fresh_ai_must_recheck_live_pr_and_ci_state": True,
            },
        }
        if include_documents:
            result["documents"] = {
                "AGENTS.md": agents_path.read_text(encoding="utf-8"),
                "CANNONLAB_START_HERE.md": start_path.read_text(encoding="utf-8"),
            }
        return result

    return ("get_cannonlab_handoff",)
