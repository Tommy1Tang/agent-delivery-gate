from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_code_impact import analyze_impact
from scripts.code_intelligence_models import content_hash
from scripts.reconcile_code_changes import _trace_semantic_hash, build_index_diff, main as reconcile_main
from tests.code_intelligence.helpers import clone, snapshot, trace


class ReconcileTests(unittest.TestCase):
    def _changed(self):
        before = snapshot(); after = clone(before); after["files"][0]["sha256"] = "sha256:" + "f" * 64; after["sourceDigest"] = "sha256:" + "8" * 64
        after["contentHash"] = content_hash(after); before_trace = trace(); after_trace = clone(before_trace); after_trace["sourceDigest"] = after["sourceDigest"]
        impact = analyze_impact(before, before_trace, symbol="app.entry")
        return before, after, before_trace, after_trace, impact

    def test_valid_change_set_passes(self) -> None:
        # @trace FR-006 AC-006 AC-015
        # @test-id TEST-CODE-RECONCILE
        before, after, before_trace, after_trace, impact = self._changed()
        result = build_index_diff(before, after, before_trace, after_trace, impact, {"codeFiles": ["app.py"]})
        self.assertEqual(result["gateVerdict"], "PASS")

    def test_snapshot_bound_symbol_ids_do_not_create_false_trace_regressions(self) -> None:
        before, after, before_trace, after_trace, impact = self._changed()
        replacement_ids = {}
        for symbol in after["symbols"]:
            symbol["manifestHash"] = "sha256:" + "9" * 64
            symbol["symbolId"] = content_hash([
                symbol["repositoryId"], symbol["relativePath"], symbol["qualifiedName"],
                symbol["symbolKind"], symbol["manifestHash"],
            ], excluded_keys=())
            replacement_ids[symbol["qualifiedName"]] = symbol["symbolId"]
        for link in after_trace["links"]:
            link["symbolRef"]["manifestHash"] = "sha256:" + "9" * 64
            link["symbolRef"]["symbolId"] = replacement_ids[link["symbolRef"]["qualifiedName"]]
        after_trace["manifestHash"] = "sha256:" + "9" * 64

        result = build_index_diff(before, after, before_trace, after_trace, impact, {"codeFiles": ["app.py"]})

        self.assertEqual(result["symbolChanges"], [])
        self.assertEqual(result["traceChanges"], [])
        self.assertEqual(result["reconciliation"]["traceRegressions"], [])
        self.assertEqual(result["gateVerdict"], "PASS")
        self.assertNotEqual(
            _trace_semantic_hash({"role": "implementation", "requirementIds": ["FR-001"]}),
            _trace_semantic_hash({"role": "implementation", "requirementIds": ["FR-001"], "symbolRef": None}),
        )

    def test_undeclared_file_and_trace_loss_block(self) -> None:
        before, after, before_trace, after_trace, impact = self._changed(); after_trace["links"] = []
        result = build_index_diff(before, after, before_trace, after_trace, impact, {"codeFiles": []})
        codes = {row["code"] for row in result["reconciliation"]["findings"]}
        self.assertEqual(result["gateVerdict"], "BLOCK"); self.assertIn("UNDECLARED_FILE_CHANGE", codes); self.assertIn("TRACE_COVERAGE_REGRESSION", codes)

    def test_schema_or_head_race_is_unknown(self) -> None:
        before, after, before_trace, after_trace, impact = self._changed(); after["schemaVersion"] = "2.0.0"; after["freshness"]["headMatches"] = False
        result = build_index_diff(before, after, before_trace, after_trace, impact, {"codeFiles": ["app.py"]})
        self.assertEqual(result["gateVerdict"], "UNKNOWN")

    def test_cli_writes_only_below_explicit_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifact_root = root / "artifacts"
            artifact_root.mkdir()
            before, after, before_trace, after_trace, impact = self._changed()
            inputs = {
                "before-snapshot": before,
                "after-snapshot": after,
                "before-trace": before_trace,
                "after-trace": after_trace,
                "impact-report": impact,
                "change-set": {"codeFiles": ["app.py"]},
            }
            arguments: list[str] = []
            for name, value in inputs.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                arguments.extend((f"--{name}", str(path)))
            arguments.extend(("--artifact-root", str(artifact_root)))
            inside = artifact_root / "diff.json"
            outside = root / "escaped.json"

            self.assertEqual(reconcile_main([*arguments, "--output", "diff.json"]), 0)
            self.assertTrue(inside.is_file())
            self.assertEqual(reconcile_main([*arguments, "--output", "../escaped.json"]), 2)
            self.assertFalse(outside.exists())


if __name__ == "__main__": unittest.main()
