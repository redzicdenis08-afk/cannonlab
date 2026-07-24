#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze-impulse-graph.py"
spec = importlib.util.spec_from_file_location("analyze_impulse_graph", SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to import {SCRIPT}")
impulse = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = impulse
spec.loader.exec_module(impulse)

FIXTURES = ROOT / "audit-fixtures"
REFERENCE_EVENTS = FIXTURES / "impulse-events-reference.csv"
CANDIDATE_EVENTS = FIXTURES / "impulse-events-candidate.csv"
CAUSAL_EVENTS = FIXTURES / "impulse-causal-events.csv"


def entity(report: dict, uuid: str) -> dict:
    return next(row for row in report["entities"] if row["uuid"] == uuid)


def test_builds_source_accounted_impulse_graph() -> None:
    report = impulse.build_graph(REFERENCE_EVENTS, CAUSAL_EVENTS)
    assert report["status"] == "WARN", report
    assert report["summary"]["entity_count"] == 6, report
    assert report["summary"]["impulse_edge_count"] == 2, report
    assert report["summary"]["unexplained_abrupt_change_count"] == 1, report

    moving = entity(report, "MOVE-A")
    assert moving["source"]["confidence"] == "high", moving
    assert [row["component_id"] for row in moving["source"]["candidates"]] == [
        "D[2,100,0]"
    ], moving
    assert len(moving["impulse_edges"]) == 1, moving
    edge = moving["impulse_edges"][0]
    assert edge["confidence"] == "high", edge
    assert edge["observed_velocity_delta"] == [1.0, 0.0, 0.0], edge
    assert [row["source_uuid"] for row in edge["source_candidates"]] == ["SRC-A"], edge
    assert edge["source_candidates"][0]["alignment_cosine"] > 0.99, edge


def test_preserves_ambiguous_explosion_sources() -> None:
    report = impulse.build_graph(REFERENCE_EVENTS, CAUSAL_EVENTS)
    moving = entity(report, "MOVE-B")
    assert len(moving["impulse_edges"]) == 1, moving
    edge = moving["impulse_edges"][0]
    assert edge["confidence"] == "ambiguous", edge
    assert [row["source_uuid"] for row in edge["source_candidates"]] == [
        "SRC-B1",
        "SRC-B2",
    ], edge
    assert report["summary"]["ambiguous_impulse_edge_count"] == 1, report


def test_marks_non_explosion_abrupt_change_unexplained() -> None:
    report = impulse.build_graph(REFERENCE_EVENTS, CAUSAL_EVENTS)
    falling = entity(report, "COLLIDE-C")
    assert falling["impulse_edges"] == [], falling
    assert len(falling["unexplained_abrupt_changes"]) == 1, falling
    change = falling["unexplained_abrupt_changes"][0]
    assert change["confidence"] == "unexplained", change
    assert change["observed_velocity_delta"] == [-1.0, 0.0, 0.0], change


def test_comparison_finds_first_velocity_divergence() -> None:
    reference = impulse.build_graph(REFERENCE_EVENTS, CAUSAL_EVENTS)
    candidate = impulse.build_graph(CANDIDATE_EVENTS, CAUSAL_EVENTS)
    comparison = impulse.compare_graphs(
        reference,
        candidate,
        max_timing_delta=0,
        max_velocity_delta=0.05,
        max_position_delta=0.1,
    )
    assert comparison["status"] == "FAIL", comparison
    assert comparison["divergence_count"] == 1, comparison
    first = comparison["first_divergence"]
    assert first["kind"] == "impulse_velocity_drift", first
    assert first["tick"] == 3, first
    assert first["reference"] == [1.0, 0.0392, 0.0], first
    assert first["candidate"] == [0.4, 0.0392, 0.0], first
    assert first["reference_raw_delta"] == [1.0, 0.0, 0.0], first
    assert first["candidate_raw_delta"] == [0.4, 0.0, 0.0], first


def test_identical_graphs_compare_cleanly() -> None:
    reference = impulse.build_graph(REFERENCE_EVENTS, CAUSAL_EVENTS)
    comparison = impulse.compare_graphs(reference, reference)
    assert comparison["status"] == "PASS", comparison
    assert comparison["first_divergence"] is None, comparison


def test_missing_continuous_telemetry_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bad-events.csv"
        path.write_text("tick,event,type,uuid\n0,ENTITY,PRIMED_TNT,x\n", encoding="utf-8")
        try:
            impulse.build_graph(path, CAUSAL_EVENTS)
        except ValueError as exc:
            assert "missing columns" in str(exc), exc
        else:
            raise AssertionError("missing trajectory columns unexpectedly passed")


def test_fractional_or_sparse_ticks_are_not_silently_rewritten() -> None:
    report = impulse.build_graph(REFERENCE_EVENTS, CAUSAL_EVENTS)
    moving = entity(report, "MOVE-A")
    edge = moving["impulse_edges"][0]
    assert edge["before_tick"] == 2, edge
    assert edge["after_tick"] == 3, edge
    assert edge["tick_gap"] == 1, edge
    assert report["truth_boundary"]["exact_vanilla_push_recreated"] is False, report


def test_nominal_drag_and_gravity_do_not_become_fake_impulses() -> None:
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        events = directory_path / "events.csv"
        causal = directory_path / "causal.csv"
        events.write_text(
            "tick,event,type,uuid,x,y,z,vx,vy,vz,fuse,affected_blocks\n"
            "0,ENTITY,PRIMED_TNT,FAST,1000,100,1000,10,0,0,80,0\n"
            "1,ENTITY,PRIMED_TNT,FAST,1009.8,99.9608,1000,9.8,-0.0392,0,79,0\n",
            encoding="utf-8",
        )
        causal.write_text(
            "tick,server_tick,sequence,event,component_id,block_type,"
            "world_x,world_y,world_z,relative_x,relative_y,relative_z,"
            "old_power,new_power,direction,moved_blocks,item,"
            "entity_uuid,entity_type,vx,vy,vz,fuse,details\n",
            encoding="utf-8",
        )
        report = impulse.build_graph(events, causal)
        fast = entity(report, "FAST")
        assert fast["impulse_edges"] == [], fast
        assert fast["unexplained_abrupt_changes"] == [], fast
        assert report["summary"]["unexplained_abrupt_change_count"] == 0, report


def main() -> None:
    tests = [
        test_builds_source_accounted_impulse_graph,
        test_preserves_ambiguous_explosion_sources,
        test_marks_non_explosion_abrupt_change_unexplained,
        test_comparison_finds_first_velocity_divergence,
        test_identical_graphs_compare_cleanly,
        test_missing_continuous_telemetry_fails_closed,
        test_fractional_or_sparse_ticks_are_not_silently_rewritten,
        test_nominal_drag_and_gravity_do_not_become_fake_impulses,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
