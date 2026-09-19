"""Execute seven deterministic Chinese/English code-structure intents."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

try:
    from .code_intelligence_models import boundary_summary, load_json_object
except ImportError:
    from code_intelligence_models import boundary_summary, load_json_object


INTENTS = ("definition", "callers", "callees", "references", "contains", "implements_requirement", "tests_for")
QUERY_SCHEMA_VERSION = "1.1.0"
REQUIREMENT_RE = re.compile(r"\b(?:CAP-[A-Z0-9]+(?:-[A-Z0-9]+)*|(?:FR|NFR|AC|BR|ST)-\d{3}|T-\d{3}(?:\.\d+)?|TASK-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b")


@dataclass(frozen=True, slots=True)
class IntentResult:
    status: str
    intent: str | None
    target: str | None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryResult:
    value: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.value)


def parse_controlled_intent(question: str) -> IntentResult:
    text = " ".join(question.strip().split())
    if not text:
        return IntentResult("UNSUPPORTED_INTENT", None, None, ("Question is empty.",))
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("definition", (r"^(.+?)(?:在哪里定义|定义在哪(?:里)?)\??$", r"^where is (.+?) defined\??$", r"^definition of (.+?)\??$")),
        ("callers", (r"^谁调用(?:了)?\s*(.+?)\??$", r"^who calls (.+?)\??$", r"^callers of (.+?)\??$")),
        ("callees", (r"^(.+?)调用(?:了)?谁\??$", r"^what does (.+?) call\??$", r"^callees of (.+?)\??$")),
        ("references", (r"^谁引用(?:了)?\s*(.+?)\??$", r"^who references (.+?)\??$", r"^references to (.+?)\??$")),
        ("contains", (r"^(?:模块|module)\s*(.+?)包含什么\??$", r"^what is in (?:module )?(.+?)\??$", r"^contents of (.+?)\??$")),
        ("implements_requirement", (r"^((?:CAP-[A-Z0-9-]+|(?:FR|NFR|AC|BR|ST)-\d{3}|T-\d{3}(?:\.\d+)?|TASK-[A-Z0-9-]+))\s*由什么实现\??$", r"^implementation of ((?:CAP-[A-Z0-9-]+|(?:FR|NFR|AC|BR|ST)-\d{3}|T-\d{3}(?:\.\d+)?|TASK-[A-Z0-9-]+))\??$", r"^what implements ((?:CAP-[A-Z0-9-]+|(?:FR|NFR|AC|BR|ST)-\d{3}|T-\d{3}(?:\.\d+)?|TASK-[A-Z0-9-]+))\??$")),
        ("tests_for", (r"^哪些测试覆盖\s*(.+?)\??$", r"^tests (?:covering|for) (.+?)\??$", r"^what tests cover (.+?)\??$")),
    )
    for intent, alternatives in patterns:
        for pattern in alternatives:
            match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
            if match:
                target = match.group(1).strip().strip("`\"'")
                return IntentResult("PARSED", intent, target)
    return IntentResult("UNSUPPORTED_INTENT", None, None, (f"Allowed intents: {', '.join(INTENTS)}",))


def _symbols(snapshot: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = snapshot.get("symbols", [])
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _resolve_symbol(snapshot: Mapping[str, object], target: str) -> list[Mapping[str, object]]:
    exact: list[Mapping[str, object]] = []
    folded: list[Mapping[str, object]] = []
    for symbol in _symbols(snapshot):
        qname = str(symbol.get("qualifiedName", ""))
        symbol_id = str(symbol.get("symbolId", ""))
        if target in {qname, symbol_id, f"{symbol.get('relativePath')}:{qname}"}:
            exact.append(symbol)
        elif qname.casefold().endswith(target.casefold()) or qname.rsplit(".", 1)[-1].casefold() == target.casefold():
            folded.append(symbol)
    return sorted(exact or folded, key=lambda row: (str(row.get("relativePath")), int(row.get("startLine", 0)), str(row.get("qualifiedName"))))


def _candidate(symbol: Mapping[str, object]) -> dict[str, object]:
    return {
        "symbolId": symbol.get("symbolId"),
        "qualifiedName": symbol.get("qualifiedName"),
        "relativePath": symbol.get("relativePath"),
        "startLine": symbol.get("startLine"),
        "endLine": symbol.get("endLine"),
    }


def _relationship_profile_ready(snapshot: Mapping[str, object]) -> bool:
    coverage = snapshot.get("relationshipCoverage")
    return (
        snapshot.get("schemaVersion") == QUERY_SCHEMA_VERSION
        and isinstance(coverage, Mapping)
        and coverage.get("classificationComplete") is True
        and coverage.get("internalGraphComplete") is True
        and coverage.get("boundaryClassificationComplete") is True
        and coverage.get("legacyUnclassifiedCount") == 0
        and isinstance(snapshot.get("boundaryRelationships"), list)
        and isinstance(snapshot.get("unresolvedInternalRelationships"), list)
        and not snapshot.get("unresolvedInternalRelationships")
    )


def _coverage_summary(snapshot: Mapping[str, object]) -> dict[str, object]:
    coverage = snapshot.get("relationshipCoverage") if isinstance(snapshot.get("relationshipCoverage"), Mapping) else {}
    profile = coverage.get("profile") if isinstance(coverage.get("profile"), Mapping) else {}
    return {
        "classificationComplete": coverage.get("classificationComplete") is True,
        "internalGraphComplete": coverage.get("internalGraphComplete") is True,
        "boundaryClassificationComplete": coverage.get("boundaryClassificationComplete") is True,
        "resolvedInternalRelationshipCount": profile.get("resolvedInternalRelationshipCount", 0),
        "auditedBoundaryRelationshipCount": profile.get("auditedBoundaryRelationshipCount", 0),
        "unresolvedInternalRelationshipCount": profile.get("unresolvedInternalRelationshipCount", 0),
        "legacyUnclassifiedRelationshipCount": coverage.get("legacyUnclassifiedCount", 0),
        "relationshipCoverageHash": coverage.get("contentHash"),
    }


def execute_query(
    snapshot: Mapping[str, object],
    trace_bridge: Mapping[str, object],
    intent: str,
    target: str,
    *,
    max_candidates: int = 20,
) -> QueryResult:
    # @trace FR-002 AC-002 AC-011 AC-012
    diagnostics: list[str] = []
    symbols_by_id = {str(row.get("symbolId")): row for row in _symbols(snapshot)}
    response_symbols: list[Mapping[str, object]] = []
    paths: list[dict[str, object]] = []
    boundary_hits: list[Mapping[str, object]] = []
    candidates: list[dict[str, object]] = []
    status = "ANSWERED"
    if intent not in INTENTS:
        status = "UNSUPPORTED_INTENT"
        diagnostics.append(f"Allowed intents: {', '.join(INTENTS)}")
    elif not _relationship_profile_ready(snapshot):
        status = "UNKNOWN"
        diagnostics.append("Snapshot relationship classification is legacy, incomplete, or internally unresolved; rebuild profile 1.1.")
    elif not bool((snapshot.get("coverage") or {}).get("complete", False)):
        status = "UNKNOWN"
        diagnostics.append("Snapshot coverage is incomplete; rebuild with full required capture coverage.")
    elif trace_bridge.get("manifestHash") != snapshot.get("manifestHash") or trace_bridge.get("sourceDigest") != snapshot.get("sourceDigest"):
        status = "UNKNOWN"
        diagnostics.append("Trace bridge is stale; re-materialize it from the current snapshot.")
    elif intent == "implements_requirement":
        if REQUIREMENT_RE.fullmatch(target) is None:
            status = "NO_MATCH"
        else:
            for link in trace_bridge.get("links", []) if isinstance(trace_bridge.get("links"), list) else []:
                if isinstance(link, Mapping) and link.get("status") == "exact" and link.get("role") == "implementation" and target in link.get("requirementIds", []):
                    symbol = link.get("symbolRef")
                    if isinstance(symbol, Mapping):
                        response_symbols.append(symbol)
            if not response_symbols:
                status = "NO_MATCH"
    elif intent == "tests_for":
        requirement_ids: set[str] = set()
        if REQUIREMENT_RE.fullmatch(target):
            requirement_ids.add(target)
        else:
            resolved = _resolve_symbol(snapshot, target)
            if len(resolved) > 1:
                status = "AMBIGUOUS"
                candidates = [_candidate(symbol) for symbol in resolved[:max_candidates]]
            elif not resolved:
                status = "NO_MATCH"
            else:
                symbol_id = str(resolved[0].get("symbolId"))
                for link in trace_bridge.get("links", []) if isinstance(trace_bridge.get("links"), list) else []:
                    if isinstance(link, Mapping) and isinstance(link.get("symbolRef"), Mapping) and str(link["symbolRef"].get("symbolId")) == symbol_id:
                        requirement_ids.update(str(item) for item in link.get("requirementIds", []))
        if status == "ANSWERED":
            for link in trace_bridge.get("links", []) if isinstance(trace_bridge.get("links"), list) else []:
                if not isinstance(link, Mapping) or link.get("role") != "test" or link.get("status") != "exact":
                    continue
                if requirement_ids.intersection(str(item) for item in link.get("requirementIds", [])):
                    symbol = link.get("symbolRef")
                    if isinstance(symbol, Mapping):
                        response_symbols.append(symbol)
            if not response_symbols:
                status = "NO_MATCH"
    else:
        resolved = _resolve_symbol(snapshot, target)
        if len(resolved) > 1:
            status = "AMBIGUOUS"
            candidates = [_candidate(symbol) for symbol in resolved[:max_candidates]]
        elif not resolved:
            status = "NO_MATCH"
        elif intent == "definition":
            response_symbols = resolved
        else:
            seed_id = str(resolved[0].get("symbolId"))
            relation_rules = {
                "callers": ({"CALLS"}, "reverse"),
                "callees": ({"CALLS"}, "forward"),
                "references": ({"REFERENCES", "INSTANTIATES"}, "reverse"),
                "contains": ({"CONTAINS", "DEFINES", "DEFINES_METHOD"}, "forward"),
            }
            allowed, direction = relation_rules[intent]
            for relation in snapshot.get("relationships", []) if isinstance(snapshot.get("relationships"), list) else []:
                if not isinstance(relation, Mapping) or str(relation.get("type")) not in allowed:
                    continue
                source = str(relation.get("sourceSymbolId"))
                destination = str(relation.get("targetSymbolId"))
                match = source == seed_id if direction == "forward" else destination == seed_id
                other = destination if direction == "forward" else source
                if match and other in symbols_by_id:
                    response_symbols.append(symbols_by_id[other])
                    paths.append({"nodeIds": [seed_id, other] if direction == "forward" else [other, seed_id], "types": [relation.get("type")], "length": 1})
            for boundary in snapshot.get("boundaryRelationships", []) if isinstance(snapshot.get("boundaryRelationships"), list) else []:
                if not isinstance(boundary, Mapping) or str(boundary.get("type")) not in allowed or str(boundary.get("internalSymbolId")) != seed_id:
                    continue
                internal_role = str(boundary.get("internalRole"))
                if (direction == "forward" and internal_role == "SOURCE") or (direction == "reverse" and internal_role == "TARGET"):
                    boundary_hits.append(boundary)
            if not response_symbols and not boundary_hits:
                status = "NO_MATCH"
    unique = {str(symbol.get("symbolId")): symbol for symbol in response_symbols}
    response_symbols = [unique[key] for key in sorted(unique, key=lambda key: (str(unique[key].get("relativePath")), int(unique[key].get("startLine", 0)), str(unique[key].get("qualifiedName"))))]
    boundary_hits.sort(key=lambda row: (str(row.get("internalSymbolId")), str(row.get("type")), str(row.get("boundaryClass")), str(row.get("boundaryKind")), str(row.get("boundaryKeyHash"))))
    facts = [f"{intent} returned {len(response_symbols)} exact symbol(s) and {len(boundary_hits)} audited boundary relation(s)."] if status == "ANSWERED" else []
    value: dict[str, object] = {
        "schemaVersion": QUERY_SCHEMA_VERSION,
        "queryStatus": status,
        "intent": intent,
        "normalizedTarget": target,
        "answerFacts": facts,
        "candidates": candidates,
        "symbols": response_symbols,
        "relationPaths": sorted(paths, key=lambda row: (row["length"], row["types"], row["nodeIds"])),
        "boundaryRelationships": [dict(row) for row in boundary_hits],
        "boundarySummary": boundary_summary(boundary_hits),
        "relationshipCoverageSummary": _coverage_summary(snapshot),
        "manifestHash": snapshot.get("manifestHash"),
        "sourceDigest": snapshot.get("sourceDigest"),
        "diagnostics": diagnostics,
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return QueryResult(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--trace-bridge", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--question")
    group.add_argument("--intent", choices=INTENTS)
    parser.add_argument("--target")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.question:
        parsed = parse_controlled_intent(args.question)
        if parsed.status != "PARSED" or parsed.intent is None or parsed.target is None:
            payload = {"schemaVersion": QUERY_SCHEMA_VERSION, "queryStatus": parsed.status, "intent": None, "normalizedTarget": None, "answerFacts": [], "candidates": [], "symbols": [], "relationPaths": [], "boundaryRelationships": [], "boundarySummary": boundary_summary([]), "relationshipCoverageSummary": {}, "manifestHash": None, "sourceDigest": None, "diagnostics": list(parsed.diagnostics), "generatedAt": datetime.now(UTC).isoformat(timespec="seconds")}
            print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
            return 1
        intent, target = parsed.intent, parsed.target
    else:
        if not args.target:
            parser.error("--target is required with --intent")
        intent, target = args.intent, args.target
    try:
        result = execute_query(load_json_object(Path(args.snapshot)), load_json_object(Path(args.trace_bridge)), str(intent), str(target)).to_dict()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"queryStatus": "UNKNOWN", "diagnostics": [type(exc).__name__]}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["queryStatus"] in {"ANSWERED", "NO_MATCH", "AMBIGUOUS"} else (2 if result["queryStatus"] == "UNKNOWN" else 1)


if __name__ == "__main__":
    sys.exit(main())
