#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def snap(rows: list[dict[str, Any]], label: str):
    for i, row in enumerate(rows):
        if row.get("type") in {"snapshot", "portal_snapshot"} and row.get("label") == label:
            return i, row
    return None


def window(rows: list[dict[str, Any]], before: str, after: str):
    a, b = snap(rows, before), snap(rows, after)
    if not a or not b or b[0] <= a[0]:
        return None
    return a[1], b[1], rows[a[0] + 1:b[0]]


def result(status: str, title: str, **evidence):
    return {"status": status, "title": title, "evidence": evidence}


def claim_witness(rows):
    for row in rows:
        if row.get("type") != "claim_witness" or row.get("label") != "setup":
            continue
        valid = (
            row.get("verified") is True
            and row.get("attacker_tag") == "Attackers"
            and row.get("victim_tag") == "Victims"
            and row.get("attacker_portal_tag") == "Attackers"
            and row.get("victim_portal_tag") == "Victims"
            and row.get("attacker_wilderness") is False
            and row.get("victim_wilderness") is False
            and row.get("attacker_portal_wilderness") is False
            and row.get("victim_portal_wilderness") is False
        )
        return valid, row
    return False, None


def portal(rows, prefix: str, count: int, fixture_mode: bool):
    attempts = []
    for n in range(1, count + 1):
        found = snap(rows, f"{prefix}-{n}")
        if not found:
            attempts.append({"run": n, "missing": True})
            continue
        i, state = found
        recent = rows[max(0, i - 50):i]
        monitors = [e for e in recent if e.get("type") == "portal_multi_place_monitor"]
        highest = [e for e in recent if e.get("type") == "portal_multi_place_highest"]
        duplicated = (
            state.get("barrel_type") == "BARREL"
            and state.get("barrel_netherite_blocks") == 27
            and int(state.get("dropped_netherite_blocks", 0)) > 0
        )
        attempts.append({
            "run": n,
            "duplicated": duplicated,
            "barrel_count": state.get("barrel_netherite_blocks"),
            "dropped_count": state.get("dropped_netherite_blocks"),
            "cancelled_events": sum(e.get("cancelled") is True for e in monitors),
            "matching_fixture_mode": sum(e.get("fixture_cancel_mode") is fixture_mode for e in highest),
        })
    hits = sum(a.get("duplicated") is True for a in attempts)
    completed = [a for a in attempts if "duplicated" in a]
    status = "confirmed" if hits >= 2 else "rejected" if completed and all(a["duplicated"] is False for a in completed) else "inconclusive"
    return result(status, "Cancelled portal creation duplicated a filled barrel", attempts=attempts, confirmed_attempts=hits, fixture_cancel_mode=fixture_mode)


def aura_tree(rows):
    attempts = []
    for n in range(1, 4):
        w = window(rows, f"aura-tree-before-{n}", f"aura-tree-after-{n}")
        if not w:
            attempts.append({"run": n, "missing": True})
            continue
        before, after, events = w
        enemy_events = [e for e in events if e.get("type") == "block_break" and isinstance(e.get("x"), int) and e["x"] >= 16]
        removed = before.get("tree_target_1") == before.get("tree_target_2") == "OAK_LOG" and after.get("tree_target_1") == after.get("tree_target_2") == "AIR"
        attempts.append({"run": n, "bypass": removed and not enemy_events, "removed": removed, "enemy_break_events": enemy_events})
    hits = sum(a.get("bypass") is True for a in attempts)
    completed = [a for a in attempts if "removed" in a]
    status = "confirmed" if hits == 3 else "rejected" if len(completed) == 3 and all(a["removed"] is False for a in completed) else "inconclusive"
    return result(status, "AuraSkills Treecapitator removed enemy-claim blocks without BlockBreakEvent", attempts=attempts, confirmed_attempts=hits)


def aura_terraform(rows):
    attempts = []
    for n in range(1, 4):
        w = window(rows, f"aura-terraform-before-{n}", f"aura-terraform-after-{n}")
        if not w:
            attempts.append({"run": n, "missing": True})
            continue
        before, after, events = w
        enemy_events = [e for e in events if e.get("type") == "block_break" and isinstance(e.get("x"), int) and e["x"] >= 16]
        removed = (
            before.get("terraform_target_1") == before.get("terraform_target_2") == before.get("terraform_target_3") == "DIRT"
            and after.get("terraform_target_1") == after.get("terraform_target_2") == after.get("terraform_target_3") == "AIR"
        )
        attempts.append({"run": n, "bypass": removed and not enemy_events, "removed": removed, "enemy_break_events": enemy_events})
    hits = sum(a.get("bypass") is True for a in attempts)
    completed = [a for a in attempts if "removed" in a]
    status = "confirmed" if hits == 3 else "rejected" if len(completed) == 3 and all(a["removed"] is False for a in completed) else "inconclusive"
    return result(status, "AuraSkills Terraform removed enemy-claim blocks without BlockBreakEvent", attempts=attempts, confirmed_attempts=hits)


def grindstone_xp(rows):
    attempts = []
    for n in range(1, 4):
        w = window(rows, f"grindstone-before-{n}", f"grindstone-after-{n}")
        if not w:
            attempts.append({"run": n, "missing": True})
            continue
        before, after, events = w
        clicks = [e for e in events if e.get("type") == "grindstone_result_click"]
        try:
            xp_before = float(before.get("attacker_enchanting_xp"))
            xp_after = float(after.get("attacker_enchanting_xp"))
        except (TypeError, ValueError):
            xp_before = xp_after = None
        persisted = (
            after.get("grindstone_input_0") == "DIAMOND_SWORDx1"
            and int(after.get("grindstone_input_fragility", 0)) >= 1
        )
        cancelled = any(e.get("cancelled") is True for e in clicks)
        gained = xp_before is not None and xp_after is not None and xp_after > xp_before
        attempts.append({
            "run": n,
            "xp_before": xp_before,
            "xp_after": xp_after,
            "xp_gain": None if xp_before is None or xp_after is None else xp_after - xp_before,
            "item_persisted": persisted,
            "cancelled_result_click": cancelled,
            "server_click_events": clicks,
            "exploitable": gained and persisted and cancelled,
        })
    hits = sum(a.get("exploitable") is True for a in attempts)
    completed = [a for a in attempts if "exploitable" in a]
    status = "confirmed" if hits == 3 else "rejected" if len(completed) == 3 and all(a["exploitable"] is False for a in completed) else "inconclusive"
    return result(
        status,
        "AuraSkills awarded repeatable grindstone XP while ExcellentEnchants preserved the cursed item",
        attempts=attempts,
        confirmed_attempts=hits,
    )


def alchemy_amplifier(rows):
    w = window(rows, "alchemy-before-take", "alchemy-after-take")
    if not w:
        return result("inconclusive", "AuraSkills paid five brewing cycles on one potion take", reason="missing_window")
    before, after, events = w
    try:
        xp_before = float(before.get("attacker_alchemy_xp"))
        xp_after = float(after.get("attacker_alchemy_xp"))
    except (TypeError, ValueError):
        return result("inconclusive", "AuraSkills paid five brewing cycles on one potion take", reason="missing_xp", before=before, after=after)
    chest_count = int(before.get("alchemy_chest_potions", 0))
    gain = xp_after - xp_before
    clicks = [e for e in events if e.get("type") == "alchemy_result_click"]
    brew_events = [e for e in rows if e.get("type") == "brew_event" and e.get("cancelled") is False]
    potion_moves = [e for e in rows if e.get("type") == "inventory_move" and e.get("item") == "POTION" and e.get("cancelled") is False]
    exact_five_cycle_witness = len(brew_events) >= 5 and chest_count >= 15
    confirmed = exact_five_cycle_witness and gain >= 49.9 and len(clicks) >= 1
    rejected = exact_five_cycle_witness and gain <= 10.1 and len(clicks) >= 1
    status = "confirmed" if confirmed else "rejected" if rejected else "inconclusive"
    return result(
        status,
        "AuraSkills paid five brewing cycles on one potion take",
        xp_before=xp_before,
        xp_after=xp_after,
        xp_gain=gain,
        hopper_extracted_potions=chest_count,
        brew_events=len(brew_events),
        potion_move_events=len(potion_moves),
        server_click_events=clicks,
    )


def simple(rows, before_label, after_label, field, vulnerable, title):
    w = window(rows, before_label, after_label)
    if not w:
        return result("inconclusive", title, reason="missing_window")
    before, after, events = w
    changed = after.get(field) == vulnerable and before.get(field) != vulnerable
    enemy_events = [e for e in events if e.get("type") == "block_break" and isinstance(e.get("x"), int) and e["x"] >= 16]
    return result("confirmed" if changed else "rejected", title, before=before, after=after, enemy_break_events=enemy_events)


def hopper(rows):
    w = window(rows, "hopper-before", "hopper-after")
    if not w:
        return result("inconclusive", "Cross-claim hopper transfer", reason="missing_window")
    before, after, events = w
    moved = int(after.get("target_chest_count", 0)) > int(before.get("target_chest_count", 0))
    return result("observed_low_impact" if moved else "rejected", "Cross-claim hopper transfer", before=before, after=after, move_events=[e for e in events if e.get("type") == "inventory_move"])


def border_chest(rows):
    w = window(rows, "border-chest-before", "border-chest-after")
    if not w:
        return result("inconclusive", "Attacker merged and looted an enemy-claim chest", reason="missing_window")
    before, after, events = w
    merges = [e for e in events if e.get("type") == "server_chest_merge" and e.get("invoked") is True]
    opens = [e for e in events if e.get("type") == "border_chest_open"]
    placed = after.get("border_attacker_chest_type") == "CHEST"
    stolen = (
        int(before.get("border_victim_netherite_count", 0)) >= 27
        and int(after.get("border_victim_netherite_count", 0)) < int(before.get("border_victim_netherite_count", 0))
        and (
            int(after.get("attacker_netherite_count", 0)) > 0
            or int(after.get("border_hopper_netherite_count", 0)) > 0
        )
    )
    denied = opens and all(e.get("cancelled") is True for e in opens)
    status = "confirmed" if merges and placed and stolen else "rejected" if merges and placed and denied else "inconclusive"
    return result(status, "Attacker merged and looted an enemy-claim chest", before=before, after=after, merge_events=merges, open_events=opens)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    rows = read_rows(args.evidence)
    claims_ok, claims = claim_witness(rows)

    def blocked(title):
        return result("inconclusive", title, reason="claims_not_verified", claim_witness=claims)

    findings = {
        "schema_version": 1,
        "event_count": len(rows),
        "claims_verified": claims_ok,
        "claim_witness": claims,
        "findings": {
            "auraskills_alchemy_five_cycle_amplifier": alchemy_amplifier(rows),
            "auraskills_excellentenchants_grindstone_xp": grindstone_xp(rows),
            "portal_factions": portal(rows, "factions", 3, False) if claims_ok else blocked("Cancelled portal creation duplicated a filled barrel"),
            "portal_cancel_control": portal(rows, "control", 2, True),
            "auraskills_terraform": aura_terraform(rows) if claims_ok else blocked("AuraSkills Terraform removed enemy-claim blocks without BlockBreakEvent"),
            "auraskills_treecapitator": aura_tree(rows) if claims_ok else blocked("AuraSkills Treecapitator removed enemy-claim blocks without BlockBreakEvent"),
            "excellentenchants_treefeller": simple(rows, "tree-before", "tree-after", "tree_target_1", "AIR", "ExcellentEnchants Treefeller crossed enemy claim") if claims_ok else blocked("ExcellentEnchants Treefeller crossed enemy claim"),
            "excellentenchants_tunnel": simple(rows, "tunnel-before", "tunnel-after", "tunnel_target", "AIR", "ExcellentEnchants Tunnel crossed enemy claim") if claims_ok else blocked("ExcellentEnchants Tunnel crossed enemy claim"),
            "excellentenchants_blast": simple(rows, "blast-before", "blast-after", "tunnel_target", "AIR", "ExcellentEnchants Blast Mining crossed enemy claim") if claims_ok else blocked("ExcellentEnchants Blast Mining crossed enemy claim"),
            "factions_piston": simple(rows, "piston-before", "piston-after", "piston_payload_target", "DIAMOND_BLOCK", "Piston moved block into enemy claim") if claims_ok else blocked("Piston moved block into enemy claim"),
            "factions_hopper": hopper(rows) if claims_ok else blocked("Cross-claim hopper transfer"),
            "factions_cross_claim_double_chest": border_chest(rows) if claims_ok else blocked("Attacker merged and looted an enemy-claim chest"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(findings, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
