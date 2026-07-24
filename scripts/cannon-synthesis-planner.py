#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Iterator, Sequence

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
EVIDENCE_RANK = {
    "unknown": 0,
    "inference": 1,
    "static": 2,
    "local-runtime": 3,
    "field-reported": 4,
    "field-verified": 5,
}
VECTOR_SET = {
    (-1, 0, 0),
    (1, 0, 0),
    (0, -1, 0),
    (0, 1, 0),
    (0, 0, -1),
    (0, 0, 1),
}
SAFE_BLOCK_ENTITY_IDS = {"minecraft:dispenser", "minecraft:dropper"}


class SynthesisError(ValueError):
    pass


@dataclass(frozen=True)
class Port:
    id: str
    kind: str
    medium: str
    position: tuple[int, int, int]
    direction: tuple[int, int, int]
    contract: dict[str, Any]


@dataclass(frozen=True)
class Component:
    id: str
    version: str
    evidence_level: str
    capability_evidence: dict[str, str]
    path: Path
    sha256: str
    data_version: int
    blocks: dict[tuple[int, int, int], str]
    block_entities: tuple[dict[str, Any], ...]
    dimensions: tuple[int, int, int]
    ports: dict[str, Port]
    reusable: bool
    source: dict[str, Any]

    @property
    def dispensers(self) -> tuple[tuple[int, int, int], ...]:
        return tuple(
            pos for pos, state in self.blocks.items() if base_state(state) == "minecraft:dispenser"
        )

    @property
    def occupied(self) -> dict[tuple[int, int, int], str]:
        return {pos: state for pos, state in self.blocks.items() if base_state(state) not in AIR}


@dataclass(frozen=True)
class Edge:
    source_node: str
    source_port: str
    target_node: str
    target_port: str
    connection: str


@dataclass(frozen=True)
class CandidatePlan:
    assignments: dict[str, Component]
    translations: dict[str, tuple[int, int, int]]
    merged_blocks: dict[tuple[int, int, int], str]
    merged_block_entities: tuple[dict[str, Any], ...]
    chunk_scan: dict[str, Any]
    bounds: dict[str, Any]
    score: tuple[int, ...]
    score_details: dict[str, Any]


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SynthesisError(f"expected JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_state(state: str) -> str:
    return state.split("[", 1)[0]


def as_triplet(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise SynthesisError(f"{label} must be a three-integer list")
    try:
        result = tuple(int(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise SynthesisError(f"{label} must be a three-integer list") from exc
    return result  # type: ignore[return-value]


def add(left: tuple[int, int, int], right: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(left[index] + right[index] for index in range(3))  # type: ignore[return-value]


def subtract(left: tuple[int, int, int], right: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def negate(value: tuple[int, int, int]) -> tuple[int, int, int]:
    return (-value[0], -value[1], -value[2])


def load_audit_module(repo_root: Path) -> ModuleType:
    audit_path = repo_root / "scripts" / "schem-audit.py"
    if not audit_path.is_file():
        raise SynthesisError(f"missing CannonLab decoder: {audit_path}")
    spec = importlib.util.spec_from_file_location("cannonlab_schem_audit", audit_path)
    if spec is None or spec.loader is None:
        raise SynthesisError(f"cannot import CannonLab decoder: {audit_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_port(component_id: str, raw: Any) -> Port:
    if not isinstance(raw, dict):
        raise SynthesisError(f"component {component_id}: each port must be an object")
    port_id = str(raw.get("id", "")).strip()
    if not port_id:
        raise SynthesisError(f"component {component_id}: port id is required")
    kind = str(raw.get("kind", "")).strip()
    if kind not in {"input", "output"}:
        raise SynthesisError(f"component {component_id} port {port_id}: kind must be input/output")
    medium = str(raw.get("medium", "")).strip()
    if not medium:
        raise SynthesisError(f"component {component_id} port {port_id}: medium is required")
    position = as_triplet(raw.get("position"), f"component {component_id} port {port_id} position")
    direction = as_triplet(raw.get("direction"), f"component {component_id} port {port_id} direction")
    if direction not in VECTOR_SET:
        raise SynthesisError(
            f"component {component_id} port {port_id}: direction must be one axis-aligned unit vector"
        )
    contract = raw.get("contract") or {}
    if not isinstance(contract, dict):
        raise SynthesisError(f"component {component_id} port {port_id}: contract must be an object")
    return Port(port_id, kind, medium, position, direction, dict(contract))


def validate_capabilities(component_id: str, raw: Any, overall_evidence: str) -> dict[str, str]:
    if not isinstance(raw, list) or not raw:
        raise SynthesisError(f"component {component_id}: capabilities must be a non-empty list")
    result: dict[str, str] = {}
    overall_rank = EVIDENCE_RANK[overall_evidence]
    for row in raw:
        if not isinstance(row, dict):
            raise SynthesisError(f"component {component_id}: each capability must be an object")
        capability = str(row.get("id", "")).strip()
        evidence = str(row.get("evidence", "")).strip()
        if not capability:
            raise SynthesisError(f"component {component_id}: capability id is required")
        if evidence not in EVIDENCE_RANK:
            raise SynthesisError(f"component {component_id} capability {capability}: invalid evidence {evidence!r}")
        if EVIDENCE_RANK[evidence] > overall_rank:
            raise SynthesisError(
                f"component {component_id} capability {capability}: capability evidence exceeds component evidence"
            )
        if capability in result:
            raise SynthesisError(f"component {component_id}: duplicate capability {capability}")
        result[capability] = evidence
    return result


def normalize_model(model: dict[str, Any], component_id: str) -> tuple[
    dict[tuple[int, int, int], str], tuple[dict[str, Any], ...], tuple[int, int, int], int
]:
    raw_blocks = model.get("blocks")
    dimensions = model.get("source_dimensions") or {}
    if not isinstance(raw_blocks, dict):
        raise SynthesisError(f"component {component_id}: decoded schematic has no block map")
    blocks: dict[tuple[int, int, int], str] = {}
    for raw_pos, raw_state in raw_blocks.items():
        if not isinstance(raw_pos, tuple) or len(raw_pos) != 3:
            raise SynthesisError(f"component {component_id}: decoded block coordinate is invalid")
        blocks[tuple(int(part) for part in raw_pos)] = str(raw_state)
    try:
        dims = (
            int(dimensions["width"]),
            int(dimensions["height"]),
            int(dimensions["length"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SynthesisError(f"component {component_id}: decoded dimensions are invalid") from exc
    if min(dims) <= 0:
        raise SynthesisError(f"component {component_id}: decoded dimensions are invalid: {dims}")
    data_version = int(model.get("data_version", 0))
    entities: list[dict[str, Any]] = []
    for entity in model.get("block_entities", ()) or ():
        if not isinstance(entity, dict):
            continue
        pos = entity.get("pos")
        if not isinstance(pos, tuple) or len(pos) != 3:
            continue
        entities.append(
            {
                "pos": tuple(int(part) for part in pos),
                "id": str(entity.get("id", "unknown")),
                "raw": entity.get("raw") if isinstance(entity.get("raw"), dict) else {},
            }
        )
    return blocks, tuple(entities), dims, data_version


def resolve_component_path(registry_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = registry_path.parent / path
    return path.resolve()


def load_registry(registry_path: Path, audit: ModuleType) -> dict[str, Component]:
    payload = load_json_object(registry_path)
    if int(payload.get("schema_version", 0)) != 1:
        raise SynthesisError("component registry schema_version must equal 1")
    rows = payload.get("components")
    if not isinstance(rows, list) or not rows:
        raise SynthesisError("component registry must contain at least one component")

    components: dict[str, Component] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise SynthesisError("each registry component must be an object")
        component_id = str(raw.get("id", "")).strip()
        if not component_id:
            raise SynthesisError("component id is required")
        if component_id in components:
            raise SynthesisError(f"duplicate component id: {component_id}")
        version = str(raw.get("version", "")).strip()
        if not version:
            raise SynthesisError(f"component {component_id}: version is required")

        evidence = raw.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise SynthesisError(f"component {component_id}: evidence must be an object")
        evidence_level = str(evidence.get("level", "")).strip()
        if evidence_level not in EVIDENCE_RANK:
            raise SynthesisError(f"component {component_id}: invalid evidence level {evidence_level!r}")
        sources = evidence.get("sources")
        if EVIDENCE_RANK[evidence_level] >= EVIDENCE_RANK["static"] and (
            not isinstance(sources, list) or not sources
        ):
            raise SynthesisError(f"component {component_id}: evidenced components require evidence.sources")

        capabilities = validate_capabilities(component_id, raw.get("capabilities"), evidence_level)
        schematic = raw.get("schematic") or {}
        if not isinstance(schematic, dict):
            raise SynthesisError(f"component {component_id}: schematic must be an object")
        raw_path = str(schematic.get("path", "")).strip()
        expected_sha = str(schematic.get("sha256", "")).strip().lower()
        if not raw_path or len(expected_sha) != 64:
            raise SynthesisError(f"component {component_id}: schematic.path and exact sha256 are required")
        path = resolve_component_path(registry_path, raw_path)
        if not path.is_file():
            raise SynthesisError(f"component {component_id}: missing schematic {path}")
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise SynthesisError(
                f"component {component_id}: schematic hash mismatch expected={expected_sha} actual={actual_sha}"
            )

        root_name, root, trailing, _size, _diagnostics = audit.load(path)
        if trailing:
            raise SynthesisError(f"component {component_id}: schematic has trailing NBT bytes")
        model = audit.decode_any(root_name, root)
        blocks, block_entities, dimensions, data_version = normalize_model(model, component_id)
        declared_data_version = int(schematic.get("data_version", data_version))
        if declared_data_version != data_version:
            raise SynthesisError(
                f"component {component_id}: declared DataVersion {declared_data_version} != decoded {data_version}"
            )

        ports: dict[str, Port] = {}
        for raw_port in raw.get("ports", ()) or ():
            port = parse_port(component_id, raw_port)
            if port.id in ports:
                raise SynthesisError(f"component {component_id}: duplicate port {port.id}")
            if not all(0 <= port.position[index] < dimensions[index] for index in range(3)):
                raise SynthesisError(
                    f"component {component_id} port {port.id}: position {port.position} is outside {dimensions}"
                )
            ports[port.id] = port
        if not ports:
            raise SynthesisError(f"component {component_id}: at least one declared port is required")

        source = raw.get("source") or {}
        if not isinstance(source, dict):
            raise SynthesisError(f"component {component_id}: source must be an object")
        components[component_id] = Component(
            id=component_id,
            version=version,
            evidence_level=evidence_level,
            capability_evidence=capabilities,
            path=path,
            sha256=actual_sha,
            data_version=data_version,
            blocks=blocks,
            block_entities=block_entities,
            dimensions=dimensions,
            ports=ports,
            reusable=bool(raw.get("reusable", False)),
            source=dict(source),
        )
    return components


def parse_request(path: Path) -> dict[str, Any]:
    request = load_json_object(path)
    if int(request.get("schema_version", 0)) != 1:
        raise SynthesisError("request schema_version must equal 1")
    nodes = request.get("nodes")
    edges = request.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise SynthesisError("request.nodes must be a non-empty list")
    if not isinstance(edges, list):
        raise SynthesisError("request.edges must be a list")
    seen = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise SynthesisError("each request node must be an object")
        node_id = str(node.get("id", "")).strip()
        if not node_id or node_id in seen:
            raise SynthesisError(f"request node id is missing or duplicated: {node_id!r}")
        seen.add(node_id)
        required = node.get("requires")
        if not isinstance(required, list) or not required or not all(str(item).strip() for item in required):
            raise SynthesisError(f"request node {node_id}: requires must be a non-empty list")
        minimum = str(node.get("min_evidence", request.get("min_evidence", "local-runtime"))).strip()
        if minimum not in EVIDENCE_RANK:
            raise SynthesisError(f"request node {node_id}: invalid min_evidence {minimum!r}")
    root_node = str(request.get("root_node", nodes[0]["id"]))
    if root_node not in seen:
        raise SynthesisError(f"root_node {root_node!r} is not present in nodes")
    request["root_node"] = root_node
    return request


def parse_edges(request: dict[str, Any], node_ids: set[str]) -> list[Edge]:
    edges: list[Edge] = []
    for raw in request.get("edges", ()):
        if not isinstance(raw, dict):
            raise SynthesisError("each edge must be an object")
        source = raw.get("from") or {}
        target = raw.get("to") or {}
        if not isinstance(source, dict) or not isinstance(target, dict):
            raise SynthesisError("edge from/to must be objects")
        source_node = str(source.get("node", ""))
        source_port = str(source.get("port", ""))
        target_node = str(target.get("node", ""))
        target_port = str(target.get("port", ""))
        if source_node not in node_ids or target_node not in node_ids:
            raise SynthesisError(f"edge references unknown node: {source_node}->{target_node}")
        if not source_port or not target_port:
            raise SynthesisError("edge ports are required")
        connection = str(raw.get("connection", "adjacent"))
        if connection not in {"adjacent", "coincident"}:
            raise SynthesisError(f"unsupported edge connection {connection!r}")
        edges.append(Edge(source_node, source_port, target_node, target_port, connection))
    return edges


def component_satisfies_node(component: Component, node: dict[str, Any], default_min: str) -> bool:
    minimum = str(node.get("min_evidence", default_min))
    required = [str(item) for item in node["requires"]]
    allowed = node.get("allowed_components")
    blocked = node.get("blocked_components")
    if isinstance(allowed, list) and allowed and component.id not in {str(item) for item in allowed}:
        return False
    if isinstance(blocked, list) and component.id in {str(item) for item in blocked}:
        return False
    threshold = EVIDENCE_RANK[minimum]
    return all(
        capability in component.capability_evidence
        and EVIDENCE_RANK[component.capability_evidence[capability]] >= threshold
        for capability in required
    )


def build_candidate_lists(
    components: dict[str, Component], request: dict[str, Any]
) -> tuple[list[str], dict[str, list[Component]]]:
    node_order = [str(node["id"]) for node in request["nodes"]]
    default_min = str(request.get("min_evidence", "local-runtime"))
    if default_min not in EVIDENCE_RANK:
        raise SynthesisError(f"invalid request min_evidence {default_min!r}")
    result: dict[str, list[Component]] = {}
    for node in request["nodes"]:
        node_id = str(node["id"])
        candidates = [
            component
            for component in components.values()
            if component_satisfies_node(component, node, default_min)
        ]
        candidates.sort(
            key=lambda component: (
                -min(EVIDENCE_RANK[level] for level in component.capability_evidence.values()),
                -EVIDENCE_RANK[component.evidence_level],
                component.id,
                component.version,
            )
        )
        limit = int(node.get("max_candidates", request.get("max_candidates_per_node", 12)))
        candidates = candidates[: max(1, limit)]
        if not candidates:
            required = ", ".join(str(item) for item in node["requires"])
            raise SynthesisError(
                f"node {node_id}: no component satisfies capabilities [{required}] at required evidence"
            )
        result[node_id] = candidates
    return node_order, result


def contracts_compatible(source: Port, target: Port) -> tuple[bool, str | None]:
    if source.kind != "output" or target.kind != "input":
        return False, "edge must connect output to input"
    if source.medium != target.medium:
        return False, f"medium mismatch {source.medium!r}!={target.medium!r}"
    shared = set(source.contract) & set(target.contract)
    conflicts = [key for key in sorted(shared) if source.contract[key] != target.contract[key]]
    if conflicts:
        return False, f"port contract mismatch on {', '.join(conflicts)}"
    return True, None


def edge_translation(
    source_translation: tuple[int, int, int], source: Port, target: Port, connection: str
) -> tuple[int, int, int]:
    source_world = add(source_translation, source.position)
    target_world = source_world if connection == "coincident" else add(source_world, source.direction)
    return subtract(target_world, target.position)


def reverse_edge_translation(
    target_translation: tuple[int, int, int], source: Port, target: Port, connection: str
) -> tuple[int, int, int]:
    target_world = add(target_translation, target.position)
    source_world = target_world if connection == "coincident" else subtract(target_world, source.direction)
    return subtract(source_world, source.position)


def solve_translations(
    assignments: dict[str, Component], edges: Sequence[Edge], root_node: str
) -> tuple[dict[str, tuple[int, int, int]] | None, list[str]]:
    errors: list[str] = []
    for edge in edges:
        source_component = assignments[edge.source_node]
        target_component = assignments[edge.target_node]
        source_port = source_component.ports.get(edge.source_port)
        target_port = target_component.ports.get(edge.target_port)
        if source_port is None or target_port is None:
            missing = []
            if source_port is None:
                missing.append(f"{source_component.id}.{edge.source_port}")
            if target_port is None:
                missing.append(f"{target_component.id}.{edge.target_port}")
            errors.append("missing declared port " + ", ".join(missing))
            continue
        compatible, reason = contracts_compatible(source_port, target_port)
        if not compatible:
            errors.append(
                f"{edge.source_node}.{edge.source_port}->{edge.target_node}.{edge.target_port}: {reason}"
            )
            continue
        if edge.connection == "adjacent" and target_port.direction != negate(source_port.direction):
            errors.append(
                f"{edge.source_node}.{edge.source_port}->{edge.target_node}.{edge.target_port}: directions are not opposed"
            )
    if errors:
        return None, errors

    translations: dict[str, tuple[int, int, int]] = {root_node: (0, 0, 0)}
    progress = True
    while progress:
        progress = False
        for edge in edges:
            source_component = assignments[edge.source_node]
            target_component = assignments[edge.target_node]
            source_port = source_component.ports[edge.source_port]
            target_port = target_component.ports[edge.target_port]
            if edge.source_node in translations:
                derived = edge_translation(
                    translations[edge.source_node], source_port, target_port, edge.connection
                )
                existing = translations.get(edge.target_node)
                if existing is None:
                    translations[edge.target_node] = derived
                    progress = True
                elif existing != derived:
                    errors.append(
                        f"inconsistent translation for {edge.target_node}: {existing} vs {derived}"
                    )
            elif edge.target_node in translations:
                derived = reverse_edge_translation(
                    translations[edge.target_node], source_port, target_port, edge.connection
                )
                existing = translations.get(edge.source_node)
                if existing is None:
                    translations[edge.source_node] = derived
                    progress = True
                elif existing != derived:
                    errors.append(
                        f"inconsistent translation for {edge.source_node}: {existing} vs {derived}"
                    )
    missing_nodes = sorted(set(assignments) - set(translations))
    if missing_nodes:
        errors.append("assembly graph is disconnected from root: " + ", ".join(missing_nodes))
    if errors:
        return None, errors
    return translations, []


def safe_block_entity_for_rewrite(entity: dict[str, Any]) -> tuple[bool, str | None]:
    entity_id = str(entity.get("id", ""))
    if entity_id not in SAFE_BLOCK_ENTITY_IDS:
        return False, f"block entity {entity_id!r} is not safe for minimal Sponge rewrite"
    raw = entity.get("raw") or {}
    if not isinstance(raw, dict):
        return False, f"block entity {entity_id!r} has invalid raw payload"
    items = raw.get("Items", raw.get("items"))
    if items not in (None, [], ()):
        return False, f"block entity {entity_id!r} contains inventory items"
    return True, None


def merge_geometry(
    assignments: dict[str, Component],
    translations: dict[str, tuple[int, int, int]],
    allow_identical_overlap: bool,
    require_lossless_block_entities: bool,
) -> tuple[dict[tuple[int, int, int], str] | None, tuple[dict[str, Any], ...], list[str]]:
    merged: dict[tuple[int, int, int], str] = {}
    owners: dict[tuple[int, int, int], str] = {}
    entities: dict[tuple[int, int, int], dict[str, Any]] = {}
    errors: list[str] = []
    for node_id in sorted(assignments):
        component = assignments[node_id]
        translation = translations[node_id]
        for local, state in component.occupied.items():
            world = add(local, translation)
            if world in merged:
                if allow_identical_overlap and merged[world] == state:
                    continue
                errors.append(
                    f"geometry overlap at {world}: {owners[world]}={merged[world]} vs {node_id}={state}"
                )
                continue
            merged[world] = state
            owners[world] = node_id
        for entity in component.block_entities:
            if require_lossless_block_entities:
                safe, reason = safe_block_entity_for_rewrite(entity)
                if not safe:
                    errors.append(f"component {component.id}: {reason}")
                    continue
            world = add(tuple(entity["pos"]), translation)
            if world in entities:
                errors.append(f"block-entity overlap at {world}: {node_id}")
                continue
            entities[world] = {
                "pos": world,
                "id": str(entity.get("id", "unknown")),
                "raw": dict(entity.get("raw") or {}),
                "owner_node": node_id,
            }
    if errors:
        return None, tuple(), errors
    return merged, tuple(entities[pos] for pos in sorted(entities)), []


def geometry_bounds(blocks: dict[tuple[int, int, int], str]) -> dict[str, Any]:
    if not blocks:
        return {
            "minimum": [0, 0, 0],
            "maximum": [0, 0, 0],
            "dimensions": [0, 0, 0],
            "volume": 0,
            "occupied_blocks": 0,
        }
    minima = [min(pos[index] for pos in blocks) for index in range(3)]
    maxima = [max(pos[index] for pos in blocks) for index in range(3)]
    dimensions = [maxima[index] - minima[index] + 1 for index in range(3)]
    return {
        "minimum": minima,
        "maximum": maxima,
        "dimensions": dimensions,
        "volume": dimensions[0] * dimensions[1] * dimensions[2],
        "occupied_blocks": len(blocks),
    }


def chunk_distribution(
    coords: Iterable[tuple[int, int, int]], offset_x: int, offset_z: int
) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for x, _y, z in coords:
        key = ((x + offset_x) // 16, (z + offset_z) // 16)
        counts[key] = counts.get(key, 0) + 1
    return counts


def scan_chunk_alignments(
    dispenser_coords: Sequence[tuple[int, int, int]], chunk_limit: int
) -> dict[str, Any]:
    scans: list[dict[str, Any]] = []
    for offset_x in range(16):
        for offset_z in range(16):
            counts = chunk_distribution(dispenser_coords, offset_x, offset_z)
            maximum = max(counts.values(), default=0)
            scans.append(
                {
                    "offset_x": offset_x,
                    "offset_z": offset_z,
                    "maximum": maximum,
                    "chunk_count": len(counts),
                    "counts": sorted(counts.values(), reverse=True),
                    "safe": maximum <= chunk_limit,
                }
            )
    by_quality = sorted(
        scans, key=lambda row: (row["maximum"], row["chunk_count"], row["offset_x"], row["offset_z"])
    )
    safe = [row for row in by_quality if row["safe"]]
    return {
        "chunk_limit": chunk_limit,
        "alignment_count": 256,
        "safe_alignment_count": len(safe),
        "best": by_quality[0] if by_quality else None,
        "worst": max(scans, key=lambda row: (row["maximum"], -row["chunk_count"])) if scans else None,
        "safe_alignments": safe,
    }


def check_constraints(
    request: dict[str, Any], bounds: dict[str, Any], chunk_scan: dict[str, Any]
) -> list[str]:
    constraints = request.get("constraints") or {}
    if not isinstance(constraints, dict):
        raise SynthesisError("request.constraints must be an object")
    errors: list[str] = []
    maximum_dimensions = constraints.get("max_dimensions")
    if maximum_dimensions is not None:
        limits = as_triplet(maximum_dimensions, "constraints.max_dimensions")
        dimensions = tuple(int(value) for value in bounds["dimensions"])
        if any(dimensions[index] > limits[index] for index in range(3)):
            errors.append(f"dimensions {dimensions} exceed max_dimensions {limits}")
    if int(bounds["occupied_blocks"]) > int(constraints.get("max_occupied_blocks", 10_000_000)):
        errors.append("occupied block limit exceeded")
    require_all = bool(constraints.get("require_all_alignments_safe", False))
    safe_count = int(chunk_scan["safe_alignment_count"])
    if require_all and safe_count != 256:
        errors.append(f"only {safe_count}/256 chunk alignments are safe")
    if not require_all and safe_count == 0:
        errors.append("no safe chunk alignment exists")
    minimum_safe = int(constraints.get("min_safe_alignments", 1))
    if safe_count < minimum_safe:
        errors.append(f"safe alignment count {safe_count} is below required {minimum_safe}")
    return errors


def score_plan(
    assignments: dict[str, Component], bounds: dict[str, Any], chunk_scan: dict[str, Any]
) -> tuple[tuple[int, ...], dict[str, Any]]:
    capability_ranks = [
        EVIDENCE_RANK[level]
        for component in assignments.values()
        for level in component.capability_evidence.values()
    ]
    overall_ranks = [EVIDENCE_RANK[component.evidence_level] for component in assignments.values()]
    minimum_capability = min(capability_ranks, default=0)
    total_capability = sum(capability_ranks)
    minimum_overall = min(overall_ranks, default=0)
    best_max = int(chunk_scan["best"]["maximum"] if chunk_scan.get("best") else 0)
    margin = int(chunk_scan["chunk_limit"]) - best_max
    safe_count = int(chunk_scan["safe_alignment_count"])
    volume = int(bounds["volume"])
    occupied = int(bounds["occupied_blocks"])
    score = (
        minimum_capability,
        minimum_overall,
        total_capability,
        safe_count,
        margin,
        -len(assignments),
        -volume,
        -occupied,
    )
    return score, {
        "minimum_capability_evidence_rank": minimum_capability,
        "minimum_component_evidence_rank": minimum_overall,
        "total_capability_evidence_rank": total_capability,
        "safe_alignment_count": safe_count,
        "best_chunk_margin": margin,
        "component_count": len(assignments),
        "volume": volume,
        "occupied_blocks": occupied,
    }


def assignment_key(node_order: Sequence[str], assignments: dict[str, Component]) -> tuple[str, ...]:
    return tuple(f"{node}:{assignments[node].id}@{assignments[node].version}" for node in node_order)


def assignment_combinations(
    node_order: Sequence[str], candidates: dict[str, list[Component]], max_combinations: int
) -> Iterator[dict[str, Component]]:
    emitted = 0
    for rows in itertools.product(*(candidates[node] for node in node_order)):
        assignment = dict(zip(node_order, rows, strict=True))
        seen: dict[str, int] = {}
        invalid = False
        for component in rows:
            seen[component.id] = seen.get(component.id, 0) + 1
            if seen[component.id] > 1 and not component.reusable:
                invalid = True
                break
        if invalid:
            continue
        yield assignment
        emitted += 1
        if emitted >= max_combinations:
            return


def plan_assemblies(
    components: dict[str, Component], request: dict[str, Any]
) -> tuple[list[CandidatePlan], dict[str, Any]]:
    node_order, candidate_lists = build_candidate_lists(components, request)
    node_ids = set(node_order)
    edges = parse_edges(request, node_ids)
    constraints = request.get("constraints") or {}
    chunk_limit = int(constraints.get("chunk_limit", 160))
    if chunk_limit <= 0:
        raise SynthesisError("constraints.chunk_limit must be positive")
    allow_identical_overlap = bool(constraints.get("allow_identical_overlap", False))
    require_lossless = bool(constraints.get("require_lossless_block_entities", True))
    max_combinations = int(request.get("max_combinations", 4096))
    max_plans = int(request.get("max_plans", 12))
    root_node = str(request["root_node"])

    plans: list[CandidatePlan] = []
    rejected: dict[str, int] = {}
    examples: list[dict[str, Any]] = []

    def reject(kind: str, assignment: dict[str, Component], reasons: list[str]) -> None:
        rejected[kind] = rejected.get(kind, 0) + 1
        if len(examples) < 20:
            examples.append(
                {
                    "kind": kind,
                    "assignment": list(assignment_key(node_order, assignment)),
                    "reasons": reasons[:8],
                }
            )

    considered = 0
    for assignment in assignment_combinations(node_order, candidate_lists, max_combinations):
        considered += 1
        translations, placement_errors = solve_translations(assignment, edges, root_node)
        if translations is None:
            reject("port-or-placement", assignment, placement_errors)
            continue
        merged, entities, merge_errors = merge_geometry(
            assignment, translations, allow_identical_overlap, require_lossless
        )
        if merged is None:
            reject("geometry-or-block-entity", assignment, merge_errors)
            continue
        dispenser_coords = [
            add(pos, translations[node])
            for node, component in assignment.items()
            for pos in component.dispensers
        ]
        chunk_scan = scan_chunk_alignments(dispenser_coords, chunk_limit)
        bounds = geometry_bounds(merged)
        constraint_errors = check_constraints(request, bounds, chunk_scan)
        if constraint_errors:
            reject("constraints", assignment, constraint_errors)
            continue
        score, score_details = score_plan(assignment, bounds, chunk_scan)
        plans.append(
            CandidatePlan(
                assignments=dict(assignment),
                translations=translations,
                merged_blocks=merged,
                merged_block_entities=entities,
                chunk_scan=chunk_scan,
                bounds=bounds,
                score=score,
                score_details=score_details,
            )
        )

    plans.sort(
        key=lambda plan: (
            tuple(-part for part in plan.score),
            assignment_key(node_order, plan.assignments),
            tuple((node, plan.translations[node]) for node in node_order),
        )
    )
    return plans[: max(1, max_plans)], {
        "considered_assignments": considered,
        "valid_plan_count_before_limit": len(plans),
        "candidate_counts": {node: len(candidate_lists[node]) for node in node_order},
        "rejected_by_kind": dict(sorted(rejected.items())),
        "rejection_examples": examples,
        "search_bounded": considered >= max_combinations,
        "max_combinations": max_combinations,
    }


def normalize_merged_model(plan: CandidatePlan) -> tuple[dict[str, Any], tuple[int, int, int]]:
    minima = tuple(int(value) for value in plan.bounds["minimum"])
    translation = negate(minima)
    normalized_blocks = {add(pos, translation): state for pos, state in plan.merged_blocks.items()}
    normalized_entities = [
        {
            "pos": add(tuple(entity["pos"]), translation),
            "id": entity["id"],
            "raw": dict(entity.get("raw") or {}),
        }
        for entity in plan.merged_block_entities
    ]
    dimensions = plan.bounds["dimensions"]
    return {
        "format": "sponge-v2",
        "version": 2,
        "data_version": 3465,
        "blocks": normalized_blocks,
        "block_entities": normalized_entities,
        "source_dimensions": {
            "width": int(dimensions[0]),
            "height": int(dimensions[1]),
            "length": int(dimensions[2]),
        },
    }, translation


def verify_compiled_output(
    output_path: Path,
    expected_model: dict[str, Any],
    audit: ModuleType,
    expected_data_version: int,
) -> dict[str, Any]:
    root_name, root, trailing, _size, diagnostics = audit.load(output_path)
    if trailing:
        raise SynthesisError("compiled output has trailing NBT bytes")
    decoded = audit.decode_any(root_name, root)
    blocks, entities, dimensions, data_version = normalize_model(decoded, "compiled-output")
    expected_blocks = {
        pos: state
        for pos, state in expected_model["blocks"].items()
        if base_state(state) not in AIR
    }
    actual_blocks = {
        pos: state for pos, state in blocks.items() if base_state(state) not in AIR
    }
    if actual_blocks != expected_blocks:
        missing = len(set(expected_blocks.items()) - set(actual_blocks.items()))
        extra = len(set(actual_blocks.items()) - set(expected_blocks.items()))
        raise SynthesisError(f"compiled geometry mismatch missing={missing} extra={extra}")
    if data_version != expected_data_version:
        raise SynthesisError(
            f"compiled DataVersion mismatch expected={expected_data_version} actual={data_version}"
        )
    expected_entity_positions = sorted(tuple(entity["pos"]) for entity in expected_model["block_entities"])
    actual_entity_positions = sorted(tuple(entity["pos"]) for entity in entities)
    if actual_entity_positions != expected_entity_positions:
        raise SynthesisError("compiled block-entity positions do not match merged model")
    return {
        "sha256": sha256_file(output_path),
        "bytes": output_path.stat().st_size,
        "data_version": data_version,
        "dimensions": list(dimensions),
        "block_entities": len(entities),
        "strict_container": diagnostics,
        "geometry_verified": True,
    }


def compile_plan(
    plan: CandidatePlan, output_path: Path, audit: ModuleType, data_version: int = 3465
) -> dict[str, Any]:
    model, normalization_translation = normalize_merged_model(plan)
    model["data_version"] = data_version
    audit.write_sponge_v2(output_path, model, data_version)
    verification = verify_compiled_output(output_path, model, audit, data_version)
    verification["normalization_translation"] = list(normalization_translation)
    return verification


def component_summary(component: Component) -> dict[str, Any]:
    return {
        "id": component.id,
        "version": component.version,
        "evidence_level": component.evidence_level,
        "capability_evidence": dict(sorted(component.capability_evidence.items())),
        "schematic": {
            "path": str(component.path),
            "sha256": component.sha256,
            "data_version": component.data_version,
        },
        "dimensions": list(component.dimensions),
        "dispenser_count": len(component.dispensers),
        "ports": sorted(component.ports),
        "source": component.source,
    }


def plan_to_json(plan: CandidatePlan, node_order: Sequence[str], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "score": list(plan.score),
        "score_details": plan.score_details,
        "nodes": {
            node: {
                "component": component_summary(plan.assignments[node]),
                "translation": list(plan.translations[node]),
            }
            for node in node_order
        },
        "bounds": plan.bounds,
        "chunk_scan": plan.chunk_scan,
        "merged": {
            "occupied_blocks": len(plan.merged_blocks),
            "block_entities": len(plan.merged_block_entities),
            "dispensers": sum(len(component.dispensers) for component in plan.assignments.values()),
        },
    }


def build_report(
    registry_path: Path,
    request_path: Path,
    components: dict[str, Component],
    request: dict[str, Any],
    plans: Sequence[CandidatePlan],
    search: dict[str, Any],
    compiled: dict[str, Any] | None,
) -> dict[str, Any]:
    node_order = [str(node["id"]) for node in request["nodes"]]
    status = "PASS" if plans else "FAIL"
    return {
        "schema_version": 1,
        "status": status,
        "registry": str(registry_path),
        "request": str(request_path),
        "component_count": len(components),
        "search": search,
        "plans": [plan_to_json(plan, node_order, rank) for rank, plan in enumerate(plans, start=1)],
        "compiled_best": compiled,
        "promotion": {
            "status": "ASSEMBLY_CANDIDATE_ONLY" if plans else "NO_VALID_ASSEMBLY",
            "next_required": [
                "reference-preservation gate against every source module",
                "real button/input runtime trace",
                "source-accounted entity and impulse graph",
                "target contract and cannon survival gates",
                "live ExtremeCraft canary before any EC-ready claim",
            ],
        },
        "truth_boundary": {
            "roles_derived_from_filenames_or_shape": False,
            "rotation_reflection_or_geometry_warp_used": False,
            "module_schematics_hash_verified": True,
            "all_connections_use_declared_ports": True,
            "private_extremecraft_parity_confirmed": False,
            "runtime_physics_confirmed": False,
            "target_breach_confirmed": False,
            "ec_ready": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan and optionally compile evidence-backed CannonLab module assemblies"
    )
    parser.add_argument("registry", type=Path)
    parser.add_argument("request", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--compile-best", type=Path)
    parser.add_argument("--output-data-version", type=int, default=3465)
    args = parser.parse_args()

    try:
        audit = load_audit_module(args.repo_root.resolve())
        components = load_registry(args.registry.resolve(), audit)
        request = parse_request(args.request.resolve())
        plans, search = plan_assemblies(components, request)
        compiled = None
        if args.compile_best is not None:
            if not plans:
                raise SynthesisError("cannot compile because no valid assembly plan exists")
            compiled = compile_plan(
                plans[0], args.compile_best.resolve(), audit, data_version=args.output_data_version
            )
        report = build_report(
            args.registry.resolve(),
            args.request.resolve(),
            components,
            request,
            plans,
            search,
            compiled,
        )
        if args.json_out:
            write_json(args.json_out.resolve(), report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if plans else 2
    except (OSError, json.JSONDecodeError, SynthesisError, ValueError) as exc:
        failure = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "private_extremecraft_parity_confirmed": False,
                "runtime_physics_confirmed": False,
                "ec_ready": False,
            },
        }
        if args.json_out:
            write_json(args.json_out.resolve(), failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
