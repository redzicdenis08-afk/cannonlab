#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

RATIO_LINE = re.compile(
    r"^\s*(?P<name>.+?)\s+Amount:\s*(?P<amount>-|\d+)\s+Tick:\s*(?P<timing>\S+)\s*$",
    re.IGNORECASE,
)
EXACT_TIMING = re.compile(r"^(?P<value>\d+(?:\.\d+)?)$")
RANGE_TIMING = re.compile(r"^(?P<minimum>\d+(?:\.\d+)?)-(?P<maximum>\d+(?:\.\d+)?)$")
OPEN_TIMING = re.compile(r"^(?P<minimum>\d+(?:\.\d+)?)\+$")

ROLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("power", ("power",)),
    ("scatter", ("scatter",)),
    ("stopper", ("stopper",)),
    ("nuke", ("nuke",)),
    ("osrb", ("osrb", "restack")),
    ("reverse", ("rev", "reverse")),
    ("hammer", ("hammer",)),
    ("falling_payload", ("sand", "concrete", "gravel")),
)

HARD_REQUIRED_ROLES = ("power",)
SOFT_REQUIRED_ROLES = ("falling_payload", "hammer")


@dataclass(frozen=True)
class Timing:
    raw: str
    minimum: float
    maximum: float | None
    open_high: bool
    exact: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "open_high": self.open_high,
            "exact": self.exact,
        }


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def parse_timing(raw: str) -> Timing:
    raw = raw.strip()
    match = EXACT_TIMING.fullmatch(raw)
    if match:
        value = float(match.group("value"))
        return Timing(raw, value, value, False, True)

    match = RANGE_TIMING.fullmatch(raw)
    if match:
        minimum = float(match.group("minimum"))
        maximum = float(match.group("maximum"))
        if maximum < minimum:
            raise ValueError(f"timing range ends before it starts: {raw!r}")
        return Timing(raw, minimum, maximum, False, minimum == maximum)

    match = OPEN_TIMING.fullmatch(raw)
    if match:
        minimum = float(match.group("minimum"))
        return Timing(raw, minimum, None, True, False)

    raise ValueError(f"unsupported timing token: {raw!r}")


def normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def tags_for(name: str) -> list[str]:
    lowered = normalize_name(name).lower()
    # Power labels describe activation cohorts, not payload entities. Keep them
    # exclusive so names such as "Sand Power" do not inflate stack accounting.
    if "power" in lowered:
        return ["power"]

    tags: list[str] = []
    for role, keywords in ROLE_KEYWORDS:
        if role == "power":
            continue
        if any(keyword in lowered for keyword in keywords):
            tags.append(role)
    if not tags:
        tags.append("auxiliary")
    return tags


def primary_role(tags: list[str]) -> str:
    # Specific mechanism tags beat generic falling payload/hammer tags.
    priority = (
        "power",
        "scatter",
        "stopper",
        "nuke",
        "osrb",
        "reverse",
        "hammer",
        "falling_payload",
        "auxiliary",
    )
    for role in priority:
        if role in tags:
            return role
    return "auxiliary"


def parse_ratio_text(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    parse_notes: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue

        match = RATIO_LINE.fullmatch(raw_line)
        if not match:
            raise ValueError(f"line {line_number}: unsupported ratio row: {raw_line!r}")

        name = normalize_name(match.group("name"))
        amount_raw = match.group("amount")
        timing = parse_timing(match.group("timing"))
        tags = tags_for(name)
        entries.append(
            {
                "index": len(entries) + 1,
                "line_number": line_number,
                "name": name,
                "normalized_name": name.lower(),
                "amount": None if amount_raw == "-" else int(amount_raw),
                "timing": timing.to_json(),
                "tags": tags,
                "primary_role": primary_role(tags),
            }
        )
        if timing.open_high:
            parse_notes.append(f"{name}: open-ended timing {timing.raw!r} preserved")
        elif not timing.exact:
            parse_notes.append(f"{name}: timing range {timing.raw!r} preserved")
        elif "." in timing.raw:
            parse_notes.append(
                f"{name}: fractional timing {timing.raw!r} preserved as authored ordering evidence"
            )

    if not entries:
        raise ValueError("ratio contains no parseable entries")
    return entries, parse_notes


def interval_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_min = float(left["timing"]["minimum"])
    right_min = float(right["timing"]["minimum"])
    left_max = left["timing"]["maximum"]
    right_max = right["timing"]["maximum"]
    left_high = float("inf") if left_max is None else float(left_max)
    right_high = float("inf") if right_max is None else float(right_max)
    return left_min <= right_high and right_min <= left_high


def timing_key(entry: dict[str, Any]) -> tuple[float, float, int]:
    timing = entry["timing"]
    maximum = float("inf") if timing["maximum"] is None else float(timing["maximum"])
    return float(timing["minimum"]), maximum, int(entry["index"])


def summarize_roles(entries: list[dict[str, Any]]) -> dict[str, Any]:
    roles: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for tag in entry["tags"]:
            roles.setdefault(tag, []).append(entry)
    return {
        role: {
            "count": len(rows),
            "amount_total": sum(int(row["amount"] or 0) for row in rows),
            "entries": [row["name"] for row in rows],
        }
        for role, rows in sorted(roles.items())
    }


def stack_accounting(entries: list[dict[str, Any]], nominal_stack: int | None) -> dict[str, Any]:
    falling = [row for row in entries if "falling_payload" in row["tags"]]

    def is_base_stack(row: dict[str, Any]) -> bool:
        name = row["normalized_name"]
        if "osrb" in name or "restack" in name:
            return False
        if name.startswith("os ") or " os " in f" {name} ":
            return False
        return "sand" in name or "concrete" in name or "gravel" in name

    base_rows = [row for row in falling if is_base_stack(row)]
    restack_rows = [
        row
        for row in falling
        if "osrb" in row["normalized_name"] or "restack" in row["normalized_name"]
    ]
    other_rows = [row for row in falling if row not in base_rows and row not in restack_rows]

    base_amount = sum(int(row["amount"] or 0) for row in base_rows)
    result: dict[str, Any] = {
        "base_stack_amount": base_amount,
        "base_stack_entries": [row["name"] for row in base_rows],
        "restack_payload_amount": sum(int(row["amount"] or 0) for row in restack_rows),
        "restack_payload_entries": [row["name"] for row in restack_rows],
        "other_falling_payload_amount": sum(int(row["amount"] or 0) for row in other_rows),
        "other_falling_payload_entries": [row["name"] for row in other_rows],
        "all_falling_payload_amount": sum(int(row["amount"] or 0) for row in falling),
        "nominal_stack": nominal_stack,
        "nominal_delta": None if nominal_stack is None else base_amount - nominal_stack,
        "nominal_match": None if nominal_stack is None else base_amount == nominal_stack,
    }
    return result


def build_timeline(entries: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(entries, key=timing_key)
    cohorts: list[dict[str, Any]] = []
    for entry in ordered:
        placed = False
        for cohort in cohorts:
            if any(interval_overlap(entry, member) for member in cohort["_members"]):
                cohort["_members"].append(entry)
                placed = True
                break
        if not placed:
            cohorts.append({"_members": [entry]})

    output: list[dict[str, Any]] = []
    for index, cohort in enumerate(cohorts, start=1):
        members = sorted(cohort["_members"], key=timing_key)
        finite_maxima = [
            float(member["timing"]["maximum"])
            for member in members
            if member["timing"]["maximum"] is not None
        ]
        output.append(
            {
                "cohort": index,
                "minimum": min(float(member["timing"]["minimum"]) for member in members),
                "maximum": max(finite_maxima) if len(finite_maxima) == len(members) else None,
                "contains_open_range": any(member["timing"]["open_high"] for member in members),
                "members": [
                    {
                        "name": member["name"],
                        "amount": member["amount"],
                        "timing": member["timing"]["raw"],
                        "tags": member["tags"],
                    }
                    for member in members
                ],
            }
        )
    return {
        "ordered_entries": [
            {
                "name": row["name"],
                "amount": row["amount"],
                "timing": row["timing"]["raw"],
                "minimum": row["timing"]["minimum"],
                "maximum": row["timing"]["maximum"],
                "tags": row["tags"],
            }
            for row in ordered
        ],
        "overlap_cohorts": output,
    }


def validate(entries: list[dict[str, Any]], stack: dict[str, Any]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    observed_roles = {tag for row in entries for tag in row["tags"]}

    for role in HARD_REQUIRED_ROLES:
        if role not in observed_roles:
            failures.append(f"missing_{role}_entry")
    for role in SOFT_REQUIRED_ROLES:
        if role not in observed_roles:
            warnings.append(f"missing_{role}_entry")

    power_entries = [row for row in entries if "power" in row["tags"]]
    non_power_entries = [row for row in entries if "power" not in row["tags"]]
    if power_entries and non_power_entries:
        first_power = min(float(row["timing"]["minimum"]) for row in power_entries)
        first_non_power = min(float(row["timing"]["minimum"]) for row in non_power_entries)
        if first_power > first_non_power:
            failures.append("first_power_begins_after_payload_or_effect")

    duplicate_names: dict[str, int] = {}
    for row in entries:
        duplicate_names[row["normalized_name"]] = duplicate_names.get(row["normalized_name"], 0) + 1
    duplicates = sorted(name for name, count in duplicate_names.items() if count > 1)
    if duplicates:
        warnings.append("duplicate_entry_names:" + ",".join(duplicates))

    if stack["nominal_stack"] is not None and not stack["nominal_match"]:
        warnings.append(
            f"base_stack_amount_{stack['base_stack_amount']}_does_not_match_nominal_{stack['nominal_stack']}"
        )

    if any(row["timing"]["open_high"] for row in entries):
        warnings.append("open_ended_timing_requires_runtime_resolution")
    if any(not row["timing"]["exact"] for row in entries):
        warnings.append("non_exact_timing_preserved_without_invented_tick")
    if any("." in row["timing"]["raw"] for row in entries):
        warnings.append("fractional_timing_is_ordering_evidence_until_runtime_traced")

    return sorted(set(failures)), sorted(set(warnings))


def compare_reports(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    ref_entries = {row["normalized_name"]: row for row in reference["entries"]}
    cand_entries = {row["normalized_name"]: row for row in candidate["entries"]}
    names = sorted(set(ref_entries) | set(cand_entries))
    rows: list[dict[str, Any]] = []
    for name in names:
        left = ref_entries.get(name)
        right = cand_entries.get(name)
        if left is None:
            rows.append({"name": name, "change": "added", "candidate": right})
        elif right is None:
            rows.append({"name": name, "change": "removed", "reference": left})
        else:
            changes: dict[str, Any] = {}
            if left["amount"] != right["amount"]:
                changes["amount"] = {"reference": left["amount"], "candidate": right["amount"]}
            if left["timing"] != right["timing"]:
                changes["timing"] = {
                    "reference": left["timing"]["raw"],
                    "candidate": right["timing"]["raw"],
                }
            if left["tags"] != right["tags"]:
                changes["tags"] = {"reference": left["tags"], "candidate": right["tags"]}
            if changes:
                rows.append({"name": name, "change": "modified", "details": changes})
    return {
        "reference_profile": reference["profile"]["id"],
        "candidate_profile": candidate["profile"]["id"],
        "changed_entries": rows,
        "changed_entry_count": len(rows),
        "base_stack_delta": (
            candidate["stack_accounting"]["base_stack_amount"]
            - reference["stack_accounting"]["base_stack_amount"]
        ),
        "all_falling_payload_delta": (
            candidate["stack_accounting"]["all_falling_payload_amount"]
            - reference["stack_accounting"]["all_falling_payload_amount"]
        ),
    }


def load_profile(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    ratio_text = payload.get("ratio_text")
    if not isinstance(ratio_text, str) or not ratio_text.strip():
        raise ValueError(f"profile lacks non-empty ratio_text: {path}")
    profile_id = payload.get("id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError(f"profile lacks id: {path}")
    nominal_stack_raw = payload.get("nominal_stack")
    nominal_stack = None if nominal_stack_raw is None else int(nominal_stack_raw)

    entries, parse_notes = parse_ratio_text(ratio_text)
    stack = stack_accounting(entries, nominal_stack)
    failures, warnings = validate(entries, stack)
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema_version": 1,
        "status": status,
        "profile": {
            "id": profile_id,
            "title": payload.get("title"),
            "family": payload.get("family"),
            "nominal_stack": nominal_stack,
            "cycle_label": payload.get("cycle_label"),
            "source": payload.get("source"),
            "evidence": payload.get("evidence"),
        },
        "entries": entries,
        "role_summary": summarize_roles(entries),
        "stack_accounting": stack,
        "timeline": build_timeline(entries),
        "parse_notes": sorted(set(parse_notes)),
        "warnings": warnings,
        "failures": failures,
        "truth_boundary": {
            "ratio_text_is_architecture_evidence": True,
            "schematic_geometry_confirmed": False,
            "redstone_wiring_confirmed": False,
            "runtime_physics_confirmed": False,
            "private_server_parity_confirmed": False,
            "timing_policy": (
                "Preserve authored exact, fractional, ranged and open timings. "
                "Do not convert them to real server ticks without a causal runtime trace."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit authored faction-cannon ratio profiles without inventing runtime proof."
    )
    parser.add_argument("profile", type=Path, help="JSON ratio profile")
    parser.add_argument("--compare", type=Path, help="optional second profile to compare")
    parser.add_argument("--json-out", type=Path, help="write report JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = load_profile(args.profile)
        if args.compare:
            candidate = load_profile(args.compare)
            report = {
                "schema_version": 1,
                "status": (
                    "FAIL"
                    if "FAIL" in {report["status"], candidate["status"]}
                    else "WARN"
                    if "WARN" in {report["status"], candidate["status"]}
                    else "PASS"
                ),
                "reference": report,
                "candidate": candidate,
                "comparison": compare_reports(report, candidate),
                "truth_boundary": {
                    "comparison_proves_runtime_equivalence": False,
                    "comparison_proves_live_server_parity": False,
                },
            }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cannon-ratio-audit: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
