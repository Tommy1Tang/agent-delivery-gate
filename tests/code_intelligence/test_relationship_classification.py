from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.build_code_index import build_index, validate_relationship_accounting
from scripts.code_graph_provider import RawGraph
from scripts.validate_code_intelligence import _manifest_has_complete_coverage


CONFIG = {
    "provider": {
        "providerVersion": "0.0.779",
        "manifestVersion": 1,
        "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84",
        "requiredCaptures": ["structure", "calls", "types", "imports"],
    },
    "sourceExtensions": [".py", ".md"],
    "excludeDirectories": ["_test_output", ".git", "__pycache__"],
}


def _relation(kind: str, source_id: str, target_id: str, source_label: str, target_label: str) -> dict[str, str]:
    return {
        "type": kind,
        "source_id": source_id,
        "target_id": target_id,
        "source_label": source_label,
        "target_label": target_label,
    }


def _migration_graph(root: Path) -> RawGraph:
    (root / "app.py").write_text("first = 1\nsecond = 2\nthird = 3\n", encoding="utf-8")
    nodes: list[dict[str, object]] = [
        {"id": "mod-app", "kind": "MODULE", "path": "app.py", "qualifiedName": "repository.app"},
        {"id": "klass", "kind": "CLASS", "path": "app.py", "qualifiedName": "app.Klass", "startLine": 1, "endLine": 3},
        {"id": "direct-a", "kind": "FUNCTION", "path": "app.py", "qualifiedName": "app.direct_a", "startLine": 1, "endLine": 1},
        {"id": "direct-b", "kind": "FUNCTION", "path": "app.py", "qualifiedName": "app.direct_b", "startLine": 2, "endLine": 2},
    ]
    relationships: list[dict[str, str]] = [
        _relation("CALLS", "direct-a", "direct-b", "Function", "Function"),
    ]

    for index in range(66):
        function_id = f"called-{index:03d}"
        nodes.append({"id": function_id, "kind": "FUNCTION", "path": "app.py", "qualifiedName": f"app.called_{index:03d}", "startLine": 1, "endLine": 1})
        relationships.append(_relation("CALLS", "mod-app", function_id, "Module", "Function"))

    for index in range(25):
        relative_path = f"internal/module_{index:03d}.py"
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"VALUE = {index}\n", encoding="utf-8")
        module_id = f"mod-internal-{index:03d}"
        nodes.append({"id": module_id, "kind": "MODULE", "path": relative_path, "qualifiedName": f"repository.internal.module_{index:03d}"})
        relationships.append(_relation("IMPORTS", "mod-app", module_id, "Module", "Module"))

    reference_id = "reference-target"
    nodes.append({"id": reference_id, "kind": "FUNCTION", "path": "app.py", "qualifiedName": "app.reference_target", "startLine": 3, "endLine": 3})
    relationships.append(_relation("REFERENCES", "mod-app", reference_id, "Module", "Function"))

    for index in range(11):
        relative_path = f"references/target_{index:03d}.md"
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Target {index}\n", encoding="utf-8")
        file_id = f"file-markdown-{index:03d}"
        module_id = f"mod-markdown-{index:03d}"
        nodes.extend([
            {"id": file_id, "kind": "FILE", "path": relative_path, "qualifiedName": relative_path},
            {"id": module_id, "kind": "MODULE", "path": relative_path, "qualifiedName": f"repository.references.target_{index:03d}"},
        ])
        relationships.append(_relation("LINKS_TO", "mod-app", file_id, "Module", "File"))

    for index in range(2):
        relative_path = f"assets/noneligible_{index:03d}.json"
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        file_id = f"file-json-{index:03d}"
        nodes.append({"id": file_id, "kind": "FILE", "path": relative_path, "qualifiedName": relative_path})
        relationships.append(_relation("LINKS_TO", "mod-app", file_id, "Module", "File"))

    relationships.extend(
        _relation("IMPORTS", "mod-app", f"external-{index:03d}", "Module", "ExternalModule")
        for index in range(496)
    )
    relationships.extend(
        _relation("INHERITS", "klass", f"base-{index:03d}", "Class", "ExternalModule")
        for index in range(10)
    )
    return RawGraph(tuple(nodes), tuple(relationships), {"capture": {"requested": ["structure", "calls", "types", "imports"]}})


class RelationshipClassificationTests(unittest.TestCase):
    def test_frozen_611_partition_and_module_identity(self) -> None:
        # @trace FR-001 FR-005 AC-001 AC-005 AC-015
        # @test-id TEST-CODE-RELATIONSHIP-PARTITION
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = build_index(root, root / "_test_output" / "partition", CONFIG, "fixture", raw_graph=_migration_graph(root))
            self.assertEqual((result.status, result.code), ("SUCCESS", "OK"))
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        coverage = snapshot["relationshipCoverage"]
        self.assertEqual(coverage["classifiableProviderRelationshipCount"], 611)
        self.assertEqual(coverage["resolvedInternalCount"], 103)
        self.assertEqual(coverage["auditedBoundaryCount"], 508)
        self.assertEqual(coverage["unresolvedInternalCount"], 0)
        self.assertEqual(coverage["profile"]["nonStructuralProviderRelationshipCount"], 612)
        self.assertEqual(coverage["profile"]["resolvedInternalRelationshipCount"], 104)
        self.assertEqual(len(snapshot["relationships"]), 104)
        self.assertEqual(len(snapshot["boundaryRelationships"]), 508)
        self.assertEqual(snapshot["unresolvedInternalRelationships"], [])
        self.assertEqual(snapshot["unresolvedRelationships"], [])
        self.assertEqual(manifest["relationships"]["coverageHash"], coverage["contentHash"])
        self.assertTrue(validate_relationship_accounting(snapshot, manifest)["valid"])
        self.assertTrue(_manifest_has_complete_coverage(manifest))

        module = next(symbol for symbol in snapshot["symbols"] if symbol["qualifiedName"] == "repository.app")
        self.assertEqual((module["symbolKind"], module["startLine"], module["endLine"]), ("MODULE", 1, 3))
        aliases = [relation for relation in snapshot["relationships"] if relation["targetResolution"] == "ELIGIBLE_FILE_TO_MODULE"]
        self.assertEqual(len(aliases), 11)

    def test_accounting_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = build_index(root, root / "_test_output" / "tamper", CONFIG, "fixture", raw_graph=_migration_graph(root))
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        snapshot["boundaryRelationships"].pop()
        validation = validate_relationship_accounting(snapshot, manifest)
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["code"], "INDEX_RELATIONSHIP_ACCOUNTING_MISMATCH")

    def test_uncertain_missing_endpoint_is_internal_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            graph = RawGraph(
                ({"id": "mod-app", "kind": "MODULE", "path": "app.py", "qualifiedName": "repository.app"},),
                (_relation("IMPORTS", "mod-app", "not-proven-external", "Module", "Mystery"),),
                {"capture": {"requested": ["structure", "calls", "types", "imports"]}},
            )
            result = build_index(root, root / "_test_output" / "gap", CONFIG, "fixture", raw_graph=graph)
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual((result.status, result.code), ("UNKNOWN", "INDEX_INTERNAL_RELATIONSHIP_GAP"))
        self.assertEqual(len(snapshot["unresolvedInternalRelationships"]), 1)
        self.assertEqual(snapshot["unresolvedRelationships"][0]["reasonCode"], "INTERNAL_TARGET_UNRESOLVED")
        self.assertFalse(snapshot["relationshipCoverage"]["internalGraphComplete"])

    def test_legacy_mixed_unresolved_requires_reindex(self) -> None:
        legacy = {
            "schemaVersion": "1.0.0",
            "relationships": [],
            "unresolvedRelationships": [{"type": "IMPORTS", "sourceProviderId": "module", "targetProviderId": "unknown", "reasonCode": "UNRESOLVED_RELATIONSHIP"}],
        }
        validation = validate_relationship_accounting(legacy)
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["code"], "INDEX_RELATIONSHIP_CLASSIFICATION_REQUIRED")

    def test_accounting_mutation_matrix_fails_closed_at_each_contract_layer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = build_index(root, root / "_test_output" / "matrix", CONFIG, "fixture", raw_graph=_migration_graph(root))
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        def rejected(mutator, *, mutate_manifest: bool = False) -> None:
            snap, man = deepcopy(snapshot), deepcopy(manifest)
            mutator(man if mutate_manifest else snap)
            self.assertFalse(validate_relationship_accounting(snap, man)["valid"])

        rejected(lambda value: value.__setitem__("relationships", {}))
        rejected(lambda value: value["relationships"].append(deepcopy(value["relationships"][0])))
        rejected(lambda value: value["relationshipCoverage"].__setitem__("profile", None))
        rejected(lambda value: value["relationshipCoverage"]["profile"].__setitem__("accountingComplete", False))
        rejected(lambda value: value["relationships"].__setitem__(0, None))
        rejected(lambda value: value["relationships"][0].__setitem__("sourceSymbolId", "missing"))
        rejected(lambda value: value["relationships"][0].__setitem__("relationshipId", "sha256:" + "0" * 64))

        external_index = next(i for i, row in enumerate(snapshot["boundaryRelationships"]) if row["boundaryClass"] == "EXTERNAL")
        noneligible_index = next(i for i, row in enumerate(snapshot["boundaryRelationships"]) if row["boundaryClass"] == "REPOSITORY_NON_ELIGIBLE")
        rejected(lambda value: value["boundaryRelationships"][external_index].__setitem__("classificationStatus", "PENDING"))
        rejected(lambda value: value["boundaryRelationships"][external_index].__setitem__("internalSymbolId", "missing"))
        rejected(lambda value: value["boundaryRelationships"][external_index].__setitem__("boundaryRole", value["boundaryRelationships"][external_index]["internalRole"]))
        rejected(lambda value: value["boundaryRelationships"][external_index].__setitem__("classificationEvidence", [{"method": "WRONG"}]))
        rejected(lambda value: value["boundaryRelationships"][noneligible_index].__setitem__("classificationEvidence", [{"method": "WRONG"}]))
        rejected(lambda value: value["boundaryRelationships"][external_index].__setitem__("boundaryKeyHash", "sha256:" + "0" * 64))
        rejected(lambda value: value["boundaryRelationships"][external_index].__setitem__("boundaryRelationshipId", "sha256:" + "0" * 64))
        rejected(lambda value: value["relationshipCoverage"].__setitem__("resolvedInternalCount", -1))
        rejected(lambda value: value["relationshipCoverage"].__setitem__("typeCounts", []))
        rejected(lambda value: value["relationshipCoverage"].__setitem__("contentHash", "sha256:" + "0" * 64))
        rejected(lambda value: value.__setitem__("relationships", None), mutate_manifest=True)
        rejected(lambda value: value["relationships"].__setitem__("coverageHash", "sha256:" + "0" * 64), mutate_manifest=True)
        rejected(lambda value: value["relationships"].__setitem__("count", -1), mutate_manifest=True)

    def test_normalization_classifies_gap_boundary_projection_and_payload_variants(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            (root / "other.py").write_text("other = 1\n", encoding="utf-8")
            (root / "data.json").write_text("{}\n", encoding="utf-8")
            package = root / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text("PACKAGE = 1\n", encoding="utf-8")
            nodes = (
                {"id": "app", "kind": "MODULE", "path": "app.py", "qualifiedName": "repository.app"},
                {"id": "fn", "payload": {"kind": "FUNCTION", "path": "app.py", "qualifiedName": "app.fn", "startLine": 1, "endLine": 1}},
                {"function": {"id": "nested", "path": "app.py", "qualified_name": "app.nested", "start_line": 1, "end_line": 1}},
                {"id": "owned", "kind": "FUNCTION", "qualifiedName": "app.owned", "startLine": 1, "endLine": 1},
                {"id": "bad-path", "kind": "FUNCTION", "path": "../escape.py", "qualifiedName": "bad", "startLine": 1, "endLine": 1},
                {"id": "data", "kind": "FILE", "path": "data.json"},
                {"id": "other", "kind": "FILE", "path": "other.py"},
                {"id": "ambiguous", "kind": "FILE", "path": "other.py"},
                {"id": "ambiguous", "kind": "FILE", "path": "other.py"},
                {"id": "pkg", "kind": "PACKAGE"},
                {"id": "init", "kind": "FILE", "path": "pkg/__init__.py"},
                {},
            )
            relationships = (
                _relation("DEFINES", "app", "owned", "Module", "Function"),
                _relation("CONTAINS_FILE", "pkg", "init", "Package", "File"),
                _relation("CONTAINS_MODULE", "pkg", "pkg", "Package", "Module"),
                _relation("CONTAINS_SECTION", "missing-a", "missing-b", "Mystery", "Mystery"),
                _relation("ALIEN", "app", "fn", "Module", "Function"),
                _relation("CALLS", "missing-a", "missing-b", "Mystery", "Mystery"),
                _relation("CALLS", "missing-a", "fn", "Mystery", "Function"),
                _relation("CALLS", "fn", "missing-b", "Function", "Mystery"),
                _relation("IMPORTS", "app", "external", "Module", "ExternalModule"),
                _relation("IMPORTS", "external-2", "app", "ExternalModule", "Module"),
                _relation("LINKS_TO", "app", "data", "Module", "File"),
                _relation("LINKS_TO", "data", "app", "File", "Module"),
                _relation("LINKS_TO", "app", "other", "Module", "File"),
                _relation("LINKS_TO", "app", "ambiguous", "Module", "File"),
            )
            graph = RawGraph(nodes, relationships, {"capture": {"requested": ["structure", "calls", "types", "imports"]}})
            result = build_index(root, root / "_test_output" / "variants", CONFIG, "fixture", raw_graph=graph)
            self.assertEqual((result.status, result.code), ("UNKNOWN", "INDEX_INTERNAL_RELATIONSHIP_GAP"))
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))

        reasons = {row["reasonCode"] for row in snapshot["unresolvedInternalRelationships"]}
        self.assertTrue({
            "INTERNAL_RELATION_TYPE_UNSUPPORTED", "INTERNAL_BOTH_UNRESOLVED", "INTERNAL_SOURCE_UNRESOLVED",
            "INTERNAL_TARGET_UNRESOLVED", "INTERNAL_FILE_TO_MODULE_PROJECTION_FAILED",
        }.issubset(reasons))
        self.assertEqual({row["boundaryClass"] for row in snapshot["boundaryRelationships"]}, {"EXTERNAL", "REPOSITORY_NON_ELIGIBLE"})
        self.assertTrue(any(row["symbolKind"] == "MODULE" and row["relativePath"] == "pkg/__init__.py" for row in snapshot["symbols"]))

        gap = deepcopy(snapshot)
        gap["unresolvedInternalRelationships"][0]["blocksCoverage"] = False
        self.assertFalse(validate_relationship_accounting(gap)["valid"])
        gap = deepcopy(snapshot)
        gap["unresolvedInternalRelationships"][0]["gapId"] = "sha256:" + "0" * 64
        self.assertFalse(validate_relationship_accounting(gap)["valid"])
        gap = deepcopy(snapshot)
        gap["unresolvedRelationships"] = []
        self.assertFalse(validate_relationship_accounting(gap)["valid"])


if __name__ == "__main__":
    unittest.main()
