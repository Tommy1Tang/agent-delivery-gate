from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import bootstrap_code_intelligence as bootstrap
from scripts.bootstrap_code_intelligence import (
    BootstrapChangeItem,
    activation_token_id,
    build_bootstrap_evidence,
    compare_process_versions,
    validate_bootstrap_bundle,
    validate_bootstrap_inventory,
)
from scripts.code_gate_mode import explain_code_gate_mode, resolve_code_gate_mode
from scripts.build_code_index import _inventory, index_config_fingerprint
from scripts.code_intelligence_models import atomic_write_json, content_hash, file_hash
from scripts.validate_code_intelligence import validate_phase
from scripts.write_evidence_ledger import append_code_intelligence_evidence, consume_activation_token, main as write_evidence_ledger


HASH = "sha256:" + "a" * 64


def _change_set() -> list[dict[str, str]]:
    return [
        {"path": "scripts/bootstrap_code_intelligence.py", "operation": "created", "category": "implementation"},
        {"path": "schemas/bootstrap-inventory.schema.json", "operation": "created", "category": "schema"},
        {"path": "tests/code_intelligence/test_bootstrap_activation.py", "operation": "created", "category": "test"},
    ]


def _post_gates() -> list[dict[str, object]]:
    return [
        {"gateId": f"C-CODE-0{number}", "verdict": "PASS", "code": "OK", "artifactHashes": [HASH]}
        for number in range(1, 5)
    ]


def _index_config() -> dict[str, object]:
    return {
        "schemaVersion": "1.0.0", "enabled": True,
        "provider": {
            "name": "code-graph-rag", "providerVersion": "0.0.779", "manifestVersion": 1,
            "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84",
            "requiredCaptures": ["structure", "calls", "types", "imports"],
        },
        "sourceExtensions": [".py"], "excludeDirectories": ["_test_output", ".tmp"],
        "symbolKinds": ["FUNCTION"], "relationshipTypes": ["CALLS"],
        "limits": {"maxDepth": 8, "maxNodes": 10000, "timeoutSeconds": 10, "maxCandidates": 20},
    }


class BootstrapActivationTests(unittest.TestCase):
    def _bundle(
        self,
        root: Path,
        *,
        delivery_id: str = "delivery-bootstrap",
        repository_id: str = "repo-1",
    ) -> dict[str, dict[str, object]]:
        manifest = root / "after-manifest.json"
        trace = root / "after-trace.json"
        config = _index_config()
        files, source_digest, _extensions, _repository = _inventory(root, config)
        atomic_write_json(manifest, {
            "schemaVersion": "1.1.0",
            "contentHash": HASH,
            "sourceDigest": source_digest,
            "configHash": content_hash(index_config_fingerprint(config), excluded_keys=()),
            "kind": "manifest",
            "coverage": {"complete": True, "missingCaptures": [], "relationshipClassificationComplete": True, "unresolvedInternalRelationshipCount": 0, "auditedBoundaryRelationshipCount": 0, "relationshipCoverageHash": HASH},
            "files": {"eligible": len(files), "indexed": len(files), "gapFiles": []},
            "relationships": {"count": 0, "unresolved": 0, "resolvedInternal": 0, "auditedBoundary": 0, "unresolvedInternal": 0, "legacyUnclassified": 0, "coverageHash": HASH, "boundaryByType": {}, "boundaryByClass": {}},
        })
        atomic_write_json(trace, {"contentHash": HASH, "kind": "trace"})
        return build_bootstrap_evidence(
            repository_id=repository_id,
            delivery_id=delivery_id,
            allowed_files=_change_set(),
            actual_files=_change_set(),
            after_manifest_path=manifest,
            after_trace_path=trace,
            post_gate_evidence=_post_gates(),
            frozen_at="2026-08-27T00:00:00Z",
            created_at="2026-08-27T01:00:00Z",
            activated_at="2026-08-27T02:00:00Z",
            artifact_root=root,
        )

    def test_semver_and_token_are_strict_and_deterministic(self) -> None:
        # @trace FR-007 AC-016
        # @test-id TEST-CODE-BOOTSTRAP-SEMVER
        self.assertLess(compare_process_versions("1.0.0", "1.1.0"), 0)
        self.assertGreater(compare_process_versions("10.0.0", "2.0.0"), 0)
        with self.assertRaises(ValueError):
            compare_process_versions("1.0.0-rc.1", "1.1.0")
        self.assertEqual(
            activation_token_id("repo-1", "1.0.0", "1.1.0"),
            activation_token_id("repo-1", "1.0.0", "1.1.0"),
        )

    def test_exact_change_set_and_scope_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            inventory = self._bundle(Path(raw))["inventory"]
        self.assertEqual(validate_bootstrap_inventory(inventory)["status"], "pass")
        extra = json.loads(json.dumps(inventory))
        extra["actualChangeSet"]["files"].append(
            {"path": "backend/src/Unrelated.java", "operation": "created", "category": "implementation"}
        )
        result = validate_bootstrap_inventory(extra)
        self.assertEqual(result["status"], "fail")
        self.assertIn("BOOTSTRAP_SCOPE_VIOLATION", result["codes"])
        self.assertIn("BOOTSTRAP_CHANGESET_MISMATCH", result["codes"])

    def test_core_schemas_are_exactly_allowlisted(self) -> None:
        expected = {
            "schemas/impact-report.schema.json",
            "schemas/index-diff.schema.json",
            "schemas/trace-link.schema.json",
        }
        self.assertEqual(
            {BootstrapChangeItem(path, "created", "schema").path for path in expected},
            expected,
        )
        with self.assertRaisesRegex(ValueError, "outside the frozen capability scope"):
            BootstrapChangeItem("schemas/impact-report-v2.schema.json", "created", "schema")

    def test_bundle_hashes_and_bidirectional_references_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = self._bundle(Path(raw))
            self.assertEqual(validate_bootstrap_bundle(bundle)["status"], "pass")
            tampered = json.loads(json.dumps(bundle))
            tampered["baselineStatement"]["inventoryHash"] = HASH
            result = validate_bootstrap_bundle(tampered)
        self.assertEqual(result["status"], "fail")
        self.assertIn("BOOTSTRAP_HASH_MISMATCH", result["codes"])

    def test_bootstrap_c05_c06_c07_and_next_delivery_normal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = self._bundle(root)
            for name, payload in bundle.items():
                atomic_write_json(root / f"{name}.json", payload)
            code = {
                "schemaVersion": "1.0.0",
                "applicability": "applicable",
                "applicabilityEvidence": {"detectedPaths": ["scripts/bootstrap_code_intelligence.py"], "eligibleFileCount": 1, "changedCodeFileCount": 1, "reason": "bootstrap"},
                "startingProcessVersion": "1.0.0",
                "activatedVersion": "1.1.0",
                "repositoryId": "repo-1",
                "deliveryId": "delivery-bootstrap",
                "provider": {"name": "code-graph-rag", "version": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"},
                "bootstrapInventory": {"path": "inventory.json", "sha256": file_hash(root / "inventory.json"), "contentHash": bundle["inventory"]["inventoryHash"]},
                "baselineStatement": {"path": "baselineStatement.json", "sha256": file_hash(root / "baselineStatement.json"), "contentHash": bundle["baselineStatement"]["contentHash"]},
                "afterManifest": bundle["inventory"]["afterManifest"],
                "afterTraceBridge": bundle["inventory"]["afterTraceBridge"],
                "activation": bundle["activation"],
                "consumedMarker": bundle["consumedMarker"],
                "gateResults": _post_gates(),
            }
            ledger = {"deliveryId": "delivery-bootstrap", "changeSet": {"files": ["scripts/bootstrap_code_intelligence.py"]}, "codeIntelligence": code}
            process = {"version": "1.1.0"}
            self.assertEqual(resolve_code_gate_mode(ledger, process, bundle["inventory"]), "bootstrap")
            report = validate_phase("delivery", root, ledger, bootstrap_inventory=bundle["inventory"], bootstrap_bundle=bundle, process=process, code_config=_index_config())
            gates = {row["gateId"]: row for row in report["gateResults"]}
            self.assertEqual(gates["C-CODE-05"]["verdict"], "NOT_APPLICABLE")
            self.assertEqual(gates["C-CODE-05"]["code"], "BOOTSTRAP_NOT_APPLICABLE")
            self.assertEqual(gates["C-CODE-06"]["code"], "BOOTSTRAP_BASELINE_CREATED")
            self.assertEqual(gates["C-CODE-06"]["comparisonMode"], "baseline-creation")
            self.assertFalse(gates["C-CODE-06"]["diffClaimed"])
            self.assertEqual(gates["C-CODE-07"]["verdict"], "PASS")
            post_report = validate_phase("post-change", root, ledger, bootstrap_inventory=bundle["inventory"], bootstrap_bundle=bundle, process=process, code_config=_index_config())
            self.assertEqual(post_report["status"], "pass")
            self.assertEqual(post_report["gateResults"][0]["code"], "BOOTSTRAP_BASELINE_CREATED")

            next_ledger = json.loads(json.dumps(ledger))
            next_ledger["deliveryId"] = "delivery-next"
            next_ledger["codeIntelligence"]["deliveryId"] = "delivery-next"
            next_ledger["codeIntelligence"]["startingProcessVersion"] = "1.1.0"
            next_ledger["codeIntelligence"].pop("bootstrapInventory")
            next_ledger["codeIntelligence"].pop("baselineStatement")
            self.assertEqual(resolve_code_gate_mode(next_ledger, process), "normal")

    def test_historical_or_duplicate_consumption_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = self._bundle(Path(raw))
        ledger = {
            "deliveryId": "delivery-second",
            "codeIntelligence": {
                "repositoryId": "repo-1",
                "deliveryId": "delivery-second",
                "startingProcessVersion": "1.0.0",
                "activatedVersion": "1.1.0",
                "activationHistory": [bundle["activation"]],
                "consumedMarkerHistory": [bundle["consumedMarker"]],
            },
        }
        decision = explain_code_gate_mode(ledger, {"version": "1.1.0"}, bundle["inventory"])
        self.assertEqual(decision["mode"], "blocked")
        self.assertEqual(decision["code"], "BOOTSTRAP_ALREADY_CONSUMED")

    def test_consume_activation_token_is_idempotent_but_never_rebound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = self._bundle(Path(raw))
        ledger: dict[str, object] = {"deliveryId": "delivery-bootstrap"}
        consume_activation_token(ledger, bundle["activation"], bundle["consumedMarker"])
        consume_activation_token(ledger, bundle["activation"], bundle["consumedMarker"])
        code = ledger["codeIntelligence"]
        self.assertEqual(len(code["activationHistory"]), 1)
        rebound = json.loads(json.dumps(bundle["activation"]))
        rebound["deliveryId"] = "delivery-other"
        with self.assertRaises(ValueError):
            consume_activation_token(ledger, rebound, bundle["consumedMarker"])

    def test_same_delivery_rework_appends_activation_and_evidence_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = self._bundle(root)
            manifest = root / "after-manifest.json"
            trace = root / "after-trace.json"
            revised_changes = [*_change_set(), {"path": "scripts/orchestrate.py", "operation": "modified", "category": "implementation"}]
            second = build_bootstrap_evidence(
                repository_id="repo-1", delivery_id="delivery-bootstrap",
                allowed_files=revised_changes, actual_files=revised_changes,
                after_manifest_path=manifest, after_trace_path=trace,
                post_gate_evidence=_post_gates(), frozen_at="2026-08-27T02:30:00Z",
                created_at="2026-08-27T02:45:00Z", activated_at="2026-08-27T03:00:00Z",
                artifact_root=root,
            )
        ledger: dict[str, object] = {
            "deliveryId": "delivery-bootstrap",
            "codeIntelligence": {
                "startingProcessVersion": "1.0.0", "activatedVersion": "1.1.0",
                "bootstrapReason": "initial-code-intelligence-baseline",
                "repositoryId": "repo-1", "deliveryId": "delivery-bootstrap",
                "bootstrapInventory": {"contentHash": first["inventory"]["inventoryHash"]},
                "activation": first["activation"], "consumedMarker": first["consumedMarker"],
                "activationHistory": [first["activation"]], "consumedMarkerHistory": [first["consumedMarker"]],
                "evidenceEvents": [],
            },
        }
        append_code_intelligence_evidence(ledger, {
            "artifactHash": second["inventory"]["inventoryHash"],
            "startingProcessVersion": "1.0.0", "activatedVersion": "1.1.0",
            "repositoryId": "repo-1", "deliveryId": "delivery-bootstrap",
            "bootstrapInventory": {"contentHash": second["inventory"]["inventoryHash"]},
        })
        consume_activation_token(ledger, second["activation"], second["consumedMarker"])
        code = ledger["codeIntelligence"]
        self.assertEqual(code["bootstrapInventory"]["contentHash"], second["inventory"]["inventoryHash"])
        self.assertEqual(code["activation"], second["activation"])
        self.assertEqual(len(code["activationHistory"]), 2)
        self.assertEqual(len(code["consumedMarkerHistory"]), 2)
        self.assertEqual(len(code["evidenceEvents"]), 2)

    def test_ledger_cli_binds_delivery_and_consumes_activation_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = self._bundle(root)
            activation_path = root / "activation.json"
            marker_path = root / "consumed-marker.json"
            atomic_write_json(activation_path, bundle["activation"])
            atomic_write_json(marker_path, bundle["consumedMarker"])
            ledger_path = root / "evidence-ledger.json"
            arguments = [
                "--ledger", str(ledger_path),
                "--task-name", "bootstrap",
                "--delivery-id", "delivery-bootstrap",
                "--starting-process-version", "1.0.0",
                "--activation", str(activation_path),
                "--consumed-marker", str(marker_path),
            ]

            self.assertEqual(write_evidence_ledger(arguments), 0)
            self.assertEqual(write_evidence_ledger(arguments), 0)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(ledger["deliveryId"], "delivery-bootstrap")
        self.assertEqual(ledger["codeIntelligence"]["startingProcessVersion"], "1.0.0")
        self.assertEqual(len(ledger["codeIntelligence"]["activationHistory"]), 1)
        self.assertEqual(len(ledger["codeIntelligence"]["consumedMarkerHistory"]), 1)

    def test_ledger_cli_rejects_incomplete_tampered_or_rebound_activation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = self._bundle(root)
            activation_path = root / "activation.json"
            marker_path = root / "consumed-marker.json"
            atomic_write_json(activation_path, bundle["activation"])
            atomic_write_json(marker_path, bundle["consumedMarker"])
            ledger_path = root / "evidence-ledger.json"
            common = ["--ledger", str(ledger_path), "--task-name", "bootstrap"]

            with self.assertRaisesRegex(ValueError, "must be provided together"):
                write_evidence_ledger([*common, "--activation", str(activation_path)])
            with self.assertRaisesRegex(ValueError, "must be provided together"):
                write_evidence_ledger([*common, "--consumed-marker", str(marker_path)])
            with self.assertRaisesRegex(ValueError, "starting-process-version"):
                write_evidence_ledger([
                    *common, "--delivery-id", "delivery-bootstrap",
                    "--activation", str(activation_path), "--consumed-marker", str(marker_path),
                ])

            tampered = dict(bundle["activation"])
            tampered["recordHash"] = HASH
            tampered_path = root / "tampered-activation.json"
            atomic_write_json(tampered_path, tampered)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                write_evidence_ledger([
                    *common, "--delivery-id", "delivery-bootstrap", "--starting-process-version", "1.0.0",
                    "--activation", str(tampered_path), "--consumed-marker", str(marker_path),
                ])

            valid_arguments = [
                *common, "--delivery-id", "delivery-bootstrap", "--starting-process-version", "1.0.0",
                "--activation", str(activation_path), "--consumed-marker", str(marker_path),
            ]
            self.assertEqual(write_evidence_ledger(valid_arguments), 0)
            with self.assertRaisesRegex(ValueError, "starting process version"):
                write_evidence_ledger([
                    *common, "--delivery-id", "delivery-bootstrap", "--starting-process-version", "1.1.0",
                    "--activation", str(activation_path), "--consumed-marker", str(marker_path),
                ])
            with self.assertRaisesRegex(ValueError, "root deliveryId"):
                write_evidence_ledger([
                    *common, "--delivery-id", "delivery-other", "--starting-process-version", "1.0.0",
                    "--activation", str(activation_path), "--consumed-marker", str(marker_path),
                ])

            other = self._bundle(root, repository_id="repo-2")
            other_activation = root / "other-activation.json"
            other_marker = root / "other-marker.json"
            atomic_write_json(other_activation, other["activation"])
            atomic_write_json(other_marker, other["consumedMarker"])
            with self.assertRaisesRegex(ValueError, "immutable activation field: repositoryId"):
                write_evidence_ledger([
                    *common, "--delivery-id", "delivery-bootstrap", "--starting-process-version", "1.0.0",
                    "--activation", str(other_activation), "--consumed-marker", str(other_marker),
                ])

    def test_bootstrap_validation_mutation_matrix_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = self._bundle(Path(raw))

        for value, field in (("", "identifier"), ("x\n", "identifier")):
            with self.assertRaises(ValueError):
                bootstrap._require_identifier(value, field)
        with self.assertRaises(ValueError):
            bootstrap._require_hash("not-a-hash", "hash")
        with self.assertRaises(ValueError):
            bootstrap._require_timestamp("yesterday", "timestamp")
        for changes in (None, [], [{}], [*_change_set(), _change_set()[0]]):
            with self.assertRaises(ValueError):
                bootstrap._normalize_changes(changes)
        with self.assertRaises(ValueError):
            bootstrap.BootstrapChangeItem("scripts/x.py", "deleted", "implementation")
        with self.assertRaises(ValueError):
            bootstrap.BootstrapChangeItem("scripts/x.py", "created", "unknown")
        self.assertTrue(bootstrap.is_allowed_bootstrap_path("scripts/next_step.py"))
        self.assertTrue(bootstrap.is_allowed_bootstrap_path("scripts/orchestrate.py"))
        self.assertTrue(bootstrap.is_allowed_bootstrap_path("scripts/code_intelligence_e2e.py"))
        self.assertTrue(bootstrap.is_allowed_bootstrap_path("assets/config/agent-team-config.json"))
        self.assertTrue(bootstrap.is_allowed_bootstrap_path("tests/fixtures/code-intelligence/polyglot/e2e_app.py"))
        self.assertFalse(bootstrap.is_allowed_bootstrap_path("tests/fixtures/code-intelligence/polyglot/escape.py"))
        self.assertFalse(bootstrap.is_allowed_bootstrap_path("scripts/x.py"))
        self.assertFalse(bootstrap.is_allowed_bootstrap_path("backend/x.py"))

        inventory_mutations = (
            lambda value: value.update({"schemaVersion": "9.0.0"}),
            lambda value: value["allowedChangeSet"].update({"freezeEvidenceHash": HASH}),
            lambda value: value.update({"activationToken": {"state": "consumed", "tokenId": "bad"}}),
            lambda value: value.update({"hashExcludedFields": []}),
            lambda value: value.update({"inventoryId": "bad"}),
            lambda value: value.update({"postGateEvidence": []}),
            lambda value: value.update({"afterManifest": None}),
            lambda value: value.update({"afterTraceBridge": {"path": "../escape", "sha256": HASH, "contentHash": HASH}}),
        )
        for mutate in inventory_mutations:
            candidate = json.loads(json.dumps(bundle["inventory"]))
            mutate(candidate)
            self.assertEqual(validate_bootstrap_inventory(candidate)["status"], "fail")
        self.assertEqual(validate_bootstrap_inventory({})["codes"], ["BOOTSTRAP_EVIDENCE_INCOMPLETE"])

        bundle_mutations = (
            lambda value: value.update({"baselineStatement": None}),
            lambda value: value["baselineStatement"].update({"schemaVersion": "9"}),
            lambda value: value["baselineStatement"].update({"statementType": "invented"}),
            lambda value: value["activation"].update({"startingProcessVersion": "9.0.0"}),
            lambda value: value["baselineStatement"].update({"hashExcludedFields": []}),
            lambda value: value["baselineStatement"].update({"statementId": "bad"}),
            lambda value: value["baselineStatement"].update({"inventoryHash": HASH}),
            lambda value: value["inventory"].update({"baselineStatement": None}),
            lambda value: value["activation"].update({"hashExcludedFields": []}),
            lambda value: value["activation"].update({"activationRecordId": "bad"}),
            lambda value: value["consumedMarker"].update({"hashExcludedFields": []}),
            lambda value: value["baselineStatement"].update({"repositoryId": "other"}),
            lambda value: value["consumedMarker"].update({"repositoryId": "other"}),
            lambda value: value["consumedMarker"].update({"activationRecordHash": HASH}),
            lambda value: value["activation"].update({"consumed": False}),
            lambda value: value["activation"].update({"inventoryHash": HASH}),
            lambda value: value["activation"].update({"afterManifestHash": "sha256:" + "0" * 64}),
            lambda value: value["baselineStatement"].update({"gateEvidenceHashes": []}),
            lambda value: value["activation"].update({"activatedAt": "bad"}),
        )
        for index, mutate in enumerate(bundle_mutations):
            candidate = json.loads(json.dumps(bundle))
            mutate(candidate)
            self.assertEqual(validate_bootstrap_bundle(candidate)["status"], "fail", index)


if __name__ == "__main__":
    unittest.main()
