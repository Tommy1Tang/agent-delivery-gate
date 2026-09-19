#!/usr/bin/env python3
"""Build and validate the one-time 1.0.0 -> 1.1.0 code-intelligence bootstrap.

The artifact graph is a DAG.  Derived identifiers and the reciprocal
BaselineStatement.inventoryHash field are explicitly excluded from their
own hashes; every exclusion is carried in ``hashExcludedFields`` and checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from .code_intelligence_models import HASH_PREFIX, atomic_write_json, bytes_hash, canonical_json, file_hash, load_json_object, normalize_relative_path
except ImportError:
    from code_intelligence_models import HASH_PREFIX, atomic_write_json, bytes_hash, canonical_json, file_hash, load_json_object, normalize_relative_path


SCHEMA_VERSION = "1.0.0"
STARTING_VERSION = "1.0.0"
ACTIVATED_VERSION = "1.1.0"
BOOTSTRAP_REASON = "initial-code-intelligence-baseline"
ABSENCE_REASON = "code-intelligence-before-baseline-not-available-prior-to-activation"
BASELINE_DECLARATION = "This evidence creates the first after baseline and does not claim a pre-change snapshot or before/after diff."
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
CATEGORIES = frozenset({"implementation", "schema", "governance", "test", "delivery-document", "generated-evidence"})
OPERATIONS = frozenset({"created", "modified"})
INVENTORY_HASH_EXCLUSIONS = ("createdAt", "inventoryHash", "inventoryId", "baselineStatement.sha256")
BASELINE_HASH_EXCLUSIONS = ("createdAt", "contentHash", "inventoryHash", "statementId")
ACTIVATION_HASH_EXCLUSIONS = ("recordHash", "activationRecordId")
MARKER_HASH_EXCLUSIONS = ("markerHash",)


@dataclass(frozen=True, slots=True, order=True)
class BootstrapChangeItem:
    path: str
    operation: str
    category: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_relative_path(self.path))
        if self.operation not in OPERATIONS:
            raise ValueError("bootstrap operation must be created or modified")
        if self.category not in CATEGORIES:
            raise ValueError("bootstrap change category is not controlled")
        if not is_allowed_bootstrap_path(self.path):
            raise ValueError(f"bootstrap path is outside the frozen capability scope: {self.path}")


@dataclass(frozen=True, slots=True)
class BaselineStatement:
    schemaVersion: str
    statementId: str
    statementType: str
    repositoryId: str
    deliveryId: str
    startingProcessVersion: str
    activatedVersion: str
    absenceReason: str
    afterManifestHash: str
    afterTraceHash: str
    inventoryHash: str
    gateEvidenceHashes: tuple[str, ...]
    comparisonMode: str
    diffClaimed: bool
    declaration: str
    createdAt: str
    hashExcludedFields: tuple[str, ...]
    contentHash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BaselineStatement":
        return cls(**{**value, "gateEvidenceHashes": tuple(value.get("gateEvidenceHashes", ())), "hashExcludedFields": tuple(value.get("hashExcludedFields", ()))})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BootstrapInventory:
    schemaVersion: str
    inventoryId: str
    repositoryId: str
    deliveryId: str
    startingProcessVersion: str
    activatedVersion: str
    allowedChangeSet: Mapping[str, object]
    actualChangeSet: Mapping[str, object]
    activationToken: Mapping[str, object]
    afterManifest: Mapping[str, object]
    afterTraceBridge: Mapping[str, object]
    baselineStatement: Mapping[str, object]
    postGateEvidence: tuple[Mapping[str, object], ...]
    createdAt: str
    hashExcludedFields: tuple[str, ...]
    inventoryHash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BootstrapInventory":
        return cls(**{**value, "postGateEvidence": tuple(value.get("postGateEvidence", ())), "hashExcludedFields": tuple(value.get("hashExcludedFields", ()))})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ActivationRecord:
    schemaVersion: str
    activationRecordId: str
    tokenId: str
    repositoryId: str
    deliveryId: str
    startingProcessVersion: str
    activatedVersion: str
    activatedAt: str
    bootstrapReason: str
    inventoryHash: str
    afterManifestHash: str
    afterTraceHash: str
    baselineStatementHash: str
    consumed: bool
    hashExcludedFields: tuple[str, ...]
    recordHash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ActivationRecord":
        return cls(**{**value, "hashExcludedFields": tuple(value.get("hashExcludedFields", ()))})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ConsumedMarker:
    schemaVersion: str
    tokenId: str
    repositoryId: str
    deliveryId: str
    activationRecordHash: str
    consumed: bool
    consumedAt: str
    hashExcludedFields: tuple[str, ...]
    markerHash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ConsumedMarker":
        return cls(**{**value, "hashExcludedFields": tuple(value.get("hashExcludedFields", ()))})  # type: ignore[arg-type]


def _require_identifier(value: object, field: str) -> str:
    text = str(value)
    if not 1 <= len(text) <= 128 or any(character in text for character in "\x00\r\n"):
        raise ValueError(f"{field} must be a 1..128 character identifier")
    return text


def _require_hash(value: object, field: str) -> str:
    text = str(value)
    if not HASH_PATTERN.fullmatch(text):
        raise ValueError(f"{field} must be a sha256 hash")
    return text


def _require_timestamp(value: object, field: str) -> str:
    text = str(value)
    if not TIMESTAMP_PATTERN.fullmatch(text):
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp")
    return text


def _semver(value: str) -> tuple[int, int, int]:
    matched = SEMVER_PATTERN.fullmatch(value)
    if not matched:
        raise ValueError(f"invalid strict SemVer: {value}")
    return tuple(int(part) for part in matched.groups())  # type: ignore[return-value]


def compare_process_versions(first: str, second: str) -> int:
    left, right = _semver(first), _semver(second)
    return (left > right) - (left < right)


def activation_token_id(repository_id: str, starting_version: str, activated_version: str) -> str:
    _require_identifier(repository_id, "repositoryId")
    _semver(starting_version)
    _semver(activated_version)
    payload = repository_id.encode("utf-8") + b"\0" + starting_version.encode("utf-8") + b"\0" + activated_version.encode("utf-8")
    return HASH_PREFIX + hashlib.sha256(payload).hexdigest()


def is_allowed_bootstrap_path(path: str) -> bool:
    normalized = normalize_relative_path(path)
    if normalized == "tests/__init__.py":
        return True
    if normalized.startswith("tests/code_intelligence/") and normalized.endswith(".py"):
        return True
    if normalized.startswith("tests/golden/") and normalized.endswith(".json"):
        name = PureName(normalized)
        return name.startswith("code-intelligence-") or name == "process-derived-role-skip.json"
    if normalized.startswith("tests/fixtures/code-intelligence/polyglot/"):
        return PureName(normalized) in {"e2e_app.py", "README.md", "requirements.json"}
    if normalized.startswith("schemas/"):
        name = PureName(normalized)
        return (
            name.startswith("code-")
            or name.startswith("bootstrap-")
            or name == "evidence-ledger.schema.json"
            or name in {
                "impact-report.schema.json",
                "index-diff.schema.json",
                "trace-link.schema.json",
            }
        )
    allowed = {
        "assets/config/code-intelligence.json",
        "assets/config/agent-team-config.json",
        "assets/config/skill-process.json", "assets/config/skill-process.yaml",
        "assets/config/skill-ontology.json", "assets/config/skill-ontology.yaml",
        "references/code-intelligence-contract.md", "references/graph-engineering-laws.md",
        "assets/prompts/development-orchestrator.prompt.md", "assets/prompts/backend-engineer.prompt.md",
        "assets/prompts/frontend-engineer.prompt.md", "assets/prompts/quality-gate-engineer.prompt.md",
        "assets/prompts/supervisor-auditor.prompt.md",
    }
    if normalized in allowed:
        return True
    if normalized.startswith("scripts/") and normalized.endswith(".py"):
        return PureName(normalized) in {
            "code_intelligence_models.py", "code_graph_provider.py", "build_code_index.py",
            "materialize_trace_links.py", "validate_code_traceability.py", "query_code_graph.py",
            "analyze_code_impact.py", "reconcile_code_changes.py", "validate_code_intelligence.py",
            "validate_delivery.py", "write_evidence_ledger.py", "next_step.py",
            "bootstrap_code_intelligence.py", "code_gate_mode.py", "orchestrate.py",
            "code_intelligence_e2e.py",
        }
    return False


def PureName(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _root_hash(value: Mapping[str, object], excluded: Iterable[str]) -> str:
    payload = {key: item for key, item in value.items() if key not in set(excluded) and key != "hashExcludedFields"}
    return bytes_hash(canonical_json(payload))


def _baseline_hash(value: Mapping[str, object]) -> str:
    return _root_hash(value, BASELINE_HASH_EXCLUSIONS)


def _inventory_hash(value: Mapping[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key not in {"createdAt", "inventoryHash", "inventoryId", "hashExcludedFields"}}
    baseline_ref = payload.get("baselineStatement")
    if isinstance(baseline_ref, Mapping):
        payload["baselineStatement"] = {key: item for key, item in baseline_ref.items() if key != "sha256"}
    return bytes_hash(canonical_json(payload))


def _pretty_json_hash(value: Mapping[str, object]) -> str:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    return bytes_hash(payload)


def _normalize_changes(values: object) -> list[dict[str, str]]:
    if not isinstance(values, list) or not values:
        raise ValueError("bootstrap change set files must be a non-empty array")
    items: list[BootstrapChangeItem] = []
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != {"path", "operation", "category"}:
            raise ValueError("each bootstrap change item must contain only path, operation and category")
        items.append(BootstrapChangeItem(str(raw["path"]), str(raw["operation"]), str(raw["category"])))
    if len({item.path for item in items}) != len(items):
        raise ValueError("bootstrap change paths must be unique")
    return [asdict(item) for item in sorted(items)]


def change_set_hash(files: object) -> str:
    return bytes_hash(canonical_json(_normalize_changes(files)))


def _artifact_ref(path: Path, root: Path) -> dict[str, str]:
    relative = normalize_relative_path(path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix())
    payload = load_json_object(path)
    claimed_content = payload.get("contentHash")
    content = str(claimed_content) if isinstance(claimed_content, str) and HASH_PATTERN.fullmatch(claimed_content) else file_hash(path)
    return {"path": relative, "sha256": file_hash(path), "contentHash": content}


def build_bootstrap_evidence(
    *, repository_id: str, delivery_id: str, allowed_files: object, actual_files: object,
    after_manifest_path: Path, after_trace_path: Path, post_gate_evidence: object,
    frozen_at: str, created_at: str, activated_at: str, artifact_root: Path,
) -> dict[str, dict[str, object]]:
    repository_id = _require_identifier(repository_id, "repositoryId")
    delivery_id = _require_identifier(delivery_id, "deliveryId")
    frozen_at = _require_timestamp(frozen_at, "frozenAt")
    created_at = _require_timestamp(created_at, "createdAt")
    activated_at = _require_timestamp(activated_at, "activatedAt")
    allowed = _normalize_changes(allowed_files)
    actual = _normalize_changes(actual_files)
    allowed_hash = change_set_hash(allowed)
    actual_hash = change_set_hash(actual)
    if allowed != actual or allowed_hash != actual_hash:
        raise ValueError("BOOTSTRAP_CHANGESET_MISMATCH")
    gates = _validate_post_gates(post_gate_evidence)
    manifest_ref = _artifact_ref(after_manifest_path, artifact_root)
    trace_ref = _artifact_ref(after_trace_path, artifact_root)
    token_id = activation_token_id(repository_id, STARTING_VERSION, ACTIVATED_VERSION)
    freeze_hash = bytes_hash(canonical_json({"repositoryId": repository_id, "deliveryId": delivery_id, "startingProcessVersion": STARTING_VERSION, "activatedVersion": ACTIVATED_VERSION, "files": allowed, "allowedHash": allowed_hash, "frozenAt": frozen_at}))
    gate_hashes = sorted({str(value) for gate in gates for value in gate["artifactHashes"]})
    baseline: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION, "statementId": "", "statementType": "bootstrap-baseline-created",
        "repositoryId": repository_id, "deliveryId": delivery_id, "startingProcessVersion": STARTING_VERSION,
        "activatedVersion": ACTIVATED_VERSION, "absenceReason": ABSENCE_REASON,
        "afterManifestHash": manifest_ref["contentHash"], "afterTraceHash": trace_ref["contentHash"],
        "inventoryHash": HASH_PREFIX + "0" * 64, "gateEvidenceHashes": gate_hashes,
        "comparisonMode": "baseline-creation", "diffClaimed": False, "declaration": BASELINE_DECLARATION,
        "createdAt": created_at, "hashExcludedFields": list(BASELINE_HASH_EXCLUSIONS), "contentHash": "",
    }
    baseline["contentHash"] = _baseline_hash(baseline)
    baseline["statementId"] = "CBS-" + str(baseline["contentHash"])[7:31]
    inventory: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION, "inventoryId": "", "repositoryId": repository_id, "deliveryId": delivery_id,
        "startingProcessVersion": STARTING_VERSION, "activatedVersion": ACTIVATED_VERSION,
        "allowedChangeSet": {"files": allowed, "allowedHash": allowed_hash, "frozenAt": frozen_at, "freezeEvidenceHash": freeze_hash},
        "actualChangeSet": {"files": actual, "actualHash": actual_hash, "capturedAt": created_at},
        "activationToken": {"tokenId": token_id, "state": "unconsumed"},
        "afterManifest": manifest_ref, "afterTraceBridge": trace_ref,
        "baselineStatement": {"path": "bootstrap-baseline-statement.json", "sha256": HASH_PREFIX + "0" * 64, "contentHash": baseline["contentHash"]},
        "postGateEvidence": gates, "createdAt": created_at,
        "hashExcludedFields": list(INVENTORY_HASH_EXCLUSIONS), "inventoryHash": "",
    }
    inventory["inventoryHash"] = _inventory_hash(inventory)
    inventory["inventoryId"] = "CBI-" + str(inventory["inventoryHash"])[7:31]
    baseline["inventoryHash"] = inventory["inventoryHash"]
    inventory["baselineStatement"]["sha256"] = _pretty_json_hash(baseline)  # type: ignore[index]
    activation: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION, "activationRecordId": "", "tokenId": token_id,
        "repositoryId": repository_id, "deliveryId": delivery_id, "startingProcessVersion": STARTING_VERSION,
        "activatedVersion": ACTIVATED_VERSION, "activatedAt": activated_at, "bootstrapReason": BOOTSTRAP_REASON,
        "inventoryHash": inventory["inventoryHash"], "afterManifestHash": manifest_ref["contentHash"],
        "afterTraceHash": trace_ref["contentHash"], "baselineStatementHash": baseline["contentHash"],
        "consumed": True, "hashExcludedFields": list(ACTIVATION_HASH_EXCLUSIONS), "recordHash": "",
    }
    activation["recordHash"] = _root_hash(activation, ACTIVATION_HASH_EXCLUSIONS)
    activation["activationRecordId"] = "CAR-" + str(activation["recordHash"])[7:31]
    marker: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION, "tokenId": token_id, "repositoryId": repository_id,
        "deliveryId": delivery_id, "activationRecordHash": activation["recordHash"], "consumed": True,
        "consumedAt": activated_at, "hashExcludedFields": list(MARKER_HASH_EXCLUSIONS), "markerHash": "",
    }
    marker["markerHash"] = _root_hash(marker, MARKER_HASH_EXCLUSIONS)
    bundle = {"inventory": inventory, "baselineStatement": baseline, "activation": activation, "consumedMarker": marker}
    result = validate_bootstrap_bundle(bundle)
    if result["status"] != "pass":
        raise ValueError(";".join(result["codes"]))
    return bundle


def _validate_post_gates(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("postGateEvidence must be an array")
    gates: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("post gate evidence must contain objects")
        gate_id = str(row.get("gateId", ""))
        hashes = row.get("artifactHashes")
        if gate_id not in {f"C-CODE-0{number}" for number in range(1, 5)} or row.get("verdict") != "PASS" or not isinstance(hashes, list):
            raise ValueError("bootstrap requires PASS evidence for C-CODE-01..04")
        gates.append({"gateId": gate_id, "verdict": "PASS", "code": str(row.get("code", "OK")), "artifactHashes": sorted(_require_hash(item, "artifactHashes") for item in hashes)})
    if {row["gateId"] for row in gates} != {f"C-CODE-0{number}" for number in range(1, 5)} or len(gates) != 4:
        raise ValueError("bootstrap requires exactly one PASS for each C-CODE-01..04")
    return sorted(gates, key=lambda row: str(row["gateId"]))


def validate_bootstrap_inventory(value: Mapping[str, object]) -> dict[str, object]:
    codes: list[str] = []
    try:
        BootstrapInventory.from_mapping(value)
        if value.get("schemaVersion") != SCHEMA_VERSION or value.get("startingProcessVersion") != STARTING_VERSION or value.get("activatedVersion") != ACTIVATED_VERSION:
            codes.append("BOOTSTRAP_VERSION_INVALID")
        elif compare_process_versions(str(value["startingProcessVersion"]), str(value["activatedVersion"])) >= 0:
            codes.append("BOOTSTRAP_VERSION_INVALID")
        repository_id = _require_identifier(value.get("repositoryId"), "repositoryId")
        _require_identifier(value.get("deliveryId"), "deliveryId")
        allowed = value.get("allowedChangeSet")
        actual = value.get("actualChangeSet")
        if not isinstance(allowed, Mapping) or not isinstance(actual, Mapping):
            raise ValueError("change sets missing")
        try:
            allowed_files = _normalize_changes(allowed.get("files"))
            actual_files = _normalize_changes(actual.get("files"))
        except ValueError as exc:
            if "outside" in str(exc):
                codes.append("BOOTSTRAP_SCOPE_VIOLATION")
                raw_allowed = allowed.get("files") if isinstance(allowed.get("files"), list) else []
                raw_actual = actual.get("files") if isinstance(actual.get("files"), list) else []
                allowed_files = [dict(item) for item in raw_allowed if isinstance(item, Mapping)]
                actual_files = [dict(item) for item in raw_actual if isinstance(item, Mapping)]
            else:
                raise
        expected_allowed_hash = bytes_hash(canonical_json(allowed_files))
        expected_actual_hash = bytes_hash(canonical_json(actual_files))
        if allowed_files != actual_files or allowed.get("allowedHash") != expected_allowed_hash or actual.get("actualHash") != expected_actual_hash or expected_allowed_hash != expected_actual_hash:
            codes.append("BOOTSTRAP_CHANGESET_MISMATCH")
        _require_timestamp(allowed.get("frozenAt"), "frozenAt")
        freeze_hash = _require_hash(allowed.get("freezeEvidenceHash"), "freezeEvidenceHash")
        expected_freeze_hash = bytes_hash(canonical_json({
            "repositoryId": repository_id,
            "deliveryId": value.get("deliveryId"),
            "startingProcessVersion": STARTING_VERSION,
            "activatedVersion": ACTIVATED_VERSION,
            "files": allowed_files,
            "allowedHash": expected_allowed_hash,
            "frozenAt": allowed.get("frozenAt"),
        }))
        if freeze_hash != expected_freeze_hash:
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        _require_timestamp(actual.get("capturedAt"), "capturedAt")
        token = value.get("activationToken")
        if not isinstance(token, Mapping) or token.get("state") != "unconsumed" or token.get("tokenId") != activation_token_id(repository_id, STARTING_VERSION, ACTIVATED_VERSION):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if tuple(value.get("hashExcludedFields", ())) != INVENTORY_HASH_EXCLUSIONS:
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        expected_inventory_hash = _inventory_hash(value)
        if value.get("inventoryHash") != expected_inventory_hash or value.get("inventoryId") != "CBI-" + expected_inventory_hash[7:31]:
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        _validate_post_gates(value.get("postGateEvidence"))
        for name in ("afterManifest", "afterTraceBridge", "baselineStatement"):
            ref = value.get(name)
            if not isinstance(ref, Mapping):
                codes.append("BOOTSTRAP_EVIDENCE_INCOMPLETE")
                continue
            _require_hash(ref.get("sha256"), f"{name}.sha256")
            _require_hash(ref.get("contentHash"), f"{name}.contentHash")
            normalize_relative_path(str(ref.get("path", "")))
    except (KeyError, TypeError, ValueError):
        if not codes:
            codes.append("BOOTSTRAP_EVIDENCE_INCOMPLETE")
    return {"status": "fail" if codes else "pass", "codes": sorted(set(codes))}


def validate_bootstrap_bundle(bundle: Mapping[str, object]) -> dict[str, object]:
    codes: list[str] = []
    inventory = bundle.get("inventory")
    baseline = bundle.get("baselineStatement")
    activation = bundle.get("activation")
    marker = bundle.get("consumedMarker")
    if not all(isinstance(item, Mapping) for item in (inventory, baseline, activation, marker)):
        return {"status": "fail", "codes": ["BOOTSTRAP_EVIDENCE_INCOMPLETE"]}
    assert isinstance(inventory, Mapping) and isinstance(baseline, Mapping) and isinstance(activation, Mapping) and isinstance(marker, Mapping)
    codes.extend(validate_bootstrap_inventory(inventory)["codes"])  # type: ignore[arg-type]
    try:
        BaselineStatement.from_mapping(baseline)
        ActivationRecord.from_mapping(activation)
        ConsumedMarker.from_mapping(marker)
        for payload in (baseline, activation, marker):
            if payload.get("schemaVersion") != SCHEMA_VERSION:
                codes.append("BOOTSTRAP_EVIDENCE_INCOMPLETE")
        _require_timestamp(baseline.get("createdAt"), "baseline.createdAt")
        _require_timestamp(activation.get("activatedAt"), "activation.activatedAt")
        _require_timestamp(marker.get("consumedAt"), "marker.consumedAt")
        if baseline.get("statementType") != "bootstrap-baseline-created" or baseline.get("absenceReason") != ABSENCE_REASON or baseline.get("comparisonMode") != "baseline-creation" or baseline.get("diffClaimed") is not False or baseline.get("declaration") != BASELINE_DECLARATION:
            codes.append("BOOTSTRAP_EVIDENCE_INCOMPLETE")
        if activation.get("startingProcessVersion") != STARTING_VERSION or activation.get("activatedVersion") != ACTIVATED_VERSION or activation.get("bootstrapReason") != BOOTSTRAP_REASON:
            codes.append("BOOTSTRAP_VERSION_INVALID")
        if tuple(baseline.get("hashExcludedFields", ())) != BASELINE_HASH_EXCLUSIONS or baseline.get("contentHash") != _baseline_hash(baseline):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if baseline.get("statementId") != "CBS-" + str(baseline.get("contentHash"))[7:31]:
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if baseline.get("inventoryHash") != inventory.get("inventoryHash"):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        baseline_ref = inventory.get("baselineStatement")
        if not isinstance(baseline_ref, Mapping) or baseline_ref.get("contentHash") != baseline.get("contentHash") or baseline_ref.get("sha256") != _pretty_json_hash(baseline):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if tuple(activation.get("hashExcludedFields", ())) != ACTIVATION_HASH_EXCLUSIONS or activation.get("recordHash") != _root_hash(activation, ACTIVATION_HASH_EXCLUSIONS):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if activation.get("activationRecordId") != "CAR-" + str(activation.get("recordHash"))[7:31]:
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if tuple(marker.get("hashExcludedFields", ())) != MARKER_HASH_EXCLUSIONS or marker.get("markerHash") != _root_hash(marker, MARKER_HASH_EXCLUSIONS):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        identity = (inventory.get("repositoryId"), inventory.get("deliveryId"), inventory.get("activationToken", {}).get("tokenId") if isinstance(inventory.get("activationToken"), Mapping) else None)
        if identity != (baseline.get("repositoryId"), baseline.get("deliveryId"), activation.get("tokenId")):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if identity != (activation.get("repositoryId"), activation.get("deliveryId"), marker.get("tokenId")):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if marker.get("repositoryId") != activation.get("repositoryId") or marker.get("deliveryId") != activation.get("deliveryId") or marker.get("activationRecordHash") != activation.get("recordHash"):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        if not activation.get("consumed") or not marker.get("consumed"):
            codes.append("BOOTSTRAP_ALREADY_CONSUMED")
        if activation.get("inventoryHash") != inventory.get("inventoryHash") or activation.get("baselineStatementHash") != baseline.get("contentHash"):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        manifest = inventory.get("afterManifest")
        trace = inventory.get("afterTraceBridge")
        if not isinstance(manifest, Mapping) or not isinstance(trace, Mapping) or activation.get("afterManifestHash") != manifest.get("contentHash") or activation.get("afterTraceHash") != trace.get("contentHash"):
            codes.append("BOOTSTRAP_HASH_MISMATCH")
        gates = inventory.get("postGateEvidence")
        gate_rows = gates if isinstance(gates, list) else []
        expected_gate_hashes = sorted({str(item) for gate in gate_rows if isinstance(gate, Mapping) for item in gate.get("artifactHashes", [])})
        if list(baseline.get("gateEvidenceHashes", [])) != expected_gate_hashes:
            codes.append("BOOTSTRAP_HASH_MISMATCH")
    except (AttributeError, KeyError, TypeError, ValueError):
        codes.append("BOOTSTRAP_EVIDENCE_INCOMPLETE")
    return {"status": "fail" if codes else "pass", "codes": sorted(set(codes))}


def _load_change_files(path: Path) -> object:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("files") if isinstance(payload, Mapping) and "files" in payload else payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build the four bootstrap evidence artifacts")
    for name in ("repository-id", "delivery-id", "allowed-change-set", "actual-change-set", "after-manifest", "after-trace", "post-gates", "frozen-at", "created-at", "activated-at", "output-dir"):
        build.add_argument(f"--{name}", required=True)
    validate = sub.add_parser("validate", help="Validate a complete bootstrap evidence bundle")
    for name in ("inventory", "baseline-statement", "activation", "consumed-marker"):
        validate.add_argument(f"--{name}", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "build":
            output = Path(args.output_dir).resolve()
            output.mkdir(parents=True, exist_ok=True)
            bundle = build_bootstrap_evidence(
                repository_id=args.repository_id, delivery_id=args.delivery_id,
                allowed_files=_load_change_files(Path(args.allowed_change_set)), actual_files=_load_change_files(Path(args.actual_change_set)),
                after_manifest_path=Path(args.after_manifest), after_trace_path=Path(args.after_trace),
                post_gate_evidence=json.loads(Path(args.post_gates).read_text(encoding="utf-8")),
                frozen_at=args.frozen_at, created_at=args.created_at, activated_at=args.activated_at, artifact_root=output.parent,
            )
            names = {"inventory": "bootstrap-inventory.json", "baselineStatement": "bootstrap-baseline-statement.json", "activation": "bootstrap-activation.json", "consumedMarker": "bootstrap-consumed-marker.json"}
            for key, filename in names.items():
                atomic_write_json(output / filename, bundle[key], allowed_root=output)
            result = {"status": "pass", "artifacts": names}
        else:
            bundle = {
                "inventory": load_json_object(Path(args.inventory)), "baselineStatement": load_json_object(Path(args.baseline_statement)),
                "activation": load_json_object(Path(args.activation)), "consumedMarker": load_json_object(Path(args.consumed_marker)),
            }
            result = validate_bootstrap_bundle(bundle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"status": "fail", "codes": [str(exc) if str(exc).startswith("BOOTSTRAP_") else "BOOTSTRAP_EVIDENCE_INCOMPLETE"], "diagnostics": [type(exc).__name__]}
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
