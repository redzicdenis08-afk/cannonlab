#!/usr/bin/env python3
"""PhaseLab passive telemetry analyzer.

Reads a PhaseLab v4.2+ CSV and produces plain-English findings without
performing movement, changing collision, or sending network packets.

Usage:
    python tools/analyze_phaselab.py C:\\path\\to\\PHASELAB_LATEST.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

CORRECTION_RE = re.compile(r"correction_distance=([-+]?\d+(?:\.\d+)?)")
LOW_SPEED = 0.01
PERSISTENT_OVERLAP_SECONDS = 0.15


@dataclass
class SegmentFinding:
    segment_id: int
    label: str
    verdict: str
    confidence: str
    duration_seconds: float
    rows: int
    mounted_samples: int
    water_samples: int
    collision_samples: int
    player_setbacks: int
    vehicle_corrections: int
    position_packets: int
    dismounts: int
    unexpected_dismounts: int
    max_player_correction: float
    max_vehicle_correction: float
    vehicle_displacement: float
    stationary_tail_seconds: float
    persistent_player_overlap_seconds: float
    persistent_vehicle_overlap_seconds: float
    evidence: list[str]


def _truth(value: str | None) -> bool:
    return str(value).strip().lower() == "true"


def _number(value: str | None, default: float = math.nan) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if "[" in text:
        text = text.split("[", 1)[0]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _vector(row: dict[str, str], prefix: str) -> tuple[float, float, float] | None:
    values = tuple(_number(row.get(f"{prefix}_{axis}")) for axis in "xyz")
    return values if all(math.isfinite(value) for value in values) else None


def _distance(a: tuple[float, float, float] | None, b: tuple[float, float, float] | None) -> float:
    if a is None or b is None:
        return 0.0
    return math.dist(a, b)


def _correction_distance(row: dict[str, str]) -> float:
    match = CORRECTION_RE.search(row.get("detail", ""))
    return float(match.group(1)) if match else 0.0


def _consecutive_seconds(rows: list[dict[str, str]], predicate) -> float:
    longest = 0.0
    start: datetime | None = None
    previous: datetime | None = None
    for row in rows:
        current = _timestamp(row.get("utc_timestamp")) or _timestamp(row.get("local_timestamp"))
        if current is None:
            continue
        if predicate(row):
            if start is None or previous is None or (current - previous).total_seconds() > 0.20:
                start = current
            longest = max(longest, (current - start).total_seconds())
        else:
            start = None
        previous = current
    return max(0.0, longest)


def _stationary_tail_seconds(rows: list[dict[str, str]]) -> float:
    samples = [row for row in rows if row.get("event") == "SAMPLE" and _truth(row.get("passenger"))]
    if not samples:
        return 0.0
    end = _timestamp(samples[-1].get("utc_timestamp")) or _timestamp(samples[-1].get("local_timestamp"))
    if end is None:
        return 0.0
    start = end
    for row in reversed(samples):
        velocity = _vector(row, "vehicle_d")
        if velocity is None or math.sqrt(sum(component * component for component in velocity)) > LOW_SPEED:
            break
        stamp = _timestamp(row.get("utc_timestamp")) or _timestamp(row.get("local_timestamp"))
        if stamp is not None:
            start = stamp
    return max(0.0, (end - start).total_seconds())


def _segment_duration(rows: list[dict[str, str]]) -> float:
    stamps = [
        _timestamp(row.get("utc_timestamp")) or _timestamp(row.get("local_timestamp"))
        for row in rows
    ]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(0.0, (max(stamps) - min(stamps)).total_seconds()) if stamps else 0.0


def analyze_segment(segment_id: int, rows: list[dict[str, str]]) -> SegmentFinding:
    events = Counter(row.get("event", "") for row in rows)
    label = next((row.get("segment_label", "GENERAL") for row in rows if row.get("segment_label") not in ("", "NONE")), "GENERAL")
    samples = [row for row in rows if row.get("event") == "SAMPLE"]
    mounted = [row for row in samples if _truth(row.get("passenger"))]
    water = [row for row in samples if _truth(row.get("in_water"))]
    collisions = [row for row in samples if _truth(row.get("horizontal_collision"))]

    player_overlap = _consecutive_seconds(
        rows,
        lambda row: _truth(row.get("passenger")) and row.get("player_box_clear", "true").lower() == "false",
    )
    vehicle_overlap = _consecutive_seconds(
        rows,
        lambda row: _truth(row.get("passenger")) and row.get("vehicle_box_clear", "true").lower() == "false",
    )

    dismount_rows = [row for row in rows if row.get("event") == "DISMOUNTED"]
    unexpected_dismounts = 0
    for row in dismount_rows:
        index = rows.index(row)
        previous = rows[index - 1] if index > 0 else row
        if not _truth(previous.get("sneaking")) and not _truth(row.get("sneaking")):
            unexpected_dismounts += 1

    player_corrections = [
        _correction_distance(row)
        for row in rows
        if row.get("event") == "SERVER_SETBACK_CORRELATED"
    ]
    vehicle_corrections = [
        _correction_distance(row)
        for row in rows
        if row.get("event") == "SERVER_VEHICLE_CORRECTION"
    ]

    first_vehicle = next((_vector(row, "vehicle") for row in mounted if _vector(row, "vehicle") is not None), None)
    last_vehicle = next((_vector(row, "vehicle") for row in reversed(mounted) if _vector(row, "vehicle") is not None), None)
    vehicle_displacement = _distance(first_vehicle, last_vehicle)
    stationary_tail = _stationary_tail_seconds(rows)

    evidence: list[str] = []
    if player_overlap >= PERSISTENT_OVERLAP_SECONDS or vehicle_overlap >= PERSISTENT_OVERLAP_SECONDS:
        verdict = "POSSIBLE_PERSISTENT_COLLISION_OVERLAP"
        confidence = "HIGH"
        evidence.append(
            f"collision clearance stayed false while mounted for player={player_overlap:.3f}s, vehicle={vehicle_overlap:.3f}s"
        )
    elif vehicle_corrections:
        verdict = "SERVER_VEHICLE_REJECTION"
        confidence = "HIGH"
        evidence.append(f"{len(vehicle_corrections)} inbound vehicle correction packet(s)")
    elif player_corrections:
        verdict = "SERVER_PLAYER_REJECTION"
        confidence = "MEDIUM"
        evidence.append(f"{len(player_corrections)} correlated player setback(s)")
    elif unexpected_dismounts:
        verdict = "UNEXPECTED_OR_SERVER_FORCED_DISMOUNT"
        confidence = "MEDIUM"
        evidence.append(f"{unexpected_dismounts} dismount(s) without a nearby sneaking signal")
    elif collisions and stationary_tail >= 0.50:
        verdict = "CLEAN_COLLISION_BLOCK"
        confidence = "HIGH"
        evidence.append(f"horizontal collision observed and mounted vehicle stayed nearly stationary for {stationary_tail:.2f}s")
    elif water and stationary_tail >= 0.50:
        verdict = "CLEAN_WATER_STOP"
        confidence = "MEDIUM"
        evidence.append(f"water observed and mounted vehicle stayed nearly stationary for {stationary_tail:.2f}s")
    else:
        verdict = "NO_HIGH_CONFIDENCE_FINDING"
        confidence = "LOW"
        evidence.append("no persistent overlap, vehicle correction, correlated rejection, or clear collision stop was observed")

    if mounted:
        evidence.append(f"mounted samples={len(mounted)}, vehicle displacement={vehicle_displacement:.3f} blocks")
    if events["SERVER_POSITION_PACKET"]:
        evidence.append(f"uncorrelated server position packets={events['SERVER_POSITION_PACKET']}")
    if dismount_rows:
        evidence.append(f"dismount events={len(dismount_rows)}")
    if "TEST_END" not in events:
        evidence.append("segment has no TEST_END marker; confidence may be reduced")
        if confidence == "HIGH":
            confidence = "MEDIUM"

    return SegmentFinding(
        segment_id=segment_id,
        label=label,
        verdict=verdict,
        confidence=confidence,
        duration_seconds=_segment_duration(rows),
        rows=len(rows),
        mounted_samples=len(mounted),
        water_samples=len(water),
        collision_samples=len(collisions),
        player_setbacks=len(player_corrections),
        vehicle_corrections=len(vehicle_corrections),
        position_packets=events["SERVER_POSITION_PACKET"],
        dismounts=len(dismount_rows),
        unexpected_dismounts=unexpected_dismounts,
        max_player_correction=max(player_corrections, default=0.0),
        max_vehicle_correction=max(vehicle_corrections, default=0.0),
        vehicle_displacement=vehicle_displacement,
        stationary_tail_seconds=stationary_tail,
        persistent_player_overlap_seconds=player_overlap,
        persistent_vehicle_overlap_seconds=vehicle_overlap,
        evidence=evidence,
    )


def analyze_csv(path: Path) -> tuple[dict[str, Any], list[SegmentFinding]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"segment_id", "segment_label", "event", "utc_timestamp"}
        missing = sorted(required.difference(reader.fieldnames or []))
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        rows = list(reader)

    segments: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        segment_id = _integer(row.get("segment_id"))
        if segment_id > 0:
            segments[segment_id].append(row)

    findings = [analyze_segment(segment_id, segment_rows) for segment_id, segment_rows in sorted(segments.items())]
    verdict_counts = Counter(finding.verdict for finding in findings)
    metadata = {
        "source": str(path.resolve()),
        "rows": len(rows),
        "segments": len(findings),
        "verdict_counts": dict(verdict_counts),
        "session_ids": sorted({row.get("session_id", "") for row in rows if row.get("session_id")}),
    }
    return metadata, findings


def render_text(metadata: dict[str, Any], findings: Iterable[SegmentFinding]) -> str:
    findings = list(findings)
    lines = [
        "PhaseLab Findings Analyzer",
        f"source={metadata['source']}",
        f"rows={metadata['rows']}",
        f"segments={metadata['segments']}",
        "",
    ]
    if not findings:
        lines.append("No marked test segments were found. Use F9 to start and end a test.")
        return "\n".join(lines) + "\n"

    for finding in findings:
        lines.extend(
            [
                f"TEST {finding.segment_id}: {finding.label}",
                f"verdict={finding.verdict}",
                f"confidence={finding.confidence}",
                f"duration_seconds={finding.duration_seconds:.3f}",
                f"mounted_samples={finding.mounted_samples}",
                f"water_samples={finding.water_samples}",
                f"collision_samples={finding.collision_samples}",
                f"player_setbacks={finding.player_setbacks}",
                f"vehicle_corrections={finding.vehicle_corrections}",
                f"unexpected_dismounts={finding.unexpected_dismounts}",
                f"vehicle_displacement={finding.vehicle_displacement:.3f}",
                f"stationary_tail_seconds={finding.stationary_tail_seconds:.3f}",
            ]
        )
        lines.extend(f"evidence=- {item}" for item in finding.evidence)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze passive PhaseLab CSV telemetry")
    parser.add_argument("csv_path", type=Path, help="Path to PHASELAB_LATEST.csv or an archived telemetry CSV")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory; defaults to the CSV folder")
    args = parser.parse_args()

    if not args.csv_path.is_file():
        parser.error(f"file not found: {args.csv_path}")

    output_dir = args.output_dir or args.csv_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata, findings = analyze_csv(args.csv_path)

    text_path = output_dir / "PHASELAB_FINDINGS.txt"
    json_path = output_dir / "PHASELAB_FINDINGS.json"
    text_path.write_text(render_text(metadata, findings), encoding="utf-8")
    json_path.write_text(
        json.dumps({"metadata": metadata, "findings": [asdict(finding) for finding in findings]}, indent=2),
        encoding="utf-8",
    )

    print(text_path)
    print(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
