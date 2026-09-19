#!/usr/bin/env python3
"""P5-3: Cross-role artifact traceability audit.

Scans docs/ for requirement IDs (FR-xxx, NFR-xxx) and verifies they appear
across multiple documents (requirements → design → API contract → tests).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Pattern to extract requirement IDs from documents.
REQ_ID_PATTERN = re.compile(r"\b((?:FR|NFR|REQ|UC|US)-\d{1,4})\b", re.IGNORECASE)

# Documents that should reference requirement IDs (in priority order).
TRACEABILITY_CHAIN = [
    "docs/01-需求规格书.md",         # Source of truth
    "docs/04-详细设计说明书.md",      # Must reference
    "docs/07-接口数据契约.md",       # Should reference
    "docs/10-单元测试用例.md",       # Should reference
    "docs/12-集成测试用例.md",       # Should reference
    "docs/16-E2E测试用例.md",       # Should reference
]


def extract_req_ids(text: str) -> set[str]:
    """Extract all requirement IDs from text."""
    return {m.group(1).upper() for m in REQ_ID_PATTERN.finditer(text)}


def trace_requirements(project_root: Path) -> dict:
    """Perform traceability analysis across delivery documents.

    Returns a report with coverage statistics and gaps.
    """
    doc_reqs: dict[str, set[str]] = {}

    for doc_path in TRACEABILITY_CHAIN:
        full_path = project_root / doc_path
        if full_path.is_file():
            try:
                text = full_path.read_text(encoding="utf-8", errors="ignore")
                doc_reqs[doc_path] = extract_req_ids(text)
            except OSError:
                doc_reqs[doc_path] = set()
        else:
            doc_reqs[doc_path] = set()

    # Source requirements (from 需求规格书)
    source_doc = TRACEABILITY_CHAIN[0]
    source_reqs = doc_reqs.get(source_doc, set())

    if not source_reqs:
        return {
            "status": "skip",
            "reason": "No requirement IDs (FR-xxx/NFR-xxx) found in 01-需求规格书.md — traceability check skipped",
            "sourceReqCount": 0,
            "gaps": [],
        }

    # Check coverage in each downstream document
    gaps: list[dict] = []
    coverage: dict[str, dict] = {}

    for doc_path in TRACEABILITY_CHAIN[1:]:
        doc_ids = doc_reqs.get(doc_path, set())
        if not (project_root / doc_path).is_file():
            coverage[doc_path] = {"exists": False, "covered": 0, "total": len(source_reqs), "pct": 0.0}
            continue

        covered = source_reqs & doc_ids
        missing = source_reqs - doc_ids
        pct = (len(covered) / len(source_reqs) * 100) if source_reqs else 0.0
        coverage[doc_path] = {
            "exists": True,
            "covered": len(covered),
            "total": len(source_reqs),
            "pct": round(pct, 1),
        }

        # Only flag gaps if document exists but coverage is very low
        if pct < 50.0 and len(source_reqs) >= 3:
            gaps.append({
                "doc": doc_path,
                "coveragePct": round(pct, 1),
                "missingReqs": sorted(missing)[:10],
            })

    return {
        "status": "pass" if not gaps else "warn",
        "sourceReqCount": len(source_reqs),
        "sourceReqs": sorted(source_reqs),
        "coverage": coverage,
        "gaps": gaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    report = trace_requirements(project_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Traceability: {report['status']} ({report['sourceReqCount']} source requirements)")
        if report.get("gaps"):
            print("\nGaps:")
            for gap in report["gaps"]:
                print(f"  - {gap['doc']}: {gap['coveragePct']}% coverage, missing: {gap['missingReqs'][:5]}")
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
