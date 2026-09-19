"""Materialize explicit requirement-to-symbol-to-test trace links."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from .code_intelligence_models import SCHEMA_VERSION, SymbolRef, atomic_write_json, content_hash, load_json_object, normalize_relative_path
except ImportError:
    from code_intelligence_models import SCHEMA_VERSION, SymbolRef, atomic_write_json, content_hash, load_json_object, normalize_relative_path


TRACE_ID_PATTERN = re.compile(
    r"^(?:CAP-[A-Z0-9]+(?:-[A-Z0-9]+)*|(?:FR|NFR|AC|BR|ST)-\d{3}|T-\d{3}(?:\.\d+)?|TASK-[A-Z0-9]+(?:-[A-Z0-9]+)*)$"
)
BUSINESS_ID_PATTERN = re.compile(r"^(?:CAP-|FR-|NFR-|AC-|BR-|ST-)")
TEST_ID_PATTERN = re.compile(r"^TEST-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
COMMENT_LINE = re.compile(r"^\s*(?:#|//|/\*|\*|<!--|--)\s*(?P<body>@(?:trace|test-id)\b.*?)\s*(?:\*/|-->)?\s*$")
MARKDOWN_FENCE_OPENER = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)$")
MARKDOWN_FENCE_CLOSER = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})[ \t]*$")
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})


@dataclass(frozen=True, slots=True)
class Declaration:
    kind: str
    values: tuple[str, ...]
    line: int
    raw: str
    relative_path: str = ""
    valid: bool = True
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class Resolution:
    status: str
    symbol: SymbolRef | None = None
    candidates: tuple[SymbolRef, ...] = ()
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class TraceBridge:
    value: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.value)


def _markdown_fence_opener(line: str) -> tuple[str, int] | None:
    marker = MARKDOWN_FENCE_OPENER.fullmatch(line)
    if marker is None:
        return None
    fence = marker.group("fence")
    info = marker.group("info")
    if fence.startswith("`") and "`" in info:
        return None
    return fence[0], len(fence)


def _closes_markdown_fence(line: str, fence_character: str, minimum_length: int) -> bool:
    marker = MARKDOWN_FENCE_CLOSER.fullmatch(line)
    if marker is None:
        return False
    fence = marker.group("fence")
    return fence[0] == fence_character and len(fence) >= minimum_length


def parse_declarations(text: str, *, markdown: bool = True) -> list[Declaration]:
    declarations: list[Declaration] = []
    open_fence: tuple[str, int] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if markdown:
            if open_fence is not None:
                if _closes_markdown_fence(line, *open_fence):
                    open_fence = None
                continue
            open_fence = _markdown_fence_opener(line)
            if open_fence is not None:
                continue
        marker = COMMENT_LINE.fullmatch(line)
        if marker is None:
            continue
        body = marker.group("body").strip()
        parts = body.split()
        kind = parts[0].removeprefix("@")
        values = tuple(parts[1:])
        valid = True
        reason: str | None = None
        if kind == "trace":
            if not values or len(set(values)) != len(values) or not any(BUSINESS_ID_PATTERN.match(value) for value in values):
                valid, reason = False, "DECLARATION_SYNTAX_INVALID"
            elif any(TRACE_ID_PATTERN.fullmatch(value) is None for value in values):
                valid, reason = False, "DECLARATION_SYNTAX_INVALID"
        else:
            if len(values) != 1 or TEST_ID_PATTERN.fullmatch(values[0]) is None:
                valid, reason = False, "DECLARATION_SYNTAX_INVALID"
        declarations.append(Declaration(kind, values, line_number, line.strip(), valid=valid, reason_code=reason))
    return declarations


def resolve_minimal_symbol(declaration: Declaration, symbols: Sequence[Mapping[str, object] | SymbolRef]) -> Resolution:
    candidates: list[SymbolRef] = []
    for value in symbols:
        try:
            symbol = SymbolRef.from_value(value)
        except (TypeError, ValueError):
            continue
        if declaration.relative_path and symbol.relativePath != declaration.relative_path:
            continue
        if symbol.startLine <= declaration.line <= symbol.endLine and symbol.symbolKind in {"FUNCTION", "METHOD", "CLASS", "SECTION"}:
            candidates.append(symbol)
    if not candidates:
        return Resolution("rejected", reason_code="ORPHAN_DECLARATION")
    minimum_span = min(symbol.endLine - symbol.startLine for symbol in candidates)
    nearest = sorted(
        (symbol for symbol in candidates if symbol.endLine - symbol.startLine == minimum_span),
        key=lambda symbol: (symbol.relativePath, symbol.startLine, symbol.endLine, symbol.symbolKind, symbol.qualifiedName),
    )
    if len(nearest) != 1:
        return Resolution("rejected", candidates=tuple(nearest), reason_code="AMBIGUOUS_SYMBOL_OWNER")
    return Resolution("exact", nearest[0], tuple(nearest))


def _requirements_from_markdown(text: str) -> tuple[set[str], set[str]]:
    known = set(re.findall(r"\b(?:CAP-[A-Z0-9]+(?:-[A-Z0-9]+)*|(?:FR|NFR|AC|BR|ST)-\d{3}|T-\d{3}(?:\.\d+)?|TASK-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b", text))
    required: set[str] = set()
    for line in text.splitlines():
        ids = re.findall(r"\b(?:FR|AC)-\d{3}\b", line)
        if ids and ("Must" in line or "P0" in line):
            required.update(ids)
    return known, required


def load_requirement_catalog(path: Path) -> tuple[set[str], set[str], str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
        known: set[str] = set()
        required: set[str] = set()
        rows: Iterable[object]
        if isinstance(value, Mapping):
            rows = value.get("requirements", value.get("items", [])) if isinstance(value.get("requirements", value.get("items", [])), list) else []
            for key in value.get("knownIds", []) if isinstance(value.get("knownIds"), list) else []:
                known.add(str(key))
            for key in value.get("requiredIds", []) if isinstance(value.get("requiredIds"), list) else []:
                required.add(str(key))
        elif isinstance(value, list):
            rows = value
        else:
            raise ValueError("requirements JSON must be an object or array")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identifier = str(row.get("id", row.get("requirementId", "")))
            if identifier:
                known.add(identifier)
                if str(row.get("priority", row.get("moscow", ""))).upper() in {"MUST", "P0", "P0-MUST"} or row.get("required") is True:
                    required.add(identifier)
    else:
        known, required = _requirements_from_markdown(text)
    return known, required, content_hash(sorted(known), excluded_keys=())


def _rejected(declaration: Declaration, reason: str, resolution: Resolution | None = None, test_id: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "declaration": {"relativePath": declaration.relative_path, "line": declaration.line},
        "requirementIds": list(declaration.values) if declaration.kind == "trace" else [],
        "testId": test_id or (declaration.values[0] if declaration.kind == "test-id" and declaration.values else None),
        "status": "rejected",
        "reasonCode": reason,
    }
    if resolution and resolution.candidates:
        value["candidates"] = [symbol.to_dict() for symbol in resolution.candidates]
    return value


def materialize_trace_links(
    project_root: Path,
    snapshot: Mapping[str, object],
    requirements_file: Path,
    output_file: Path | None = None,
) -> TraceBridge:
    # @trace FR-003 AC-003
    root = project_root.resolve(strict=True)
    known_ids, _required_ids, requirements_hash = load_requirement_catalog(requirements_file)
    symbols = snapshot.get("symbols", [])
    if not isinstance(symbols, list):
        raise ValueError("snapshot symbols must be an array")
    paths = sorted({str(symbol.get("relativePath")) for symbol in symbols if isinstance(symbol, Mapping) and symbol.get("relativePath")})
    declarations: list[Declaration] = []
    for relative_path in paths:
        path = root / normalize_relative_path(relative_path)
        if not path.is_file() or path.is_symlink():
            continue
        for declaration in parse_declarations(
            path.read_text(encoding="utf-8", errors="strict"),
            markdown=path.suffix.lower() in MARKDOWN_SUFFIXES,
        ):
            declarations.append(Declaration(
                declaration.kind, declaration.values, declaration.line, declaration.raw,
                relative_path, declaration.valid, declaration.reason_code,
            ))

    resolved: list[tuple[Declaration, Resolution]] = [(declaration, resolve_minimal_symbol(declaration, symbols)) for declaration in declarations]
    test_owners: dict[str, list[tuple[Declaration, Resolution]]] = {}
    for declaration, resolution in resolved:
        if declaration.kind == "test-id" and declaration.valid and declaration.values:
            test_owners.setdefault(declaration.values[0], []).append((declaration, resolution))
    duplicate_tests = {test_id for test_id, owners in test_owners.items() if len(owners) != 1}
    test_id_by_symbol: dict[str, str] = {}
    for test_id, owners in test_owners.items():
        declaration, resolution = owners[0]
        if test_id not in duplicate_tests and resolution.symbol:
            test_id_by_symbol[resolution.symbol.symbolId] = test_id

    links: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for declaration, resolution in resolved:
        if not declaration.valid:
            rejected.append(_rejected(declaration, declaration.reason_code or "DECLARATION_SYNTAX_INVALID", resolution))
            continue
        if resolution.symbol is None:
            rejected.append(_rejected(declaration, resolution.reason_code or "ORPHAN_DECLARATION", resolution))
            continue
        if declaration.kind == "test-id":
            if declaration.values[0] in duplicate_tests:
                rejected.append(_rejected(declaration, "DUPLICATE_TEST_ID", resolution))
            continue
        unknown = [identifier for identifier in declaration.values if identifier not in known_ids]
        if unknown:
            rejected.append(_rejected(declaration, "UNKNOWN_REQUIREMENT_ID", resolution))
            continue
        test_id = test_id_by_symbol.get(resolution.symbol.symbolId)
        role = "test" if test_id else "implementation"
        row: dict[str, object] = {
            "declaration": {"relativePath": declaration.relative_path, "line": declaration.line},
            "symbolRef": resolution.symbol.to_dict(),
            "requirementIds": sorted(declaration.values),
            "role": role,
            "testId": test_id,
            "status": "exact",
            "reasonCode": None,
            "manifestHash": str(snapshot.get("manifestHash", "")),
            "sourceDigest": str(snapshot.get("sourceDigest", "")),
            "requirementsHash": requirements_hash,
        }
        row["traceLinkId"] = content_hash(row, excluded_keys=())
        links.append(row)
    links.sort(key=lambda row: (str(row["symbolRef"]["symbolId"]), str(row["role"]), str(row["testId"] or ""), str(row["traceLinkId"])))
    rejected.sort(key=lambda row: (str(row["declaration"]["relativePath"]), int(row["declaration"]["line"]), str(row["reasonCode"])))
    bridge: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "manifestHash": str(snapshot.get("manifestHash", "")),
        "sourceDigest": str(snapshot.get("sourceDigest", "")),
        "requirementsHash": requirements_hash,
        "links": links,
        "rejected": rejected,
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    bridge["contentHash"] = content_hash(bridge)
    bridge["traceBridgeId"] = "CTB-" + str(bridge["contentHash"]).removeprefix("sha256:")[:24]
    if output_file is not None:
        atomic_write_json(output_file, bridge, allowed_root=root)
    return TraceBridge(bridge)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        bridge = materialize_trace_links(Path(args.project_root), load_json_object(Path(args.snapshot)), Path(args.requirements), Path(args.output)).to_dict()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {"status": "BLOCK", "code": "TRACE_SCHEMA_INVALID", "diagnostics": [type(exc).__name__]}
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    payload = {"status": "SUCCESS", "code": "OK", "traceBridgeId": bridge["traceBridgeId"], "contentHash": bridge["contentHash"], "rejectedCount": len(bridge["rejected"])}
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if not bridge["rejected"] else 1


if __name__ == "__main__":
    sys.exit(main())
