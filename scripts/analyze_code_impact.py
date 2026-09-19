"""Compute fail-closed pre-change impact from canonical offline artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .code_intelligence_models import SCHEMA_VERSION, ImpactVerdict, atomic_write_json, boundary_summary, content_hash, load_json_object, normalize_relative_path
except ImportError:
    from code_intelligence_models import SCHEMA_VERSION, ImpactVerdict, atomic_write_json, boundary_summary, content_hash, load_json_object, normalize_relative_path


TRAVERSED_RELATIONS = frozenset({"CALLS", "REFERENCES", "INSTANTIATES", "INHERITS", "IMPLEMENTS", "OVERRIDES", "IMPORTS", "EXPORTS", "EXPORTS_MODULE", "IMPLEMENTS_MODULE", "EXPOSES", "RESOLVES_TO", "LINKS_TO"})
IMPACT_SCHEMA_VERSION = "1.1.0"
UNKNOWN_NAMES = {
    "U-01": "INVALID_SEED", "U-02": "AMBIGUOUS_SEED", "U-03": "STALE_HEAD", "U-04": "STALE_SOURCE_DIGEST",
    "U-05": "STALE_CONFIG", "U-06": "PROVIDER_UNAVAILABLE", "U-07": "PROVIDER_SCHEMA_MISMATCH",
    "U-08": "INDEX_INTEGRITY_FAILURE", "U-09": "COVERAGE_INCOMPLETE", "U-10": "UNRESOLVED_SYMBOL",
    "U-11": "UNRESOLVED_RELATIONSHIP", "U-12": "TRACE_BRIDGE_STALE", "U-13": "UNKNOWN_REQUIREMENT_ID",
    "U-14": "DEPTH_TRUNCATED", "U-15": "NODE_LIMIT_EXCEEDED", "U-16": "TIMEOUT",
    "U-17": "SOURCE_CHANGED_DURING_ANALYSIS", "U-18": "REPORT_SCHEMA_INVALID",
}
REMEDIATIONS = {
    "U-01": "Provide one existing requirement, symbol or repository-relative file seed.",
    "U-02": "Disambiguate the seed with a qualified name or SymbolRef.",
    "U-03": "Rebuild the index at the current HEAD.", "U-04": "Rebuild after the source tree is stable.",
    "U-05": "Rebuild with the current locked configuration.", "U-06": "Install and probe the pinned provider.",
    "U-07": "Restore the pinned provider and codec schema.", "U-08": "Discard the exact derived index directory and rebuild it.",
    "U-09": "Add language coverage or provide a mechanically proven exclusion, then rebuild.",
    "U-10": "Repair unresolved symbol paths and rebuild.", "U-11": "Repair unresolved relation endpoints and rebuild.",
    "U-12": "Re-materialize the trace bridge from the current snapshot and requirements.",
    "U-13": "Use an ID from the authoritative requirements catalog.", "U-14": "Increase max depth or narrow the seed and retry.",
    "U-15": "Increase max nodes or narrow the seed and retry.", "U-16": "Increase timeout or narrow the seed and retry.",
    "U-17": "Wait for a stable source tree and rerun the full analysis.", "U-18": "Repair the artifact to schemaVersion 1.0.0 and retry.",
}


def _reason(code: str, evidence: list[str] | tuple[str, ...] = ()) -> dict[str, object]:
    return {"code": code, "name": UNKNOWN_NAMES[code], "evidence": sorted(str(item) for item in evidence), "remediation": REMEDIATIONS[code]}


def _symbol_key(symbol: Mapping[str, object]) -> tuple[str, int, int, str, str]:
    return (str(symbol.get("relativePath", "")), int(symbol.get("startLine", 0)), int(symbol.get("endLine", 0)), str(symbol.get("symbolKind", "")), str(symbol.get("qualifiedName", "")))


def _resolve_seed(snapshot: Mapping[str, object], trace: Mapping[str, object], seed_type: str, seed_value: str) -> tuple[dict[str, object], list[str]]:
    symbols = [row for row in snapshot.get("symbols", []) if isinstance(row, Mapping)] if isinstance(snapshot.get("symbols"), list) else []
    matches: list[Mapping[str, object]] = []
    requirements: list[str] = []
    files: list[str] = []
    errors: list[str] = []
    if seed_type == "requirement":
        requirements = [seed_value]
        for link in trace.get("links", []) if isinstance(trace.get("links"), list) else []:
            if isinstance(link, Mapping) and link.get("status") == "exact" and link.get("role") == "implementation" and seed_value in link.get("requirementIds", []):
                symbol = link.get("symbolRef")
                if isinstance(symbol, Mapping):
                    matches.append(symbol)
        if not matches:
            errors.append("U-13")
    elif seed_type == "file":
        try:
            normalized = normalize_relative_path(seed_value)
        except ValueError:
            errors.append("U-01")
        else:
            files = [normalized]
            matches = [symbol for symbol in symbols if str(symbol.get("relativePath")) == normalized]
            if not matches:
                errors.append("U-01")
    elif seed_type == "symbol":
        matches = [symbol for symbol in symbols if seed_value in {str(symbol.get("symbolId")), str(symbol.get("qualifiedName")), f"{symbol.get('relativePath')}:{symbol.get('qualifiedName')}"}]
        if not matches:
            matches = [symbol for symbol in symbols if str(symbol.get("qualifiedName", "")).casefold().endswith(seed_value.casefold())]
        if not matches:
            errors.append("U-01")
        elif len(matches) > 1:
            errors.append("U-02")
    else:
        errors.append("U-01")
    status = "RESOLVED" if matches and not errors else ("AMBIGUOUS" if "U-02" in errors else "NOT_FOUND")
    return {
        "status": status,
        "symbols": sorted((dict(row) for row in matches), key=_symbol_key),
        "requirements": requirements,
        "files": files,
    }, errors


def analyze_impact(
    snapshot: Mapping[str, object],
    trace_bridge: Mapping[str, object],
    seed_type: str | None = None,
    seed_value: str | None = None,
    *,
    requirement: str | None = None,
    symbol: str | None = None,
    file: str | None = None,
    depth: int = 8,
    max_nodes: int = 10000,
    timeout_seconds: float = 10,
    analysis_run_id: str = "CIR-prechange",
    fault_flags: Mapping[str, object] | None = None,
) -> dict[str, object]:
    # @trace FR-005 AC-005 AC-010 AC-015
    supplied = [("requirement", requirement), ("symbol", symbol), ("file", file)]
    explicit = [(kind, value) for kind, value in supplied if value is not None]
    if explicit:
        if len(explicit) == 1:
            seed_type, seed_value = explicit[0][0], str(explicit[0][1])
        else:
            seed_type, seed_value = "invalid", "multiple-seeds"
    seed_type = seed_type or "invalid"
    seed_value = seed_value or ""
    flags = dict(fault_flags or {})
    request = {"seedType": seed_type, "seedValue": seed_value, "depth": depth, "maxNodes": max_nodes, "timeoutSeconds": timeout_seconds}
    resolution, seed_errors = _resolve_seed(snapshot, trace_bridge, seed_type, seed_value)
    unknown: list[dict[str, object]] = [_reason(code, [seed_value]) for code in seed_errors]
    freshness = snapshot.get("freshness", {}) if isinstance(snapshot.get("freshness"), Mapping) else {}
    provider = snapshot.get("providerState", {}) if isinstance(snapshot.get("providerState"), Mapping) else {}
    integrity = snapshot.get("integrity", {}) if isinstance(snapshot.get("integrity"), Mapping) else {}
    coverage = snapshot.get("coverage", {}) if isinstance(snapshot.get("coverage"), Mapping) else {}
    relationship_coverage = snapshot.get("relationshipCoverage", {}) if isinstance(snapshot.get("relationshipCoverage"), Mapping) else {}
    unresolved_internal = snapshot.get("unresolvedInternalRelationships", []) if isinstance(snapshot.get("unresolvedInternalRelationships"), list) else []
    legacy_unclassified = int(relationship_coverage.get("legacyUnclassifiedCount", 0)) if isinstance(relationship_coverage.get("legacyUnclassifiedCount", 0), int) else 1
    checks = (
        ("U-03", freshness.get("headMatches", True) is False, ["HEAD"]),
        ("U-04", freshness.get("sourceDigestMatches", True) is False, ["sourceDigest"]),
        ("U-05", freshness.get("configMatches", True) is False, ["configHash"]),
        ("U-06", provider.get("available", True) is False or flags.get("providerUnavailable") is True, ["provider"]),
        ("U-07", provider.get("schemaMatches", True) is False or provider.get("identityVerified") is not True or flags.get("providerSchemaMismatch") is True, ["codecSchemaSha256", "providerIdentity"]),
        ("U-08", integrity.get("valid", True) is False or flags.get("integrityFailure") is True, ["index"]),
        ("U-09", coverage.get("complete", False) is False or relationship_coverage.get("classificationComplete") is not True or relationship_coverage.get("boundaryClassificationComplete") is not True, list(coverage.get("gapFiles", [])) + list(coverage.get("missingCaptures", [])) + ["relationshipCoverage"]),
        ("U-10", bool(snapshot.get("unresolvedSymbols")), [str(len(snapshot.get("unresolvedSymbols", [])))]),
        ("U-11", bool(unresolved_internal) or bool(snapshot.get("unresolvedRelationships")) or legacy_unclassified > 0, [str(len(unresolved_internal) + len(snapshot.get("unresolvedRelationships", [])) + legacy_unclassified)]),
        ("U-12", trace_bridge.get("manifestHash") != snapshot.get("manifestHash") or trace_bridge.get("sourceDigest") != snapshot.get("sourceDigest") or flags.get("traceStale") is True, ["traceBridge"]),
        ("U-17", freshness.get("sourceChangedDuringAnalysis", False) is True or flags.get("sourceChangedDuringAnalysis") is True, ["sourceDigest"]),
        ("U-18", snapshot.get("schemaVersion") != IMPACT_SCHEMA_VERSION or trace_bridge.get("schemaVersion") != SCHEMA_VERSION or not isinstance(snapshot.get("boundaryRelationships"), list) or not isinstance(snapshot.get("relationshipCoverage"), Mapping) or flags.get("reportSchemaInvalid") is True, ["schemaVersion"]),
    )
    for code, condition, evidence in checks:
        if condition:
            unknown.append(_reason(code, evidence))

    symbols = {str(row.get("symbolId")): row for row in snapshot.get("symbols", []) if isinstance(row, Mapping)} if isinstance(snapshot.get("symbols"), list) else {}
    adjacency: dict[str, list[tuple[str, str]]] = {key: [] for key in symbols}
    for relation in snapshot.get("relationships", []) if isinstance(snapshot.get("relationships"), list) else []:
        if not isinstance(relation, Mapping) or str(relation.get("type")) not in TRAVERSED_RELATIONS:
            continue
        source = str(relation.get("sourceSymbolId")); target = str(relation.get("targetSymbolId")); kind = str(relation.get("type"))
        if source in adjacency and target in adjacency:
            adjacency[source].append((target, kind)); adjacency[target].append((source, kind))
    for key in adjacency:
        adjacency[key].sort(key=lambda row: (row[1], _symbol_key(symbols[row[0]])))

    seed_ids = {str(row.get("symbolId")) for row in resolution["symbols"] if isinstance(row, Mapping)}
    queue: deque[tuple[str, int, tuple[str, ...], tuple[str, ...]]] = deque((identifier, 0, (identifier,), ()) for identifier in sorted(seed_ids))
    visited: set[str] = set(seed_ids)
    affected_ids: set[str] = set()
    paths: list[dict[str, object]] = []
    depth_truncated = False
    node_truncated = False
    timed_out = False
    started = time.monotonic()
    while queue:
        if time.monotonic() - started >= timeout_seconds:
            timed_out = True
            break
        current, current_depth, node_path, type_path = queue.popleft()
        neighbors = adjacency.get(current, [])
        if current_depth >= depth:
            if any(other not in visited for other, _kind in neighbors):
                depth_truncated = True
            continue
        for other, kind in neighbors:
            if other in visited:
                continue
            if len(visited) >= max_nodes:
                node_truncated = True
                queue.clear()
                break
            visited.add(other); affected_ids.add(other)
            next_nodes = node_path + (other,); next_types = type_path + (kind,)
            paths.append({"nodeIds": list(next_nodes), "types": list(next_types), "length": len(next_types)})
            queue.append((other, current_depth + 1, next_nodes, next_types))
    if depth_truncated:
        unknown.append(_reason("U-14", [f"maxDepth={depth}"]))
    if node_truncated:
        unknown.append(_reason("U-15", [f"maxNodes={max_nodes}"]))
    if timed_out:
        unknown.append(_reason("U-16", [f"timeoutSeconds={timeout_seconds}"]))

    affected_requirements: set[str] = set(resolution["requirements"])
    tests: set[str] = set()
    relevant_ids = affected_ids | seed_ids
    for link in trace_bridge.get("links", []) if isinstance(trace_bridge.get("links"), list) else []:
        if not isinstance(link, Mapping) or link.get("status") != "exact" or not isinstance(link.get("symbolRef"), Mapping):
            continue
        link_symbol = str(link["symbolRef"].get("symbolId"))
        if link_symbol in relevant_ids:
            affected_requirements.update(str(item) for item in link.get("requirementIds", []))
    for link in trace_bridge.get("links", []) if isinstance(trace_bridge.get("links"), list) else []:
        if isinstance(link, Mapping) and link.get("status") == "exact" and link.get("role") == "test" and affected_requirements.intersection(str(item) for item in link.get("requirementIds", [])) and link.get("testId"):
            tests.add(str(link["testId"]))
    affected_symbols = sorted((dict(symbols[identifier]) for identifier in affected_ids if identifier in symbols), key=_symbol_key)
    affected_files = sorted({str(row.get("relativePath")) for row in affected_symbols})
    boundary_hits = [
        dict(row) for row in snapshot.get("boundaryRelationships", [])
        if isinstance(row, Mapping) and str(row.get("internalSymbolId")) in relevant_ids
    ] if isinstance(snapshot.get("boundaryRelationships"), list) else []
    boundary_hits.sort(key=lambda row: (str(row.get("internalSymbolId")), str(row.get("type")), str(row.get("internalRole")), str(row.get("boundaryClass")), str(row.get("boundaryKind")), str(row.get("boundaryKeyHash"))))
    # A test reachable only through explicit trace is still a real affected item.
    extra_impact = bool(affected_symbols or tests or boundary_hits)
    deduplicated_unknown = {str(row["code"]): row for row in unknown}
    unknown = [deduplicated_unknown[code] for code in sorted(deduplicated_unknown)]
    verdict = ImpactVerdict.UNKNOWN.value if unknown else (ImpactVerdict.FOUND.value if extra_impact else ImpactVerdict.NO_IMPACT.value)
    coverage_result = {
        "complete": bool(coverage.get("complete", False)),
        "gapFiles": sorted(str(item) for item in coverage.get("gapFiles", [])),
        "missingCaptures": sorted(str(item) for item in coverage.get("missingCaptures", [])),
        "unresolvedSymbolCount": len(snapshot.get("unresolvedSymbols", [])),
        "unresolvedRelationshipCount": len(unresolved_internal) + legacy_unclassified,
        "resolvedInternalRelationshipCount": int((relationship_coverage.get("profile") or {}).get("resolvedInternalRelationshipCount", len(snapshot.get("relationships", [])))) if isinstance(relationship_coverage.get("profile"), Mapping) else len(snapshot.get("relationships", [])),
        "auditedBoundaryRelationshipCount": int((relationship_coverage.get("profile") or {}).get("auditedBoundaryRelationshipCount", len(snapshot.get("boundaryRelationships", [])))) if isinstance(relationship_coverage.get("profile"), Mapping) else len(snapshot.get("boundaryRelationships", [])),
        "unresolvedInternalRelationshipCount": len(unresolved_internal),
        "legacyUnclassifiedRelationshipCount": legacy_unclassified,
        "boundaryClassificationComplete": relationship_coverage.get("boundaryClassificationComplete") is True,
    }
    report: dict[str, object] = {
        "schemaVersion": IMPACT_SCHEMA_VERSION,
        "analysisRunId": analysis_run_id,
        "requestHash": content_hash(request, excluded_keys=()),
        "manifestHash": snapshot.get("manifestHash"),
        "traceBridgeHash": trace_bridge.get("contentHash"),
        "sourceDigest": snapshot.get("sourceDigest"),
        "seedResolution": resolution,
        "scope": {"relations": sorted(TRAVERSED_RELATIONS), "directions": "BOTH", "maxDepth": depth, "maxNodes": max_nodes, "timeoutSeconds": timeout_seconds},
        "coverage": coverage_result,
        "affected": {"symbols": affected_symbols, "files": affected_files, "requirements": sorted(affected_requirements), "tests": sorted(tests), "relationPaths": sorted(paths, key=lambda row: (row["length"], row["types"], row["nodeIds"])), "boundaryRelationships": boundary_hits, "boundarySummary": boundary_summary(boundary_hits)},
        "recommendedTests": sorted(tests),
        "verdict": verdict,
        "unknownReasons": unknown,
        "freshness": dict(freshness),
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    report["contentHash"] = content_hash(report)
    report["impactReportId"] = "CIRP-" + str(report["contentHash"]).removeprefix("sha256:")[:24]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--trace-bridge", required=True)
    seed = parser.add_mutually_exclusive_group(required=True)
    seed.add_argument("--requirement"); seed.add_argument("--symbol"); seed.add_argument("--file")
    parser.add_argument("--artifact-root", required=True, help="Trusted existing root for derived artifacts")
    parser.add_argument("--output", required=True)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--max-nodes", type=int, default=10000)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifact_root_argument = Path(args.artifact_root)
        if artifact_root_argument.is_symlink():
            raise ValueError("symlinked artifact root is forbidden")
        artifact_root = artifact_root_argument.resolve(strict=True)
        if not artifact_root.is_dir():
            raise ValueError("artifact root must be an existing directory")
        output = artifact_root / normalize_relative_path(args.output)
        report = analyze_impact(load_json_object(Path(args.snapshot)), load_json_object(Path(args.trace_bridge)), requirement=args.requirement, symbol=args.symbol, file=args.file, depth=args.depth, max_nodes=args.max_nodes, timeout_seconds=args.timeout_seconds)
        atomic_write_json(output, report, allowed_root=artifact_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "UNKNOWN", "unknownReasons": [_reason("U-18", [type(exc).__name__])]}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if report["verdict"] in {"FOUND", "NO_IMPACT"} else 2


if __name__ == "__main__":
    sys.exit(main())
