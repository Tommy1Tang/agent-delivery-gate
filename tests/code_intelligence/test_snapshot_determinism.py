from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_code_index import _inventory, build_index, index_config_fingerprint
from scripts.code_graph_provider import RawGraph
from scripts.code_intelligence_models import (
    ImpactVerdict,
    SymbolRef,
    atomic_write_json,
    canonical_json,
    content_hash,
    ensure_contained,
    load_json_object,
    normalize_relative_path,
)


CONFIG = {
    "provider": {"providerVersion": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84", "requiredCaptures": ["structure", "calls", "types", "imports"]},
    "sourceExtensions": [".py"], "excludeDirectories": ["_test_output", ".git", "__pycache__"]
}


class SnapshotDeterminismTests(unittest.TestCase):
    def test_three_builds_have_identical_stable_hashes(self) -> None:
        # @trace FR-001 AC-001 AC-009 AC-011 AC-012 AC-013 AC-014
        # @test-id TEST-CODE-INDEX-DETERMINISM
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); (root / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            graph = RawGraph(({"id": "f", "kind": "FUNCTION", "path": "app.py", "qualifiedName": "app.f", "startLine": 1, "endLine": 2},), (), {"capture": {"requested": ["structure", "calls", "types", "imports"]}})
            results = [build_index(root, root / "_test_output" / f"run-{index}", CONFIG, "fixture", raw_graph=graph) for index in range(3)]
        self.assertEqual({item.snapshot_hash for item in results}, {results[0].snapshot_hash})
        self.assertTrue(all(item.status == "SUCCESS" for item in results))

    def test_path_normalization_and_traversal(self) -> None:
        self.assertEqual(normalize_relative_path("a\\b.py"), "a/b.py")
        for invalid in ("../x.py", "C:\\x.py", "/x.py"):
            with self.assertRaises(ValueError): normalize_relative_path(invalid)

    def test_dirty_state_and_coverage_gap_affect_hash(self) -> None:
        first = {"source": {"dirty": False}, "coverage": {"complete": True}}
        second = {"source": {"dirty": True}, "coverage": {"complete": False}}
        self.assertNotEqual(content_hash(first), content_hash(second))

    def test_delivery_reports_are_excluded_without_hiding_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "app.py"
            source.write_text("value = 1\n", encoding="utf-8")
            report = root / "docs" / "10-report.md"
            report.parent.mkdir()
            report.write_text("quality report v1\n", encoding="utf-8")
            config = {
                **CONFIG,
                "sourceExtensions": [".py", ".md"],
                "excludePaths": ["docs\\10-report.md"],
            }

            files, first_digest, _extensions, repository = _inventory(root, config)
            self.assertEqual([row["relativePath"] for row in files], ["app.py"])
            self.assertNotIn("docs/10-report.md", repository)
            self.assertEqual(index_config_fingerprint(config)["excludePaths"], ["docs/10-report.md"])

            report.write_text("quality report v2\n", encoding="utf-8")
            self.assertEqual(_inventory(root, config)[1], first_digest)
            source.write_text("value = 2\n", encoding="utf-8")
            self.assertNotEqual(_inventory(root, config)[1], first_digest)

    def test_incomplete_snapshot_is_written_for_unknown_queries_but_not_successful(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app.py").write_text("def indexed(): pass\n", encoding="utf-8")
            (root / "missing.py").write_text("def missing(): pass\n", encoding="utf-8")
            graph = RawGraph(
                ({"id": "indexed", "kind": "FUNCTION", "path": "app.py", "qualifiedName": "app.indexed", "startLine": 1, "endLine": 1},),
                (),
                {"capture": {"requested": ["structure", "calls", "types", "imports"]}},
            )

            result = build_index(root, root / "_test_output" / "partial", CONFIG, "fixture", raw_graph=graph)

            self.assertEqual((result.status, result.code), ("UNKNOWN", "INDEX_COVERAGE_INCOMPLETE"))
            self.assertIsNotNone(result.snapshot_path)
            self.assertTrue(result.snapshot_path.is_file())
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
            self.assertFalse(snapshot["coverage"]["complete"])
            self.assertEqual(snapshot["coverage"]["gapFiles"], ["missing.py"])

    def test_model_contract_rejects_invalid_identity_paths_and_json(self) -> None:
        valid = SymbolRef("repo", "app.py", "app.entry", "function", 1, 2, "sha256:" + "a" * 64)
        self.assertIs(SymbolRef.from_value(valid), valid)
        self.assertEqual(SymbolRef.from_value(valid.to_dict()).symbolId, valid.symbolId)
        for values in (
            ("", "app.py", "app.entry", "FUNCTION", 1, 2, ""),
            ("repo", "app.py", "app.entry", "FUNCTION", 0, 2, ""),
            ("repo", "app.py", "app.entry", "FUNCTION", 2, 1, ""),
            ("repo", "app.py", "app.entry", "FUNCTION", 1, 2, "sha256:" + "a" * 64, "sha256:" + "f" * 64),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                SymbolRef(*values)
        for invalid in ("", "\x00", "a/../b.py"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                normalize_relative_path(invalid)

        payload = {
            "symbol": valid,
            "verdict": ImpactVerdict.FOUND,
            "path": Path("a/b"),
            "tuple": (2, 1),
            "set": {"b", "a"},
            "drop": "volatile",
        }
        encoded = json.loads(canonical_json(payload, excluded_keys=("drop",)))
        self.assertEqual(encoded["verdict"], "FOUND")
        self.assertEqual(encoded["path"], "a/b")
        self.assertEqual(encoded["set"], ["a", "b"])
        self.assertNotIn("drop", encoded)
        with self.assertRaises(ValueError):
            canonical_json(math.inf)
        with self.assertRaises(TypeError):
            canonical_json(object())

    def test_atomic_json_and_containment_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            target = root / "nested" / "value.json"
            atomic_write_json(target, {"ok": True}, allowed_root=root)
            self.assertEqual(load_json_object(target), {"ok": True})
            self.assertEqual(ensure_contained(root, root, allow_root=True), root)
            with self.assertRaisesRegex(ValueError, "root itself"):
                ensure_contained(root, root)
            with self.assertRaisesRegex(ValueError, "outside"):
                ensure_contained(root, root.parent / "escape.json")
            link = root / "link"
            link.mkdir()
            original_is_symlink = Path.is_symlink
            with patch.object(Path, "is_symlink", lambda self: self.name == "link" or original_is_symlink(self)):
                with self.assertRaisesRegex(ValueError, "symlinked"):
                    ensure_contained(root, link / "value.json")

            bad_json = root / "array.json"
            bad_json.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                load_json_object(bad_json)
            failed = root / "failed.json"
            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_json(failed, {"ok": False}, allowed_root=root)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.json.*.tmp")), [])


if __name__ == "__main__": unittest.main()
