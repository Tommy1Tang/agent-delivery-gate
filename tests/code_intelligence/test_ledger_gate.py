from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts import write_evidence_ledger as writer
from scripts.build_code_index import _inventory, index_config_fingerprint
from scripts.validate_code_intelligence import validate_phase
from scripts.code_intelligence_models import content_hash, file_hash
from scripts.write_evidence_ledger import append_code_intelligence_evidence


HASH = "sha256:" + "a" * 64


class LedgerGateTests(unittest.TestCase):
    def test_legacy_and_docs_only_remain_valid(self) -> None:
        ledger = {"taskName": "legacy", "changeSet": {"files": ["docs/readme.md"]}}
        with tempfile.TemporaryDirectory() as raw:
            result = validate_phase("delivery", Path(raw), ledger)
        self.assertEqual(result["status"], "pass"); self.assertEqual(result["applicability"], "not-applicable")

    def test_code_change_without_new_evidence_blocks(self) -> None:
        # @trace FR-007 AC-007 AC-014 AC-015
        # @test-id TEST-CODE-LEDGER-GATE
        with tempfile.TemporaryDirectory() as raw:
            result = validate_phase("pre-change", Path(raw), {"changeSet": {"files": ["scripts/app.py"]}})
        self.assertEqual(result["status"], "fail"); self.assertIn("LEDGER_CODE_INTELLIGENCE_REQUIRED", result["blockingReasons"])

    def test_append_is_idempotent_by_artifact_hash(self) -> None:
        ledger: dict = {}; evidence = {"artifactHash": HASH, "applicability": "not-applicable", "applicabilityEvidence": {"detectedPaths": [], "eligibleFileCount": 0, "changedCodeFileCount": 0, "reason": "docs only"}}
        append_code_intelligence_evidence(ledger, evidence); append_code_intelligence_evidence(ledger, evidence)
        self.assertEqual(len(ledger["codeIntelligence"]["evidenceEvents"]), 1)

    def test_unknown_impact_is_never_pass(self) -> None:
        code = {
            "schemaVersion": "1.0.0", "applicability": "applicable", "applicabilityEvidence": {"detectedPaths": ["app.py"], "eligibleFileCount": 1, "changedCodeFileCount": 1, "reason": "code"},
            "startingProcessVersion": "1.1.0", "activatedVersion": "1.1.0", "repositoryId": "repo-normal", "deliveryId": "delivery-normal",
            "provider": {"name": "code-graph-rag", "version": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"},
            "beforeManifest": {"path": "before.json", "sha256": HASH, "contentHash": HASH}, "beforeTraceBridge": {"path": "trace.json", "sha256": HASH, "contentHash": HASH},
            "preChangeImpactReports": [{"path": "impact.json", "sha256": HASH, "contentHash": HASH, "verdict": "UNKNOWN"}],
            "gateResults": [{"gateId": gate, "verdict": "PASS", "artifactHashes": [HASH], "commandRef": "fixture", "exitCode": 0, "timestamp": "2026-08-27T00:00:00Z"} for gate in ("C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-05")],
        }
        with tempfile.TemporaryDirectory() as raw:
            result = validate_phase("pre-change", Path(raw), {"deliveryId": "delivery-normal", "changeSet": {"files": ["app.py"]}, "codeIntelligence": code})
        self.assertNotEqual(result["status"], "pass"); self.assertIn("IMPACT_TRUNCATED", result["unknownReasons"])

    def test_recorded_c02_pass_cannot_hide_incomplete_manifest_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "before.json"
            manifest.write_text(json.dumps({"coverage": {"complete": False, "missingCaptures": []}}), encoding="utf-8")
            code = {
                "applicability": "applicable",
                "startingProcessVersion": "1.1.0",
                "activatedVersion": "1.1.0",
                "repositoryId": "repo-normal",
                "deliveryId": "delivery-normal",
                "provider": {"name": "code-graph-rag", "version": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"},
                "beforeManifest": {"path": "before.json", "sha256": file_hash(manifest), "contentHash": HASH},
                "beforeTraceBridge": {"path": "trace.json", "sha256": HASH, "contentHash": HASH},
                "preChangeImpactReports": [{"verdict": "NO_IMPACT"}],
                "gateResults": [{"gateId": gate, "verdict": "PASS", "commandRef": "fixture"} for gate in ("C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-05")],
            }
            report = validate_phase("pre-change", root, {"deliveryId": "delivery-normal", "changeSet": {"files": ["app.py"]}, "codeIntelligence": code})

        c02 = next(row for row in report["gateResults"] if row["gateId"] == "C-CODE-02")
        self.assertEqual((c02["verdict"], c02["code"]), ("BLOCK", "INDEX_RELATIONSHIP_CLASSIFICATION_REQUIRED"))

    def test_current_workspace_content_change_blocks_without_file_count_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = {
                "schemaVersion": "1.0.0", "enabled": True,
                "provider": {
                    "name": "code-graph-rag", "providerVersion": "0.0.779", "manifestVersion": 1,
                    "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84",
                    "requiredCaptures": ["structure", "calls", "types", "imports"],
                },
                "sourceExtensions": [".py", ".md"], "excludeDirectories": ["_test_output", ".tmp"],
                "excludePaths": ["docs/10-report.md"],
                "symbolKinds": ["FUNCTION"], "relationshipTypes": ["CALLS"],
                "limits": {"maxDepth": 8, "maxNodes": 10000, "timeoutSeconds": 10, "maxCandidates": 20},
            }
            config_dir = root / "assets" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "code-intelligence.json").write_text(json.dumps(config), encoding="utf-8")
            source = root / "app.py"
            source.write_text("value = 1\n", encoding="utf-8")
            report_file = root / "docs" / "10-report.md"
            report_file.parent.mkdir()
            report_file.write_text("quality report v1\n", encoding="utf-8")
            files, digest, _extensions, _repository = _inventory(root, config)
            manifest = {
                "schemaVersion": "1.1.0", "sourceDigest": digest,
                "configHash": content_hash(index_config_fingerprint(config), excluded_keys=()),
                "files": {"eligible": len(files), "indexed": len(files), "gapFiles": []},
                "relationships": {
                    "count": 0, "unresolved": 0, "resolvedInternal": 0, "auditedBoundary": 0,
                    "unresolvedInternal": 0, "legacyUnclassified": 0, "coverageHash": HASH,
                    "boundaryByType": {}, "boundaryByClass": {},
                },
                "coverage": {
                    "complete": True, "missingCaptures": [], "relationshipClassificationComplete": True,
                    "unresolvedInternalRelationshipCount": 0, "auditedBoundaryRelationshipCount": 0,
                    "relationshipCoverageHash": HASH,
                },
            }
            manifest_path = root / "before.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            code = {
                "applicability": "applicable", "startingProcessVersion": "1.1.0", "activatedVersion": "1.1.0",
                "repositoryId": "repo-normal", "deliveryId": "delivery-normal",
                "provider": {"name": "code-graph-rag", "version": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"},
                "beforeManifest": {"path": "before.json", "sha256": file_hash(manifest_path), "contentHash": HASH},
                "beforeTraceBridge": {"path": "trace.json", "sha256": HASH, "contentHash": HASH},
                "preChangeImpactReports": [{"verdict": "NO_IMPACT"}],
                "gateResults": [{"gateId": gate, "verdict": "PASS", "commandRef": "fixture"} for gate in ("C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-05")],
            }
            ledger = {"deliveryId": "delivery-normal", "changeSet": {"files": ["app.py"]}, "codeIntelligence": code}
            self.assertEqual(validate_phase("pre-change", root, ledger)["status"], "pass")
            report_file.write_text("quality report v2\n", encoding="utf-8")
            self.assertEqual(validate_phase("pre-change", root, ledger)["status"], "pass")
            source.write_text("value = 2\n", encoding="utf-8")
            report = validate_phase("pre-change", root, ledger)

        c01 = next(row for row in report["gateResults"] if row["gateId"] == "C-CODE-01")
        self.assertEqual((c01["verdict"], c01["code"]), ("BLOCK", "U-04"))
        self.assertIn("U-04", report["blockingReasons"])

    def test_c02_rejects_internal_relationship_gap_and_discloses_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "before.json"
            manifest.write_text(json.dumps({
                "schemaVersion": "1.1.0",
                "files": {"eligible": 1, "indexed": 1, "gapFiles": []},
                "relationships": {
                    "count": 1, "unresolved": 1, "resolvedInternal": 1, "auditedBoundary": 2,
                    "unresolvedInternal": 1, "legacyUnclassified": 0, "coverageHash": HASH,
                    "boundaryByType": {"IMPORTS": 2}, "boundaryByClass": {"EXTERNAL": 2},
                },
                "coverage": {
                    "complete": False, "missingCaptures": [], "relationshipClassificationComplete": True,
                    "unresolvedInternalRelationshipCount": 1, "auditedBoundaryRelationshipCount": 2,
                    "relationshipCoverageHash": HASH,
                },
            }), encoding="utf-8")
            code = {
                "applicability": "applicable", "startingProcessVersion": "1.1.0", "activatedVersion": "1.1.0",
                "repositoryId": "repo-normal", "deliveryId": "delivery-normal",
                "provider": {"name": "code-graph-rag", "version": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"},
                "beforeManifest": {"path": "before.json", "sha256": file_hash(manifest), "contentHash": HASH},
                "beforeTraceBridge": {"path": "trace.json", "sha256": HASH, "contentHash": HASH},
                "preChangeImpactReports": [{"verdict": "NO_IMPACT"}],
                "gateResults": [{"gateId": gate, "verdict": "PASS", "commandRef": "fixture"} for gate in ("C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-05")],
            }
            report = validate_phase("pre-change", root, {"deliveryId": "delivery-normal", "changeSet": {"files": ["app.py"]}, "codeIntelligence": code})
        c02 = next(row for row in report["gateResults"] if row["gateId"] == "C-CODE-02")
        self.assertEqual((c02["verdict"], c02["code"]), ("BLOCK", "INDEX_INTERNAL_RELATIONSHIP_GAP"))
        self.assertEqual(c02["relationshipSummary"]["boundaryByType"], {"IMPORTS": 2})

    def test_writer_public_parsers_merge_and_rich_cli_are_fail_closed(self) -> None:
        role = writer.parse_role_run("backend-engineer|blocked|manual|summary|bad|bad|a,b")
        self.assertEqual((role["durationMs"], role["retryCount"], role["blockedBy"]), (0, 0, ["a", "b"]))
        self.assertNotIn("changeSet", role)
        self.assertEqual(writer.parse_command("pytest|pass|ok|12")["durationMs"], 12)
        self.assertEqual(writer.parse_command("x")["status"], "not-run")
        event = writer.parse_event('role-start|started|backend|2026-01-01T00:00:00Z|{"x":1}')
        self.assertEqual(event["context"], {"x": 1})
        self.assertEqual(writer.parse_event("info|bad|||not-json")["context"], {"raw": "not-json"})
        self.assertNotIn("roleId", writer.parse_event("||||"))
        trace_row = writer.parse_trace("FR-1|summary|a.py,b.py|T-1|D-1|A-1")
        self.assertEqual(trace_row["designRef"], ["D-1"])
        self.assertNotIn("requirementSummary", writer.parse_trace("FR-2||a.py|T-2||"))
        reverse = writer.parse_reverse_sync("TASK-1|contract|code|FR-1|docs/prd.md|closed|1,2|done")
        self.assertEqual(reverse["context"]["prdSectionsUpdated"], ["1", "2"])
        self.assertNotIn("originFRId", writer.parse_reverse_sync("TASK-2|||||||" )["context"])

        with self.assertRaisesRegex(ValueError, "JSON object"):
            writer.append_code_intelligence_evidence({}, [])
        with self.assertRaisesRegex(ValueError, "codeIntelligence"):
            writer.append_code_intelligence_evidence({}, {"codeIntelligence": []})
        with self.assertRaisesRegex(ValueError, "ledger.codeIntelligence"):
            writer.append_code_intelligence_evidence({"codeIntelligence": []}, {})
        with self.assertRaisesRegex(ValueError, "evidenceEvents"):
            writer.append_code_intelligence_evidence({"codeIntelligence": {"evidenceEvents": {}}}, {})

        ledger: dict = {}
        incoming = {
            "schemaVersion": "1.0.0", "repositoryId": "repo-1",
            "preChangeImpactReports": [{"sha256": HASH}],
            "gateResults": [{"gateId": "C-CODE-01", "artifactHashes": [HASH], "verdict": "PASS"}],
        }
        writer.append_code_intelligence_evidence(ledger, {"codeIntelligence": incoming})
        writer.append_code_intelligence_evidence(ledger, {"artifactHash": HASH, "codeIntelligence": incoming})
        self.assertEqual(len(ledger["codeIntelligence"]["preChangeImpactReports"]), 1)
        self.assertEqual(len(ledger["codeIntelligence"]["gateResults"]), 1)
        with self.assertRaisesRegex(ValueError, "historical"):
            writer.append_code_intelligence_evidence(ledger, {"repositoryId": "repo-2"})

        errors = writer._validate_ledger({"roleRuns": {}, "commands": {}, "artifacts": {}, "qualityGates": {}}, Path("unused"))
        self.assertGreaterEqual(len(errors), 8)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger_path = root / "evidence-ledger.json"
            ledger_path.write_text("{broken", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                recreated = writer.load_or_create(ledger_path, "recovered")
            self.assertEqual(recreated["taskName"], "recovered")
            self.assertTrue(ledger_path.with_suffix(".corrupted.json").exists())
            self.assertIsNone(writer._backup_ledger(root / "missing.json"))

            gate_path = root / "gate.json"
            gate_path.write_text(json.dumps({"gateId": "Q", "status": "pass"}), encoding="utf-8")
            evidence_path = root / "evidence.json"
            evidence_path.write_text(json.dumps({"artifactHash": HASH, "applicability": "not-applicable"}), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = writer.main([
                    "--ledger", str(ledger_path), "--task-name", "rich", "--json",
                    "--role-run", "backend-engineer|completed|manual|done|10|1|",
                    "--command", "pytest|pass|ok|5", "--artifact", "a.txt", "--artifact", "a.txt",
                    "--quality-gate-json", str(gate_path), "--rework", "coverage",
                    "--security-block", "secret", "--event", "info|message||| ",
                    "--trace", "FR-1|summary|a.py|T-1|D-1|A-1",
                    "--reverse-sync-event", "TASK-1|||||closed|||",
                    "--code-intelligence-evidence", str(evidence_path), "--total-wall-time", "25",
                    "--delivery-id", "delivery-rich", "--starting-process-version", "1.0.0",
                ])
            self.assertEqual(code, 0)
            written = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(written["observability"]["reworkCount"], 1)
            self.assertEqual(written["observability"]["securityBlockCount"], 1)
            self.assertEqual(written["observability"]["totalWallTimeMs"], 25)
            self.assertEqual(written["artifacts"], ["a.txt"])


if __name__ == "__main__": unittest.main()
