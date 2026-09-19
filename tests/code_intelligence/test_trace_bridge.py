from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import materialize_trace_links as trace_materializer
from scripts.materialize_trace_links import Declaration, load_requirement_catalog, materialize_trace_links, parse_declarations, resolve_minimal_symbol
from tests.code_intelligence.helpers import HASH_A, HASH_B, symbol


class TraceBridgeTests(unittest.TestCase):
    def test_strict_parser_and_minimal_owner(self) -> None:
        # @trace FR-003 AC-003
        # @test-id TEST-CODE-TRACE-BRIDGE
        declarations = parse_declarations("# @trace FR-001 AC-001\n# @test-id TEST-FR-001\n# @trace unknown words\n")
        self.assertEqual([row.valid for row in declarations], [True, True, False])
        outer = symbol("app.py", "outer", 1, 20); inner = symbol("app.py", "inner", 3, 8)
        declaration = Declaration("trace", ("FR-001",), 5, "# @trace FR-001", "app.py")
        self.assertEqual(resolve_minimal_symbol(declaration, [outer, inner]).symbol.qualifiedName, "inner")

    def test_markdown_fenced_code_is_not_an_authoritative_declaration(self) -> None:
        markdown = "\n".join((
            "<!-- @trace FR-001 AC-001 -->",
            "   ````text",
            "# @trace FR-999 AC-999",
            "```",
            "# @trace FR-998 AC-998",
            "   ````   ",
            "// @trace FR-002 AC-002",
            "~~~python",
            "# @test-id TEST-IN-FENCE",
            "~~~~",
            "<!-- @test-id TEST-OUTSIDE -->",
        ))

        declarations = parse_declarations(markdown, markdown=True)

        self.assertEqual(
            [(row.kind, row.values, row.line) for row in declarations],
            [
                ("trace", ("FR-001", "AC-001"), 1),
                ("trace", ("FR-002", "AC-002"), 7),
                ("test-id", ("TEST-OUTSIDE",), 11),
            ],
        )

    def test_unclosed_markdown_fence_suppresses_declarations_through_eof(self) -> None:
        markdown = "   ~~~ markdown\n# @trace FR-999 AC-999\n# @test-id TEST-IN-FENCE\n"

        self.assertEqual(parse_declarations(markdown, markdown=True), [])

    def test_ambiguous_and_orphan_are_rejected(self) -> None:
        declaration = Declaration("trace", ("FR-001",), 5, "# @trace FR-001", "app.py")
        same_a = symbol("app.py", "a", 1, 10); same_b = symbol("app.py", "b", 1, 10)
        self.assertEqual(resolve_minimal_symbol(declaration, [same_a, same_b]).reason_code, "AMBIGUOUS_SYMBOL_OWNER")
        self.assertEqual(resolve_minimal_symbol(Declaration("trace", ("FR-001",), 99, "", "app.py"), [same_a]).reason_code, "ORPHAN_DECLARATION")

    def test_duplicate_test_and_unknown_id_do_not_create_exact_links(self) -> None:
        # @trace FR-004 AC-004
        # @test-id TEST-CODE-TRACE-GATE
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = "def prod():\n    # @trace FR-001 FR-999\n    pass\n\ndef test_a():\n    # @trace FR-001\n    # @test-id TEST-DUP\n    pass\n\ndef test_b():\n    # @trace FR-001\n    # @test-id TEST-DUP\n    pass\n"
            (root / "app.py").write_text(source, encoding="utf-8")
            requirements = root / "requirements.json"; requirements.write_text(json.dumps({"knownIds": ["FR-001", "AC-001"], "requiredIds": ["FR-001"]}), encoding="utf-8")
            snap = {"manifestHash": HASH_A, "sourceDigest": HASH_B, "symbols": [symbol("app.py", "prod", 1, 3), symbol("app.py", "test_a", 5, 8), symbol("app.py", "test_b", 10, 13)]}
            bridge = materialize_trace_links(root, snap, requirements).to_dict()
        codes = [row["reasonCode"] for row in bridge["rejected"]]
        self.assertIn("UNKNOWN_REQUIREMENT_ID", codes); self.assertEqual(codes.count("DUPLICATE_TEST_ID"), 2)
        self.assertTrue(all(row["role"] != "test" for row in bridge["links"]))

    def test_requirement_catalog_accepts_json_shapes_and_markdown_priorities(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cases = (
                ("array.json", [{"id": "FR-001", "priority": "Must"}, None, {"requirementId": "AC-001", "required": True}], {"FR-001", "AC-001"}, {"FR-001", "AC-001"}),
                ("object.json", {"knownIds": ["FR-002"], "requiredIds": ["FR-002"], "items": [{"id": "NFR-001", "moscow": "P0-MUST"}]}, {"FR-002", "NFR-001"}, {"FR-002", "NFR-001"}),
                ("nonlists.json", {"knownIds": "FR-003", "requiredIds": None, "requirements": "bad"}, set(), set()),
            )
            for name, value, expected_known, expected_required in cases:
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                known, required, digest = load_requirement_catalog(path)
                self.assertEqual((known, required), (expected_known, expected_required))
                self.assertTrue(digest.startswith("sha256:"))
            markdown = root / "requirements.md"
            markdown.write_text("| FR-004 | Must |\nAC-004 P0\nNFR-002 should\n", encoding="utf-8")
            known, required, _digest = load_requirement_catalog(markdown)
            self.assertEqual(known, {"FR-004", "AC-004", "NFR-002"})
            self.assertEqual(required, {"FR-004", "AC-004"})
            scalar = root / "scalar.json"
            scalar.write_text("42", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "object or array"):
                load_requirement_catalog(scalar)

    def test_trace_materialization_success_rejections_and_output(self) -> None:
        malformed = parse_declarations("# @trace\n# @trace FR-001 FR-001\n# @trace FR-001 BAD\n# @test-id\n# @test-id bad\n")
        self.assertTrue(all(not row.valid for row in malformed))
        self.assertEqual(parse_declarations("```bad`info\n# @trace FR-001\n", markdown=True)[0].values, ("FR-001",))

        declaration = Declaration("trace", ("FR-001",), 2, "", "app.py")
        valid = symbol("app.py", "app.f", 1, 4)
        self.assertEqual(resolve_minimal_symbol(declaration, [{"bad": True}, symbol("other.py", "other.f", 1, 4), valid]).status, "exact")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            requirements = root / "requirements.json"
            requirements.write_text(json.dumps({"knownIds": ["FR-001"]}), encoding="utf-8")
            source = "def f():\n    # @trace FR-001\n    # @test-id TEST-F-001\n    pass\n\ndef orphan():\n    # @trace FR-001\n"
            (root / "app.py").write_text(source, encoding="utf-8")
            snap = {
                "manifestHash": HASH_A,
                "sourceDigest": HASH_B,
                "symbols": [symbol("app.py", "app.f", 1, 4), symbol("missing.py", "missing.f", 1, 2)],
            }
            output = root / "artifacts" / "trace.json"
            bridge = materialize_trace_links(root, snap, requirements, output).to_dict()
            self.assertTrue(output.is_file())
            self.assertEqual(bridge["links"][0]["role"], "test")
            self.assertEqual(bridge["links"][0]["testId"], "TEST-F-001")

            invalid_snap = dict(snap)
            invalid_snap["symbols"] = "bad"
            with self.assertRaisesRegex(ValueError, "symbols must be an array"):
                materialize_trace_links(root, invalid_snap, requirements)

    def test_trace_materializer_cli_success_rejected_and_schema_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            requirements = root / "requirements.json"
            requirements.write_text(json.dumps({"knownIds": ["FR-001"]}), encoding="utf-8")
            (root / "app.py").write_text("def f():\n    # @trace FR-001\n    pass\n", encoding="utf-8")
            snap = {"manifestHash": HASH_A, "sourceDigest": HASH_B, "symbols": [symbol("app.py", "app.f", 1, 3)]}
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(json.dumps(snap), encoding="utf-8")
            commands = (
                (["trace", "--project-root", str(root), "--snapshot", str(snapshot_path), "--requirements", str(requirements), "--output", str(root / "ok.json"), "--json"], 0),
                (["trace", "--project-root", str(root), "--snapshot", str(root / "missing.json"), "--requirements", str(requirements), "--output", str(root / "bad.json")], 1),
            )
            for argv, expected in commands:
                with self.subTest(argv=argv), patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                    self.assertEqual(trace_materializer.main(), expected)
            (root / "app.py").write_text("def f():\n    # @trace FR-999\n    pass\n", encoding="utf-8")
            argv = ["trace", "--project-root", str(root), "--snapshot", str(snapshot_path), "--requirements", str(requirements), "--output", str(root / "rejected.json")]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(trace_materializer.main(), 1)


if __name__ == "__main__": unittest.main()
