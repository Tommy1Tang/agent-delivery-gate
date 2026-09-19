from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_code_impact import UNKNOWN_NAMES, analyze_impact, main as impact_main
from tests.code_intelligence.helpers import HASH_B, HASH_C, clone, snapshot, trace


class ImpactAnalysisTests(unittest.TestCase):
    def test_found_and_no_impact(self) -> None:
        found = analyze_impact(snapshot(), trace(), symbol="app.entry")
        self.assertEqual(found["verdict"], "FOUND"); self.assertIn("TEST-FR-001", found["recommendedTests"])
        snap = snapshot(); snap["relationships"] = []
        empty_trace = trace(); empty_trace["links"] = []
        no_impact = analyze_impact(snap, empty_trace, symbol="app.entry")
        self.assertEqual(no_impact["verdict"], "NO_IMPACT")

    def test_every_unknown_code_forces_unknown(self) -> None:
        # @trace FR-005 AC-005 AC-010 AC-015
        # @test-id TEST-CODE-IMPACT-UNKNOWN
        scenarios = {
            "U-01": lambda s, t, k: k.update(symbol="missing"),
            "U-02": lambda s, t, k: (s["symbols"].append({**s["symbols"][0], "symbolId": "sha256:" + "9" * 64, "qualifiedName": "other.entry"}), k.update(symbol="entry")),
            "U-03": lambda s, t, k: s["freshness"].update(headMatches=False),
            "U-04": lambda s, t, k: s["freshness"].update(sourceDigestMatches=False),
            "U-05": lambda s, t, k: s["freshness"].update(configMatches=False),
            "U-06": lambda s, t, k: s["providerState"].update(available=False),
            "U-07": lambda s, t, k: s["providerState"].update(schemaMatches=False),
            "U-08": lambda s, t, k: s["integrity"].update(valid=False),
            "U-09": lambda s, t, k: s["coverage"].update(complete=False, gapFiles=["x.rb"]),
            "U-10": lambda s, t, k: s.update(unresolvedSymbols=[{"id": "x"}]),
            "U-11": lambda s, t, k: s.update(unresolvedRelationships=[{"id": "x"}]),
            "U-12": lambda s, t, k: t.update(manifestHash="sha256:" + "e" * 64),
            "U-13": lambda s, t, k: k.clear() or k.update(requirement="FR-999"),
            "U-14": lambda s, t, k: k.update(depth=0),
            "U-15": lambda s, t, k: k.update(max_nodes=1),
            "U-16": lambda s, t, k: k.update(timeout_seconds=0),
            "U-17": lambda s, t, k: s["freshness"].update(sourceChangedDuringAnalysis=True),
            "U-18": lambda s, t, k: s.update(schemaVersion="2.0.0"),
        }
        self.assertEqual(set(scenarios), set(UNKNOWN_NAMES))
        for code, mutate in scenarios.items():
            with self.subTest(code=code):
                snap, bridge = clone(snapshot()), clone(trace()); kwargs = {"symbol": "app.entry"}; mutate(snap, bridge, kwargs)
                report = analyze_impact(snap, bridge, **kwargs)
                self.assertEqual(report["verdict"], "UNKNOWN"); self.assertIn(code, {row["code"] for row in report["unknownReasons"]})

    def test_boundary_hit_is_found_even_when_traversal_stops(self) -> None:
        snap = snapshot(); seed = snap["symbols"][0]
        snap["relationships"] = []
        snap["boundaryRelationships"] = [{
            "boundaryRelationshipId": HASH_B, "rawRelationshipId": HASH_C, "type": "IMPORTS", "internalSymbolId": seed["symbolId"],
            "internalRole": "SOURCE", "boundaryRole": "TARGET", "boundaryClass": "EXTERNAL", "boundaryKind": "UNDECLARED_EXTERNAL_MODULE",
            "boundaryKey": "external.package", "boundaryKeyHash": HASH_B,
            "classificationEvidence": [{"method": "REPOSITORY_MODULE_INVENTORY_NEGATIVE", "ruleId": "fixture", "artifactHash": HASH_C}],
            "classificationStatus": "AUDITED", "traversalPolicy": "STOP_AT_BOUNDARY", "classificationOrigin": "LEGACY_UNRESOLVED",
        }]
        snap["relationshipCoverage"]["profile"].update(resolvedInternalRelationshipCount=0, auditedBoundaryRelationshipCount=1)
        bridge = trace(); bridge["links"] = []
        report = analyze_impact(snap, bridge, symbol="app.entry")
        self.assertEqual(report["verdict"], "FOUND")
        self.assertEqual(report["affected"]["boundarySummary"]["total"], 1)
        self.assertEqual(report["affected"]["symbols"], [])

    def test_legacy_unresolved_projection_is_unknown(self) -> None:
        snap = snapshot(); snap["schemaVersion"] = "1.0.0"
        snap.pop("relationshipCoverage"); snap.pop("boundaryRelationships"); snap.pop("unresolvedInternalRelationships")
        snap["unresolvedRelationships"] = [{"reasonCode": "UNRESOLVED_RELATIONSHIP"}]
        report = analyze_impact(snap, trace(), symbol="app.entry")
        self.assertEqual(report["verdict"], "UNKNOWN")
        self.assertTrue({"U-11", "U-18"}.issubset({row["code"] for row in report["unknownReasons"]}))

    def test_cli_requires_trusted_artifact_root_and_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifact_root = root / "artifacts"
            artifact_root.mkdir()
            snapshot_path = root / "snapshot.json"
            trace_path = root / "trace.json"
            snapshot_path.write_text(json.dumps(snapshot()), encoding="utf-8")
            trace_path.write_text(json.dumps(trace()), encoding="utf-8")
            common = [
                "--snapshot", str(snapshot_path), "--trace-bridge", str(trace_path),
                "--symbol", "app.entry", "--artifact-root", str(artifact_root),
            ]
            inside = artifact_root / "impact.json"
            outside = root / "escaped.json"

            self.assertEqual(impact_main([*common, "--output", "impact.json"]), 0)
            self.assertTrue(inside.is_file())
            self.assertEqual(impact_main([*common, "--output", "../escaped.json"]), 2)
            self.assertFalse(outside.exists())

    def test_seed_resolution_and_malformed_relation_matrix(self) -> None:
        snap, bridge = snapshot(), trace()
        by_requirement = analyze_impact(snap, bridge, requirement="FR-001")
        self.assertEqual(by_requirement["seedResolution"]["status"], "RESOLVED")
        self.assertEqual(by_requirement["seedResolution"]["requirements"], ["FR-001"])

        by_file = analyze_impact(snap, bridge, file="app.py")
        self.assertEqual(by_file["seedResolution"]["files"], ["app.py"])
        for file_name in ("../escape.py", "missing.py"):
            with self.subTest(file=file_name):
                self.assertIn("U-01", {row["code"] for row in analyze_impact(snap, bridge, file=file_name)["unknownReasons"]})
        self.assertIn("U-01", {row["code"] for row in analyze_impact(snap, bridge, "invalid", "value")["unknownReasons"]})
        self.assertIn("U-01", {row["code"] for row in analyze_impact(snap, bridge, requirement="FR-001", symbol="app.entry")["unknownReasons"]})

        malformed = clone(snap)
        malformed["relationships"] = [None, {"type": "IGNORED"}, *malformed["relationships"]]
        malformed_bridge = clone(bridge)
        malformed_bridge["links"] = [None, {"status": "rejected"}, *malformed_bridge["links"]]
        self.assertEqual(analyze_impact(malformed, malformed_bridge, symbol="app.entry")["verdict"], "FOUND")

        non_list_trace = clone(bridge)
        non_list_trace["links"] = "bad"
        report = analyze_impact(snap, non_list_trace, requirement="FR-001")
        self.assertIn("U-13", {row["code"] for row in report["unknownReasons"]})

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            snapshot_path, trace_path = root / "snapshot.json", root / "trace.json"
            snapshot_path.write_text(json.dumps(snap), encoding="utf-8")
            trace_path.write_text(json.dumps(bridge), encoding="utf-8")
            artifact_file = root / "not-a-directory"
            artifact_file.write_text("file", encoding="utf-8")
            self.assertEqual(impact_main([
                "--snapshot", str(snapshot_path), "--trace-bridge", str(trace_path), "--file", "app.py",
                "--artifact-root", str(artifact_file), "--output", "impact.json",
            ]), 2)


if __name__ == "__main__": unittest.main()
