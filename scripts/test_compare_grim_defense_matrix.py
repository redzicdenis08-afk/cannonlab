#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).with_name("compare_grim_defense_matrix.py")
spec = importlib.util.spec_from_file_location("compare_grim", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def verdict(stack, boat, horse):
    return {
        "stack_id": stack,
        "grim_version": "none" if stack == "baseline" else "test",
        "by_family": {
            "boat": {"successes": boat[0], "attempts": boat[1]},
            "horse": {"successes": horse[0], "attempts": horse[1]},
        },
    }


base = verdict("baseline", (2, 2), (1, 2))
blocked = module.compare(base, verdict("grim", (0, 2), (0, 2)))
assert blocked["blocked"] == 2
assert blocked["regressions"] == 0
regressed = module.compare(base, verdict("grim", (1, 2), (0, 2)))
assert regressed["regressions"] == 1
assert regressed["blocked"] == 1
print("ok")
