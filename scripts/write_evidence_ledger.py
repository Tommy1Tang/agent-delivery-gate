#!/usr/bin/env python3
"""Create or update a delivery evidence ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

try:
    from .bootstrap_code_intelligence import (
        ACTIVATION_HASH_EXCLUSIONS,
        MARKER_HASH_EXCLUSIONS,
        ActivationRecord,
        ConsumedMarker,
        _require_identifier,
        _root_hash,
        _semver,
    )
    from .code_intelligence_models import file_hash, load_json_object, normalize_relative_path
except ImportError:
    from bootstrap_code_intelligence import (
        ACTIVATION_HASH_EXCLUSIONS,
        MARKER_HASH_EXCLUSIONS,
        ActivationRecord,
        ConsumedMarker,
        _require_identifier,
        _root_hash,
        _semver,
    )
    from code_intelligence_models import file_hash, load_json_object, normalize_relative_path


def _evidence_hash(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def append_code_intelligence_evidence(ledger: dict, evidence: dict) -> dict:
    """Merge one immutable code-intelligence evidence event idempotently.

    Existing ledger fields are preserved.  ``artifactHash`` is the idempotency
    key; if a producer omits it, a canonical hash of the evidence object is
    used.  Historical verdicts are never rewritten.
    """
    if not isinstance(evidence, dict):
        raise ValueError("code-intelligence evidence must be a JSON object")
    incoming = evidence.get("codeIntelligence", evidence)
    if not isinstance(incoming, dict):
        raise ValueError("codeIntelligence must be a JSON object")
    artifact_hash = str(evidence.get("artifactHash") or evidence.get("sha256") or evidence.get("contentHash") or _evidence_hash(incoming))
    container = ledger.setdefault("codeIntelligence", {
        "schemaVersion": "1.0.0",
        "applicability": "legacy-unmigrated",
        "applicabilityEvidence": {"detectedPaths": [], "eligibleFileCount": 0, "changedCodeFileCount": 0, "reason": "Evidence migration has started."},
    })
    if not isinstance(container, dict):
        raise ValueError("ledger.codeIntelligence must be a JSON object")
    events = container.setdefault("evidenceEvents", [])
    if not isinstance(events, list):
        raise ValueError("ledger.codeIntelligence.evidenceEvents must be an array")
    if any(isinstance(row, dict) and row.get("artifactHash") == artifact_hash for row in events):
        return ledger
    bootstrap_identity_fields = {
        "startingProcessVersion", "activatedVersion", "bootstrapReason", "repositoryId", "deliveryId",
    }
    bootstrap_revision_fields = {
        "activatedAt", "activation", "consumedMarker", "bootstrapInventory", "baselineStatement",
        "afterManifest", "afterTraceBridge",
    }
    same_bootstrap_delivery = (
        isinstance(incoming.get("bootstrapInventory"), dict)
        and container.get("startingProcessVersion") == incoming.get("startingProcessVersion") == "1.0.0"
        and container.get("activatedVersion") == incoming.get("activatedVersion") == "1.1.0"
        and container.get("repositoryId") == incoming.get("repositoryId")
        and container.get("deliveryId") == incoming.get("deliveryId")
    )
    old_inventory = container.get("bootstrapInventory")
    if same_bootstrap_delivery and isinstance(old_inventory, dict) and old_inventory != incoming.get("bootstrapInventory"):
        old_content_hash = old_inventory.get("contentHash")
        preserved = any(
            isinstance(row, dict)
            and isinstance(row.get("evidence"), dict)
            and isinstance(row["evidence"].get("bootstrapInventory"), dict)
            and row["evidence"]["bootstrapInventory"].get("contentHash") == old_content_hash
            for row in events
        )
        if not preserved:
            revision = {
                key: container[key]
                for key in (
                    "startingProcessVersion", "activatedVersion", "activatedAt", "bootstrapReason",
                    "repositoryId", "deliveryId", "afterManifest", "afterTraceBridge",
                    "bootstrapInventory", "baselineStatement", "activation", "consumedMarker",
                )
                if key in container
            }
            events.append({"artifactHash": str(old_content_hash or _evidence_hash(revision)), "evidence": revision})
    for key in (
        "schemaVersion", "applicability", "applicabilityEvidence", "provider",
        "startingProcessVersion", "activatedVersion", "activatedAt", "bootstrapReason",
        "repositoryId", "deliveryId", "activation", "consumedMarker",
        "beforeManifest", "beforeTraceBridge", "afterManifest", "afterTraceBridge",
        "indexDiff", "bootstrapInventory", "baselineStatement", "migrationNotes",
    ):
        if key in incoming:
            if key in container and container[key] != incoming[key]:
                if key in bootstrap_identity_fields:
                    raise ValueError(f"refusing to rewrite historical code-intelligence field: {key}")
                if key in bootstrap_revision_fields and not same_bootstrap_delivery:
                    raise ValueError(f"refusing to rewrite historical code-intelligence field: {key}")
                if key in {"beforeManifest", "beforeTraceBridge", "afterManifest", "afterTraceBridge", "indexDiff"} and key not in bootstrap_revision_fields:
                    raise ValueError(f"refusing to rewrite historical code-intelligence field: {key}")
            container[key] = incoming[key]
    for report in incoming.get("preChangeImpactReports", []) if isinstance(incoming.get("preChangeImpactReports"), list) else []:
        reports = container.setdefault("preChangeImpactReports", [])
        report_hash = report.get("sha256") if isinstance(report, dict) else None
        if not any(isinstance(row, dict) and row.get("sha256") == report_hash for row in reports):
            reports.append(report)
    for gate in incoming.get("gateResults", []) if isinstance(incoming.get("gateResults"), list) else []:
        gates = container.setdefault("gateResults", [])
        identity = (gate.get("gateId"), tuple(gate.get("artifactHashes", [])), gate.get("verdict")) if isinstance(gate, dict) else None
        if not any(isinstance(row, dict) and (row.get("gateId"), tuple(row.get("artifactHashes", [])), row.get("verdict")) == identity for row in gates):
            gates.append(gate)
    events.append({"artifactHash": artifact_hash, "evidence": incoming})
    return ledger


def consume_activation_token(ledger: dict, activation: dict, consumed_marker: dict) -> dict:
    """Append an activation revision without deleting same-delivery history."""
    if not isinstance(activation, dict) or not isinstance(consumed_marker, dict):
        raise ValueError("activation and consumed marker must be JSON objects")
    try:
        ActivationRecord.from_mapping(activation)
        ConsumedMarker.from_mapping(consumed_marker)
    except (TypeError, ValueError) as exc:
        raise ValueError("activation and consumed marker JSON shape is invalid") from exc
    if activation.get("recordHash") != _root_hash(activation, ACTIVATION_HASH_EXCLUSIONS):
        raise ValueError("activation record hash mismatch")
    if consumed_marker.get("markerHash") != _root_hash(consumed_marker, MARKER_HASH_EXCLUSIONS):
        raise ValueError("consumed marker hash mismatch")
    identity = (activation.get("tokenId"), activation.get("repositoryId"), activation.get("deliveryId"))
    marker_identity = (consumed_marker.get("tokenId"), consumed_marker.get("repositoryId"), consumed_marker.get("deliveryId"))
    ledger_delivery = ledger.get("deliveryId")
    if not isinstance(ledger_delivery, str) or not ledger_delivery:
        raise ValueError("ledger root deliveryId must be bound before activation consumption")
    _require_identifier(ledger_delivery, "deliveryId")
    if identity != marker_identity or consumed_marker.get("activationRecordHash") != activation.get("recordHash"):
        raise ValueError("activation and consumed marker binding mismatch")
    if activation.get("deliveryId") != ledger_delivery:
        raise ValueError("activation token cannot be rebound to another delivery")
    if activation.get("consumed") is not True or consumed_marker.get("consumed") is not True:
        raise ValueError("activation token rollback is forbidden")
    container = ledger.get("codeIntelligence")
    if container is None:
        container = {
            "schemaVersion": "1.0.0",
            "applicability": "applicable",
            "applicabilityEvidence": {"detectedPaths": [], "eligibleFileCount": 0, "changedCodeFileCount": 0, "reason": "bootstrap activation"},
        }
        ledger["codeIntelligence"] = container
    if not isinstance(container, dict):
        raise ValueError("ledger.codeIntelligence must be a JSON object")
    immutable_identity = (
        ("startingProcessVersion", activation.get("startingProcessVersion")),
        ("activatedVersion", activation.get("activatedVersion")),
        ("bootstrapReason", activation.get("bootstrapReason")),
        ("repositoryId", activation.get("repositoryId")),
        ("deliveryId", activation.get("deliveryId")),
    )
    for key, value in immutable_identity:
        if key in container and container[key] != value:
            raise ValueError(f"refusing to rewrite immutable activation field: {key}")
    activation_history = container.setdefault("activationHistory", [])
    marker_history = container.setdefault("consumedMarkerHistory", [])
    if not isinstance(activation_history, list) or not isinstance(marker_history, list):
        raise ValueError("activation histories must be arrays")
    token_id = activation.get("tokenId")
    for historical in activation_history + marker_history:
        if isinstance(historical, dict) and historical.get("tokenId") == token_id:
            if historical.get("repositoryId") != activation.get("repositoryId") or historical.get("deliveryId") != activation.get("deliveryId"):
                raise ValueError("activation token was already consumed by another repository/delivery")
    current_activation = container.get("activation")
    current_marker = container.get("consumedMarker")
    if isinstance(current_activation, dict) and current_activation != activation:
        current_identity = (current_activation.get("tokenId"), current_activation.get("repositoryId"), current_activation.get("deliveryId"))
        if current_identity != identity:
            raise ValueError("activation token was already consumed by another repository/delivery")
        if str(activation.get("activatedAt", "")) <= str(current_activation.get("activatedAt", "")):
            raise ValueError("activation revision timestamp must advance")
        if not any(isinstance(row, dict) and row.get("recordHash") == current_activation.get("recordHash") for row in activation_history):
            activation_history.append(current_activation)
    if isinstance(current_marker, dict) and current_marker != consumed_marker:
        if not any(isinstance(row, dict) and row.get("markerHash") == current_marker.get("markerHash") for row in marker_history):
            marker_history.append(current_marker)
    if not any(isinstance(row, dict) and row.get("recordHash") == activation.get("recordHash") for row in activation_history):
        activation_history.append(activation)
    if not any(isinstance(row, dict) and row.get("markerHash") == consumed_marker.get("markerHash") for row in marker_history):
        marker_history.append(consumed_marker)
    for key, value in (*immutable_identity, ("activatedAt", activation.get("activatedAt")), ("activation", activation), ("consumedMarker", consumed_marker)):
        container[key] = value
    return ledger


def _bind_delivery_id(ledger: dict, delivery_id: str) -> None:
    _require_identifier(delivery_id, "deliveryId")
    existing = ledger.get("deliveryId")
    if existing is not None and existing != delivery_id:
        raise ValueError("refusing to rewrite ledger root deliveryId")
    code = ledger.get("codeIntelligence")
    if isinstance(code, dict) and code.get("deliveryId") not in (None, delivery_id):
        raise ValueError("ledger root deliveryId does not match codeIntelligence.deliveryId")
    ledger["deliveryId"] = delivery_id


def _bind_starting_process_version(ledger: dict, version: str, *, bootstrap: bool) -> None:
    _semver(version)
    container = ledger.get("codeIntelligence")
    if container is None:
        container = {
            "schemaVersion": "1.0.0",
            "applicability": "applicable" if bootstrap else "legacy-unmigrated",
            "applicabilityEvidence": {
                "detectedPaths": [],
                "eligibleFileCount": 0,
                "changedCodeFileCount": 0,
                "reason": "bootstrap activation" if bootstrap else "Starting process version captured by caller.",
            },
        }
        ledger["codeIntelligence"] = container
    if not isinstance(container, dict):
        raise ValueError("ledger.codeIntelligence must be a JSON object")
    if container.get("startingProcessVersion") not in (None, version):
        raise ValueError("refusing to rewrite immutable starting process version")
    container["startingProcessVersion"] = version


def _get_schema_path() -> Path:
    """Resolve the evidence-ledger schema relative to this script."""
    return (Path(__file__).resolve().parent.parent / "schemas" / "evidence-ledger.schema.json")


def _validate_ledger(ledger: dict, schema_path: Path) -> list[str]:
    """Basic structural validation against the evidence-ledger schema.
    Returns a list of validation error messages (empty = valid)."""
    errors = []
    required = ["taskName", "createdAt", "deliveryStatus", "deliveryGateEvidence", "roleRuns", "commands", "artifacts", "qualityGates", "observability"]
    for key in required:
        if key not in ledger:
            errors.append(f"Missing required key: {key}")
    if "roleRuns" in ledger and not isinstance(ledger["roleRuns"], list):
        errors.append("roleRuns must be an array")
    if "commands" in ledger and not isinstance(ledger["commands"], list):
        errors.append("commands must be an array")
    if "artifacts" in ledger and not isinstance(ledger["artifacts"], list):
        errors.append("artifacts must be an array")
    if "qualityGates" in ledger and not isinstance(ledger["qualityGates"], list):
        errors.append("qualityGates must be an array")
    return errors


def _backup_ledger(ledger_path: Path) -> Path | None:
    """Create a timestamped backup of the existing ledger before modification."""
    if not ledger_path.exists():
        return None
    backup_dir = ledger_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"evidence-ledger-{timestamp}.json"
    shutil.copy2(ledger_path, backup_path)
    return backup_path


def empty_ledger(task_name: str) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    return {
        "taskName": task_name,
        "createdAt": created_at,
        "deliveryStatus": "in-progress",
        "deliveryGateEvidence": {
            "status": "fail",
            "blockingReasons": ["Delivery validation has not run."],
            "runAt": created_at,
            "strictMode": True,
            "command": "not-run: scripts/validate_delivery.py",
        },
        "roleRuns": [],
        "commands": [],
        "artifacts": [],
        "qualityGates": [],
        "observability": {},
    }


def load_or_create(path: Path, task_name: str) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # Corrupted ledger — backup and recreate
            corrupted_backup = path.with_suffix(".corrupted.json")
            shutil.copy2(path, corrupted_backup)
            print(f"Warning: Corrupted ledger backed up to {corrupted_backup}: {exc}", file=sys.stderr)
            return empty_ledger(task_name)
    return empty_ledger(task_name)


def parse_role_run(value: str) -> dict:
    # roleId|status|sessionMode|summary|durationMs|retryCount|blockedBy1,blockedBy2
    parts = value.split("|")
    while len(parts) < 7:
        parts.append("")
    role_id, status, session_mode, summary, duration_raw, retry_raw, blocked_raw = parts[:7]
    duration_ms = int(duration_raw) if duration_raw.isdigit() else 0
    retry_count = int(retry_raw) if retry_raw.isdigit() else 0
    blocked_by = [b.strip() for b in blocked_raw.split(",") if b.strip()] if blocked_raw else []
    result = {
        "roleId": role_id,
        "status": status or "completed",
        "sessionMode": session_mode or "manual",
        "summary": summary,
        "durationMs": duration_ms,
        "retryCount": retry_count,
        "blockedBy": blocked_by,
    }
    if result["status"] in {"completed", "complete", "success", "passed"}:
        result["changeSet"] = {"modified": [], "created": [], "deleted": []}
    return result


def parse_command(value: str) -> dict:
    # command|status|evidence|durationMs
    parts = value.split("|")
    while len(parts) < 4:
        parts.append("")
    command, status, evidence, duration_raw = parts[:4]
    duration_ms = int(duration_raw) if duration_raw.isdigit() else 0
    return {
        "command": command,
        "status": status or "not-run",
        "evidence": evidence,
        "durationMs": duration_ms,
    }


def parse_event(value: str) -> dict:
    # eventType|message|roleId|timestamp|contextJson
    parts = value.split("|")
    while len(parts) < 5:
        parts.append("")
    event_type, message, role_id, timestamp, context_raw = parts[:5]
    context = {}
    if context_raw:
        try:
            context = json.loads(context_raw)
        except json.JSONDecodeError:
            context = {"raw": context_raw}
    result = {
        "eventType": event_type or "info",
        "message": message,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    if role_id:
        result["roleId"] = role_id
    if context:
        result["context"] = context
    return result


def parse_trace(value: str) -> dict:
    # requirementId|summary|codeFilesCsv|testCasesCsv|designRefsCsv|artifactsCsv
    parts = value.split("|")
    while len(parts) < 6:
        parts.append("")
    req_id, summary, code_csv, test_csv, design_csv, artifact_csv = parts[:6]
    result: dict = {
        "requirementId": req_id,
        "codeFiles": [f.strip() for f in code_csv.split(",") if f.strip()],
        "testCases": [t.strip() for t in test_csv.split(",") if t.strip()],
    }
    if summary:
        result["requirementSummary"] = summary
    if design_csv:
        result["designRef"] = [d.strip() for d in design_csv.split(",") if d.strip()]
    if artifact_csv:
        result["artifacts"] = [a.strip() for a in artifact_csv.split(",") if a.strip()]
    return result


def parse_reverse_sync(value: str) -> dict:
    # taskId|driftType|driftSource|originFRId|closurePath|closureStatus|prdSectionsCsv|message
    parts = value.split("|")
    while len(parts) < 8:
        parts.append("")
    task_id, drift_type, drift_source, origin_fr, closure_path, closure_status, sections_csv, message = parts[:8]
    sections = [s.strip() for s in sections_csv.split(",") if s.strip()]
    context: dict = {
        "taskId": task_id,
        "driftType": drift_type or "behavior",
        "driftSource": drift_source,
        "closureStatus": closure_status or "open",
    }
    if origin_fr:
        context["originFRId"] = origin_fr
    if closure_path:
        context["closurePath"] = closure_path
    if sections:
        context["prdSectionsUpdated"] = sections
    return {
        "eventType": "reverse_sync_event",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message or f"Reverse sync task {task_id} -> {closure_status or 'open'}",
        "context": context,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="Ledger JSON path")
    parser.add_argument("--task-name", default="Unnamed task", help="Task name for a new ledger")
    parser.add_argument("--role-run", action="append", default=[], help="roleId|status|sessionMode|summary|durationMs|retryCount|blockedBy1,blockedBy2")
    parser.add_argument("--command", action="append", default=[], help="command|status|evidence|durationMs")
    parser.add_argument("--artifact", action="append", default=[], help="Artifact path")
    parser.add_argument("--quality-gate-json", action="append", default=[], help="Path to a quality gate JSON file")
    parser.add_argument("--rework", action="append", default=[], help="Rework reason (appends to observability.reworkReasons)")
    parser.add_argument("--security-block", action="append", default=[], help="Security block detail (appends to observability.securityBlockDetails)")
    parser.add_argument("--event", action="append", default=[], help="eventType|message|roleId|timestamp|contextJson (appends to eventLog)")
    parser.add_argument("--trace", action="append", default=[], help="requirementId|summary|codeFilesCsv|testCasesCsv|designRefsCsv|artifactsCsv (appends to traceabilityMatrix)")
    parser.add_argument("--reverse-sync-event", action="append", default=[], help="taskId|driftType|driftSource|originFRId|closurePath|closureStatus|prdSectionsCsv|message (appends a reverse_sync_event into eventLog)")
    parser.add_argument("--code-intelligence-evidence", action="append", default=[], help="Path to a code-intelligence evidence JSON object; may be repeated")
    parser.add_argument("--bootstrap-inventory", action="append", default=[], help="Path to a finalized BootstrapInventory JSON; may be repeated")
    parser.add_argument("--delivery-id", help="Bind the immutable root deliveryId; an existing different value is rejected")
    parser.add_argument("--starting-process-version", help="Caller-captured strict SemVer; an existing different value is rejected")
    parser.add_argument("--activation", help="Path to a finalized ActivationRecord JSON; requires --consumed-marker")
    parser.add_argument("--consumed-marker", help="Path to a finalized ConsumedMarker JSON; requires --activation")
    parser.add_argument("--total-wall-time", type=int, default=0, help="Total wall time in ms")
    parser.add_argument("--json", action="store_true", help="Print ledger JSON")
    args = parser.parse_args(argv)

    if bool(args.activation) != bool(args.consumed_marker):
        raise ValueError("--activation and --consumed-marker must be provided together")
    if args.activation and not args.starting_process_version:
        raise ValueError("--starting-process-version must be provided by the caller for activation consumption")
    if args.starting_process_version:
        _semver(args.starting_process_version)

    ledger_path = Path(args.ledger).resolve()
    ledger = load_or_create(ledger_path, args.task_name)
    if args.delivery_id:
        _bind_delivery_id(ledger, args.delivery_id)

    for value in args.role_run:
        ledger["roleRuns"].append(parse_role_run(value))
    for value in args.command:
        ledger["commands"].append(parse_command(value))
    for artifact in args.artifact:
        if artifact not in ledger["artifacts"]:
            ledger["artifacts"].append(artifact)
    for gate_path in args.quality_gate_json:
        ledger["qualityGates"].append(json.loads(Path(gate_path).read_text(encoding="utf-8")))

    # Observability
    obs = ledger.setdefault("observability", {})
    if args.total_wall_time:
        obs["totalWallTimeMs"] = (obs.get("totalWallTimeMs", 0) or 0) + args.total_wall_time
    for reason in args.rework:
        obs.setdefault("reworkReasons", []).append(reason)
        obs["reworkCount"] = len(obs["reworkReasons"])
    for detail in args.security_block:
        obs.setdefault("securityBlockDetails", []).append(detail)
        obs["securityBlockCount"] = len(obs["securityBlockDetails"])

    # Event log (P0)
    for value in args.event:
        ledger.setdefault("eventLog", []).append(parse_event(value))

    # Traceability matrix (P0)
    for value in args.trace:
        ledger.setdefault("traceabilityMatrix", []).append(parse_trace(value))

    # Reverse sync events: code -> PRD back-fill closure trail. Stored under eventLog with
    # eventType='reverse_sync_event' (see schemas/evidence-ledger.schema.json) and read by
    # supervisor-auditor when verifying prdDriftClosed.
    for value in args.reverse_sync_event:
        ledger.setdefault("eventLog", []).append(parse_reverse_sync(value))

    for evidence_path in args.code_intelligence_evidence:
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        append_code_intelligence_evidence(ledger, evidence)

    for inventory_path in args.bootstrap_inventory:
        path = Path(inventory_path).resolve(strict=True)
        inventory = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(inventory, dict) or not inventory.get("inventoryHash"):
            raise ValueError("bootstrap inventory is invalid")
        try:
            relative = normalize_relative_path(path.relative_to(ledger_path.parent.parent).as_posix())
        except ValueError:
            relative = normalize_relative_path(path.name)
        append_code_intelligence_evidence(ledger, {
            "artifactHash": inventory["inventoryHash"],
            "bootstrapInventory": {"path": relative, "sha256": file_hash(path), "contentHash": inventory["inventoryHash"]},
            "startingProcessVersion": inventory.get("startingProcessVersion"),
            "activatedVersion": inventory.get("activatedVersion"),
            "repositoryId": inventory.get("repositoryId"),
            "deliveryId": inventory.get("deliveryId"),
        })

    if args.delivery_id:
        _bind_delivery_id(ledger, args.delivery_id)
    if args.starting_process_version:
        _bind_starting_process_version(ledger, args.starting_process_version, bootstrap=bool(args.activation))
    if args.activation and args.consumed_marker:
        activation = load_json_object(Path(args.activation).resolve(strict=True))
        consumed_marker = load_json_object(Path(args.consumed_marker).resolve(strict=True))
        if activation.get("startingProcessVersion") != args.starting_process_version:
            raise ValueError("caller starting process version does not match activation")
        consume_activation_token(ledger, activation, consumed_marker)

    # Validate before writing
    schema_path = _get_schema_path()
    validation_errors = _validate_ledger(ledger, schema_path)
    if validation_errors:
        print(f"Warning: Ledger validation issues: {validation_errors}", file=sys.stderr)

    # Backup existing ledger before overwriting
    _backup_ledger(ledger_path)

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
    else:
        print(f"Wrote evidence ledger: {ledger_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
