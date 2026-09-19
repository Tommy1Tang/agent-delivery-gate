"""
PRD Quality Validator — validates content quality of docs/01-需求规格书.md
against the mandatory output contract defined in product-analyst.prompt.md.

Usage:
    python scripts/validate_prd_quality.py --project-root <path>

Exit codes:
    0 = pass (all checks green)
    1 = fail (blocking issues found)
    2 = warn (non-blocking issues found)
"""

import argparse
import re
import sys
from pathlib import Path


def find_prd(project_root: Path) -> Path | None:
    """Locate the PRD file."""
    candidates = [
        project_root / "docs" / "01-需求规格书.md",
        project_root / "docs" / "01-需求规格书.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Try glob for sub-specs
    docs = project_root / "docs"
    if docs.exists():
        matches = list(docs.glob("01*需求规格书*.md"))
        if matches:
            return matches[0]
    return None


class Issue:
    def __init__(self, severity: str, code: str, message: str):
        self.severity = severity  # BLOCK / WARN
        self.code = code
        self.message = message

    def __str__(self):
        return f"[{self.severity}] {self.code}: {self.message}"


def check_fr_ids(content: str) -> list[Issue]:
    """E1: All FR must have stable IDs."""
    issues = []
    fr_pattern = re.compile(r"###\s+FR-(\d+)")
    fr_ids = fr_pattern.findall(content)
    if not fr_ids:
        issues.append(Issue("BLOCK", "E1-NO-FR", "No FR-xxx entries found in PRD"))
    # Check uniqueness
    if len(fr_ids) != len(set(fr_ids)):
        issues.append(Issue("BLOCK", "E1-DUP", f"Duplicate FR IDs detected: {[x for x in fr_ids if fr_ids.count(x) > 1]}"))
    return issues


def check_error_paths(content: str) -> list[Issue]:
    """E3: Each FR must have error path or explicit error-path-NA."""
    issues = []
    fr_sections = re.split(r"###\s+FR-\d+", content)[1:]  # skip before first FR
    fr_ids = re.findall(r"###\s+(FR-\d+)", content)
    for i, section in enumerate(fr_sections):
        fr_id = fr_ids[i] if i < len(fr_ids) else f"FR-{i+1}"
        has_error = bool(re.search(r"(?:Error Path|异常情况|异常路径|error.path)", section, re.IGNORECASE))
        has_na = bool(re.search(r"error-path-NA", section, re.IGNORECASE))
        if not has_error and not has_na:
            issues.append(Issue("BLOCK", "E3-MISSING", f"{fr_id} missing Error Path (or explicit error-path-NA)"))
    return issues


def check_nfr_quantified(content: str) -> list[Issue]:
    """E2: NFR must be SMART-quantified, no vague words."""
    issues = []
    nfr_sections = re.split(r"###\s+NFR-\d+", content)[1:]
    nfr_ids = re.findall(r"###\s+(NFR-\d+)", content)
    vague_patterns = re.compile(r"(系统应快速|高可用|安全可靠|性能要好|速度要快|尽可能快|适当|足够)", re.IGNORECASE)
    for i, section in enumerate(nfr_sections):
        nfr_id = nfr_ids[i] if i < len(nfr_ids) else f"NFR-{i+1}"
        if vague_patterns.search(section):
            issues.append(Issue("BLOCK", "E2-VAGUE", f"{nfr_id} contains vague/non-quantified description"))
        # Check for at least one number
        if not re.search(r"\d+", section):
            issues.append(Issue("WARN", "E2-NO-NUM", f"{nfr_id} has no quantified value"))
    return issues


def check_ac_format(content: str) -> list[Issue]:
    """S1-2: AC must use Given-When-Then format with coverage trace."""
    issues = []
    ac_sections = re.split(r"###\s+AC-\d+", content)[1:]
    ac_ids = re.findall(r"###\s+(AC-\d+)", content)
    for i, section in enumerate(ac_sections):
        ac_id = ac_ids[i] if i < len(ac_ids) else f"AC-{i+1}"
        has_gwt = bool(re.search(r"(Given|When|Then|在什么情况下|做了什么|应该看到)", section, re.IGNORECASE))
        has_coverage = bool(re.search(r"(\*\*覆盖\*\*|对应功能)", section, re.IGNORECASE))
        if not has_gwt:
            issues.append(Issue("BLOCK", "S1-2-FORMAT", f"{ac_id} not in Given-When-Then format"))
        if not has_coverage:
            issues.append(Issue("WARN", "S1-2-TRACE", f"{ac_id} missing coverage trace (覆盖：FR-xxx)"))
    return issues


def check_state_machine(content: str) -> list[Issue]:
    """E5: Business objects with ≥ 3 states must have state diagram + transition table."""
    issues = []
    # Look for stateDiagram or state-related content
    state_keywords = re.findall(r"(ST-\d+)", content)
    has_diagram = bool(re.search(r"stateDiagram|状态机|状态流转图", content))
    has_table = bool(re.search(r"转移\s*ID|前置状态|后置状态|从什么状态", content))
    if state_keywords and not has_diagram:
        issues.append(Issue("WARN", "E5-NO-DIAGRAM", "State transitions defined but no state diagram found"))
    if state_keywords and not has_table:
        issues.append(Issue("WARN", "E5-NO-TABLE", "State transitions defined but no transition table found"))
    return issues


def check_glossary(content: str) -> list[Issue]:
    """E7: Glossary section must exist."""
    issues = []
    has_glossary = bool(re.search(r"(Glossary|名词解释|业务术语)", content, re.IGNORECASE))
    if not has_glossary:
        issues.append(Issue("WARN", "E7-MISSING", "No Glossary / 名词解释 section found"))
    return issues


def check_ambiguity_signals(content: str) -> list[Issue]:
    """S1-1: Check for common ambiguity signals."""
    issues = []
    ambiguity_patterns = [
        (r"尽快|尽可能|适当|差不多|一些|多些|快些", "模糊量词"),
        (r"(?<!\w)用户(?!\s*[（(])", "未限定角色的'用户'"),  # 'user' without role qualifier
    ]
    for pattern, label in ambiguity_patterns:
        matches = re.findall(pattern, content)
        if len(matches) > 2:  # Allow some tolerance
            issues.append(Issue("WARN", "S1-1-AMBIG", f"Multiple ambiguity signals ({label}): {len(matches)} occurrences"))
    return issues


def check_moscow(content: str) -> list[Issue]:
    """RQ-A: When FR ≥ 5, MoSCoW classification is required."""
    issues = []
    fr_count = len(re.findall(r"###\s+FR-\d+", content))
    if fr_count >= 5:
        has_moscow = bool(re.search(r"(MoSCoW|Must|Should|Could|Won't|必须做|最好做|可以做|暂不做|优先级)", content))
        if not has_moscow:
            issues.append(Issue("BLOCK", "RQ-A-MISSING", f"FR count = {fr_count} (≥5) but no MoSCoW/priority classification found"))
    return issues


def check_metrics(content: str) -> list[Issue]:
    """E12: Success metrics must be defined."""
    issues = []
    has_metrics = bool(re.search(r"(成功度量|衡量指标|North Star|指标层级|最关键指标)", content, re.IGNORECASE))
    if not has_metrics:
        issues.append(Issue("WARN", "E12-MISSING", "No success metrics section found"))
    return issues


def run_validation(project_root: Path) -> tuple[list[Issue], dict]:
    """Run all checks and return issues + summary."""
    prd_path = find_prd(project_root)
    if not prd_path:
        return [Issue("BLOCK", "FILE-MISSING", "docs/01-需求规格书.md not found")], {}

    content = prd_path.read_text(encoding="utf-8")
    all_issues: list[Issue] = []

    checks = [
        check_fr_ids,
        check_error_paths,
        check_nfr_quantified,
        check_ac_format,
        check_state_machine,
        check_glossary,
        check_ambiguity_signals,
        check_moscow,
        check_metrics,
    ]

    for check_fn in checks:
        all_issues.extend(check_fn(content))

    summary = {
        "file": str(prd_path),
        "total_issues": len(all_issues),
        "blocks": len([i for i in all_issues if i.severity == "BLOCK"]),
        "warns": len([i for i in all_issues if i.severity == "WARN"]),
        "fr_count": len(re.findall(r"###\s+FR-\d+", content)),
        "nfr_count": len(re.findall(r"###\s+NFR-\d+", content)),
        "ac_count": len(re.findall(r"###\s+AC-\d+", content)),
        "status": "pass" if not any(i.severity == "BLOCK" for i in all_issues) else "fail",
    }

    return all_issues, summary


def main():
    parser = argparse.ArgumentParser(description="Validate PRD content quality")
    parser.add_argument("--project-root", required=True, help="Path to project root")
    args = parser.parse_args()

    project_root = Path(args.project_root)
    if not project_root.exists():
        print(f"ERROR: Project root not found: {project_root}")
        sys.exit(1)

    issues, summary = run_validation(project_root)

    print("=" * 60)
    print("PRD Quality Validation Report")
    print("=" * 60)
    print(f"File: {summary.get('file', 'NOT FOUND')}")
    print(f"FR count: {summary.get('fr_count', 0)}")
    print(f"NFR count: {summary.get('nfr_count', 0)}")
    print(f"AC count: {summary.get('ac_count', 0)}")
    print(f"Status: {summary.get('status', 'fail').upper()}")
    print(f"Issues: {summary.get('blocks', 0)} BLOCK + {summary.get('warns', 0)} WARN")
    print("-" * 60)

    if issues:
        for issue in issues:
            print(f"  {issue}")
    else:
        print("  ✅ All checks passed!")

    print("=" * 60)

    if summary.get("status") == "fail":
        sys.exit(1)
    elif summary.get("warns", 0) > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
