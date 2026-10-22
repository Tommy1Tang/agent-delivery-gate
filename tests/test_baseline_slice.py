from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_baseline_slice import build_slice  # noqa: E402


CAPABILITY_TABLE = """# 能力目录

| capability_id | 名称 | 优先级 | 关联 process_id | 关联 entity_id |
|---|---|---|---|---|
| CAP-01 | 创建任务 | Must | PROC-01 | ENT-Task |
"""


class BaselineSliceTest(unittest.TestCase):
    def _build(self, owl: str) -> dict:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        input_dir = root / "docs" / "input"
        input_dir.mkdir(parents=True)
        (input_dir / "01-能力目录.md").write_text(CAPABILITY_TABLE, encoding="utf-8")
        ontology_dir = input_dir / "models" / "ontology"
        ontology_dir.mkdir(parents=True)
        (ontology_dir / "d.owl").write_text(owl, encoding="utf-8")
        return build_slice(root, "docs/input", "CAP-01")

    def test_owl_matches_trace_stable_id(self):
        report = self._build(
            '<?xml version="1.0"?>'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
            ' xmlns:owl="http://www.w3.org/2002/07/owl#"'
            ' xmlns:trace="urn:research-to-project-input:trace#">'
            '<owl:Class rdf:about="http://x#任务">'
            '<trace:稳定标识>ENT-Task</trace:稳定标识>'
            '</owl:Class></rdf:RDF>'
        )

        self.assertTrue(report["found"])
        self.assertEqual(report["sliceInputs"]["owl"], ["models/ontology/d.owl"])

    def test_owl_without_stable_id_does_not_match_entity(self):
        report = self._build(
            '<?xml version="1.0"?>'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
            ' xmlns:owl="http://www.w3.org/2002/07/owl#">'
            '<owl:Class rdf:about="http://x#任务"/>'
            '</rdf:RDF>'
        )

        self.assertTrue(report["found"])
        self.assertEqual(report["sliceInputs"]["owl"], [])


if __name__ == "__main__":
    unittest.main()
