#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shared = load("shared_core_envelope_test_base", "legacy-shared-core-audit.py")
envelope = load("shared_core_envelope_test", "legacy-shared-core-envelope.py")
architecture = shared.load_script(
    "shared_core_envelope_test_architecture", "legacy-cannon-architecture.py"
)


def run(
    first_all,
    second_all,
    *,
    seed=None,
    turns=0,
    max_layers=8,
    max_added_support=4096,
):
    return envelope.expand_support_shell(
        shared,
        architecture,
        set(seed or {(0, 0, 0), (1, 0, 0)}),
        first_all,
        second_all,
        turns,
        max_layers=max_layers,
        max_added_support=max_added_support,
    )


def test_identical_obsidian_shell_closes() -> None:
    blocks = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (49, 0),
    }
    result = run(blocks, blocks)
    assert result["classification"] == "FACE_CLOSED_AFTER_SHARED_SUPPORT_EXPANSION", result
    assert result["added_support_count"] == 1, result
    assert result["layers_completed"] == 1, result
    assert result["promotion_eligible"] is False, result


def test_one_sided_support_stays_open() -> None:
    first = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (49, 0),
    }
    second = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
    }
    result = run(first, second)
    assert result["classification"] == "OPEN_OR_UNRESOLVED_SHARED_REGION", result
    assert result["residual_boundary_edge_counts"]["first_only_nonair"] == 1, result


def test_shared_functional_continuation_is_not_swallowed() -> None:
    blocks = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (23, 5),
    }
    result = run(blocks, blocks)
    assert result["classification"] == "OPEN_OR_UNRESOLVED_SHARED_REGION", result
    assert result["added_support_count"] == 0, result
    assert result["residual_boundary_edge_counts"]["shared_equivalent_functional"] == 1, result


def test_directional_support_is_unresolved_after_rotation() -> None:
    first = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (107, 0),
    }
    second = dict(first)
    result = run(first, second, turns=1)
    assert result["classification"] == "OPEN_OR_UNRESOLVED_SHARED_REGION", result
    assert result["residual_boundary_edge_counts"]["shared_unresolved_support"] == 1, result


def test_support_cap_fails_closed() -> None:
    blocks = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (49, 0),
        (3, 0, 0): (49, 0),
    }
    result = run(blocks, blocks, max_added_support=1)
    assert result["classification"] == "SHARED_SUPPORT_EXPANSION_INCOMPLETE", result
    assert result["support_expansion_truncated"] is True, result
    assert result["added_support_count"] == 1, result


def main() -> int:
    tests = [
        test_identical_obsidian_shell_closes,
        test_one_sided_support_stays_open,
        test_shared_functional_continuation_is_not_swallowed,
        test_directional_support_is_unresolved_after_rotation,
        test_support_cap_fails_closed,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} shared support-envelope regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
