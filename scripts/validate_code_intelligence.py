"""Aggregate deterministic C-CODE-01..07 evidence for one delivery phase."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Mapping

try:
    from .bootstrap_code_intelligence import validate_bootstrap_bundle, validate_bootstrap_inventory
    from .build_code_index import _inventory, index_config_fingerprint
    from .code_gate_mode import explain_code_gate_mode
    from .code_intelligence_models import content_hash, file_hash, load_json_object, normalize_relative_path
except ImportError:
    from bootstrap_code_intelligence import validate_bootstrap_bundle, validate_bootstrap_inventory
    from build_code_index import _inventory, index_config_fingerprint
    from code_gate_mode import explain_code_gate_mode
    from code_intelligence_models import content_hash, file_hash, load_json_object, normalize_relative_path


CODE_EXTENSIONS = frozenset({".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".cs", ".cpp", ".c", ".h", ".kt", ".kts", ".swift", ".rb", ".php"})
PHASE_GATES = {
    "pre-change": ("C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-05"),
    "post-change": ("C-CODE-06",),
    "delivery": tuple(f"C-CODE-0{index}" for index in range(1, 8)),
}


def _paths(value: object, parent_key: str = "") -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in {"changeSet", "aggregateChangeSet", "changedFiles", "codeFiles", "declaredCodeFiles"}:
                yield from _paths(child, str(key))
            elif parent_key in {"changeSet", "aggregateChangeSet"}:
                yield from _paths(child, parent_key)
    elif isinstance(value, list):
        for child in value:
            yield from _paths(child, parent_key)
    elif isinstance(value, str) and parent_key:
        yield value


def has_code_change(ledger: Mapping[str, object]) -> bool:
    code = ledger.get("codeIntelligence")
    if isinstance(code, Mapping) and code.get("applicability") == "applicable":
        return True
    for raw in _paths(ledger):
        candidate = raw.replace("\\", "/").split(":", 1)[0]
        if Path(candidate).suffix.lower() in CODE_EXTENSIONS:
            return True
    return False


def _result(gate_id: str, verdict: str, code: str, evidence: list[str], remediation: str, **extra: object) -> dict[str, object]:
    return {"gateId": gate_id, "verdict": verdict, "code": code, "evidence": sorted(evidence), "remediation": remediation, **extra}


def _explicit(code: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = code.get("gateResults", [])
    return {
        str(row["gateId"]): row
        for row in rows if isinstance(rows, list) and isinstance(row, Mapping) and str(row.get("gateId", "")) in PHASE_GATES["delivery"]
    }


def _artifact_check(project_root: Path, reference: object) -> tuple[bool, str]:
    if not isinstance(reference, Mapping):
        return False, "artifact reference missing"
    try:
        relative = normalize_relative_path(str(reference.get("path", "")))
        unresolved = project_root / relative
        if unresolved.is_symlink():
            return False, "symlinked artifact is forbidden"
        path = unresolved.resolve(strict=False)
        path.relative_to(project_root.resolve(strict=True))
    except ValueError:
        return False, "artifact path invalid or outside project root"
    if path.is_symlink() or not path.is_file():
        return False, f"artifact unavailable: {relative}"
    actual = file_hash(path)
    return actual == reference.get("sha256"), relative if actual == reference.get("sha256") else f"artifact hash mismatch: {relative}"


def _load_ref(project_root: Path, reference: object) -> dict[str, object] | None:
    if not isinstance(reference, Mapping):
        return None
    try:
        relative = normalize_relative_path(str(reference.get("path", "")))
        unresolved = project_root / relative
        if unresolved.is_symlink():
            return None
        path = unresolved.resolve(strict=True)
        path.relative_to(project_root.resolve(strict=True))
        return load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _manifest_has_complete_coverage(manifest: Mapping[str, object] | None) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    if manifest.get("schemaVersion") != "1.1.0":
        return False
    coverage = manifest.get("coverage")
    files = manifest.get("files")
    relationships = manifest.get("relationships")
    if not isinstance(coverage, Mapping) or coverage.get("complete") is not True or not isinstance(relationships, Mapping):
        return False
    if coverage.get("missingCaptures") != [] or not isinstance(files, Mapping):
        return False
    if coverage.get("relationshipClassificationComplete") is not True or coverage.get("unresolvedInternalRelationshipCount") != 0:
        return False
    coverage_hash = coverage.get("relationshipCoverageHash")
    if not isinstance(coverage_hash, str) or relationships.get("coverageHash") != coverage_hash:
        return False
    if relationships.get("unresolvedInternal") != 0 or relationships.get("legacyUnclassified") != 0:
        return False
    boundary_count = relationships.get("auditedBoundary")
    if not isinstance(boundary_count, int) or isinstance(boundary_count, bool) or coverage.get("auditedBoundaryRelationshipCount") != boundary_count:
        return False
    eligible = files.get("eligible")
    indexed = files.get("indexed")
    return isinstance(eligible, int) and not isinstance(eligible, bool) and indexed == eligible and files.get("gapFiles") == []


def _relationship_gate_code(manifest: Mapping[str, object] | None) -> str:
    if not isinstance(manifest, Mapping) or manifest.get("schemaVersion") != "1.1.0":
        return "INDEX_RELATIONSHIP_CLASSIFICATION_REQUIRED"
    coverage = manifest.get("coverage")
    relationships = manifest.get("relationships")
    if not isinstance(coverage, Mapping) or not isinstance(relationships, Mapping):
        return "INDEX_RELATIONSHIP_ACCOUNTING_MISMATCH"
    if relationships.get("unresolvedInternal", 0) or coverage.get("unresolvedInternalRelationshipCount", 0):
        return "INDEX_INTERNAL_RELATIONSHIP_GAP"
    if relationships.get("legacyUnclassified", 0):
        return "INDEX_RELATIONSHIP_CLASSIFICATION_REQUIRED"
    if coverage.get("relationshipClassificationComplete") is not True or coverage.get("relationshipCoverageHash") != relationships.get("coverageHash"):
        return "INDEX_RELATIONSHIP_ACCOUNTING_MISMATCH"
    if coverage.get("auditedBoundaryRelationshipCount") != relationships.get("auditedBoundary"):
        return "INDEX_BOUNDARY_CLASSIFICATION_INCOMPLETE"
    return "INDEX_COVERAGE_INCOMPLETE"


def _process(project_root: Path, supplied: Mapping[str, object] | None) -> Mapping[str, object]:
    if supplied is not None:
        return supplied
    candidate = project_root / "assets" / "config" / "skill-process.json"
    if not candidate.is_file():
        candidate = Path(__file__).resolve().parent.parent / "assets" / "config" / "skill-process.json"
    return load_json_object(candidate)


def _bundle_from_ledger(project_root: Path, code: Mapping[str, object], inventory: Mapping[str, object] | None) -> dict[str, object] | None:
    baseline = _load_ref(project_root, code.get("baselineStatement"))
    activation = code.get("activation")
    marker = code.get("consumedMarker")
    if inventory is None or not isinstance(baseline, Mapping) or not isinstance(activation, Mapping) or not isinstance(marker, Mapping):
        return None
    return {"inventory": inventory, "baselineStatement": baseline, "activation": activation, "consumedMarker": marker}


def _index_config(project_root: Path, supplied: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if supplied is not None:
        return supplied
    candidate = project_root / "assets" / "config" / "code-intelligence.json"
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return load_json_object(candidate)


def _current_freshness(
    project_root: Path,
    manifest: Mapping[str, object] | None,
    config: Mapping[str, object] | None,
) -> tuple[bool, str, list[str]]:
    if not isinstance(manifest, Mapping):
        return False, "INDEX_ARTIFACT_UNAVAILABLE", ["manifest"]
    if not isinstance(config, Mapping):
        return False, "U-05", ["assets/config/code-intelligence.json"]
    try:
        files, current_digest, _extensions, _repository_files = _inventory(project_root, config)
        current_config_hash = content_hash(index_config_fingerprint(config), excluded_keys=())
    except (OSError, TypeError, ValueError):
        return False, "U-04", ["workspace inventory"]
    if manifest.get("configHash") != current_config_hash:
        return False, "U-05", [str(manifest.get("configHash", "")), current_config_hash]
    if manifest.get("sourceDigest") != current_digest:
        return False, "U-04", [str(manifest.get("sourceDigest", "")), current_digest]
    manifest_files = manifest.get("files") if isinstance(manifest.get("files"), Mapping) else {}
    if manifest_files.get("eligible") != len(files):
        return False, "U-04", [f"manifestEligible={manifest_files.get('eligible')}", f"currentEligible={len(files)}"]
    return True, "OK", [current_digest, current_config_hash]


def validate_phase(
    phase: str,
    project_root: Path,
    ledger: Mapping[str, object],
    *,
    bootstrap_inventory: Mapping[str, object] | None = None,
    bootstrap_bundle: Mapping[str, object] | None = None,
    process: Mapping[str, object] | None = None,
    code_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    # @trace FR-007 AC-007 AC-014 AC-015 AC-016
    if phase not in PHASE_GATES:
        raise ValueError(f"unsupported phase: {phase}")
    if not has_code_change(ledger):
        results = [_result(gate, "NOT_APPLICABLE", "NO_CODE_CHANGE", [], "No action required for an objectively non-code delivery.") for gate in PHASE_GATES[phase]]
        return {"phase": phase, "status": "pass", "applicability": "not-applicable", "mode": "normal", "gateResults": results, "blockingReasons": [], "unknownReasons": []}
    code = ledger.get("codeIntelligence")
    if not isinstance(code, Mapping) or code.get("applicability") != "applicable":
        results = [_result(gate, "BLOCK", "LEDGER_CODE_INTELLIGENCE_REQUIRED", [], "Generate and append code-intelligence evidence for the current code change.") for gate in PHASE_GATES[phase]]
        return {"phase": phase, "status": "fail", "applicability": "applicable", "mode": "blocked", "gateResults": results, "blockingReasons": ["LEDGER_CODE_INTELLIGENCE_REQUIRED"], "unknownReasons": []}
    if bootstrap_inventory is None:
        bootstrap_inventory = _load_ref(project_root, code.get("bootstrapInventory"))
    decision = explain_code_gate_mode(ledger, _process(project_root, process), bootstrap_inventory)
    mode = str(decision["mode"])
    if bootstrap_bundle is None and mode == "bootstrap":
        bootstrap_bundle = _bundle_from_ledger(project_root, code, bootstrap_inventory)
    resolved_config = _index_config(project_root, code_config)
    explicit = _explicit(code)
    provider = code.get("provider") if isinstance(code.get("provider"), Mapping) else {}
    provider_ok = provider.get("name") == "code-graph-rag" and provider.get("version") == "0.0.779" and provider.get("manifestVersion") == 1 and provider.get("codecSchemaSha256") == "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"
    results: list[dict[str, object]] = []
    core: dict[str, dict[str, object]] = {}

    for gate in PHASE_GATES[phase]:
        recorded = explicit.get(gate)
        verdict = str(recorded.get("verdict")) if recorded else ""
        if recorded and verdict in {"BLOCK", "UNKNOWN"}:
            row = _result(gate, verdict, "RECORDED_GATE_FAILURE", [str(recorded.get("commandRef", ""))], "Repair the recorded failure and rerun the deterministic gate.")
        elif mode == "blocked" and gate in {"C-CODE-05", "C-CODE-06", "C-CODE-07"}:
            row = _result(gate, "BLOCK", str(decision["code"]), [str(reason) for reason in decision.get("reasons", [])], "Repair version, inventory, token/history or delivery binding.")
        elif gate == "C-CODE-01":
            key = "afterManifest" if mode == "bootstrap" else "beforeManifest"
            manifest = _load_ref(project_root, code.get(key))
            freshness_required = mode == "bootstrap" or phase == "pre-change"
            fresh, freshness_code, freshness_evidence = _current_freshness(project_root, manifest, resolved_config) if freshness_required else (True, "OK", [])
            ok = provider_ok and isinstance(code.get(key), Mapping) and verdict == "PASS" and fresh
            failure_code = freshness_code if not fresh else "PROVIDER_CONTRACT_MISMATCH"
            row = _result(gate, "PASS" if ok else "BLOCK", "OK" if ok else failure_code, freshness_evidence, "Rebuild the index from the current workspace and frozen portable config before continuing.")
        elif gate == "C-CODE-02":
            manifest_key = "afterManifest" if mode == "bootstrap" else "beforeManifest"
            manifest = _load_ref(project_root, code.get(manifest_key))
            ok = verdict == "PASS" and _manifest_has_complete_coverage(manifest)
            relationships = manifest.get("relationships") if isinstance(manifest, Mapping) and isinstance(manifest.get("relationships"), Mapping) else {}
            summary = {
                "resolvedInternalCount": relationships.get("resolvedInternal"),
                "auditedBoundaryCount": relationships.get("auditedBoundary"),
                "boundaryByType": relationships.get("boundaryByType", {}),
                "boundaryByClass": relationships.get("boundaryByClass", {}),
                "unresolvedInternalCount": relationships.get("unresolvedInternal"),
                "legacyUnclassifiedCount": relationships.get("legacyUnclassified"),
            }
            row = _result(gate, "PASS" if ok else "BLOCK", "OK" if ok else _relationship_gate_code(manifest), [], "Verify canonical hash, eligible-file coverage and the exclusive relationship partition.", relationshipSummary=summary)
        elif gate == "C-CODE-03":
            key = "afterTraceBridge" if mode == "bootstrap" else "beforeTraceBridge"
            ok = isinstance(code.get(key), Mapping) and verdict == "PASS"
            row = _result(gate, "PASS" if ok else "BLOCK", "OK" if ok else "TRACE_SCHEMA_INVALID", [], "Materialize exact links with no rejected declaration.")
        elif gate == "C-CODE-04":
            ok = verdict == "PASS"
            row = _result(gate, "PASS" if ok else "BLOCK", "OK" if ok else "MISSING_TEST_LINK", [], "Provide Must/P0 implementation and test links.")
        elif gate == "C-CODE-05" and mode == "bootstrap":
            ok = validate_bootstrap_inventory(bootstrap_inventory or {}).get("status") == "pass"
            row = _result(gate, "NOT_APPLICABLE" if ok else "BLOCK", "BOOTSTRAP_NOT_APPLICABLE" if ok else "BOOTSTRAP_EVIDENCE_INCOMPLETE", [str((bootstrap_inventory or {}).get("inventoryHash", ""))], "Use the frozen one-time inventory; do not fabricate a before graph.")
        elif gate == "C-CODE-05":
            reports = code.get("preChangeImpactReports", []) if isinstance(code.get("preChangeImpactReports"), list) else []
            unknown = any(isinstance(item, Mapping) and item.get("verdict") == "UNKNOWN" for item in reports)
            ok = bool(reports) and not unknown and all(not isinstance(item, Mapping) or item.get("verdict") in {"FOUND", "NO_IMPACT"} for item in reports)
            row = _result(gate, "UNKNOWN" if unknown else ("PASS" if ok and verdict == "PASS" else "BLOCK"), "IMPACT_TRUNCATED" if unknown else ("OK" if ok and verdict == "PASS" else "IMPACT_EVIDENCE_REQUIRED"), [], "Generate a fresh non-UNKNOWN impact report.")
        elif gate == "C-CODE-06" and mode == "bootstrap":
            bundle_result = validate_bootstrap_bundle(bootstrap_bundle or {})
            after_manifest = _load_ref(project_root, code.get("afterManifest"))
            fresh, freshness_code, freshness_evidence = _current_freshness(project_root, after_manifest, resolved_config)
            core_pass = all(
                (core.get(f"C-CODE-0{number}") or explicit.get(f"C-CODE-0{number}") or {}).get("verdict") == "PASS"
                for number in range(1, 5)
            )
            ok = bundle_result["status"] == "pass" and core_pass and fresh
            code_value = "BOOTSTRAP_BASELINE_CREATED" if ok else (freshness_code if not fresh else str((bundle_result.get("codes") or ["BOOTSTRAP_EVIDENCE_INCOMPLETE"])[0]))
            row = _result(gate, "PASS" if ok else "BLOCK", code_value, freshness_evidence, "Provide a fresh after manifest, trace, inventory and baseline.", comparisonMode="baseline-creation", diffClaimed=False)
        elif gate == "C-CODE-06":
            after_manifest = _load_ref(project_root, code.get("afterManifest"))
            fresh, freshness_code, freshness_evidence = _current_freshness(project_root, after_manifest, resolved_config)
            ok = all(isinstance(code.get(key), Mapping) for key in ("afterManifest", "afterTraceBridge", "indexDiff")) and verdict == "PASS" and fresh
            row = _result(gate, "PASS" if ok else "BLOCK", "OK" if ok else (freshness_code if not fresh else "RECONCILE_BASELINE_INCOMPARABLE"), freshness_evidence, "Reindex from the current workspace, rebuild trace links and reconcile the changeSet.")
        else:
            if mode == "bootstrap":
                bundle_result = validate_bootstrap_bundle(bootstrap_bundle or {})
                refs = [code.get(key) for key in ("afterManifest", "afterTraceBridge", "bootstrapInventory", "baselineStatement")]
                artifact_results = [_artifact_check(project_root, ref) for ref in refs]
                ok = bundle_result["status"] == "pass" and all(item[0] for item in artifact_results)
                code_value = "OK" if ok else str((bundle_result.get("codes") or ["LEDGER_ARTIFACT_HASH_MISMATCH"])[0])
            else:
                refs = [code.get(key) for key in ("beforeManifest", "beforeTraceBridge", "afterManifest", "afterTraceBridge", "indexDiff")]
                refs.extend(code.get("preChangeImpactReports", []) if isinstance(code.get("preChangeImpactReports"), list) else [])
                artifact_results = [_artifact_check(project_root, ref) for ref in refs]
                ok = bool(refs) and all(item[0] for item in artifact_results) and verdict == "PASS"
                code_value = "OK" if ok else "LEDGER_ARTIFACT_HASH_MISMATCH"
            row = _result(gate, "PASS" if ok else "BLOCK", code_value, [item[1] for item in artifact_results], "Repair artifact references and append C-CODE-07 PASS evidence.")
        results.append(row)
        if gate in {"C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-04"}:
            core[gate] = row

    blocks = [str(row["code"]) for row in results if row["verdict"] == "BLOCK"]
    unknowns = [str(row["code"]) for row in results if row["verdict"] == "UNKNOWN"]
    status = "unknown" if unknowns and not blocks else ("fail" if blocks else "pass")
    return {"phase": phase, "status": status, "applicability": "applicable", "mode": mode, "gateResults": results, "blockingReasons": blocks, "unknownReasons": unknowns}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=tuple(PHASE_GATES))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--bootstrap-inventory")
    parser.add_argument("--config", help="Portable code-intelligence config; defaults to assets/config/code-intelligence.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        inventory = load_json_object(Path(args.bootstrap_inventory)) if args.bootstrap_inventory else None
        config = load_json_object(Path(args.config)) if args.config else None
        result = validate_phase(args.phase, Path(args.project_root).resolve(strict=True), load_json_object(Path(args.ledger)), bootstrap_inventory=inventory, code_config=config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"phase": args.phase, "status": "fail", "blockingReasons": ["LEDGER_SCHEMA_INVALID"], "diagnostics": [type(exc).__name__]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["status"] == "pass" else (2 if result["status"] == "unknown" else 1)


if __name__ == "__main__":
    sys.exit(main())
