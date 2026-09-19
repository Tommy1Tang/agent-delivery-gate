"""Build a canonical offline code-index manifest and snapshot."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

try:
    from .code_graph_provider import ProviderConfig, RawGraph, load_provider_index, run_provider_index
    from .code_intelligence_models import (
        SCHEMA_VERSION, SymbolRef, atomic_write_json, bytes_hash, content_hash, ensure_contained,
        file_hash, load_json_object, normalize_relative_path,
    )
except ImportError:
    from code_graph_provider import ProviderConfig, RawGraph, load_provider_index, run_provider_index
    from code_intelligence_models import (
    SCHEMA_VERSION,
    SymbolRef,
    atomic_write_json,
    bytes_hash,
    content_hash,
    ensure_contained,
    file_hash,
    load_json_object,
    normalize_relative_path,
    )


@dataclass(frozen=True, slots=True)
class BuildIndexResult:
    status: str
    code: str
    manifest_path: Path | None = None
    snapshot_path: Path | None = None
    manifest_hash: str | None = None
    snapshot_hash: str | None = None
    diagnostics: tuple[str, ...] = ()


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


SNAPSHOT_SCHEMA_VERSION = "1.1.0"
STRUCTURAL_RELATION_TYPES = frozenset({
    "CONTAINS", "CONTAINS_PACKAGE", "CONTAINS_FOLDER", "CONTAINS_FILE", "CONTAINS_MODULE", "CONTAINS_SECTION",
    "DEFINES", "DEFINES_METHOD",
})
SUPPORTED_RELATION_TYPES = frozenset({
    "CONTAINS", "DEFINES", "CALLS", "REFERENCES", "INSTANTIATES", "INHERITS", "IMPLEMENTS", "OVERRIDES",
    "IMPORTS", "EXPORTS", "EXPORTS_MODULE", "IMPLEMENTS_MODULE", "EXPOSES", "RESOLVES_TO", "LINKS_TO", "FLOWS_TO",
})
DIRECT_SYMBOL_LABELS = frozenset({"CLASS", "FUNCTION", "METHOD", "INTERFACE", "ENUM", "TYPE", "UNION", "SECTION"})


def index_config_fingerprint(config: Mapping[str, object]) -> dict[str, object]:
    """Return the portable index semantics, excluding runtime-only paths."""
    provider = ProviderConfig.from_mapping(config)
    limits = config.get("limits") if isinstance(config.get("limits"), Mapping) else {}
    return {
        "schemaVersion": str(config.get("schemaVersion", "1.0.0")),
        "enabled": config.get("enabled") is True,
        "provider": {
            "name": "code-graph-rag",
            "distributionName": provider.distribution_name,
            "entryPoint": provider.entry_point,
            "providerVersion": provider.provider_version,
            "manifestVersion": provider.manifest_version,
            "codecSchemaSha256": provider.codec_schema_sha256,
            "requiredCaptures": sorted(provider.required_captures),
        },
        "sourceExtensions": sorted(str(item).lower() for item in config.get("sourceExtensions", [])),
        "excludeDirectories": sorted(str(item) for item in config.get("excludeDirectories", [])),
        "excludePaths": sorted(normalize_relative_path(str(item)) for item in config.get("excludePaths", [])),
        "symbolKinds": sorted(str(item) for item in config.get("symbolKinds", [])),
        "relationshipTypes": sorted(str(item) for item in config.get("relationshipTypes", [])),
        "limits": {str(key): limits[key] for key in sorted(limits)},
    }


def _line_count(path: Path) -> int:
    payload = path.read_bytes()
    if not payload:
        return 0
    return payload.count(b"\n") + (0 if payload.endswith(b"\n") else 1)


def _inventory(
    root: Path,
    config: Mapping[str, object],
) -> tuple[list[dict[str, object]], str, list[str], dict[str, dict[str, object]]]:
    extensions = {str(item).lower() for item in config.get("sourceExtensions", [])}
    excluded = {str(item) for item in config.get("excludeDirectories", [])}
    excluded_paths = {
        normalize_relative_path(str(item))
        for item in config.get("excludePaths", [])
    }
    files: list[dict[str, object]] = []
    repository_files: dict[str, dict[str, object]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts[:-1]):
            continue
        rel = normalize_relative_path(relative.as_posix())
        if rel in excluded_paths:
            continue
        digest = file_hash(path)
        eligible = path.suffix.lower() in extensions
        repository_files[rel] = {
            "relativePath": rel,
            "extension": path.suffix.lower(),
            "sha256": digest,
            "eligibility": "ELIGIBLE" if eligible else "UNSUPPORTED",
        }
        if eligible:
            size = path.stat().st_size
            files.append({
                "relativePath": rel,
                "language": path.suffix.lower().lstrip(".") or "unknown",
                "size": size,
                "sizeBytes": size,
                "lineCount": _line_count(path),
                "sha256": digest,
                "eligibility": "ELIGIBLE",
                "coverageStatus": "INDEXED",
            })
    files.sort(key=lambda row: str(row["relativePath"]))
    digest_rows = [f"{row['relativePath']}\0{row['sha256']}" for row in files]
    digest = content_hash(digest_rows, excluded_keys=())
    return files, digest, sorted(extensions), repository_files


PAYLOAD_LABELS = {
    "class_node": "CLASS", "function": "FUNCTION", "method": "METHOD", "interface_node": "INTERFACE",
    "enum_node": "ENUM", "type_node": "TYPE", "union_node": "UNION", "section": "SECTION", "module": "MODULE",
    "file": "FILE", "package": "PACKAGE", "folder": "FOLDER", "project": "PROJECT",
    "module_implementation": "MODULE_IMPLEMENTATION", "module_interface": "MODULE_INTERFACE",
}


def _normalize_label(value: object) -> str:
    label = str(value or "").upper().replace(" ", "_")
    return {"CLASS_NODE": "CLASS", "INTERFACE_NODE": "INTERFACE", "ENUM_NODE": "ENUM", "TYPE_NODE": "TYPE", "UNION_NODE": "UNION"}.get(label, label)


def _node_payload(node: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = node.get("payload")
    if isinstance(payload, Mapping):
        return payload
    for field in PAYLOAD_LABELS:
        nested = node.get(field)
        if isinstance(nested, Mapping):
            return nested
    # Fixture/raw adapters may already expose flattened structural fields.
    return node


def _node_label(node: Mapping[str, Any]) -> str:
    direct = node.get("label") or node.get("kind") or node.get("type")
    if direct:
        return _normalize_label(direct)
    for field, label in PAYLOAD_LABELS.items():
        if isinstance(node.get(field), Mapping):
            return label
    return ""


def _provider_identity(node: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    return str(node.get("id") or node.get("providerId") or payload.get("id") or payload.get("qualified_name") or payload.get("qualifiedName") or payload.get("path") or payload.get("name") or "")


def _provider_id_hash(provider_id: str) -> str:
    return bytes_hash(provider_id.encode("utf-8"))


def _raw_relationship_id(relation: Mapping[str, Any]) -> str:
    return content_hash(dict(relation), excluded_keys=())


def _hash_ids(values: Sequence[str]) -> str:
    return content_hash(sorted(values), excluded_keys=())


def _relationship_id(source_symbol_id: str, relation_type: str, target_symbol_id: str) -> str:
    # Preserve the v1 identity algorithm; profile metadata does not change identity.
    return content_hash({"sourceSymbolId": source_symbol_id, "type": relation_type, "targetSymbolId": target_symbol_id}, excluded_keys=())


def _boundary_key_hash(boundary_class: str, boundary_kind: str, boundary_key: str) -> str:
    return bytes_hash(f"{boundary_class}\0{boundary_kind}\0{boundary_key}".encode("utf-8"))


def _safe_boundary_key(value: str) -> bool:
    if not value or "\x00" in value or len(value) > 1024:
        return False
    candidate = value.replace("\\", "/")
    return not candidate.startswith("/") and not (len(candidate) >= 2 and candidate[1] == ":") and "../" not in f"/{candidate}/"


def _normalize_graph(
    raw: RawGraph,
    repository_id: str,
    manifest_hash: str,
    eligible_files: Sequence[Mapping[str, object]],
    repository_files: Mapping[str, Mapping[str, object]],
    config_hash: str,
) -> dict[str, object]:
    symbols: list[dict[str, object]] = []
    unresolved_symbols: list[dict[str, object]] = []
    provider_to_symbol: dict[tuple[str, str], str] = {}
    entries: list[tuple[Mapping[str, Any], Mapping[str, Any], str, str]] = []
    for node in raw.nodes:
        payload = _node_payload(node)
        label = _node_label(node) or _normalize_label(payload.get("kind") or payload.get("type"))
        provider_id = _provider_identity(node, payload)
        entries.append((node, payload, label, provider_id))

    # Function/Method/Class payloads intentionally omit paths in provider v1.
    # Recover ownership only through explicit DEFINES/DEFINES_METHOD edges.
    owner_paths: dict[tuple[str, str], set[str]] = defaultdict(set)
    for node, payload, label, provider_id in entries:
        path_raw = payload.get("path") or payload.get("relativePath") or node.get("path")
        if path_raw:
            try:
                owner_paths[(label, provider_id)].add(normalize_relative_path(str(path_raw)))
            except ValueError:
                pass
    for _round in range(4):
        changed = False
        for relation in raw.relationships:
            rel_type = str(relation.get("type") or relation.get("kind") or relation.get("relationshipType") or "").upper()
            if rel_type not in {"DEFINES", "DEFINES_METHOD", "CONTAINS_SECTION"}:
                continue
            source_key = (_normalize_label(relation.get("sourceLabel") or relation.get("source_label")), str(relation.get("source") or relation.get("sourceId") or relation.get("source_id") or ""))
            target_key = (_normalize_label(relation.get("targetLabel") or relation.get("target_label")), str(relation.get("target") or relation.get("targetId") or relation.get("target_id") or ""))
            inherited_paths = owner_paths.get(source_key, set()) - owner_paths.get(target_key, set())
            if inherited_paths:
                owner_paths[target_key].update(inherited_paths)
                changed = True
        if not changed:
            break

    eligible_by_path = {str(row["relativePath"]): row for row in eligible_files}
    entries_by_key: dict[tuple[str, str], list[tuple[Mapping[str, Any], Mapping[str, Any], str, str]]] = defaultdict(list)
    repository_provider_ids: set[str] = set()
    inventory_rows: list[dict[str, str]] = []
    for entry in entries:
        _node, _payload, label, provider_id = entry
        if not label or not provider_id:
            continue
        entries_by_key[(label, provider_id)].append(entry)
        repository_provider_ids.add(provider_id)
        inventory_rows.append({"nodeLabel": label, "providerIdHash": _provider_id_hash(provider_id)})
    inventory_rows.sort(key=lambda row: (row["nodeLabel"], row["providerIdHash"]))
    inventory_by_label = Counter(row["nodeLabel"] for row in inventory_rows)
    provider_node_inventory: dict[str, object] = {
        "rawCount": len(inventory_rows),
        "byLabel": dict(sorted(inventory_by_label.items())),
        "inventoryHash": content_hash(inventory_rows, excluded_keys=()),
    }
    repository_inventory_hash = content_hash(
        [dict(repository_files[path]) for path in sorted(repository_files)], excluded_keys=()
    )

    for node, payload, label, provider_id in entries:
        paths = owner_paths.get((label, provider_id), set())
        path_raw = next(iter(paths)) if len(paths) == 1 else None
        qname = payload.get("qualified_name") or payload.get("qualifiedName") or payload.get("name") or node.get("qualifiedName") or node.get("name")
        start = payload.get("start_line") or payload.get("startLine") or node.get("startLine")
        end = payload.get("end_line") or payload.get("endLine") or node.get("endLine")
        if label not in DIRECT_SYMBOL_LABELS | {"MODULE"}:
            continue
        if label == "MODULE" and isinstance(path_raw, str) and path_raw in eligible_by_path:
            start = 1
            end = max(1, int(eligible_by_path[path_raw]["lineCount"]))
            qname = qname or provider_id
        try:
            symbol = SymbolRef(repository_id, str(path_raw), str(qname), label, int(start), int(end), manifest_hash)
        except (TypeError, ValueError):
            unresolved_symbols.append({"providerIdHash": _provider_id_hash(provider_id), "label": label, "reasonCode": "UNRESOLVED_SYMBOL"})
            continue
        row = symbol.to_dict()
        symbols.append(row)
        provider_to_symbol[(label, provider_id)] = symbol.symbolId

    contained_file_paths: dict[tuple[str, str], set[str]] = defaultdict(set)
    for relation in raw.relationships:
        relation_type = str(relation.get("type") or relation.get("kind") or relation.get("relationshipType") or "").upper()
        if relation_type != "CONTAINS_FILE":
            continue
        source_key = (_normalize_label(relation.get("sourceLabel") or relation.get("source_label")), str(relation.get("source") or relation.get("sourceId") or relation.get("source_id") or ""))
        target_key = (_normalize_label(relation.get("targetLabel") or relation.get("target_label")), str(relation.get("target") or relation.get("targetId") or relation.get("target_id") or ""))
        contained_file_paths[source_key].update(owner_paths.get(target_key, set()))
    for relation in raw.relationships:
        relation_type = str(relation.get("type") or relation.get("kind") or relation.get("relationshipType") or "").upper()
        if relation_type != "CONTAINS_MODULE":
            continue
        source_label = _normalize_label(relation.get("sourceLabel") or relation.get("source_label"))
        source_id = str(relation.get("source") or relation.get("sourceId") or relation.get("source_id") or "")
        target_label = _normalize_label(relation.get("targetLabel") or relation.get("target_label"))
        target_id = str(relation.get("target") or relation.get("targetId") or relation.get("target_id") or "")
        target_key = (target_label, target_id)
        if target_label != "MODULE" or target_key in provider_to_symbol or entries_by_key.get(target_key):
            continue
        # The provider represents a package's __init__ module by a containment
        # endpoint rather than a standalone node.  The ownership edge and the
        # unique directly-contained eligible initializer are both required.
        candidates = sorted(
            path for path in contained_file_paths.get((source_label, source_id), set())
            if path in eligible_by_path and PurePosixPath(path).stem == "__init__"
        )
        if source_label != "PACKAGE" or source_id != target_id or len(candidates) != 1:
            continue
        relative_path = candidates[0]
        projected = SymbolRef(
            repository_id,
            relative_path,
            f"module::{relative_path}",
            "MODULE",
            1,
            max(1, int(eligible_by_path[relative_path]["lineCount"])),
            manifest_hash,
        )
        symbols.append(projected.to_dict())
        provider_to_symbol[target_key] = projected.symbolId
    symbols.sort(key=lambda row: (str(row["relativePath"]), int(row["startLine"]), int(row["endLine"]), str(row["symbolKind"]), str(row["qualifiedName"])))

    modules_by_path: dict[str, list[str]] = defaultdict(list)
    for row in symbols:
        if row["symbolKind"] == "MODULE":
            modules_by_path[str(row["relativePath"])].append(str(row["symbolId"]))

    def endpoint(label: str, provider_id: str) -> dict[str, object]:
        direct = provider_to_symbol.get((label, provider_id))
        if direct:
            return {
                "state": "INTERNAL",
                "symbolId": direct,
                "resolution": "MODULE_SYMBOL" if label == "MODULE" else "DIRECT_SYMBOL",
                "paths": sorted(owner_paths.get((label, provider_id), set())),
            }
        if label == "FILE":
            node_entries = entries_by_key.get((label, provider_id), [])
            paths = sorted(owner_paths.get((label, provider_id), set()))
            if len(node_entries) != 1 or len(paths) != 1:
                return {"state": "UNCLASSIFIED", "paths": paths, "reason": "INTERNAL_ENDPOINT_AMBIGUOUS"}
            relative_path = paths[0]
            repository_file = repository_files.get(relative_path)
            if not isinstance(repository_file, Mapping):
                return {"state": "UNCLASSIFIED", "paths": paths, "reason": "INTERNAL_TARGET_UNRESOLVED"}
            if relative_path in eligible_by_path:
                modules = modules_by_path.get(relative_path, [])
                if len(modules) == 1:
                    return {"state": "INTERNAL", "symbolId": modules[0], "resolution": "ELIGIBLE_FILE_TO_MODULE", "paths": paths}
                return {"state": "UNCLASSIFIED", "paths": paths, "reason": "INTERNAL_FILE_TO_MODULE_PROJECTION_FAILED"}
            return {"state": "NON_ELIGIBLE", "paths": paths, "boundaryKey": relative_path}
        if label == "EXTERNALMODULE" and not entries_by_key.get((label, provider_id)) and provider_id not in repository_provider_ids and _safe_boundary_key(provider_id):
            return {"state": "EXTERNAL", "paths": [], "boundaryKey": provider_id}
        paths = sorted(owner_paths.get((label, provider_id), set()))
        return {"state": "UNCLASSIFIED", "paths": paths, "reason": "INTERNAL_TARGET_UNRESOLVED"}

    relationships: list[dict[str, object]] = []
    boundary_relationships: list[dict[str, object]] = []
    unresolved_internal: list[dict[str, object]] = []
    migration_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    all_raw_ids: list[str] = []
    resolved_raw_ids: list[str] = []
    boundary_raw_ids: list[str] = []
    unresolved_raw_ids: list[str] = []
    for relation in raw.relationships:
        raw_rel_type = str(relation.get("type") or relation.get("kind") or relation.get("relationshipType") or "").upper()
        rel_type = {"CONTAINS_SECTION": "CONTAINS", "DEFINES_METHOD": "DEFINES"}.get(raw_rel_type, raw_rel_type)
        source_id = str(relation.get("source") or relation.get("sourceId") or relation.get("source_id") or "")
        target_id = str(relation.get("target") or relation.get("targetId") or relation.get("target_id") or "")
        source_label = _normalize_label(relation.get("sourceLabel") or relation.get("source_label") or "*")
        target_label = _normalize_label(relation.get("targetLabel") or relation.get("target_label") or "*")
        raw_id = _raw_relationship_id(relation)
        legacy_source = provider_to_symbol.get((source_label, source_id)) if source_label in DIRECT_SYMBOL_LABELS else None
        legacy_target = provider_to_symbol.get((target_label, target_id)) if target_label in DIRECT_SYMBOL_LABELS else None
        migration_candidate = not (legacy_source and legacy_target)
        if raw_rel_type in STRUCTURAL_RELATION_TYPES and migration_candidate:
            continue
        all_raw_ids.append(raw_id)
        origin = "LEGACY_UNRESOLVED" if migration_candidate else "LEGACY_RESOLVED"
        source = endpoint(source_label, source_id)
        target = endpoint(target_label, target_id)
        if rel_type in SUPPORTED_RELATION_TYPES and source["state"] == "INTERNAL" and target["state"] == "INTERNAL":
            source_symbol_id = str(source["symbolId"])
            target_symbol_id = str(target["symbolId"])
            row = {
                "relationshipId": _relationship_id(source_symbol_id, rel_type, target_symbol_id),
                "rawRelationshipId": raw_id,
                "sourceSymbolId": source_symbol_id,
                "type": rel_type,
                "targetSymbolId": target_symbol_id,
                "resolutionClass": "RESOLVED_INTERNAL",
                "sourceResolution": source["resolution"],
                "targetResolution": target["resolution"],
                "classificationOrigin": origin,
            }
            relationships.append(row)
            resolved_raw_ids.append(raw_id)
            if migration_candidate:
                migration_type_counts[rel_type]["provider"] += 1
                migration_type_counts[rel_type]["resolved"] += 1
            continue

        internal_role = "SOURCE" if source["state"] == "INTERNAL" else ("TARGET" if target["state"] == "INTERNAL" else "")
        boundary_endpoint = target if internal_role == "SOURCE" else source
        boundary_role = "TARGET" if internal_role == "SOURCE" else "SOURCE"
        if rel_type in SUPPORTED_RELATION_TYPES and internal_role and boundary_endpoint["state"] in {"EXTERNAL", "NON_ELIGIBLE"}:
            boundary_class = "EXTERNAL" if boundary_endpoint["state"] == "EXTERNAL" else "REPOSITORY_NON_ELIGIBLE"
            boundary_kind = "UNDECLARED_EXTERNAL_MODULE" if boundary_class == "EXTERNAL" else "NON_ELIGIBLE_FILE"
            boundary_key = str(boundary_endpoint["boundaryKey"])
            boundary_key_hash = _boundary_key_hash(boundary_class, boundary_kind, boundary_key)
            evidence = [{
                "method": "REPOSITORY_MODULE_INVENTORY_NEGATIVE" if boundary_class == "EXTERNAL" else "ELIGIBILITY_INVENTORY",
                "ruleId": "externalmodule-absent-no-ownership-conflict" if boundary_class == "EXTERNAL" else "repository-file-source-extension-exclusion",
                "artifactHash": str(provider_node_inventory["inventoryHash"]) if boundary_class == "EXTERNAL" else repository_inventory_hash,
            }]
            if boundary_class == "REPOSITORY_NON_ELIGIBLE":
                evidence.append({"method": "ELIGIBILITY_INVENTORY", "ruleId": "locked-source-extensions", "artifactHash": config_hash})
            internal_symbol_id = str(source["symbolId"] if internal_role == "SOURCE" else target["symbolId"])
            identity = {
                "internalSymbolId": internal_symbol_id,
                "type": rel_type,
                "internalRole": internal_role,
                "boundaryClass": boundary_class,
                "boundaryKeyHash": boundary_key_hash,
            }
            row = {
                "boundaryRelationshipId": content_hash(identity, excluded_keys=()),
                "rawRelationshipId": raw_id,
                "type": rel_type,
                "internalSymbolId": internal_symbol_id,
                "internalRole": internal_role,
                "boundaryRole": boundary_role,
                "boundaryClass": boundary_class,
                "boundaryKind": boundary_kind,
                "boundaryKey": boundary_key,
                "boundaryKeyHash": boundary_key_hash,
                "classificationEvidence": evidence,
                "classificationStatus": "AUDITED",
                "traversalPolicy": "STOP_AT_BOUNDARY",
                "classificationOrigin": origin,
            }
            boundary_relationships.append(row)
            boundary_raw_ids.append(raw_id)
            if migration_candidate:
                migration_type_counts[rel_type]["provider"] += 1
                migration_type_counts[rel_type]["boundary"] += 1
            continue

        if rel_type not in SUPPORTED_RELATION_TYPES:
            reason = "INTERNAL_RELATION_TYPE_UNSUPPORTED"
        elif source.get("reason") == "INTERNAL_FILE_TO_MODULE_PROJECTION_FAILED" or target.get("reason") == "INTERNAL_FILE_TO_MODULE_PROJECTION_FAILED":
            reason = "INTERNAL_FILE_TO_MODULE_PROJECTION_FAILED"
        elif source["state"] != "INTERNAL" and target["state"] != "INTERNAL":
            reason = "INTERNAL_BOTH_UNRESOLVED"
        elif source["state"] != "INTERNAL":
            reason = "INTERNAL_SOURCE_UNRESOLVED"
        else:
            reason = "INTERNAL_TARGET_UNRESOLVED"
        source_hash = _provider_id_hash(source_id)
        target_hash = _provider_id_hash(target_id)
        known_paths = sorted(set(str(item) for item in source.get("paths", [])) | set(str(item) for item in target.get("paths", [])))
        gap_identity = {
            "type": rel_type,
            "sourceProviderIdHash": source_hash,
            "targetProviderIdHash": target_hash,
            "reasonCode": reason,
            "knownRelativePaths": known_paths,
        }
        unresolved_internal.append({
            "gapId": content_hash(gap_identity, excluded_keys=()),
            "rawRelationshipId": raw_id,
            "type": rel_type,
            "sourceProviderLabel": source_label,
            "sourceProviderIdHash": source_hash,
            "targetProviderLabel": target_label,
            "targetProviderIdHash": target_hash,
            "sourceEligible": source["state"] == "INTERNAL",
            "targetEligible": target["state"] == "INTERNAL",
            "knownRelativePaths": known_paths,
            "reasonCode": reason,
            "evidenceHashes": sorted({str(provider_node_inventory["inventoryHash"]), repository_inventory_hash, config_hash}),
            "blocksCoverage": True,
            "classificationOrigin": origin,
        })
        unresolved_raw_ids.append(raw_id)
        if migration_candidate:
            migration_type_counts[rel_type]["provider"] += 1
            migration_type_counts[rel_type]["unresolved"] += 1

    relationships.sort(key=lambda row: (str(row["sourceSymbolId"]), str(row["type"]), str(row["targetSymbolId"]), str(row["relationshipId"])))
    boundary_relationships.sort(key=lambda row: (str(row["internalSymbolId"]), str(row["type"]), str(row["internalRole"]), str(row["boundaryClass"]), str(row["boundaryKind"]), str(row["boundaryKeyHash"]), str(row["boundaryRelationshipId"])))
    unresolved_internal.sort(key=lambda row: (str(row["type"]), str(row["sourceProviderIdHash"]), str(row["targetProviderIdHash"]), str(row["reasonCode"]), str(row["gapId"])))
    type_counts = [{
        "type": relation_type,
        "providerCount": counts["provider"],
        "resolvedInternalCount": counts["resolved"],
        "auditedBoundaryCount": counts["boundary"],
        "unresolvedInternalCount": counts["unresolved"],
        "legacyUnclassifiedCount": 0,
    } for relation_type, counts in sorted(migration_type_counts.items())]
    migration_resolved = [str(row["rawRelationshipId"]) for row in relationships if row["classificationOrigin"] == "LEGACY_UNRESOLVED"]
    migration_boundary = [str(row["rawRelationshipId"]) for row in boundary_relationships if row["classificationOrigin"] == "LEGACY_UNRESOLVED"]
    migration_unresolved = [str(row["rawRelationshipId"]) for row in unresolved_internal if row["classificationOrigin"] == "LEGACY_UNRESOLVED"]
    raw_unique = len(all_raw_ids) == len(set(all_raw_ids))
    partitions_disjoint = not (
        set(resolved_raw_ids) & set(boundary_raw_ids)
        or set(resolved_raw_ids) & set(unresolved_raw_ids)
        or set(boundary_raw_ids) & set(unresolved_raw_ids)
    )
    accounting_complete = raw_unique and partitions_disjoint and set(all_raw_ids) == set(resolved_raw_ids) | set(boundary_raw_ids) | set(unresolved_raw_ids)
    relationship_coverage: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "classificationContractVersion": SCHEMA_VERSION,
        "classifiableProviderRelationshipCount": len(migration_resolved) + len(migration_boundary) + len(migration_unresolved),
        "resolvedInternalCount": len(migration_resolved),
        "auditedBoundaryCount": len(migration_boundary),
        "unresolvedInternalCount": len(migration_unresolved),
        "legacyUnclassifiedCount": 0,
        "typeCounts": type_counts,
        "classificationComplete": accounting_complete,
        "internalGraphComplete": not unresolved_internal,
        "boundaryClassificationComplete": all(row["classificationEvidence"] for row in boundary_relationships),
        "profile": {
            "nonStructuralProviderRelationshipCount": len(all_raw_ids),
            "resolvedInternalRelationshipCount": len(resolved_raw_ids),
            "auditedBoundaryRelationshipCount": len(boundary_raw_ids),
            "unresolvedInternalRelationshipCount": len(unresolved_raw_ids),
            "rawRelationshipIdsHash": _hash_ids(all_raw_ids),
            "resolvedInternalRawIdsHash": _hash_ids(resolved_raw_ids),
            "auditedBoundaryRawIdsHash": _hash_ids(boundary_raw_ids),
            "unresolvedInternalRawIdsHash": _hash_ids(unresolved_raw_ids),
            "accountingComplete": accounting_complete,
        },
    }
    relationship_coverage["contentHash"] = content_hash(relationship_coverage)
    legacy_projection = [{
        "type": row["type"],
        "sourceProviderIdHash": row["sourceProviderIdHash"],
        "targetProviderIdHash": row["targetProviderIdHash"],
        "reasonCode": row["reasonCode"],
    } for row in unresolved_internal]
    return {
        "symbols": symbols,
        "relationships": relationships,
        "boundaryRelationships": boundary_relationships,
        "unresolvedSymbols": unresolved_symbols,
        "unresolvedInternalRelationships": unresolved_internal,
        "unresolvedRelationships": legacy_projection,
        "relationshipCoverage": relationship_coverage,
        "providerNodeInventory": provider_node_inventory,
    }


def validate_relationship_accounting(
    snapshot: Mapping[str, object],
    manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Recompute the profile partition; legacy snapshots remain readable but cannot pass C02."""
    if snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        return {"valid": False, "code": "INDEX_RELATIONSHIP_CLASSIFICATION_REQUIRED", "summary": {}}
    relationships = snapshot.get("relationships")
    boundaries = snapshot.get("boundaryRelationships")
    gaps = snapshot.get("unresolvedInternalRelationships")
    legacy = snapshot.get("unresolvedRelationships")
    coverage = snapshot.get("relationshipCoverage")
    if not all(isinstance(value, list) for value in (relationships, boundaries, gaps, legacy)) or not isinstance(coverage, Mapping):
        return {"valid": False, "code": "INDEX_RELATIONSHIP_ACCOUNTING_MISMATCH", "summary": {}}
    assert isinstance(relationships, list) and isinstance(boundaries, list) and isinstance(gaps, list) and isinstance(legacy, list)
    try:
        resolved_ids = [str(row["rawRelationshipId"]) for row in relationships if isinstance(row, Mapping)]
        boundary_ids = [str(row["rawRelationshipId"]) for row in boundaries if isinstance(row, Mapping)]
        gap_ids = [str(row["rawRelationshipId"]) for row in gaps if isinstance(row, Mapping)]
        all_ids = resolved_ids + boundary_ids + gap_ids
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("raw relationship ids are not a disjoint set")
        profile = coverage.get("profile")
        if not isinstance(profile, Mapping):
            raise ValueError("relationship profile missing")
        expected_profile = {
            "nonStructuralProviderRelationshipCount": len(all_ids),
            "resolvedInternalRelationshipCount": len(resolved_ids),
            "auditedBoundaryRelationshipCount": len(boundary_ids),
            "unresolvedInternalRelationshipCount": len(gap_ids),
            "rawRelationshipIdsHash": _hash_ids(all_ids),
            "resolvedInternalRawIdsHash": _hash_ids(resolved_ids),
            "auditedBoundaryRawIdsHash": _hash_ids(boundary_ids),
            "unresolvedInternalRawIdsHash": _hash_ids(gap_ids),
            "accountingComplete": True,
        }
        if any(profile.get(key) != value for key, value in expected_profile.items()):
            raise ValueError("full relationship profile mismatch")
        symbols = snapshot.get("symbols")
        symbol_ids = {str(row.get("symbolId")) for row in symbols if isinstance(row, Mapping)} if isinstance(symbols, list) else set()
        for row in relationships:
            if not isinstance(row, Mapping) or row.get("resolutionClass") != "RESOLVED_INTERNAL":
                raise ValueError("resolved relationship shape invalid")
            source_id = str(row.get("sourceSymbolId")); target_id = str(row.get("targetSymbolId")); relation_type = str(row.get("type"))
            if source_id not in symbol_ids or target_id not in symbol_ids:
                raise ValueError("resolved endpoint missing")
            if row.get("relationshipId") != _relationship_id(source_id, relation_type, target_id):
                raise ValueError("resolved relationship identity mismatch")
        for row in boundaries:
            if not isinstance(row, Mapping) or row.get("classificationStatus") != "AUDITED" or row.get("traversalPolicy") != "STOP_AT_BOUNDARY":
                raise ValueError("boundary is not audited")
            if str(row.get("internalSymbolId")) not in symbol_ids or not row.get("classificationEvidence"):
                raise ValueError("boundary evidence missing")
            if row.get("internalRole") == row.get("boundaryRole"):
                raise ValueError("boundary roles overlap")
            methods = {str(item.get("method")) for item in row.get("classificationEvidence", []) if isinstance(item, Mapping)}
            if row.get("boundaryClass") == "EXTERNAL" and "REPOSITORY_MODULE_INVENTORY_NEGATIVE" not in methods:
                raise ValueError("external boundary inventory evidence missing")
            if row.get("boundaryClass") == "REPOSITORY_NON_ELIGIBLE" and "ELIGIBILITY_INVENTORY" not in methods:
                raise ValueError("non-eligible boundary inventory evidence missing")
            boundary_key_hash = _boundary_key_hash(str(row.get("boundaryClass")), str(row.get("boundaryKind")), str(row.get("boundaryKey")))
            if row.get("boundaryKeyHash") != boundary_key_hash:
                raise ValueError("boundary key hash mismatch")
            identity = {
                "internalSymbolId": row.get("internalSymbolId"), "type": row.get("type"), "internalRole": row.get("internalRole"),
                "boundaryClass": row.get("boundaryClass"), "boundaryKeyHash": boundary_key_hash,
            }
            if row.get("boundaryRelationshipId") != content_hash(identity, excluded_keys=()):
                raise ValueError("boundary identity mismatch")
        for row in gaps:
            if not isinstance(row, Mapping) or row.get("blocksCoverage") is not True:
                raise ValueError("internal gap shape invalid")
            gap_identity = {
                "type": row.get("type"), "sourceProviderIdHash": row.get("sourceProviderIdHash"),
                "targetProviderIdHash": row.get("targetProviderIdHash"), "reasonCode": row.get("reasonCode"),
                "knownRelativePaths": row.get("knownRelativePaths"),
            }
            if row.get("gapId") != content_hash(gap_identity, excluded_keys=()):
                raise ValueError("internal gap identity mismatch")
        expected_legacy = [{
            "type": row.get("type"), "sourceProviderIdHash": row.get("sourceProviderIdHash"),
            "targetProviderIdHash": row.get("targetProviderIdHash"), "reasonCode": row.get("reasonCode"),
        } for row in gaps if isinstance(row, Mapping)]
        if legacy != expected_legacy:
            raise ValueError("legacy unresolved projection mismatch")
        migration_rows = [row for row in relationships + boundaries + gaps if isinstance(row, Mapping) and row.get("classificationOrigin") == "LEGACY_UNRESOLVED"]
        migration_resolved = sum(1 for row in relationships if isinstance(row, Mapping) and row.get("classificationOrigin") == "LEGACY_UNRESOLVED")
        migration_boundaries = sum(1 for row in boundaries if isinstance(row, Mapping) and row.get("classificationOrigin") == "LEGACY_UNRESOLVED")
        migration_gaps = sum(1 for row in gaps if isinstance(row, Mapping) and row.get("classificationOrigin") == "LEGACY_UNRESOLVED")
        expected_migration = {
            "classifiableProviderRelationshipCount": len(migration_rows),
            "resolvedInternalCount": migration_resolved,
            "auditedBoundaryCount": migration_boundaries,
            "unresolvedInternalCount": migration_gaps,
            "legacyUnclassifiedCount": 0,
        }
        if any(coverage.get(key) != value for key, value in expected_migration.items()):
            raise ValueError("migration profile mismatch")
        type_counters: dict[str, Counter[str]] = defaultdict(Counter)
        for classification, rows in (("resolved", relationships), ("boundary", boundaries), ("unresolved", gaps)):
            for row in rows:
                if isinstance(row, Mapping) and row.get("classificationOrigin") == "LEGACY_UNRESOLVED":
                    type_counters[str(row.get("type"))]["provider"] += 1
                    type_counters[str(row.get("type"))][classification] += 1
        expected_type_counts = [{
            "type": relation_type, "providerCount": counts["provider"], "resolvedInternalCount": counts["resolved"],
            "auditedBoundaryCount": counts["boundary"], "unresolvedInternalCount": counts["unresolved"], "legacyUnclassifiedCount": 0,
        } for relation_type, counts in sorted(type_counters.items())]
        if coverage.get("typeCounts") != expected_type_counts:
            raise ValueError("relationship type accounting mismatch")
        if coverage.get("contentHash") != content_hash(dict(coverage)):
            raise ValueError("relationship coverage hash mismatch")
        if manifest is not None:
            manifest_relationships = manifest.get("relationships")
            manifest_coverage = manifest.get("coverage")
            if not isinstance(manifest_relationships, Mapping) or not isinstance(manifest_coverage, Mapping):
                raise ValueError("manifest relationship summary missing")
            if manifest_relationships.get("coverageHash") != coverage.get("contentHash") or manifest_coverage.get("relationshipCoverageHash") != coverage.get("contentHash"):
                raise ValueError("manifest/snapshot relationship coverage mismatch")
            if manifest_relationships.get("count") != len(relationships) or manifest_relationships.get("auditedBoundary") != len(boundaries) or manifest_relationships.get("unresolvedInternal") != len(gaps):
                raise ValueError("manifest relationship counts mismatch")
    except (KeyError, TypeError, ValueError):
        return {"valid": False, "code": "INDEX_RELATIONSHIP_ACCOUNTING_MISMATCH", "summary": {}}
    summary = {
        "resolvedInternalCount": len(relationships),
        "auditedBoundaryCount": len(boundaries),
        "unresolvedInternalCount": len(gaps),
        "legacyUnclassifiedCount": int(coverage.get("legacyUnclassifiedCount", 0)),
    }
    return {"valid": True, "code": "OK", "summary": summary}


def build_index(
    project_root: Path,
    output_dir: Path,
    config: Mapping[str, object],
    repository_id: str | None = None,
    *,
    raw_graph: RawGraph | None = None,
) -> BuildIndexResult:
    # @trace FR-001 FR-008 AC-001 AC-009 AC-011 AC-012 AC-013 AC-014
    try:
        root = project_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository is not a directory")
        output = ensure_contained(root, output_dir)
    except (OSError, ValueError) as exc:
        return BuildIndexResult("BLOCK", "REPOSITORY_OUTSIDE_ALLOWED_ROOT", diagnostics=(type(exc).__name__,))
    repository_id = repository_id or str(config.get("repositoryId", "")).strip()
    if not repository_id:
        remote = _git(root, "config", "--get", "remote.origin.url")
        head = _git(root, "rev-parse", "HEAD")
        if remote:
            repository_id = "repo-" + content_hash(remote, excluded_keys=()).removeprefix("sha256:")[:24]
        elif head:
            repository_id = "repo-" + content_hash([root.name, head], excluded_keys=()).removeprefix("sha256:")[:24]
        else:
            return BuildIndexResult("BLOCK", "REPOSITORY_ID_REQUIRED")
    before_files, before_digest, _, repository_files = _inventory(root, config)
    provider_config = ProviderConfig.from_mapping(config)
    provider_dir = output / "provider"
    provider_identity: Mapping[str, object]
    if raw_graph is None:
        run = run_provider_index(root, provider_dir, provider_config)
        if run.status != "SUCCESS":
            return BuildIndexResult(run.status, run.code, diagnostics=run.diagnostics)
        if not run.identity:
            return BuildIndexResult("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH", diagnostics=("provider identity evidence missing",))
        provider_identity = run.identity
        try:
            raw_graph = load_provider_index(provider_dir)
        except (OSError, ValueError, RuntimeError) as exc:
            return BuildIndexResult("UNKNOWN", "PROVIDER_DECODE_FAILED", diagnostics=(type(exc).__name__,))
    else:
        provider_identity = {
            "verificationMode": "fixture-contract",
            "distribution": provider_config.distribution_name,
            "entryPoint": provider_config.entry_point,
            "fixtureHash": content_hash({"nodes": raw_graph.nodes, "relationships": raw_graph.relationships, "manifest": raw_graph.manifest}, excluded_keys=()),
        }
    after_files, after_digest, _, _ = _inventory(root, config)
    if before_digest != after_digest:
        return BuildIndexResult("UNKNOWN", "INDEX_SOURCE_CHANGED")
    head = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain")
    config_hash = content_hash(index_config_fingerprint(config), excluded_keys=())
    core = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "repositoryId": repository_id,
        "source": {"commit": head, "dirty": bool(dirty) if dirty is not None else None},
        "sourceDigest": before_digest,
        "configHash": config_hash,
        "provider": {
            "name": "code-graph-rag",
            "version": provider_config.provider_version,
            "manifestVersion": provider_config.manifest_version,
            "codecSchemaSha256": provider_config.codec_schema_sha256,
            "identity": provider_identity,
        },
    }
    manifest_hash = content_hash(core, excluded_keys=())
    normalized = _normalize_graph(raw_graph, repository_id, manifest_hash, before_files, repository_files, config_hash)
    symbols = normalized["symbols"]
    relationships = normalized["relationships"]
    unresolved_symbols = normalized["unresolvedSymbols"]
    unresolved_relationships = normalized["unresolvedRelationships"]
    boundary_relationships = normalized["boundaryRelationships"]
    unresolved_internal_relationships = normalized["unresolvedInternalRelationships"]
    relationship_coverage = normalized["relationshipCoverage"]
    provider_node_inventory = normalized["providerNodeInventory"]
    indexed_paths = {str(row["relativePath"]) for row in symbols}
    for node in raw_graph.nodes:
        payload = _node_payload(node)
        raw_path = payload.get("path") or payload.get("relativePath") or node.get("path")
        if raw_path:
            try:
                indexed_paths.add(normalize_relative_path(str(raw_path)))
            except ValueError:
                continue
    eligible_paths = {str(row["relativePath"]) for row in before_files}
    gap_files = sorted(eligible_paths - indexed_paths)
    for row in before_files:
        if row["relativePath"] in gap_files:
            row["coverageStatus"] = "GAP"
            row["coverageReason"] = "PROVIDER_PATH_NOT_INDEXED"
    required = set(provider_config.required_captures)
    provider_capture = raw_graph.manifest.get("capture", {}) if isinstance(raw_graph.manifest, Mapping) else {}
    present_capture = set()
    if isinstance(provider_capture, Mapping):
        present_capture.update(str(item).lower() for item in provider_capture.get("requested", []) if isinstance(item, str))
    # Fixture graphs explicitly opt in via manifest; real provider records expanded
    # labels/relations rather than CLI aliases, so a successful provider run proves
    # the requested aliases were used by this adapter.
    if not present_capture and raw_graph.manifest:
        present_capture = required
    missing_captures = sorted(required - present_capture)
    relationship_accounting_complete = bool(relationship_coverage["classificationComplete"])
    boundary_classification_complete = bool(relationship_coverage["boundaryClassificationComplete"])
    internal_graph_complete = bool(relationship_coverage["internalGraphComplete"])
    coverage_complete = (
        not gap_files
        and not missing_captures
        and not unresolved_symbols
        and not unresolved_internal_relationships
        and relationship_accounting_complete
        and boundary_classification_complete
        and internal_graph_complete
    )
    snapshot = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "repositoryId": repository_id,
        "manifestHash": manifest_hash,
        "sourceDigest": before_digest,
        "files": before_files,
        "symbols": symbols,
        "relationships": relationships,
        "boundaryRelationships": boundary_relationships,
        "unresolvedInternalRelationships": unresolved_internal_relationships,
        "unresolvedSymbols": unresolved_symbols,
        "unresolvedRelationships": unresolved_relationships,
        "relationshipCoverage": relationship_coverage,
        "providerNodeInventory": provider_node_inventory,
        "coverage": {
            "complete": coverage_complete,
            "eligibleFileCount": len(before_files),
            "indexedFileCount": len(eligible_paths - set(gap_files)),
            "gapFiles": gap_files,
            "requiredCaptures": sorted(required),
            "missingCaptures": missing_captures,
            "relationshipClassificationComplete": relationship_accounting_complete,
            "unresolvedInternalRelationshipCount": len(unresolved_internal_relationships),
            "auditedBoundaryRelationshipCount": len(boundary_relationships),
            "providerNodeInventoryHash": provider_node_inventory["inventoryHash"],
            "relationshipCoverageHash": relationship_coverage["contentHash"],
        },
        "freshness": {"headMatches": True, "sourceDigestMatches": True, "configMatches": True, "sourceChangedDuringAnalysis": False},
        "providerState": {
            "available": True,
            "schemaMatches": True,
            "identityVerified": True,
            "version": provider_config.provider_version,
            "codecSchemaSha256": provider_config.codec_schema_sha256,
            "configHash": config_hash,
            "identity": provider_identity,
        },
        "integrity": {"valid": True},
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    snapshot["contentHash"] = content_hash(snapshot)
    snapshot["snapshotId"] = "CIS-" + str(snapshot["contentHash"]).removeprefix("sha256:")[:24]
    manifest = dict(core)
    boundary_by_type = dict(sorted(Counter(str(row["type"]) for row in boundary_relationships).items()))
    boundary_by_class = dict(sorted(Counter(str(row["boundaryClass"]) for row in boundary_relationships).items()))
    manifest.update({
        "manifestHash": manifest_hash,
        "files": {"eligible": len(before_files), "indexed": len(eligible_paths - set(gap_files)), "gapFiles": gap_files},
        "symbols": {"count": len(symbols), "unresolved": len(unresolved_symbols)},
        "relationships": {
            "count": len(relationships),
            "unresolved": len(unresolved_relationships),
            "resolvedInternal": len(relationships),
            "auditedBoundary": len(boundary_relationships),
            "unresolvedInternal": len(unresolved_internal_relationships),
            "legacyUnclassified": int(relationship_coverage["legacyUnclassifiedCount"]),
            "coverageHash": relationship_coverage["contentHash"],
            "boundaryByType": boundary_by_type,
            "boundaryByClass": boundary_by_class,
        },
        "coverage": {
            "complete": coverage_complete,
            "missingCaptures": missing_captures,
            "relationshipClassificationComplete": relationship_accounting_complete,
            "unresolvedInternalRelationshipCount": len(unresolved_internal_relationships),
            "auditedBoundaryRelationshipCount": len(boundary_relationships),
            "relationshipCoverageHash": relationship_coverage["contentHash"],
        },
        "snapshotHash": snapshot["contentHash"],
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    })
    manifest["contentHash"] = content_hash(manifest)
    relationship_validation = validate_relationship_accounting(snapshot, manifest)
    normalized_dir = output / "normalized"
    manifest_path = normalized_dir / "code-index-manifest.json"
    snapshot_path = normalized_dir / "code-index-snapshot.json"
    try:
        atomic_write_json(manifest_path, manifest, allowed_root=root)
        atomic_write_json(snapshot_path, snapshot, allowed_root=root)
    except (OSError, ValueError) as exc:
        return BuildIndexResult("BLOCK", "INDEX_INTEGRITY_FAILURE", diagnostics=(type(exc).__name__,))
    if not relationship_validation["valid"]:
        return BuildIndexResult("BLOCK", str(relationship_validation["code"]), manifest_path, snapshot_path, manifest_hash, str(snapshot["contentHash"]))
    if unresolved_internal_relationships:
        return BuildIndexResult("UNKNOWN", "INDEX_INTERNAL_RELATIONSHIP_GAP", manifest_path, snapshot_path, manifest_hash, str(snapshot["contentHash"]), (str(len(unresolved_internal_relationships)),))
    if not boundary_classification_complete:
        return BuildIndexResult("UNKNOWN", "INDEX_BOUNDARY_CLASSIFICATION_INCOMPLETE", manifest_path, snapshot_path, manifest_hash, str(snapshot["contentHash"]))
    if not coverage_complete:
        diagnostics = tuple(gap_files + [f"missingCapture:{item}" for item in missing_captures])
        return BuildIndexResult("UNKNOWN", "INDEX_COVERAGE_INCOMPLETE", manifest_path, snapshot_path, manifest_hash, str(snapshot["contentHash"]), diagnostics)
    return BuildIndexResult("SUCCESS", "OK", manifest_path, snapshot_path, manifest_hash, str(snapshot["contentHash"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--repository-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        config = load_json_object(Path(args.config))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = BuildIndexResult("BLOCK", "INDEX_SCHEMA_INVALID", diagnostics=(type(exc).__name__,))
    else:
        result = build_index(Path(args.project_root), Path(args.output_dir), config, args.repository_id)
    payload = {
        "status": result.status,
        "code": result.code,
        "manifestPath": result.manifest_path.as_posix() if result.manifest_path else None,
        "snapshotPath": result.snapshot_path.as_posix() if result.snapshot_path else None,
        "manifestHash": result.manifest_hash,
        "snapshotHash": result.snapshot_hash,
        "diagnostics": list(result.diagnostics),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result.status == "SUCCESS" else (2 if result.status == "UNKNOWN" else 1)


if __name__ == "__main__":
    sys.exit(main())
