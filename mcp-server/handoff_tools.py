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
        raid_path = root / "profiles/raid/extremecraft-15-chunk-regen-objective-v1.json"
        raid_doc_path = root / "docs/EXTREMECRAFT_15_CHUNK_RAID_PROGRAM.md"

        required = [
            agents_path,
            start_path,
            grammar_path,
            private_path,
            public_path,
            priority_path,
            raid_path,
            raid_doc_path,
        ]
        missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"CannonLab handoff is incomplete: {missing}")

        grammar = json.loads(grammar_path.read_text(encoding="utf-8"))
        private_profile = json.loads(private_path.read_text(encoding="utf-8"))
        public_contract = json.loads(public_path.read_text(encoding="utf-8"))
        priorities = json.loads(priority_path.read_text(encoding="utf-8"))
        raid_objective = json.loads(raid_path.read_text(encoding="utf-8"))

        result: dict[str, Any] = {
            "schema_version": 2,
            "mandatory_read_order": [
                "AGENTS.md",
                "CANNONLAB_START_HERE.md",
                "README.md",
                "docs/CANNON_GRAMMAR_AND_PARITY.md",
                "docs/CANNON_PARITY_CAMPAIGNS.md",
                "docs/EXTREMECRAFT_15_CHUNK_RAID_PROGRAM.md",
                "profiles/raid/extremecraft-15-chunk-regen-objective-v1.json",
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
                "fifteen_chunk_raid_program_exists": True,
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
                "raid_required_modules": len(raid_objective.get("required_modules", [])),
                "raid_conditional_modules": len(raid_objective.get("conditional_modules", {})),
                "chunk_alignment_offsets": 256,
            },
            "raid_objective": {
                "profile": "profiles/raid/extremecraft-15-chunk-regen-objective-v1.json",
                "planner": "plan_extremecraft_raid_program",
                "buffer_depth_chunks": raid_objective["objective"]["buffer_depth_chunks"],
                "exact_flight_distance_blocks": raid_objective["objective"]["exact_muzzle_to_first_target_blocks"],
                "regen_depth_chunks": raid_objective["objective"]["regen_depth_chunks"],
                "wall_group_count": raid_objective["objective"]["wall_group_count"],
                "buffer_depth_is_projectile_distance": False,
                "buffer_depth_is_wall_count": False,
                "buffer_depth_is_regen_depth": False,
            },
            "required_first_actions": [
                "identify target profile, defense, distance and requested modules",
                "run plan_extremecraft_raid_program for a fifteen-chunk objective",
                "plan or inspect paired parity probes",
                "measure exact raid-lane distances, wall groups, regen depth and heights",
                "expand the module dependency proof campaign",
                "reuse only exact evidence meeting the requested promotion level",
                "classify the first causal failure before changing geometry",
            ],
            "forbidden_shortcuts": [
                "fifteen chunks converted into an assumed 240-block shot",
                "buffer depth treated as wall count or regeneration depth",
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
                "raid_program_proves_fifteen_chunk_capability": False,
                "fresh_ai_must_recheck_live_pr_and_ci_state": True,
            },
        }
        if include_documents:
            result["documents"] = {
                "AGENTS.md": agents_path.read_text(encoding="utf-8"),
                "CANNONLAB_START_HERE.md": start_path.read_text(encoding="utf-8"),
                "docs/EXTREMECRAFT_15_CHUNK_RAID_PROGRAM.md": raid_doc_path.read_text(
                    encoding="utf-8"
                ),
            }
        return result

    return ("get_cannonlab_handoff",)
