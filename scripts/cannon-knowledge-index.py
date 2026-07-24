#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "cannonlab-community-knowledge-v1"
CUES = ("because", "basically", "how it works", "what happens", "the reason", "you need", "timing", "game tick", "render", "ratio", "before", "after")


def load_ontology(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    header: dict[str, Any] = {}
    concepts: list[dict[str, Any]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid ontology JSON at {path}:{number}: {error}") from error
        if item.get("type") == "header":
            header = item
        elif item.get("id"):
            concepts.append(item)
    if header.get("schema") != "cannonlab-cannon-ontology-v1" or not concepts:
        raise ValueError("unsupported or empty ontology")
    ids = [item["id"] for item in concepts]
    if len(ids) != len(set(ids)):
        raise ValueError("ontology ids must be unique")
    return header, concepts


def load_videos(paths: Iterable[Path]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for video in data.get("videos", []):
            video_id = str(video.get("video_id") or video.get("id") or "").strip()
            if not video_id:
                continue
            current = merged.setdefault(video_id, dict(video))
            for key in ("title", "uploader", "channel", "description", "upload_date", "url"):
                if not current.get(key) and video.get(key):
                    current[key] = video[key]
            if len(video.get("transcript") or []) > len(current.get("transcript") or []):
                current["transcript"] = video["transcript"]
                current["transcript_source"] = video.get("transcript_source")
    return list(merged.values())


def alias_pattern(alias: str) -> re.Pattern[str]:
    tokens = re.findall(r"[a-z0-9]+", alias.lower())
    if not tokens:
        raise ValueError(f"empty alias: {alias!r}")
    body = r"[\s_./-]+".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)


def count(patterns: list[re.Pattern[str]], text: str) -> int:
    return sum(len(pattern.findall(text or "")) for pattern in patterns)


def context(chunks: list[dict[str, Any]], index: int, radius: int = 3) -> str:
    return " ".join(str(chunk.get("text") or "").strip() for chunk in chunks[max(0, index-radius):index+radius+1]).strip()


def score_video(concept: dict[str, Any], video: dict[str, Any], max_contexts: int) -> dict[str, Any] | None:
    patterns = [alias_pattern(alias) for alias in concept.get("aliases", [])]
    title = str(video.get("title") or "")
    description = str(video.get("description") or video.get("description_snippet") or "")
    title_hits = count(patterns, title)
    description_hits = count(patterns, description)
    transcript_hits = 0
    cue_hits = 0
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()
    chunks = video.get("transcript") or []
    for index, chunk in enumerate(chunks):
        if not count(patterns, str(chunk.get("text") or "")):
            continue
        transcript_hits += count(patterns, str(chunk.get("text") or ""))
        excerpt = context(chunks, index)
        normalized = re.sub(r"\W+", " ", excerpt.lower()).strip()
        cues = sum(cue in excerpt.lower() for cue in CUES)
        cue_hits += cues
        if normalized not in seen and len(contexts) < max_contexts:
            seen.add(normalized)
            contexts.append({"start_seconds": int(chunk.get("start_ms") or 0)//1000, "text": excerpt, "explanation_cues": cues})
    score = title_hits*12 + description_hits*4 + transcript_hits + cue_hits*2
    if score <= 0:
        return None
    return {
        "video_id": video.get("video_id"), "title": title,
        "uploader": video.get("uploader") or video.get("channel") or "",
        "url": video.get("url") or f"https://www.youtube.com/watch?v={video.get('video_id','')}",
        "upload_date": video.get("upload_date"),
        "transcript_source": video.get("transcript_source") or ("present" if chunks else "none"),
        "score": score, "title_hits": title_hits, "description_hits": description_hits,
        "transcript_hits": transcript_hits, "explanation_cues": cue_hits,
        "contexts": contexts, "evidence_class": "community-source"
    }



def build_index(header: dict[str, Any], concepts: list[dict[str, Any]], videos: list[dict[str, Any]], max_sources: int = 12, max_contexts: int = 4) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    family_counts: defaultdict[str, int] = defaultdict(int)
    gaps: list[dict[str, Any]] = []
    for concept in concepts:
        sources = [scored for video in videos if (scored := score_video(concept, video, max_contexts)) is not None]
        sources.sort(key=lambda source: (source["score"], source["transcript_hits"], source["title_hits"]), reverse=True)
        transcript_sources = sum(source["transcript_hits"] > 0 for source in sources)
        strength = "multi-source-transcript" if transcript_sources >= 3 else "single-source-transcript" if transcript_sources else "metadata-only" if sources else "none"
        family_counts[concept.get("family", "unknown")] += 1
        results.append({
            **concept,
            "coverage": {"source_count": len(sources), "transcript_source_count": transcript_sources, "strength": strength},
            "top_sources": sources[:max_sources],
            "classification_boundary": "Community evidence explains vocabulary and candidate mechanisms only. Confirm schematic roles with static plus causal runtime evidence; confirm ExtremeCraft parity live."
        })
        if transcript_sources < 2:
            gaps.append({"concept_id": concept["id"], "reason": "fewer than two transcript-bearing community sources", "source_count": len(sources), "transcript_source_count": transcript_sources})
    owners: defaultdict[str, list[str]] = defaultdict(list)
    for concept in concepts:
        for alias in concept.get("aliases", []):
            owners[alias.lower()].append(concept["id"])
    collisions = [{"alias": alias, "concept_ids": ids} for alias, ids in sorted(owners.items()) if len(ids) > 1]
    transcript_characters = sum(sum(len(str(chunk.get("text") or "")) for chunk in (video.get("transcript") or [])) for video in videos)
    return {
        "schema": SCHEMA,
        "source_class": "community-theory",
        "ontology_schema": header["schema"],
        "truth_boundary": header.get("truth_boundary"),
        "corpus_summary": {
            "unique_videos": len(videos),
            "videos_with_transcripts": sum(bool(video.get("transcript")) for video in videos),
            "transcript_characters": transcript_characters,
            "concepts": len(concepts),
            "families": dict(sorted(family_counts.items()))
        },
        "concepts": results,
        "coverage_gaps": gaps,
        "alias_collisions": collisions
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index public cannoning sources against CannonLab's conservative ontology.")
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, action="append", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--max-sources", type=int, default=12)
    parser.add_argument("--max-contexts", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    header, concepts = load_ontology(args.ontology)
    videos = load_videos(args.corpus)
    result = build_index(header, concepts, videos, args.max_sources, args.max_contexts)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "schema": result["schema"], **result["corpus_summary"], "coverage_gaps": len(result["coverage_gaps"]), "json_out": str(args.json_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
