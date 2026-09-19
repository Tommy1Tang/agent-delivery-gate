from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import query_code_graph as query
from scripts.query_code_graph import INTENTS, execute_query, parse_controlled_intent
from tests.code_intelligence.helpers import HASH_A, HASH_B, HASH_C, clone, snapshot, trace


class QueryIntentTests(unittest.TestCase):
    def test_all_seven_intents_parse_in_chinese_and_english(self) -> None:
        # @trace FR-002 AC-002 AC-011 AC-012
        # @test-id TEST-CODE-CONTROLLED-QUERY
        pairs = [
            ("app.entry 在哪里定义", "where is app.entry defined"), ("谁调用 app.worker", "who calls app.worker"),
            ("app.entry 调用了谁", "what does app.entry call"), ("谁引用 app.worker", "references to app.worker"),
            ("模块 app.entry 包含什么", "what is in module app.entry"), ("FR-001 由什么实现", "implementation of FR-001"),
            ("哪些测试覆盖 app.entry", "tests covering app.entry"),
        ]
        parsed = [parse_controlled_intent(question).intent for pair in pairs for question in pair]
        self.assertEqual(set(parsed), set(INTENTS))

    def test_queries_return_symbol_and_path_evidence(self) -> None:
        callers = execute_query(snapshot(), trace(), "callers", "app.worker").to_dict()
        self.assertEqual(callers["queryStatus"], "ANSWERED"); self.assertEqual(callers["symbols"][0]["qualifiedName"], "app.entry")
        self.assertEqual(callers["relationPaths"][0]["types"], ["CALLS"])
        requirement = execute_query(snapshot(), trace(), "implements_requirement", "FR-001").to_dict()
        self.assertEqual(requirement["symbols"][0]["qualifiedName"], "app.entry")

    def test_ambiguous_symbol_returns_candidates(self) -> None:
        snap = snapshot(); duplicate = dict(snap["symbols"][0]); duplicate["qualifiedName"] = "other.entry"; duplicate["symbolId"] = "sha256:" + "d" * 64; snap["symbols"].append(duplicate)
        result = execute_query(snap, trace(), "definition", "entry").to_dict()
        self.assertEqual(result["queryStatus"], "AMBIGUOUS"); self.assertEqual(len(result["candidates"]), 2)

    def test_boundary_hit_is_answered_and_disclosed(self) -> None:
        snap = snapshot(); seed = snap["symbols"][0]
        boundary = {
            "boundaryRelationshipId": HASH_B, "rawRelationshipId": HASH_C, "type": "CALLS", "internalSymbolId": seed["symbolId"],
            "internalRole": "SOURCE", "boundaryRole": "TARGET", "boundaryClass": "EXTERNAL", "boundaryKind": "UNDECLARED_EXTERNAL_MODULE",
            "boundaryKey": "external.package", "boundaryKeyHash": HASH_B,
            "classificationEvidence": [{"method": "REPOSITORY_MODULE_INVENTORY_NEGATIVE", "ruleId": "fixture", "artifactHash": HASH_C}],
            "classificationStatus": "AUDITED", "traversalPolicy": "STOP_AT_BOUNDARY", "classificationOrigin": "LEGACY_UNRESOLVED",
        }
        snap["relationships"] = []
        snap["boundaryRelationships"] = [boundary]
        snap["relationshipCoverage"]["profile"].update(resolvedInternalRelationshipCount=0, auditedBoundaryRelationshipCount=1)
        result = execute_query(snap, trace(), "callees", "app.entry").to_dict()
        self.assertEqual(result["queryStatus"], "ANSWERED")
        self.assertEqual(result["boundarySummary"]["total"], 1)
        self.assertEqual(result["symbols"], [])

    def test_legacy_snapshot_requires_reindex(self) -> None:
        snap = snapshot(); snap["schemaVersion"] = "1.0.0"
        snap.pop("relationshipCoverage"); snap.pop("boundaryRelationships"); snap.pop("unresolvedInternalRelationships")
        result = execute_query(snap, trace(), "definition", "app.entry").to_dict()
        self.assertEqual(result["queryStatus"], "UNKNOWN")
        self.assertIn("profile 1.1", result["diagnostics"][0])

    def test_query_status_and_trace_resolution_matrix(self) -> None:
        snap = snapshot()
        bridge = trace()
        self.assertEqual(parse_controlled_intent("   ").status, "UNSUPPORTED_INTENT")
        self.assertEqual(parse_controlled_intent("explain everything").status, "UNSUPPORTED_INTENT")
        self.assertEqual(execute_query(snap, bridge, "invented", "app.entry").to_dict()["queryStatus"], "UNSUPPORTED_INTENT")

        incomplete = clone(snap)
        incomplete["coverage"]["complete"] = False
        self.assertEqual(execute_query(incomplete, bridge, "definition", "app.entry").to_dict()["queryStatus"], "UNKNOWN")
        stale = clone(bridge)
        stale["sourceDigest"] = HASH_C
        self.assertIn("stale", execute_query(snap, stale, "definition", "app.entry").to_dict()["diagnostics"][0])

        self.assertEqual(execute_query(snap, bridge, "definition", "missing").to_dict()["queryStatus"], "NO_MATCH")
        self.assertEqual(execute_query(snap, bridge, "implements_requirement", "not-an-id").to_dict()["queryStatus"], "NO_MATCH")
        self.assertEqual(execute_query(snap, bridge, "implements_requirement", "FR-999").to_dict()["queryStatus"], "NO_MATCH")
        malformed_links = clone(bridge)
        malformed_links["links"] = [None, {"status": "exact", "role": "implementation", "requirementIds": ["FR-001"], "symbolRef": "bad"}]
        self.assertEqual(execute_query(snap, malformed_links, "implements_requirement", "FR-001").to_dict()["queryStatus"], "NO_MATCH")

        by_requirement = execute_query(snap, bridge, "tests_for", "FR-001").to_dict()
        self.assertEqual(by_requirement["symbols"][0]["qualifiedName"], "app.worker")
        by_symbol = execute_query(snap, bridge, "tests_for", "app.entry").to_dict()
        self.assertEqual(by_symbol["symbols"][0]["qualifiedName"], "app.worker")
        self.assertEqual(execute_query(snap, bridge, "tests_for", "missing").to_dict()["queryStatus"], "NO_MATCH")
        no_tests = clone(bridge)
        no_tests["links"] = [no_tests["links"][0], "bad"]
        self.assertEqual(execute_query(snap, no_tests, "tests_for", "FR-001").to_dict()["queryStatus"], "NO_MATCH")
        duplicate = clone(snap["symbols"][0])
        duplicate["qualifiedName"] = "other.entry"
        duplicate["symbolId"] = "sha256:" + "d" * 64
        ambiguous = clone(snap)
        ambiguous["symbols"].append(duplicate)
        self.assertEqual(execute_query(ambiguous, bridge, "tests_for", "entry", max_candidates=1).to_dict()["queryStatus"], "AMBIGUOUS")

    def test_relation_direction_and_boundary_matrix(self) -> None:
        base = snapshot()
        bridge = trace()
        first, second = base["symbols"]
        cases = (
            ("callees", "app.entry", "CALLS", first["symbolId"], second["symbolId"], "app.worker"),
            ("callers", "app.worker", "CALLS", first["symbolId"], second["symbolId"], "app.entry"),
            ("references", "app.worker", "REFERENCES", first["symbolId"], second["symbolId"], "app.entry"),
            ("references", "app.worker", "INSTANTIATES", first["symbolId"], second["symbolId"], "app.entry"),
            ("contains", "app.entry", "CONTAINS", first["symbolId"], second["symbolId"], "app.worker"),
            ("contains", "app.entry", "DEFINES", first["symbolId"], second["symbolId"], "app.worker"),
            ("contains", "app.entry", "DEFINES_METHOD", first["symbolId"], second["symbolId"], "app.worker"),
        )
        for intent, target, relation_type, source, destination, expected in cases:
            with self.subTest(intent=intent, relation=relation_type):
                snap = clone(base)
                snap["relationships"] = [None, {"type": "IGNORED"}, {"type": relation_type, "sourceSymbolId": source, "targetSymbolId": destination}]
                result = execute_query(snap, bridge, intent, target).to_dict()
                self.assertEqual(result["queryStatus"], "ANSWERED")
                self.assertEqual(result["symbols"][0]["qualifiedName"], expected)

        no_edge = clone(base)
        no_edge["relationships"] = [{"type": "CALLS", "sourceSymbolId": HASH_C, "targetSymbolId": HASH_A}]
        self.assertEqual(execute_query(no_edge, bridge, "callees", "app.entry").to_dict()["queryStatus"], "NO_MATCH")

        reverse_boundary = clone(base)
        reverse_boundary["relationships"] = []
        reverse_boundary["boundaryRelationships"] = [
            None,
            {"type": "IGNORED"},
            {
                "type": "CALLS", "internalSymbolId": second["symbolId"], "internalRole": "TARGET",
                "boundaryClass": "EXTERNAL", "boundaryKind": "PACKAGE", "boundaryKeyHash": HASH_C,
            },
        ]
        result = execute_query(reverse_boundary, bridge, "callers", "app.worker").to_dict()
        self.assertEqual(result["queryStatus"], "ANSWERED")
        self.assertEqual(result["boundarySummary"]["total"], 1)

    def test_query_cli_success_unsupported_and_io_failure(self) -> None:
        snap, bridge = snapshot(), trace()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            snapshot_path, bridge_path = root / "snapshot.json", root / "bridge.json"
            snapshot_path.write_text(json.dumps(snap), encoding="utf-8")
            bridge_path.write_text(json.dumps(bridge), encoding="utf-8")
            commands = (
                (["query", "--snapshot", str(snapshot_path), "--trace-bridge", str(bridge_path), "--question", "where is app.entry defined", "--json"], 0),
                (["query", "--snapshot", str(snapshot_path), "--trace-bridge", str(bridge_path), "--question", "explain everything"], 1),
                (["query", "--snapshot", str(root / "missing.json"), "--trace-bridge", str(bridge_path), "--intent", "definition", "--target", "app.entry"], 2),
            )
            for argv, expected in commands:
                with self.subTest(argv=argv), patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                    self.assertEqual(query.main(), expected)
            with patch.object(sys, "argv", ["query", "--snapshot", str(snapshot_path), "--trace-bridge", str(bridge_path), "--intent", "definition"]), self.assertRaises(SystemExit) as raised:
                query.main()
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__": unittest.main()
