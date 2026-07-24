#!/usr/bin/env python3
"""
CI fire analyzer — reads a CannonLab lab-artifacts results dir (real Sakura fire
telemetry) and diagnoses WHY a cannon did or didn't breach. Operationalizes the
feedback loop: fire in CI -> this tells you the exact failure mode.

Usage: python ci_fire_analyzer.py <path-to-results-dir-or-run-summary.json>

Diagnosis focuses on the mechanic that decides watered-wall raids:
  did the payload TNT explode EMBEDDED in sand (breaches water) or bare in
  water (cancelled)? Reads breach-events.csv per-explosion evidence.
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

def find_summary(root: Path):
    if root.is_file() and root.name == "run-summary.json": return root
    hits = list(root.rglob("run-summary.json"))
    return hits[0] if hits else None

def analyze(root: Path):
    summ = find_summary(root)
    if not summ:
        print("no run-summary.json found under", root); return 1
    base = summ.parent
    S = json.loads(summ.read_text(encoding="utf-8"))
    print("="*64)
    print("CANNON:", S.get("cannon_file"))
    print(f"target: {S.get('target_material')} {S.get('target_type')} @ dist {S.get('target_distance')}"
          f"  finish: {S.get('finish_reason')}")
    # per-shot
    for shot_dir in sorted(base.glob("shot-*")):
        sm_p = shot_dir / "summary.json"
        if not sm_p.exists(): continue
        sm = json.loads(sm_p.read_text(encoding="utf-8"))
        launched = sm.get("maximum_forward_distance", 0) >= 3
        print(f"\n[{shot_dir.name}]")
        print(f"  LAUNCH : payload={sm.get('saw_payload')}  dispenses={sm.get('dispense_events')}"
              f"  explosions={sm.get('explosions')}  max_forward={sm.get('maximum_forward_distance'):.1f}"
              f"  -> {'LAUNCHED' if launched else 'NO LAUNCH'}")
        print(f"  BREACH : destroyed={sm.get('destroyed_blocks')}  embedded_expl={sm.get('embedded_payload_explosions')}"
              f"  falling_blocks_max={sm.get('maximum_falling_blocks')}  tnt_max={sm.get('maximum_tnt_entities')}")
        # per-explosion embed evidence
        be = shot_dir / "breach-events.csv"
        if be.exists():
            rows = list(csv.DictReader(be.open(encoding="utf-8")))
            expl = [r for r in rows if r.get("event") == "EXPLOSION"]
            in_water = sum(1 for r in expl if r.get("center_block") == "WATER")
            embedded = sum(1 for r in expl if str(r.get("falling_overlap_evidence")).lower() == "true")
            hit_target = sum(1 for r in expl if str(r.get("target_contact")).lower() == "true")
            print(f"  EVIDENCE: {len(expl)} explosions | in_water={in_water} | sand-embedded={embedded}"
                  f" | target_contact={hit_target}")
            # verdict
            if launched and sm.get("destroyed_blocks",0) == 0:
                if embedded == 0 and in_water > 0:
                    print("  >>> DIAGNOSIS: launches fine, but payload detonates in WATER with NO sand embedded")
                    print("      -> water cancels every blast. FIX: co-locate sand with payload TNT (hybrid timing).")
                elif hit_target == 0:
                    print("  >>> DIAGNOSIS: explosions never reach the target box (short/mis-timed).")
            elif sm.get("destroyed_blocks",0) > 0:
                print("  >>> BREACH SUCCESS: sand-embed working, target taking damage.")
    return 0

if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    raise SystemExit(analyze(root))
