"""Diff canonical snapshots and reconcile them with impact and changeSet facts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    from .code_intelligence_models import SCHEMA_VERSION, atomic_write_json, content_hash, load_json_object, normalize_relative_path
except ImportError:
    from code_intelligence_models import SCHEMA_VERSION, atomic_write_json, content_hash, load_json_object, normalize_relative_path


SNAPSHOT_SCHEMA_VERSIONS = frozenset({"1.0.0", "1.1.0"})


def _change_rows(
    before_rows: list[Mapping[str, object]],
    after_rows: list[Mapping[str, object]],
    key: Callable[[Mapping[str, object]], str],
    path: Callable[[Mapping[str, object]], str | None],
    digest: Callable[[Mapping[str, object]], str] | None = None,
) -> list[dict[str, object]]:
    row_hash = digest or (lambda row: content_hash(row, excluded_keys=()))
    before = {key(row): row for row in before_rows}; after = {key(row): row for row in after_rows}
    changes: list[dict[str, object]] = []
    for stable_id in sorted(set(before) | set(after)):
        old = before.get(stable_id); new = after.get(stable_id)
        if old is None:
            row: dict[str, object] = {"changeType": "ADDED", "stableId": stable_id, "afterHash": content_hash(new, excluded_keys=())}
            relative = path(new) if new else None
        elif new is None:
            row = {"changeType": "REMOVED", "stableId": stable_id, "beforeHash": content_hash(old, excluded_keys=())}
            relative = path(old)
        else:
            old_hash = row_hash(old); new_hash = row_hash(new)
            if old_hash == new_hash:
                continue
            row = {"changeType": "MODIFIED", "stableId": stable_id, "beforeHash": old_hash, "afterHash": new_hash}
            relative = path(new)
        if relative:
            row["relativePath"] = relative
        changes.append(row)
    return sorted(changes, key=lambda row: (str(row["changeType"]), str(row.get("relativePath", "")), str(row["stableId"])))


def _symbol_stable(row: Mapping[str, object]) -> str:
    return content_hash([row.get("repositoryId"), row.get("relativePath"), row.get("qualifiedName"), row.get("symbolKind")], excluded_keys=())


def _symbol_semantic_hash(row: Mapping[str, object]) -> str:
    return content_hash({key: value for key, value in row.items() if key not in {"symbolId", "manifestHash"}}, excluded_keys=())


def _relation_stable(row: Mapping[str, object]) -> str:
    return str(row.get("relationshipId") or content_hash([row.get("sourceSymbolId"), row.get("type"), row.get("targetSymbolId")], excluded_keys=()))


def _trace_stable(row: Mapping[str, object]) -> str:
    symbol = row.get("symbolRef", {}) if isinstance(row.get("symbolRef"), Mapping) else {}
    symbol_identity = [
        symbol.get("repositoryId"), symbol.get("relativePath"),
        symbol.get("qualifiedName"), symbol.get("symbolKind"),
    ]
    return content_hash([symbol_identity, row.get("role"), row.get("testId"), sorted(row.get("requirementIds", []))], excluded_keys=())


def _trace_semantic_hash(row: Mapping[str, object]) -> str:
    value = {key: item for key, item in row.items() if key not in {"traceLinkId", "manifestHash", "sourceDigest"}}
    symbol = value.get("symbolRef")
    if isinstance(symbol, Mapping):
        value["symbolRef"] = {key: item for key, item in symbol.items() if key not in {"symbolId", "manifestHash"}}
    return content_hash(value, excluded_keys=())


def diff_snapshots(
    before_snapshot: Mapping[str, object],
    after_snapshot: Mapping[str, object],
    before_trace: Mapping[str, object] | None = None,
    after_trace: Mapping[str, object] | None = None,
) -> dict[str, list[dict[str, object]]]:
    before_files = [row for row in before_snapshot.get("files", []) if isinstance(row, Mapping)] if isinstance(before_snapshot.get("files"), list) else []
    after_files = [row for row in after_snapshot.get("files", []) if isinstance(row, Mapping)] if isinstance(after_snapshot.get("files"), list) else []
    before_symbols = [row for row in before_snapshot.get("symbols", []) if isinstance(row, Mapping)] if isinstance(before_snapshot.get("symbols"), list) else []
    after_symbols = [row for row in after_snapshot.get("symbols", []) if isinstance(row, Mapping)] if isinstance(after_snapshot.get("symbols"), list) else []
    before_rel = [row for row in before_snapshot.get("relationships", []) if isinstance(row, Mapping)] if isinstance(before_snapshot.get("relationships"), list) else []
    after_rel = [row for row in after_snapshot.get("relationships", []) if isinstance(row, Mapping)] if isinstance(after_snapshot.get("relationships"), list) else []
    before_links = [row for row in (before_trace or {}).get("links", []) if isinstance(row, Mapping)] if isinstance((before_trace or {}).get("links"), list) else []
    after_links = [row for row in (after_trace or {}).get("links", []) if isinstance(row, Mapping)] if isinstance((after_trace or {}).get("links"), list) else []
    return {
        "fileChanges": _change_rows(before_files, after_files, lambda row: str(row.get("relativePath")), lambda row: str(row.get("relativePath"))),
        "symbolChanges": _change_rows(before_symbols, after_symbols, _symbol_stable, lambda row: str(row.get("relativePath")), _symbol_semantic_hash),
        "relationshipChanges": _change_rows(before_rel, after_rel, _relation_stable, lambda _row: None),
        "traceChanges": _change_rows(before_links, after_links, _trace_stable, lambda row: str((row.get("symbolRef") or {}).get("relativePath", "")) if isinstance(row.get("symbolRef"), Mapping) else None, _trace_semantic_hash),
    }


def _declared_files(change_set: Mapping[str, object]) -> set[str]:
    values: list[object] = []
    for key in ("declaredCodeFiles", "codeFiles", "files", "changedFiles", "changeSet"):
        value = change_set.get(key)
        if isinstance(value, list): values.extend(value)
    result: set[str] = set()
    for value in values:
        raw = value.get("path", value.get("file", "")) if isinstance(value, Mapping) else value
        try:
            result.add(normalize_relative_path(str(raw)))
        except ValueError:
            continue
    return result


def _finding(code: str, severity: str, subject: str, evidence: list[str], remediation: str) -> dict[str, object]:
    return {"code": code, "severity": severity, "subject": subject, "evidence": sorted(evidence), "remediation": remediation}


def reconcile_change_set(
    delta: Mapping[str, list[dict[str, object]]],
    before_snapshot: Mapping[str, object],
    after_snapshot: Mapping[str, object],
    before_trace: Mapping[str, object],
    after_trace: Mapping[str, object],
    impact_report: Mapping[str, object],
    change_set: Mapping[str, object],
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    unknown_reasons: list[str] = []
    comparable = (
        before_snapshot.get("schemaVersion") == after_snapshot.get("schemaVersion")
        and before_snapshot.get("schemaVersion") in SNAPSHOT_SCHEMA_VERSIONS
        and before_snapshot.get("repositoryId") == after_snapshot.get("repositoryId")
    )
    before_provider = before_snapshot.get("providerState", {}) if isinstance(before_snapshot.get("providerState"), Mapping) else {}
    after_provider = after_snapshot.get("providerState", {}) if isinstance(after_snapshot.get("providerState"), Mapping) else {}
    for key in ("version", "codecSchemaSha256", "configHash", "identityVerified", "identity"):
        if key in before_provider or key in after_provider:
            comparable = comparable and before_provider.get(key) == after_provider.get(key)
    after_freshness = after_snapshot.get("freshness", {}) if isinstance(after_snapshot.get("freshness"), Mapping) else {}
    if not comparable:
        unknown_reasons.append("RECONCILE_BASELINE_INCOMPARABLE")
    if after_freshness.get("headMatches", True) is False or after_freshness.get("sourceChangedDuringAnalysis", False) is True:
        unknown_reasons.append("SOURCE_CHANGED_DURING_RECONCILE")
    if impact_report.get("verdict") == "UNKNOWN" or impact_report.get("manifestHash") != before_snapshot.get("manifestHash"):
        unknown_reasons.append("IMPACT_EVIDENCE_INVALID")

    declared = _declared_files(change_set)
    actual = {str(row.get("relativePath")) for row in delta.get("fileChanges", []) if row.get("relativePath")}
    undeclared_files = sorted(actual - declared); declared_not_changed = sorted(declared - actual)
    for item in undeclared_files:
        findings.append(_finding("UNDECLARED_FILE_CHANGE", "BLOCK", item, [item], "Add the file to the reviewed changeSet or revert it."))
    for item in declared_not_changed:
        findings.append(_finding("DECLARED_FILE_NOT_CHANGED", "BLOCK", item, [item], "Correct the changeSet to match the canonical diff."))

    impact_symbols: set[str] = set()
    seed = impact_report.get("seedResolution", {}) if isinstance(impact_report.get("seedResolution"), Mapping) else {}
    affected = impact_report.get("affected", {}) if isinstance(impact_report.get("affected"), Mapping) else {}
    for row in list(seed.get("symbols", [])) + list(affected.get("symbols", [])):
        if isinstance(row, Mapping) and row.get("symbolId"): impact_symbols.add(str(row["symbolId"]))
    before_symbols = {_symbol_stable(row): row for row in before_snapshot.get("symbols", []) if isinstance(row, Mapping)} if isinstance(before_snapshot.get("symbols"), list) else {}
    after_symbols = {_symbol_stable(row): row for row in after_snapshot.get("symbols", []) if isinstance(row, Mapping)} if isinstance(after_snapshot.get("symbols"), list) else {}
    allowed_stable = {stable for stable, row in {**before_symbols, **after_symbols}.items() if str(row.get("symbolId")) in impact_symbols or str(row.get("relativePath")) in declared}
    undeclared_symbols = sorted(str(row.get("stableId")) for row in delta.get("symbolChanges", []) if str(row.get("stableId")) not in allowed_stable and str(row.get("relativePath", "")) not in declared)
    for item in undeclared_symbols:
        findings.append(_finding("UNDECLARED_SYMBOL_CHANGE", "BLOCK", item, [item], "Re-run impact analysis with the correct seed or revert the symbol change."))

    before_ids = {str(row.get("symbolId")): _symbol_stable(row) for row in before_snapshot.get("symbols", []) if isinstance(row, Mapping)} if isinstance(before_snapshot.get("symbols"), list) else {}
    after_ids = {str(row.get("symbolId")): _symbol_stable(row) for row in after_snapshot.get("symbols", []) if isinstance(row, Mapping)} if isinstance(after_snapshot.get("symbols"), list) else {}
    endpoint_violations: list[str] = []
    for change in delta.get("relationshipChanges", []):
        stable = str(change.get("stableId")); relation = next((row for row in list(before_snapshot.get("relationships", [])) + list(after_snapshot.get("relationships", [])) if isinstance(row, Mapping) and _relation_stable(row) == stable), None)
        if relation is None: continue
        endpoint_stable = {before_ids.get(str(relation.get("sourceSymbolId"))), before_ids.get(str(relation.get("targetSymbolId"))), after_ids.get(str(relation.get("sourceSymbolId"))), after_ids.get(str(relation.get("targetSymbolId")))} - {None}
        if not endpoint_stable.issubset(allowed_stable): endpoint_violations.append(stable)
    for item in sorted(endpoint_violations):
        findings.append(_finding("RELATION_ENDPOINT_OUT_OF_SCOPE", "BLOCK", item, [item], "Include both endpoints in the reviewed impact scope."))

    before_exact = {_trace_stable(row): row for row in before_trace.get("links", []) if isinstance(row, Mapping) and row.get("status") == "exact"} if isinstance(before_trace.get("links"), list) else {}
    after_exact = {_trace_stable(row): row for row in after_trace.get("links", []) if isinstance(row, Mapping) and row.get("status") == "exact"} if isinstance(after_trace.get("links"), list) else {}
    trace_regressions = sorted(set(before_exact) - set(after_exact))
    for item in trace_regressions:
        findings.append(_finding("TRACE_COVERAGE_REGRESSION", "BLOCK", item, [item], "Restore the exact trace link or update the reviewed requirements baseline."))
    before_cov = before_snapshot.get("coverage", {}) if isinstance(before_snapshot.get("coverage"), Mapping) else {}
    after_cov = after_snapshot.get("coverage", {}) if isinstance(after_snapshot.get("coverage"), Mapping) else {}
    coverage_regressions: list[str] = []
    if before_cov.get("complete") is True and after_cov.get("complete") is not True: coverage_regressions.append("complete:true->false")
    if len(after_cov.get("gapFiles", [])) > len(before_cov.get("gapFiles", [])): coverage_regressions.append("gapFiles increased")
    for item in coverage_regressions:
        findings.append(_finding("TRACE_COVERAGE_REGRESSION", "BLOCK", item, [item], "Restore index coverage before reconciliation."))

    if unknown_reasons:
        verdict = "UNKNOWN"
        for item in sorted(set(unknown_reasons)):
            findings.append(_finding(item, "UNKNOWN", item, [item], "Rebuild fresh comparable artifacts and rerun reconciliation."))
    else:
        verdict = "BLOCK" if findings else "PASS"
    return {
        "declaredCodeFiles": sorted(declared), "actualCodeFiles": sorted(actual), "undeclaredFileChanges": undeclared_files,
        "declaredFilesNotChanged": declared_not_changed, "allowedSymbolIds": sorted(impact_symbols), "undeclaredSymbolChanges": undeclared_symbols,
        "relationEndpointViolations": sorted(endpoint_violations), "traceRegressions": trace_regressions, "coverageRegressions": coverage_regressions,
        "findings": sorted(findings, key=lambda row: (str(row["severity"]), str(row["code"]), str(row["subject"]))), "verdict": verdict,
    }


def build_index_diff(before_snapshot: Mapping[str, object], after_snapshot: Mapping[str, object], before_trace: Mapping[str, object], after_trace: Mapping[str, object], impact_report: Mapping[str, object], change_set: Mapping[str, object]) -> dict[str, object]:
    # @trace FR-006 AC-006 AC-015
    delta = diff_snapshots(before_snapshot, after_snapshot, before_trace, after_trace)
    reconciliation = reconcile_change_set(delta, before_snapshot, after_snapshot, before_trace, after_trace, impact_report, change_set)
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION, "repositoryId": after_snapshot.get("repositoryId"),
        "beforeManifest": {"contentHash": before_snapshot.get("contentHash"), "manifestHash": before_snapshot.get("manifestHash")},
        "afterManifest": {"contentHash": after_snapshot.get("contentHash"), "manifestHash": after_snapshot.get("manifestHash")},
        "impactReport": {"contentHash": impact_report.get("contentHash"), "manifestHash": impact_report.get("manifestHash")},
        "changeSetHash": content_hash(change_set, excluded_keys=()), **delta, "reconciliation": reconciliation,
        "gateVerdict": reconciliation["verdict"], "unknownReasons": sorted({str(row["code"]) for row in reconciliation["findings"] if row["severity"] == "UNKNOWN"}),
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    result["contentHash"] = content_hash(result); result["diffId"] = "CDI-" + str(result["contentHash"]).removeprefix("sha256:")[:24]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-snapshot", required=True); parser.add_argument("--after-snapshot", required=True)
    parser.add_argument("--before-trace", required=True); parser.add_argument("--after-trace", required=True)
    parser.add_argument("--impact-report", required=True); parser.add_argument("--change-set", required=True)
    parser.add_argument("--artifact-root", required=True, help="Trusted existing root for derived artifacts")
    parser.add_argument("--output", required=True, help="Artifact-root-relative output path")
    parser.add_argument("--json", action="store_true"); args = parser.parse_args(argv)
    try:
        artifact_root_argument = Path(args.artifact_root)
        if artifact_root_argument.is_symlink():
            raise ValueError("symlinked artifact root is forbidden")
        artifact_root = artifact_root_argument.resolve(strict=True)
        if not artifact_root.is_dir():
            raise ValueError("artifact root must be an existing directory")
        output = artifact_root / normalize_relative_path(args.output)
        result = build_index_diff(load_json_object(Path(args.before_snapshot)), load_json_object(Path(args.after_snapshot)), load_json_object(Path(args.before_trace)), load_json_object(Path(args.after_trace)), load_json_object(Path(args.impact_report)), load_json_object(Path(args.change_set)))
        atomic_write_json(output, result, allowed_root=artifact_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"gateVerdict": "UNKNOWN", "unknownReasons": [type(exc).__name__]}, ensure_ascii=False)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["gateVerdict"] == "PASS" else (2 if result["gateVerdict"] == "UNKNOWN" else 1)


if __name__ == "__main__": sys.exit(main())
