#!/usr/bin/env python3
"""P5-5: Validate document structure against templates.

Checks that delivery documents follow their template's required heading structure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Map from delivery document to its template file.
DOC_TEMPLATE_MAP = {
    "docs/01-需求规格书.md": "assets/templates/需求规格书.template.md",
    "docs/02-开发计划.md": "assets/templates/开发计划.template.md",
    "docs/04-详细设计说明书.md": "assets/templates/详细设计说明书.template.md",
    "docs/07-接口数据契约.md": "assets/templates/接口数据契约.template.md",
    "docs/10-单元测试用例.md": "assets/templates/单元测试用例.template.md",
    "docs/11-单元测试报告.md": "assets/templates/单元测试报告.template.md",
    "docs/12-集成测试用例.md": "assets/templates/集成测试用例.template.md",
    "docs/13-集成测试报告.md": "assets/templates/集成测试报告.template.md",
    "docs/14-代码评审.md": "assets/templates/代码评审.template.md",
    "docs/15-安全评审.md": "assets/templates/安全评审.template.md",
    "docs/18-部署说明.md": "assets/templates/部署说明.template.md",
    "docs/19-监督审计.md": "assets/templates/监督审计.template.md",
}

# Heading extraction regex (matches ## and ### level headings).
HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def extract_required_headings(template_text: str) -> list[tuple[int, str]]:
    """Extract (level, title) tuples from a template.

    Only includes level-2 headings (##) as required structural elements.
    Level-1 is the document title, level-3 are optional sub-sections.
    """
    headings = []
    for match in HEADING_PATTERN.finditer(template_text):
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 2:
            # Normalize: remove template variables like {xxx} and trim
            clean_title = re.sub(r"\{[^}]+\}", "", title).strip()
            if clean_title:
                headings.append((level, clean_title))
    return headings


def extract_doc_headings(doc_text: str) -> list[tuple[int, str]]:
    """Extract all headings from a delivery document."""
    headings = []
    for match in HEADING_PATTERN.finditer(doc_text):
        level = len(match.group(1))
        title = match.group(2).strip()
        headings.append((level, title))
    return headings


def check_structure(doc_headings: list[tuple[int, str]], required_headings: list[tuple[int, str]]) -> list[str]:
    """Check that required headings are present in the document.

    Uses fuzzy matching: a required heading is considered present if any
    document heading contains the required title as a substring (case-insensitive).
    """
    missing = []
    doc_titles_lower = [h[1].lower() for h in doc_headings]

    for _level, req_title in required_headings:
        req_lower = req_title.lower()
        # Fuzzy match: check if req_title is a substring of any doc heading
        found = any(req_lower in dt or dt in req_lower for dt in doc_titles_lower)
        if not found:
            missing.append(req_title)

    return missing


def validate_doc_structure(skill_root: Path, project_root: Path) -> dict:
    """Validate all delivery documents against their templates.

    Returns a report with pass/fail status and details per document.
    """
    results: list[dict] = []
    blocking: list[str] = []

    for doc_rel, template_rel in DOC_TEMPLATE_MAP.items():
        doc_path = project_root / doc_rel
        template_path = skill_root / template_rel

        if not doc_path.is_file():
            continue  # Missing doc is caught by validate_delivery.py

        if not template_path.is_file():
            continue  # Missing template is caught by check_skill_integrity.py

        try:
            doc_text = doc_path.read_text(encoding="utf-8", errors="ignore")
            template_text = template_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        required = extract_required_headings(template_text)
        if not required:
            continue  # Template has no structured headings

        doc_heads = extract_doc_headings(doc_text)
        missing = check_structure(doc_heads, required)

        status = "pass" if not missing else "warn" if len(missing) <= 2 else "fail"
        entry = {
            "doc": doc_rel,
            "requiredHeadings": len(required),
            "presentHeadings": len(required) - len(missing),
            "status": status,
        }
        if missing:
            entry["missingHeadings"] = missing[:5]
        results.append(entry)

        # Only BLOCK if > 50% of required headings are missing
        if len(missing) > len(required) * 0.5 and len(required) >= 3:
            blocking.append(
                f"{doc_rel}: missing {len(missing)}/{len(required)} required sections "
                f"(sample: {missing[:3]}). Document does not conform to template structure."
            )

    return {
        "status": "pass" if not blocking else "fail",
        "blockingReasons": blocking,
        "details": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to the skill root")
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    project_root = Path(args.project_root).resolve()
    report = validate_doc_structure(skill_root, project_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Doc Structure: {report['status'].upper()}")
        for detail in report["details"]:
            print(f"  - {detail['status'].upper()} {detail['doc']} ({detail['presentHeadings']}/{detail['requiredHeadings']})")
            if detail.get("missingHeadings"):
                for h in detail["missingHeadings"]:
                    print(f"    → missing: {h}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
