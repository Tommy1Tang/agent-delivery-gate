#!/usr/bin/env python3
"""Validate project delivery artifacts against software-development-team gates."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# Project hard thresholds (must align with SKILL.md / unified-large-delivery-policy.md /
# quality-gate-engineer.prompt.md / supervisor-auditor.prompt.md).
UNIT_TEST_COVERAGE_MIN = 90.0
INTEGRATION_TEST_COVERAGE_MIN = 80.0
# E2E is now MANDATORY for every delivery (no opt-out). E2E pass-rate must be 100%
# and at least one P0 user-journey case must exist.
E2E_PASS_RATE_MIN = 100.0
E2E_MIN_CASE_COUNT = 1

# Content-level red flag patterns (case-insensitive).
# verdict = BLOCK detection now covers Chinese conclusions and common variants
# (裁决 / 结论 / verdict / BLOCKED / 阻断 / 不通过) so reviewers cannot escape detection
# by switching language or label.
BLOCK_PATTERNS_VERDICT = [
    re.compile(r"verdict\s*[:=\uff1a]\s*[`\"\u201c]?\s*BLOCK(?:ED)?\b", re.IGNORECASE),
    re.compile(r"verdict\s*[:=\uff1a]\s*BLOCK(?:ED)?\b", re.IGNORECASE),
    re.compile(r"裁决\s*[:=\uff1a]\s*[`\"\u201c]?\s*BLOCK(?:ED)?\b", re.IGNORECASE),
    re.compile(r"结论\s*[:=\uff1a]\s*[`\"\u201c]?\s*BLOCK(?:ED)?\b", re.IGNORECASE),
    re.compile(r"(?:裁决|结论|发布门禁结论|审查结论|verdict)\s*[:=\uff1a]\s*[`\"\u201c]?\s*阻断\b", re.IGNORECASE),
    re.compile(r"(?:裁决|结论|发布门禁结论|审查结论|verdict)\s*[:=\uff1a]\s*[`\"\u201c]?\s*不通过\b", re.IGNORECASE),
]
BUILD_FAILURE_PATTERN = re.compile(r"BUILD\s+FAIL(URE|ED)", re.IGNORECASE)
NO_TEST_IMPL_PATTERNS = [
    re.compile(r"单元测试实现\s*[|:\uff1a]?\s*0\s*个"),
    re.compile(r"代码覆盖率\s*[|:\uff1a]?\s*0\s*%"),
    re.compile(r"覆盖率\s*[:\uff1a]?\s*0%"),
    re.compile(r"未实现」?、?核心模块无自动化测试"),
    re.compile(r"单元测试执行\s*[|:\uff1a]?\s*⚠\ufe0f?\s*未执行"),
]
# Conditional-pass detection: covers all soft-pass variants. Any of these is BLOCK.
CONDITIONAL_PASS_PATTERNS = [
    re.compile(r"有条件通过"),
    re.compile(r"附条件通过"),
    re.compile(r"条件性通过"),
    re.compile(r"有保留通过"),
    re.compile(r"原则上?通过"),
    re.compile(r"原则性通过"),
    re.compile(r"基本通过"),
    re.compile(r"临时通过"),
    re.compile(r"通过\s*\uff08\s*有条件\s*\uff09"),
    re.compile(r"通过\s*\(\s*有条件\s*\)"),
    re.compile(r"通过\s*\uff08\s*附条件\s*\uff09"),
    re.compile(r"通过\s*\(\s*附条件\s*\)"),
]

# Placeholder / unfilled-content patterns. Any of these in a delivery doc means the
# document is a stub, not a finished artifact, and must BLOCK delivery. Aligned with
# halt-and-resume-policy.md and unified-large-delivery-policy.md.
PLACEHOLDER_PATTERNS = [
    re.compile(r"<\s*TBD\s*>", re.IGNORECASE),
    re.compile(r"<\s*TBC\s*>", re.IGNORECASE),
    re.compile(r"<\s*TODO\s*>", re.IGNORECASE),
    re.compile(r"<\s*FIXME\s*>", re.IGNORECASE),
    re.compile(r"<\s*待填写\s*>"),
    re.compile(r"<\s*待补充\s*>"),
    re.compile(r"<\s*待确认\s*>"),
    re.compile(r"<\s*占位\s*>"),
    re.compile(r"\[\s*placeholder\s*\]", re.IGNORECASE),
    re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"),  # ${VAR} unfilled template
    re.compile(r"xxx+", re.IGNORECASE),  # xxx / xxxxx placeholder
    re.compile(r"待补充(?!。)"),  # 「待补充」 in body
    re.compile(r"待确认"),
    re.compile(r"待补(?![。，充])"),  # standalone 待补 (avoid 待补充)
    re.compile(r"待办(?![。，公])"),  # 待办 (avoid 待办公)
    re.compile(r"^\s*\.{3,}\s*$", re.MULTILINE),  # standalone "..." line
    re.compile(r"^\s*。{3,}\s*$", re.MULTILINE),  # standalone “。。。” line
    # NOTE: standalone "---" is a legitimate markdown horizontal rule and is NOT treated as a placeholder.
    re.compile(r"暂无(?![依限可法设置需他])"),  # 暂无 (avoid 暂无依赖/暂无限制/...)
    re.compile(r"暂略(?!过)"),  # 暂略 placeholder, avoid 暂略过
    re.compile(r"见后续"),  # see-later placeholder
    re.compile(r"见后补充"),
    re.compile(r"后续补充"),
    re.compile(r"^\s*N/?A\s*$", re.IGNORECASE | re.MULTILINE),  # standalone N/A line
]

# Halt states that MUST block delivery declaration. Aligned with
# schemas/evidence-ledger.schema.json deliveryStatus enum.
HALT_BLOCKING_STATES = {
    "halted-pending-user",
    "halted-circuit-broken",
    "halted-multi-crash",
    "halted-user-cancel",
    "failed-closed",
}

# Whitelist for roleRuns[*].reasonForSkip. Any other value is BLOCK.
ALLOWED_REASON_FOR_SKIP = {
    "tooling-missing",
    "upstream-blocked",
    "user-approved",
    "objective-conditions-met",
    "cascade-block",
}

# Hard rework caps (mirrored in evidence-ledger.schema.json maximum).
MAX_REWORK_CUMULATIVE = 10
MAX_REWORK_PER_ROOT_CAUSE = 5
COVERAGE_PATTERN = re.compile(
    r"(?:单元测试|代码)覆盖率\s*[:：|]\s*([0-9]+(?:\.[0-9]+)?)\s*%",
)
INTEGRATION_COVERAGE_PATTERN = re.compile(
    r"集成测试覆盖率\s*[:：|]\s*([0-9]+(?:\.[0-9]+)?)\s*%",
)
# E2E pass-rate field, e.g. 「E2E测试通过率：100.0%」 / 「端到端测试通过率 | 100%」.
E2E_PASS_RATE_PATTERN = re.compile(
    r"(?:E2E|e2e|端到端)测试通过率\s*[:：|]\s*([0-9]+(?:\.[0-9]+)?)\s*%",
)
# E2E executed/total counts, e.g. 「执行总数：12 个」 / 「E2E 用例总数 | 12」.
E2E_TOTAL_PATTERN = re.compile(
    r"(?:E2E|e2e|端到端)[不可用例测试\s]*(?:总数|总计|总量)\s*[:：|]\s*([0-9]+)",
)
# Anti AI-fabrication: E2E report must contain real execution evidence.
# Each pattern below is OPTIONAL on its own, but at least 2 of {trace, screenshot, stdout}
# must be present and non-empty (see _scan_e2e_evidence() below).
E2E_TRACE_PATTERN = re.compile(
    r"(?:trace|追踪文件|trace\.zip|trace\.json)\s*[:：|]?\s*(\S+)",
    re.IGNORECASE,
)
E2E_SCREENSHOT_PATTERN = re.compile(
    r"(?:screenshot|截图(?:路径)?|截屏)\s*[:：|]?\s*(\S+\.(?:png|jpe?g|webp))",
    re.IGNORECASE,
)
E2E_STDOUT_PATTERN = re.compile(
    r"(?:stdout|运行输出|执行日志|console\s*output|run\s*log)\s*[:：|]?\s*(\S+)",
    re.IGNORECASE,
)

# Roles that MUST appear in evidence-ledger.roleRuns with status='completed' for every delivery.
# Skipping any of these is BLOCK (no opt-out, even with reasonForSkip whitelist).
MANDATORY_ROLES_IN_LEDGER = {
    "browser-e2e-engineer",
}

# Well-known coverage artifact paths (relative to project root) grouped by stack.
# If the text report claims >= threshold but NONE of these exist, we BLOCK.
COVERAGE_ARTIFACT_PATHS = [
    # Java / Maven / Jacoco
    "backend/target/site/jacoco/index.html",
    "target/site/jacoco/index.html",
    "build/reports/jacoco/test/html/index.html",
    # Node / Jest / NYC
    "coverage/lcov.info",
    "coverage/lcov-report/index.html",
    "coverage/cobertura-coverage.xml",
    "frontend/coverage/lcov.info",
    # Python / pytest-cov
    "htmlcov/index.html",
    ".coverage",
    "coverage.xml",
]

# Database migration directories (aligned with detect_stack.py DB_MIGRATION_HINTS).
DB_MIGRATION_DIRS = [
    "src/main/resources/db/migration",
    "src/main/resources/db/changelog",
    "db/migrate",
    "migrations",
    "prisma/migrations",
    "supabase/migrations",
    "backend/src/main/resources/db/migration",
]

# Regex for extracting table names from data-design doc.
_TABLE_NAME_PATTERN = re.compile(
    r"(?:CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|\")?([\w]+)|"
    r"\|\s*([\w_]+)\s*\|.*?(?:表|table|entity))",
    re.IGNORECASE,
)
# Simpler: just capture all backtick-quoted or column-1 markdown identifiers
_TABLE_DESIGN_PATTERN = re.compile(
    r"(?:^|\|)\s*`?([a-z][a-z0-9_]{2,})`?\s*\|",
    re.IGNORECASE | re.MULTILINE,
)



def load_config(skill_root: Path) -> dict:
    return json.loads((skill_root / "assets" / "config" / "agent-team-config.json").read_text(encoding="utf-8"))


def check_file(project_root: Path, relative_path: str) -> tuple[bool, str]:
    path = project_root / relative_path
    if not path.exists():
        # Numbered-prefix variant is the canonical naming (see
        # references/team-workflow.md and agent-team-config expectedOutputs);
        # the unnumbered form is a legacy alias. Accept either.
        alt = _resolve_doc_alias(project_root, relative_path)
        if alt is None:
            return False, "missing"
        path = alt
    if path.is_file() and path.stat().st_size == 0:
        return False, "empty"
    return True, "present"


def _resolve_doc_alias(project_root: Path, relative_path: str) -> Path | None:
    """Resolve docs/<name>.md <-> docs/<NN>-<name>.md naming aliases.

    The skill's canonical convention is the numbered prefix
    (docs/01-需求规格书.md), but the unnumbered form appears in older prompts
    and projects. Rather than fail a delivery over a naming variant, resolve
    whichever file actually exists.
    """
    if not relative_path.startswith("docs/") or not relative_path.endswith(".md"):
        return None
    name = relative_path[len("docs/"):]
    docs_dir = project_root / "docs"
    if not docs_dir.is_dir():
        return None

    stripped = re.sub(r"^\d+(?:\.\d+)*-", "", name)
    for cand in sorted(docs_dir.glob("*.md")):
        cand_name = re.sub(r"^\d+(?:\.\d+)*-", "", cand.name)
        if cand_name == stripped and cand.is_file():
            return cand
    return None


def _read_text(project_root: Path, relative_path: str) -> str | None:
    path = project_root / relative_path
    if not path.exists() or not path.is_file():
        path = _resolve_doc_alias(project_root, relative_path)
        if path is None:
            return None
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _scan_block_verdict(text: str) -> bool:
    return any(p.search(text) for p in BLOCK_PATTERNS_VERDICT)


def _scan_build_failure(text: str) -> bool:
    return bool(BUILD_FAILURE_PATTERN.search(text))


def _scan_zero_test_impl(text: str) -> bool:
    return any(p.search(text) for p in NO_TEST_IMPL_PATTERNS)


def _scan_conditional_pass(text: str) -> bool:
    return any(p.search(text) for p in CONDITIONAL_PASS_PATTERNS)


def _scan_placeholders(text: str) -> list[str]:
    """Return distinct placeholder tokens found in text. Empty list = none."""
    # “待确认项” is a governed heading in the security/deployment templates,
    # not unfinished body content.  Keep the body strict: a bare “待确认”
    # anywhere outside a Markdown heading still blocks delivery.
    scan_text = "\n".join(
        "" if line.lstrip().startswith("#") and "待确认项" in line else line
        for line in text.splitlines()
    )
    found: list[str] = []
    seen: set[str] = set()
    for pat in PLACEHOLDER_PATTERNS:
        for m in pat.finditer(scan_text):
            token = m.group(0)
            if token not in seen:
                seen.add(token)
                found.append(token)
    return found


def derive_role_policy(process: dict) -> dict[str, set[str]]:
    """Derive objective skip and mandatory role sets from the process truth source."""
    skippable: set[str] = set()
    mandatory: set[str] = set()
    nodes = process.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("skill process nodes must be an array")
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "role-dispatch":
            continue
        role = node.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("every role-dispatch node must declare role")
        satisfied_by = node.get("satisfiedBy")
        accept = satisfied_by.get("acceptStatuses", []) if isinstance(satisfied_by, dict) else []
        if node.get("skippable") is True and isinstance(accept, list) and "skipped" in accept:
            skippable.add(role)
        else:
            mandatory.add(role)
    return {"objectiveSkippableRoles": skippable, "mandatoryRoles": mandatory}


def _read_evidence_ledger(project_root: Path) -> dict | None:
    """Try to load the evidence ledger from common locations."""
    candidates = [
        project_root / "docs" / "evidence-ledger.json",
        project_root / "evidence-ledger.json",
        project_root / ".qoder" / "evidence-ledger.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _validate_evidence_ledger_schema(skill_root: Path, ledger: dict) -> list[str]:
    """Validate the complete ledger with the published Draft 2020-12 schema."""
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        return ["evidence-ledger: Draft 2020-12 validator unavailable; install jsonschema+referencing before delivery validation"]
    schema_dir = skill_root / "schemas"
    try:
        schema = json.loads((schema_dir / "evidence-ledger.schema.json").read_text(encoding="utf-8"))
        registry = Registry()
        for path in sorted(schema_dir.glob("*.schema.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            identifier = value.get("$id") if isinstance(value, dict) else None
            if isinstance(identifier, str):
                registry = registry.with_resource(identifier, Resource.from_contents(value))
        errors = sorted(Draft202012Validator(schema, registry=registry).iter_errors(ledger), key=lambda item: list(item.absolute_path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"evidence-ledger: schema validation setup failed ({type(exc).__name__})"]
    return [
        "evidence-ledger schema: " + ("/".join(str(part) for part in error.absolute_path) or "<root>") + f": {error.message}"
        for error in errors
    ]


def _scan_unit_coverage(text: str) -> float | None:
    matches = COVERAGE_PATTERN.findall(text)
    if not matches:
        return None
    try:
        # Use the minimum reported number to be conservative.
        return min(float(m) for m in matches)
    except ValueError:
        return None


def _scan_integration_coverage(text: str) -> float | None:
    matches = INTEGRATION_COVERAGE_PATTERN.findall(text)
    if not matches:
        return None
    try:
        return min(float(m) for m in matches)
    except ValueError:
        return None


def _scan_e2e_pass_rate(text: str) -> float | None:
    matches = E2E_PASS_RATE_PATTERN.findall(text)
    if not matches:
        return None
    try:
        return min(float(m) for m in matches)
    except ValueError:
        return None


def _scan_e2e_total(text: str) -> int | None:
    matches = E2E_TOTAL_PATTERN.findall(text)
    if not matches:
        return None
    try:
        return max(int(m) for m in matches)
    except ValueError:
        return None


def _scan_e2e_evidence(text: str) -> list[str]:
    """Anti AI-fabrication scan. Return a list of MISSING evidence categories.

    A real E2E report should reference at least 2 of: {trace file path,
    screenshot path, stdout/run-log path}. Pure markdown text declaring 100%
    pass-rate without any of these is treated as fabricated.
    """
    missing: list[str] = []
    if not E2E_TRACE_PATTERN.search(text):
        missing.append("trace file path (Playwright trace.zip / Cypress trace / similar)")
    if not E2E_SCREENSHOT_PATTERN.search(text):
        missing.append("screenshot path (.png/.jpg/.webp)")
    if not E2E_STDOUT_PATTERN.search(text):
        missing.append("stdout / run-log path (real command output)")
    # Must have at least 2 categories present, i.e. at most 1 missing.
    if len(missing) >= 2:
        return missing
    return []


def _check_coverage_artifacts(project_root: Path) -> list[str]:
    """P0-2: Verify that real coverage output files exist.

    If docs claim coverage >= threshold but zero artifact files are present on disk,
    the coverage claim is likely fabricated.
    """
    found = [p for p in COVERAGE_ARTIFACT_PATHS if (project_root / p).exists()]
    if found:
        return []  # At least one real artifact exists — OK.
    return [
        "coverage-artifact: unit/integration test report claims passing coverage but no real "
        "coverage artifact found on disk (checked: jacoco/lcov/htmlcov/.coverage/coverage.xml). "
        "Run tests with coverage enabled and verify output files exist before declaring coverage numbers."
    ]


def _check_ledger_temporal_consistency(
    project_root: Path, ledger: dict
) -> list[str]:
    """P0-3: Check that doc files' mtime falls within ledger delivery window.

    If the ledger declares createdAt but docs/ files have not been modified since long before
    that timestamp, the ledger is likely stale or fabricated.
    """
    issues: list[str] = []
    created_at_str = ledger.get("createdAt") or ""
    if not created_at_str:
        return []  # Cannot check without createdAt
    try:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return []  # Malformed; other checks will catch this.

    # Allow a generous 48-hour tolerance before createdAt (in case role started early).
    tolerance_seconds = 48 * 3600
    threshold_ts = created_at.timestamp() - tolerance_seconds

    docs_dir = project_root / "docs"
    if not docs_dir.is_dir():
        return []
    stale_files: list[str] = []
    for f in docs_dir.iterdir():
        if not f.is_file() or f.suffix not in (".md", ".json"):
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime < threshold_ts:
            stale_files.append(f.name)
    if stale_files and len(stale_files) >= 3:
        # Only BLOCK if many files are stale (avoids false-positive on single unchanged doc).
        sample = ", ".join(sorted(stale_files)[:5])
        issues.append(
            f"evidence-ledger temporal consistency: {len(stale_files)} doc files have mtime "
            f"older than ledger.createdAt - 48h (sample: {sample}). "
            "This indicates the ledger was created without actual role execution. "
            "Re-run roles or verify file timestamps."
        )
    return issues


def _check_db_migration_alignment(project_root: Path) -> list[str]:
    """P0-4: Cross-check data design doc with migration directory presence.

    If docs/数据设计说明书.md exists (meaning the project has a data layer),
    then at least one migration directory must also exist. Additionally, table names
    listed in the design doc should have *some* representation in migration SQL files.
    """
    issues: list[str] = []
    design_text = _read_text(project_root, "docs/数据设计说明书.md")
    if design_text is None:
        return []  # No data layer — skip.

    # Check migration directory exists.
    migration_found: list[str] = []
    for d in DB_MIGRATION_DIRS:
        full = project_root / d
        if full.exists() and full.is_dir():
            migration_found.append(d)
    if not migration_found:
        issues.append(
            "database-migration: docs/数据设计说明书.md exists (project has data layer) "
            "but no migration directory found. Expected at least one of: "
            + ", ".join(DB_MIGRATION_DIRS[:4]) + ". "
            "Schema changes without versioned migrations are forbidden."
        )
        return issues  # Cannot do table reconciliation without migrations.

    # Extract table names from design doc.
    design_tables: set[str] = set()
    for m in _TABLE_DESIGN_PATTERN.finditer(design_text):
        name = m.group(1).lower()
        # Exclude common markdown noise words.
        if name not in ("id", "name", "type", "status", "table", "column", "field",
                        "description", "remark", "create", "update", "delete", "index"):
            design_tables.add(name)

    if not design_tables:
        return issues  # Cannot parse table names — skip reconciliation.

    # Scan migration files for table references.
    migration_content = ""
    for md in migration_found:
        for sql_file in (project_root / md).rglob("*"):
            if sql_file.is_file() and sql_file.suffix in (".sql", ".xml", ".json", ".ts", ".js"):
                try:
                    migration_content += sql_file.read_text(encoding="utf-8", errors="ignore").lower()
                except OSError:
                    pass
    if not migration_content:
        return issues

    missing_tables = sorted(t for t in design_tables if t not in migration_content)
    if missing_tables and len(missing_tables) > len(design_tables) * 0.5:
        issues.append(
            f"database-migration: {len(missing_tables)}/{len(design_tables)} tables from "
            f"数据设计说明书 not found in migration files (sample: {missing_tables[:5]}). "
            "Design doc and migrations are out of sync."
        )
    return issues


def _check_agent_timing_format(project_root: Path) -> list[str]:
    """P4-10: Validate docs/agent-timing.md format if it exists.

    Checks that the file has a proper table with ISO 8601 timestamps.
    """
    issues: list[str] = []
    timing_text = _read_text(project_root, "docs/agent-timing.md")
    if timing_text is None:
        # File not yet created — will be created during execution.
        # Only BLOCK if execution log exists (meaning roles ran but timing wasn't tracked).
        exec_log = _read_text(project_root, "docs/\u6267\u884c\u65e5\u5fd7.md")
        if exec_log is not None:
            issues.append(
                "agent-timing: docs/\u6267\u884c\u65e5\u5fd7.md exists but docs/agent-timing.md is missing — "
                "Orchestrator must maintain agent-timing.md with real-time role dispatch/completion timestamps"
            )
        return issues

    # Check for table header
    if "|" not in timing_text:
        issues.append(
            "agent-timing: docs/agent-timing.md exists but contains no markdown table — "
            "must have a table with columns: #, Agent名称, 角色, 任务描述, 开始时间, 结束时间, 运行时间, 状态"
        )
        return issues

    # Check for ISO 8601 timestamps (at least one should exist)
    iso_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
    if not iso_pattern.search(timing_text):
        issues.append(
            "agent-timing: docs/agent-timing.md lacks ISO 8601 timestamps (expected format: 2026-05-19T09:22:00)"
        )

    # Check row count vs expected roles
    data_rows = [line for line in timing_text.split("\n") if line.strip().startswith("|") and not line.strip().startswith("|-")]
    # Subtract header row
    data_row_count = max(0, len(data_rows) - 1)
    if data_row_count < 2:
        issues.append(
            f"agent-timing: docs/agent-timing.md has only {data_row_count} data rows — "
            "expected at least 2 role dispatch entries for a valid delivery"
        )

    return issues


def _check_completeness_markers(project_root: Path) -> list[str]:
    """P4-13: Check that key delivery documents end with <!-- END-OF-DOC --> marker.

    Files missing this marker are likely truncated by LLM output window.
    """
    issues: list[str] = []
    # Only check files that exist and are non-empty.
    completeness_targets = [
        "docs/\u9700\u6c42\u89c4\u683c\u4e66.md",
        "docs/\u8be6\u7ec6\u8bbe\u8ba1\u8bf4\u660e\u4e66.md",
        "docs/\u63a5\u53e3\u6570\u636e\u5951\u7ea6.md",
        "docs/\u5355\u5143\u6d4b\u8bd5\u62a5\u544a.md",
        "docs/\u96c6\u6210\u6d4b\u8bd5\u62a5\u544a.md",
        "docs/E2E\u6d4b\u8bd5\u62a5\u544a.md",
        "docs/\u4ee3\u7801\u8bc4\u5ba1.md",
        "docs/\u76d1\u7763\u5ba1\u8ba1.md",
    ]
    for doc in completeness_targets:
        text = _read_text(project_root, doc)
        if text is None:
            continue  # Missing file is caught by other checks.
        # Check last 200 chars for the marker
        tail = text[-200:] if len(text) > 200 else text
        if "<!-- END-OF-DOC -->" not in tail:
            issues.append(
                f"{doc}: missing completeness marker <!-- END-OF-DOC --> at end of file — "
                "document may be truncated. Re-dispatch owning role to regenerate complete file."
            )
    return issues


def _reconcile_changeset_with_disk(project_root: Path) -> list[str]:
    """P6-8: Verify that changeSet claims match actual disk state.

    Checks evidence-ledger roleRuns[*].changeSet.created files actually exist
    and changeSet.deleted files actually don't exist.
    """
    issues: list[str] = []
    ledger = _read_evidence_ledger(project_root)
    if ledger is None:
        return []  # No ledger — cannot reconcile

    for run in ledger.get("roleRuns") or []:
        if not isinstance(run, dict):
            continue
        role_id = run.get("roleId", "unknown")
        status = run.get("status", "")
        if status not in ("completed", "complete", "success", "passed"):
            continue

        cs = run.get("changeSet")
        if not isinstance(cs, dict) or cs.get("missing"):
            continue

        # Check created files exist
        created = cs.get("created", [])
        missing_created: list[str] = []
        for f in created:
            if not isinstance(f, str):
                continue
            if not (project_root / f).exists():
                missing_created.append(f)

        if missing_created and len(missing_created) > len(created) * 0.5:
            sample = ", ".join(missing_created[:3])
            issues.append(
                f"changeSet-drift[{role_id}]: {len(missing_created)}/{len(created)} 'created' files "
                f"do not exist on disk (sample: {sample}). Role may have hallucinated file creation."
            )

        # Check deleted files don't exist (they should be gone)
        deleted = cs.get("deleted", [])
        still_exists: list[str] = []
        for f in deleted:
            if not isinstance(f, str):
                continue
            if (project_root / f).exists():
                still_exists.append(f)

        if still_exists:
            sample = ", ".join(still_exists[:3])
            issues.append(
                f"changeSet-drift[{role_id}]: {len(still_exists)} 'deleted' files still exist on disk "
                f"(sample: {sample}). Deletion was claimed but not executed."
            )

    return issues


def _check_enhancement_declarations(project_root: Path) -> list[str]:
    """FC-B/OC-A: Verify enhancement declarations flow integrity.

    If evidence-ledger contains enhancementDeclarations with declarations,
    verify implementing roles received them and QA verified them.
    """
    issues: list[str] = []
    ledger = _read_evidence_ledger(project_root)
    if ledger is None:
        return []  # No ledger = checked elsewhere

    decls = ledger.get("enhancementDeclarations")
    if not decls or not decls.get("declarations"):
        return []  # No declarations = nothing to check

    total = decls.get("totalCount", len(decls.get("declarations", [])))
    if total == 0:
        return []

    # Check that implementing roles have receivedDeclarations
    role_runs = ledger.get("roleRuns", [])
    implementing_roles = {d.get("target") for d in decls.get("declarations", []) if d.get("target")}
    for role_run in role_runs:
        role_id = role_run.get("roleId", "")
        if role_id in implementing_roles and role_run.get("status") == "completed":
            received = role_run.get("receivedDeclarations", [])
            if not received:
                issues.append(
                    f"enhancement-declaration-flow: role '{role_id}' is a declaration target "
                    f"but has empty receivedDeclarations — Orchestrator may not have passed declarations in handoff"
                )

    # Check unfulfilled ratio (warning at >30%, blocking at >50%)
    unfulfilled = decls.get("unfulfilledCount", 0)
    waived = decls.get("waivedCount", 0)
    effective_unfulfilled = unfulfilled - waived
    if total > 0 and effective_unfulfilled > 0:
        ratio = effective_unfulfilled / total
        if ratio > 0.5:
            issues.append(
                f"enhancement-declaration-fulfillment: {effective_unfulfilled}/{total} declarations "
                f"unfulfilled ({ratio*100:.0f}% > 50% threshold) — indicates systemic implementation gap"
            )

    return issues


def _check_phases_consistency(project_root: Path) -> list[str]:
    """FC-B/OC-H: Verify incremental delivery phases have consistent structure.

    Each phase must have boundaryRef, independent deliveryGateEvidence,
    and consistent handoverTo/receivedFrom chain.
    """
    issues: list[str] = []
    ledger = _read_evidence_ledger(project_root)
    if ledger is None:
        return []

    phases = ledger.get("phases", [])
    if not phases:
        return []  # No phases = single-phase delivery, OK

    for i, phase in enumerate(phases):
        phase_id = phase.get("phaseId", f"phase-{i}")

        # Each completed phase must have deliveryGateEvidence
        if phase.get("status") == "completed" and not phase.get("deliveryGateEvidence"):
            issues.append(
                f"phase-consistency: phase '{phase_id}' is completed but has no "
                f"deliveryGateEvidence — each phase must be independently validated"
            )

        # Check handover chain consistency
        if i > 0:
            prev_phase = phases[i - 1]
            expected_from = prev_phase.get("phaseId", f"phase-{i-1}")
            actual_from = phase.get("receivedFrom", "")
            if actual_from and actual_from != expected_from:
                issues.append(
                    f"phase-consistency: phase '{phase_id}' receivedFrom='{actual_from}' "
                    f"does not match previous phase '{expected_from}'"
                )

        # Rollback scope must not exceed phase boundary
        rollback_scope = phase.get("rollbackScope", [])
        role_runs_in_phase = phase.get("roleRuns", [])
        if rollback_scope and not role_runs_in_phase:
            issues.append(
                f"phase-consistency: phase '{phase_id}' has rollbackScope but no roleRuns — "
                f"cannot verify rollback isolation"
            )

    return issues


def _check_parallel_conditions(project_root: Path) -> list[str]:
    """FC-B/OC-D: Verify parallel role execution preconditions.

    If two roles ran concurrently (overlapping timestamps), check that
    the parallel condition from OC-D was satisfied.
    """
    issues: list[str] = []
    ledger = _read_evidence_ledger(project_root)
    if ledger is None:
        return []

    role_runs = ledger.get("roleRuns", [])
    if len(role_runs) < 2:
        return []

    # Detect parallel pairs by checking if any two roles have overlapping
    # execution windows (using eventLog timestamps if available)
    event_log = ledger.get("eventLog", [])
    if not event_log:
        return []  # Cannot verify without event log

    # Build role start/end times from event log
    role_times: dict[str, dict] = {}
    for event in event_log:
        role_id = event.get("roleId", "")
        event_type = event.get("eventType", "")
        ts = event.get("timestamp", "")
        if not role_id or not ts:
            continue
        if role_id not in role_times:
            role_times[role_id] = {}
        if event_type == "role-start":
            role_times[role_id]["start"] = ts
        elif event_type == "role-complete":
            role_times[role_id]["end"] = ts

    # Check for FE+BE parallel without frozen contract
    fe_roles = [r for r in role_times if "frontend" in r]
    be_roles = [r for r in role_times if "backend" in r]
    dc_roles = [r for r in role_times if "data-contract" in r]

    if fe_roles and be_roles:
        for fe in fe_roles:
            for be in be_roles:
                fe_start = role_times[fe].get("start", "")
                be_end = role_times[be].get("end", "")
                be_start = role_times[be].get("start", "")
                fe_end = role_times[fe].get("end", "")
                # Simple overlap check: FE started before BE ended AND BE started before FE ended
                if fe_start and be_end and be_start and fe_end:
                    if fe_start < be_end and be_start < fe_end:
                        # They ran in parallel — check contract was frozen
                        dc_completed = any(
                            r.get("status") == "completed"
                            for r in role_runs
                            if "data-contract" in r.get("roleId", "")
                        )
                        if not dc_completed:
                            issues.append(
                                f"parallel-condition: FE ({fe}) and BE ({be}) ran in parallel "
                                f"but data-contract-designer did not complete first — "
                                f"contract must be frozen before FE+BE parallelization (OC-D)"
                            )

    return issues


def _check_epic_completeness(project_root: Path) -> list[str]:
    """RQ-D/E/F: Verify Epic grouping integrity.

    If the ledger contains epics array (FR >= 5), verify:
    1. All epics listed in ledger have corresponding spec files on disk.
    2. All role runs have epicId when epics are active.
    3. Epic dependencies have no cycles.
    """
    issues: list[str] = []
    ledger = _read_evidence_ledger(project_root)
    if ledger is None:
        return []

    epics = ledger.get("epics")
    if not epics or len(epics) == 0:
        return []  # No epics = small project, nothing to check

    # 1. Check that each epic has a spec file on disk
    for epic in epics:
        epic_id = epic.get("epicId", "")
        spec_file = epic.get("specFile", "")
        if spec_file:
            spec_path = project_root / spec_file
            if not spec_path.exists():
                issues.append(
                    f"epic-completeness: {epic_id} declares spec file {spec_file} but file does not exist on disk"
                )

    # 2. Check that role runs have epicId when epics are active
    role_runs = ledger.get("roleRuns", [])
    epic_implementing_roles = {"backend-engineer", "frontend-engineer", "execution-engineer", "data-contract-designer", "ui-designer"}
    for run in role_runs:
        role_id = (run.get("roleId", "") or "").lower()
        # Skip non-implementing roles (PA, Architect, QA, Auditor, etc.)
        if not any(impl in role_id for impl in epic_implementing_roles):
            continue
        epic_id = run.get("epicId")
        if not epic_id:
            issues.append(
                f"epic-completeness: role {role_id} ran but has no epicId — "
                f"when epics are active, all implementing roles must declare epicId"
            )

    # 3. Check for epic dependency cycles
    epic_deps: dict[str, list[str]] = {}
    for epic in epics:
        eid = epic.get("epicId", "")
        deps = epic.get("dependsOnEpics", [])
        if deps:
            epic_deps[eid] = deps

    # Simple cycle detection via DFS
    visited: set[str] = set()
    rec_stack: set[str] = set()
    def _has_cycle(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for dep in epic_deps.get(node, []):
            if dep not in visited:
                if _has_cycle(dep):
                    return True
            elif dep in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    for eid in epic_deps:
        if eid not in visited:
            if _has_cycle(eid):
                issues.append(
                    f"epic-completeness: Epic dependency cycle detected — check dependsOnEpics for cycle"
                )
                break

    return issues


def _check_input_contract_gate(project_root: Path) -> list[str]:
    """Upstream input contract gate (references/prd-input-contract.md).

    Only applies when the project supplies docs/input/. Re-runs the mechanical
    validation here so a role cannot claim the gate passed without evidence:
    broken traceability links and Must-level capability gaps are detected by
    script, not by eyeballing markdown tables.
    """
    blocking: list[str] = []
    if not (project_root / "docs" / "input").is_dir():
        return blocking

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate_input_contract import validate as _validate_input
    except ImportError:
        return [
            "input-contract gate: docs/input/ 存在但 scripts/validate_input_contract.py "
            "不可用，无法验证输入完整性门禁"
        ]

    try:
        report = _validate_input(project_root, "docs/input")
    except Exception as exc:  # noqa: BLE001 - never let the gate crash the run
        return [f"input-contract gate: 校验脚本执行异常 ({exc})"]

    verdict = report.get("verdict")
    gap_list = project_root / "docs" / "输入缺口清单.md"
    gap_list_ok = gap_list.exists() and gap_list.stat().st_size > 0

    if verdict == "fail":
        details = "; ".join((report.get("blocking") or [])[:3]) or "see script output"
        blocking.append(f"input-contract gate: verdict = fail -> {details}")
    elif verdict == "partial" and not gap_list_ok:
        details = "; ".join((report.get("mustGaps") or [])[:3]) or "see script output"
        blocking.append(
            "input-contract gate: verdict = partial 但缺少 docs/输入缺口清单.md，"
            f"输入缺口必须显式披露 -> {details}"
        )

    for ref in (report.get("brokenRefs") or [])[:5]:
        blocking.append(
            f"input-contract traceability: {ref['id']} 被引用于 "
            f"{', '.join(ref.get('referencedAt', []))}，但未定义于 {ref.get('ownerFile')}"
        )

    return blocking


def _is_self_executing_delivery_gate(report: dict[str, Any]) -> bool:
    """Allow SP-18 to prove its own command evidence without circular pre-writing.

    The final gate command cannot already exist as a passing ledger command on
    its first honest execution.  This exemption is deliberately narrow: every
    predecessor must already be satisfied, SP-18 must be the sole pending node,
    and its only unmet condition must be the command evidence produced by this
    very validator run.  Any additional unmet or downstream node still blocks.
    """
    progress = report.get("progress") or {}
    unmet = report.get("unmet") or []
    return (
        report.get("state") == "actionable"
        and report.get("currentNode") == "SP-18"
        and report.get("nodeType") == "gate"
        and progress.get("pending") == 1
        and len(unmet) == 1
        and "validate_delivery" in str(unmet[0])
        and not report.get("downstreamPending")
        and not report.get("blockedBy")
    )


def _check_process_node_coverage(project_root: Path, skill_root: Path) -> list[str]:
    """Replay the process pointer to expose skipped nodes at acceptance time.

    The Orchestrator advances through skill-process.json node by node. Here we
    recompute the pointer from the evidence ledger + filesystem: if any
    applicable node is still unsatisfied, the delivery cannot be complete no
    matter what the roles reported.
    """
    blocking: list[str] = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from next_step import resolve as _resolve_pointer
    except ImportError:
        return ["process-coverage: scripts/next_step.py 不可用，无法验证流程节点覆盖完整性"]

    try:
        report = _resolve_pointer(skill_root, project_root)
    except Exception as exc:  # noqa: BLE001 - never let the gate crash the run
        return [f"process-coverage: 指针推导异常 ({exc})"]

    state = report.get("state")
    if state == "halted":
        blocking.append(
            f"process-coverage: deliveryStatus={report.get('deliveryStatus')}，"
            "挂起的交付不得宣布完成"
        )
        return blocking

    if state == "actionable" and not _is_self_executing_delivery_gate(report):
        blocking.append(
            f"process-coverage: 还有 {report['progress']['pending']} 个适用流程节点未完成，"
            f"当前卡在 {report.get('currentNode')} {report.get('nodeName')}（"
            + "; ".join((report.get("unmet") or [])[:3]) + "）"
        )
        for item in report.get("downstreamPending", [])[:5]:
            blocking.append(f"process-coverage: 节点未覆盖 -> {item}")

    return blocking


_ENT_RE = re.compile(r"\bENT-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def _check_owl_traceability(project_root: Path) -> list[str]:
    """OWL baseline traceability gate (development-baseline-contract.md §9).

    Applies only when the project ships an OWL baseline
    (docs/input/models/ontology/*.owl). The Data Engineer prompt requires every
    table/field to back-link to the OWL class/property IRI and entity_id, so a
    code -> table -> OWL chain exists. This gate enforces that chain mechanically
    instead of trusting the role's self-report.

    Severity is deliberately calibrated. OWL -> relational mapping is NOT 1:1:
    an inheritance hierarchy may collapse to one table, or split into an
    extension table -- the choice is driven by query pattern and performance,
    NOT by OWL. Therefore PARTIAL entity coverage is legitimate and is NOT
    blocked. Only the unambiguous failure is blocked: a data design that
    references ZERO modeled entities while a model exists, because no legitimate
    engineering choice produces a complete disconnect.
    """
    blocking: list[str] = []
    ontology_dir = project_root / "docs" / "input" / "models" / "ontology"
    if not ontology_dir.is_dir() or not sorted(ontology_dir.glob("*.owl")):
        return blocking  # no OWL baseline -> gate not applicable

    domain_files = sorted((project_root / "docs" / "input").glob("02-*.md"))
    if not domain_files:
        return blocking
    try:
        domain_text = domain_files[0].read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return blocking
    modeled = set(_ENT_RE.findall(domain_text))
    if not modeled:
        return blocking

    design_text = _read_text(project_root, "docs/数据设计说明书.md")
    if design_text is None:
        return blocking  # 05 absence is judged by other gates
    traced = modeled & set(_ENT_RE.findall(design_text))
    if not traced:
        blocking.append(
            f"owl-traceability: OWL 基线存在且 02-领域模型 定义了 {len(modeled)} 个实体，"
            "但 05-数据设计说明书 未回链任何 entity_id（代码→表→OWL 追溯链完全断裂）。"
            "继承可合并/拆分（非 1:1），但不得整体脱链。"
        )
    return blocking


def validate_content_gates(project_root: Path, skill_root: Path | None = None) -> list[str]:
    """Inspect the contents of key delivery documents for hard violations.

    Returns a list of blocking reasons. Empty list = pass.
    """
    blocking: list[str] = []
    role_policy = {"objectiveSkippableRoles": set(), "mandatoryRoles": set()}
    if skill_root is not None:
        try:
            process = json.loads((skill_root / "assets" / "config" / "skill-process.json").read_text(encoding="utf-8"))
            if not isinstance(process, dict):
                raise ValueError("process root must be an object")
            role_policy = derive_role_policy(process)
        except (OSError, ValueError, json.JSONDecodeError):
            blocking.append("skill-process: unable to derive role skip policy from process truth source")

    # 1. Code review must be PASS, not BLOCK.
    review_text = _read_text(project_root, "docs/代码评审.md")
    if review_text is not None:
        if _scan_block_verdict(review_text):
            blocking.append("docs/代码评审.md: verdict = BLOCK detected")
        if _scan_conditional_pass(review_text):
            blocking.append("docs/代码评审.md: “有条件通过” is forbidden, must be PASS or BLOCK")

    # 2. Security review must be PASS when present.
    sec_text = _read_text(project_root, "docs/安全评审.md")
    if sec_text is not None:
        if _scan_block_verdict(sec_text):
            blocking.append("docs/安全评审.md: verdict = BLOCK detected")
        if _scan_conditional_pass(sec_text):
            blocking.append("docs/安全评审.md: “有条件通过” is forbidden, must be PASS or BLOCK")

    # 3. Unit test report must show real execution + coverage >= threshold.
    unit_report = _read_text(project_root, "docs/单元测试报告.md")
    if unit_report is not None:
        if _scan_build_failure(unit_report):
            blocking.append("docs/单元测试报告.md: BUILD FAILURE detected (test compile/run failed)")
        if _scan_zero_test_impl(unit_report):
            blocking.append(
                "docs/单元测试报告.md: zero unit-test implementation / 0% coverage detected",
            )
        coverage = _scan_unit_coverage(unit_report)
        if coverage is None:
            # Hard rule: coverage field must be present and machine-readable.
            blocking.append(
                "docs/单元测试报告.md: unit-test coverage field is missing or unparseable "
                "(must contain a line like '单元测试覆盖率：XX.X%' or '代码覆盖率：XX.X%'); "
                "missing the field is treated as 0% and BLOCKs delivery",
            )
        elif coverage < UNIT_TEST_COVERAGE_MIN:
            blocking.append(
                f"docs/单元测试报告.md: unit-test coverage {coverage:.1f}% < {UNIT_TEST_COVERAGE_MIN:.0f}% (project hard threshold)",
            )

    # 4. Integration test report must show coverage >= threshold (when present).
    integ_report = _read_text(project_root, "docs/集成测试报告.md")
    if integ_report is not None:
        if _scan_build_failure(integ_report):
            blocking.append("docs/集成测试报告.md: BUILD FAILURE detected")
        coverage = _scan_integration_coverage(integ_report)
        if coverage is None:
            blocking.append(
                "docs/集成测试报告.md: integration-test coverage field is missing or unparseable "
                "(must contain a line like '集成测试覆盖率：XX.X%'); missing the field is treated as 0% and BLOCKs delivery",
            )
        elif coverage < INTEGRATION_TEST_COVERAGE_MIN:
            blocking.append(
                f"docs/集成测试报告.md: integration-test coverage {coverage:.1f}% < {INTEGRATION_TEST_COVERAGE_MIN:.0f}% (project hard threshold)",
            )

    # 4b. E2E test report is MANDATORY for every delivery. Missing the file, BUILD
    #     FAILURE, missing pass-rate field, sub-100% pass rate, or zero cases all BLOCK.
    e2e_cases_text = _read_text(project_root, "docs/E2E测试用例.md")
    if e2e_cases_text is None:
        blocking.append(
            "docs/E2E测试用例.md: missing — E2E is mandatory for every delivery; Browser E2E Engineer must produce this file",
        )
    e2e_report = _read_text(project_root, "docs/E2E测试报告.md")
    if e2e_report is None:
        blocking.append(
            "docs/E2E测试报告.md: missing — E2E is mandatory for every delivery; Browser E2E Engineer must produce this file",
        )
    else:
        if _scan_build_failure(e2e_report):
            blocking.append("docs/E2E测试报告.md: BUILD FAILURE / run failure detected")
        if _scan_block_verdict(e2e_report):
            blocking.append("docs/E2E测试报告.md: verdict = BLOCK detected")
        if _scan_conditional_pass(e2e_report):
            blocking.append("docs/E2E测试报告.md: “有条件通过” is forbidden, must be PASS or BLOCK")
        pass_rate = _scan_e2e_pass_rate(e2e_report)
        if pass_rate is None:
            blocking.append(
                "docs/E2E测试报告.md: E2E pass-rate field is missing or unparseable "
                "(must contain a line like 'E2E测试通过率：XX.X%'); missing is treated as 0% and BLOCKs delivery",
            )
        elif pass_rate < E2E_PASS_RATE_MIN:
            blocking.append(
                f"docs/E2E测试报告.md: E2E pass-rate {pass_rate:.1f}% < {E2E_PASS_RATE_MIN:.0f}% (project hard threshold)",
            )
        total = _scan_e2e_total(e2e_report)
        if total is None:
            blocking.append(
                "docs/E2E测试报告.md: E2E case-total field is missing or unparseable "
                "(must contain a line like 'E2E测试总数：N'); missing is treated as 0 and BLOCKs delivery",
            )
        elif total < E2E_MIN_CASE_COUNT:
            blocking.append(
                f"docs/E2E测试报告.md: E2E case total = {total} < {E2E_MIN_CASE_COUNT} (must cover at least one P0 user journey)",
            )
        # Anti AI-fabrication: real execution must leave evidence (trace / screenshot / stdout).
        missing_ev = _scan_e2e_evidence(e2e_report)
        if missing_ev:
            blocking.append(
                "docs/E2E测试报告.md: insufficient real-execution evidence (anti AI-fabrication). "
                "At least 2 of {trace, screenshot, stdout} must be present; missing: "
                + "; ".join(missing_ev),
            )

    # 5. Supervisor audit conclusion must NOT be “有条件通过”.
    audit_text = _read_text(project_root, "docs/监督审计.md")
    if audit_text is not None and _scan_conditional_pass(audit_text):
        blocking.append(
            "docs/监督审计.md: “有条件通过” is forbidden; conclusion must be “通过” or “不通过，返工修复”",
        )

    # 6. Placeholder content scan across all key delivery documents.
    # Expanded coverage: required + conditional documents + execution log
    # to close the gap exposed in skill self-audit (UI / E2E / performance / planning / cases).
    placeholder_targets = [
        "docs/需求规格书.md",
        "docs/开发计划.md",
        "docs/任务清单.md",
        "docs/详细设计说明书.md",
        "docs/数据设计说明书.md",
        "docs/接口数据契约.md",
        "docs/UI设计说明.md",
        "docs/UI优化说明.md",
        "docs/性能优化说明.md",
        "docs/单元测试用例.md",
        "docs/单元测试报告.md",
        "docs/集成测试用例.md",
        "docs/集成测试报告.md",
        "docs/E2E测试用例.md",
        "docs/E2E测试报告.md",
        "docs/代码评审.md",
        "docs/安全评审.md",
        "docs/部署说明.md",
        "docs/监督审计.md",
        "docs/执行日志.md",
    ]
    for doc in placeholder_targets:
        text = _read_text(project_root, doc)
        if text is None:
            continue
        tokens = _scan_placeholders(text)
        if tokens:
            sample = ", ".join(tokens[:5])
            blocking.append(
                f"{doc}: placeholder content detected ({sample}) — unfilled stubs cannot be delivered",
            )

    # 7. Evidence ledger MUST exist and pass interlock checks.
    #    Missing ledger is now BLOCK (was previously skipped).
    ledger = _read_evidence_ledger(project_root)
    if ledger is None:
        blocking.append(
            "evidence-ledger: ledger file not found in any of "
            "docs/evidence-ledger.json | evidence-ledger.json | .qoder/evidence-ledger.json. "
            "Auditor cannot dispatch without it (see schemas/evidence-ledger.schema.json).",
        )
    else:
        if skill_root is not None:
            blocking.extend(_validate_evidence_ledger_schema(skill_root, ledger))
        # 7a. deliveryStatus interlock
        status = ledger.get("deliveryStatus")
        if not isinstance(status, str) or not status:
            blocking.append(
                "evidence-ledger: required field 'deliveryStatus' missing or empty "
                "(see schemas/evidence-ledger.schema.json required list)",
            )
        elif status in HALT_BLOCKING_STATES:
            blocking.append(
                f"evidence-ledger: deliveryStatus = '{status}' — halt/failed states cannot pass the delivery gate; "
                "produce docs/未完成交付报告.md per references/halt-and-resume-policy.md instead",
            )
        if status == "halted-user-cancel":
            cancel_ev = ledger.get("cancellationEvidence") or {}
            if cancel_ev.get("cancellationOrigin") != "user" or not cancel_ev.get("userMessageRef"):
                blocking.append(
                    "evidence-ledger: halted-user-cancel requires cancellationEvidence.cancellationOrigin = 'user' "
                    "and a non-empty userMessageRef",
                )

        # 7b. deliveryGateEvidence interlock (Auditor must consume real validator output).
        gate_ev = ledger.get("deliveryGateEvidence")
        if not isinstance(gate_ev, dict) or not gate_ev:
            blocking.append(
                "evidence-ledger: required field 'deliveryGateEvidence' missing — "
                "Orchestrator must paste the latest validate_delivery.py output before Auditor dispatch",
            )
        else:
            for k in ("status", "blockingReasons", "runAt"):
                if k not in gate_ev:
                    blocking.append(
                        f"evidence-ledger.deliveryGateEvidence: required key '{k}' missing",
                    )
            if gate_ev.get("strictMode") is False and not ledger.get("strictModeWaiver"):
                blocking.append(
                    "evidence-ledger: deliveryGateEvidence.strictMode=false but no strictModeWaiver block; "
                    "--no-strict requires user-approved waiver (see schemas/evidence-ledger.schema.json strictModeWaiver)",
                )

        # 7c. rework cap interlock (HARD) — supports LP-D adaptive caps.
        adaptive_caps = ledger.get("adaptiveReworkCaps") or {}
        effective_cumulative_cap = adaptive_caps.get("cumulativeCap", MAX_REWORK_CUMULATIVE)
        effective_per_root_cap = adaptive_caps.get("perRootCauseCap", MAX_REWORK_PER_ROOT_CAUSE)
        rework = (ledger.get("observability") or {}).get("reworkCount")
        if isinstance(rework, (int, float)) and rework > effective_cumulative_cap:
            blocking.append(
                f"evidence-ledger: observability.reworkCount = {rework} > {effective_cumulative_cap} (cumulative rework cap, LP-D adaptive={bool(adaptive_caps)})",
            )
        per_root = (ledger.get("observability") or {}).get("reworkPerRootCause") or ledger.get("reworkPerRootCause") or {}
        if isinstance(per_root, dict):
            for root_id, n in per_root.items():
                if isinstance(n, (int, float)) and n > effective_per_root_cap:
                    blocking.append(
                        f"evidence-ledger: reworkPerRootCause[{root_id}] = {n} > {effective_per_root_cap} (per-root-cause rework cap, LP-D adaptive={bool(adaptive_caps)})",
                    )
        # 7d. reworkCount vs roleRuns reconciliation.
        if isinstance(rework, (int, float)) and rework > 0:
            if not isinstance(per_root, dict) or not per_root:
                blocking.append(
                    "evidence-ledger: observability.reworkCount > 0 but reworkPerRootCause is empty — "
                    "per-root-cause breakdown is mandatory to verify the 5-per-root cap",
                )
            role_retry_total = 0
            for run in ledger.get("roleRuns") or []:
                rc = run.get("retryCount") if isinstance(run, dict) else None
                if isinstance(rc, (int, float)):
                    role_retry_total += int(rc)
            # reworkCount counts user-initiated rework iterations; it must be <= sum(retryCount)+role_blocked_loops.
            # Conservative reconciliation: reworkCount must NOT exceed total retryCount across all roles.
            if role_retry_total > 0 and rework > role_retry_total:
                blocking.append(
                    f"evidence-ledger: observability.reworkCount={rework} exceeds sum(roleRuns[*].retryCount)={role_retry_total}; "
                    "self-reported rework count is unsupported by per-role retry evidence",
                )

        # 7e. roleRuns[*].reasonForSkip whitelist + skippable-role whitelist.
        for run in ledger.get("roleRuns") or []:
            if not isinstance(run, dict):
                continue
            run_status = run.get("status")
            if run_status not in ("skipped", "skip", "not-run"):
                continue
            role_id = run.get("roleId", "<unknown>")
            reason = run.get("reasonForSkip")
            if not reason:
                blocking.append(
                    f"evidence-ledger.roleRuns[{role_id}]: status='skipped' but reasonForSkip missing "
                    "(must be one of {tooling-missing|upstream-blocked|user-approved|objective-conditions-met|cascade-block})",
                )
            elif reason not in ALLOWED_REASON_FOR_SKIP:
                blocking.append(
                    f"evidence-ledger.roleRuns[{role_id}]: reasonForSkip='{reason}' not in whitelist "
                    f"({sorted(ALLOWED_REASON_FOR_SKIP)})",
                )
            elif reason == "objective-conditions-met":
                if role_id not in role_policy["objectiveSkippableRoles"]:
                    blocking.append(
                        f"evidence-ledger.roleRuns[{role_id}]: 'objective-conditions-met' is not allowed for non-skippable roles "
                        f"(process-derived skippable roles: {sorted(role_policy['objectiveSkippableRoles'])})",
                    )
                if not run.get("objectiveConditionsRef"):
                    blocking.append(
                        f"evidence-ledger.roleRuns[{role_id}]: reasonForSkip='objective-conditions-met' requires "
                        "objectiveConditionsRef (specific clause references, e.g. 'performance-engineer.prompt.md L13-19 condition 1')",
                    )

        # 7e2. Mandatory roles must appear in roleRuns with completed status (no opt-out).
        present_roles: dict[str, str] = {}
        for run in ledger.get("roleRuns") or []:
            if isinstance(run, dict):
                rid = run.get("roleId")
                rstatus = run.get("status") or ""
                if isinstance(rid, str) and rid:
                    present_roles[rid] = rstatus
        for mandatory in MANDATORY_ROLES_IN_LEDGER:
            if mandatory not in present_roles:
                blocking.append(
                    f"evidence-ledger.roleRuns: mandatory role '{mandatory}' is missing "
                    f"(role is mandatory for every delivery; no skip allowed)",
                )
            elif present_roles[mandatory] not in ("completed", "complete", "success", "passed"):
                blocking.append(
                    f"evidence-ledger.roleRuns[{mandatory}]: status='{present_roles[mandatory]}' is not a completed terminal state "
                    f"(mandatory role must reach 'completed'; skipped/blocked is forbidden)",
                )

        # 7f. fallbackTrigger interlock (silent fallback is forbidden).
        has_fallback = any(
            isinstance(run, dict) and run.get("sessionMode") == "single-session-fallback"
            for run in (ledger.get("roleRuns") or [])
        )
        if has_fallback:
            ft = ledger.get("fallbackTrigger")
            if not isinstance(ft, dict) or not ft:
                blocking.append(
                    "evidence-ledger: roleRuns contains sessionMode='single-session-fallback' but fallbackTrigger is missing "
                    "(see schemas/evidence-ledger.schema.json fallbackTrigger; required fields: "
                    "fallbackReason / fallbackApprover / fallbackTimestamp)",
                )
            else:
                for k in ("fallbackReason", "fallbackApprover", "fallbackTimestamp"):
                    if not ft.get(k):
                        blocking.append(
                            f"evidence-ledger.fallbackTrigger: required field '{k}' missing",
                        )

        # 7g. expectedOutputs coverage check (P1-3).
        #     For each completed role, verify that changeSet covers expectedOutputs.
        config_path = skill_root / "assets" / "config" / "agent-team-config.json" if skill_root else None
        role_expected_outputs: dict[str, list[str]] = {}
        if config_path and config_path.exists():
            try:
                _cfg = json.loads(config_path.read_text(encoding="utf-8"))
                for _role in _cfg.get("roles", []):
                    _rid = _role.get("id", "")
                    _eo = _role.get("expectedOutputs", [])
                    if _rid and _eo:
                        role_expected_outputs[_rid] = _eo
            except Exception:
                pass  # Non-critical: config parse error does not block delivery

        completed_role_touched: dict[str, set[str]] = {}
        completed_role_declared_outputs: dict[str, set[str]] = {}
        completed_role_has_change_set: set[str] = set()
        completed_roles: set[str] = set()
        for run in ledger.get("roleRuns") or []:
            if not isinstance(run, dict):
                continue
            run_status = run.get("status", "")
            if run_status not in ("completed", "complete", "success", "passed"):
                continue
            role_id = run.get("roleId", "")
            if not role_id:
                continue
            completed_roles.add(role_id)
            completed_role_declared_outputs.setdefault(role_id, set()).update(
                value for value in (run.get("expectedOutputs") or []) if isinstance(value, str)
            )
            completed_role_touched.setdefault(role_id, set())
            change_set = run.get("changeSet")
            if isinstance(change_set, dict) and not change_set.get("missing"):
                completed_role_has_change_set.add(role_id)
                completed_role_touched[role_id].update(
                    value
                    for value in (
                        change_set.get("modified", [])
                        + change_set.get("created", [])
                        + change_set.get("deleted", [])
                    )
                    if isinstance(value, str)
                )

        # Rework/reverification creates several completed occurrences for the
        # same role.  Expected outputs belong to the role's delivery as a
        # whole; a read-only reverify must not be forced to rewrite artifacts
        # that an earlier completed occurrence already produced.
        for role_id in sorted(completed_roles):
            expected = role_expected_outputs.get(role_id) or sorted(
                completed_role_declared_outputs.get(role_id, set())
            )
            if not expected:
                continue
            if role_id not in completed_role_has_change_set:
                blocking.append(
                    f"evidence-ledger.roleRuns[{role_id}]: completed delivery has no usable changeSet; "
                    f"cannot verify expectedOutputs coverage ({expected})",
                )
                continue
            all_touched = completed_role_touched.get(role_id, set())
            # Glob-style expectedOutputs (e.g. "scripts/**") — check prefix match.
            for pattern in expected:
                prefix = pattern.rstrip("*").rstrip("/")
                if not any(f.startswith(prefix) or f == pattern for f in all_touched):
                    blocking.append(
                        f"evidence-ledger.roleRuns[{role_id}]: expectedOutput '{pattern}' not covered by aggregated changeSet "
                        f"(touched: {sorted(all_touched)[:5]}{'...' if len(all_touched) > 5 else ''})",
                    )

    # 8. Audit document interlock with deliveryGateEvidence (Auditor must paste validator output).
    audit_text2 = _read_text(project_root, "docs/监督审计.md")
    if audit_text2 is not None:
        # Auditor MUST quote the validator output verbatim. Look for at least one of:
        # "validate_delivery.py" + "status" + ("pass" or "fail").
        has_command = "validate_delivery.py" in audit_text2
        has_status = bool(re.search(r"status\s*[:=\uff1a]\s*[`\"\u201c]?\s*(pass|fail)\b", audit_text2, re.IGNORECASE))
        if not (has_command and has_status):
            blocking.append(
                "docs/监督审计.md: Auditor must paste the latest validate_delivery.py output (command + status: pass/fail) verbatim. "
                "Free-text references like '已检查' are not enough.",
            )

    # 9. Coverage artifact existence (P0-2).
    #    Only check when coverage is claimed >= threshold (file exists + coverage parsed).
    unit_report_text = _read_text(project_root, "docs/单元测试报告.md")
    integ_report_text = _read_text(project_root, "docs/集成测试报告.md")
    coverage_claimed = False
    if unit_report_text and _scan_unit_coverage(unit_report_text) is not None:
        coverage_claimed = True
    if integ_report_text and _scan_integration_coverage(integ_report_text) is not None:
        coverage_claimed = True
    if coverage_claimed:
        blocking.extend(_check_coverage_artifacts(project_root))

    # 10. Ledger temporal consistency (P0-3).
    if ledger is not None:
        blocking.extend(_check_ledger_temporal_consistency(project_root, ledger))

    # 11. Database migration alignment (P0-4).
    blocking.extend(_check_db_migration_alignment(project_root))

    # 12. Agent timing format validation (P4-10).
    blocking.extend(_check_agent_timing_format(project_root))

    # 13. Completeness Guard: END-OF-DOC tail marker check (P4-13).
    blocking.extend(_check_completeness_markers(project_root))

    # 14. Document structure conformance (P5-5).
    # Note: skill_root is not available here; caller (validate_delivery) handles this.

    # 15. Requirement traceability audit (P5-3).
    try:
        from trace_requirements import trace_requirements as _tr
        trace_report = _tr(project_root)
        if trace_report.get("status") == "fail":
            for gap in trace_report.get("gaps", []):
                blocking.append(
                    f"traceability: {gap['doc']} covers only {gap['coveragePct']}% of source requirements "
                    f"(missing: {gap['missingReqs'][:5]})"
                )
    except ImportError:
        pass  # trace_requirements.py not in path — skip

    # 16. changeSet disk reconciliation (P6-8).
    blocking.extend(_reconcile_changeset_with_disk(project_root))

    # 17. OC Enhancement declarations flow verification (FC-B).
    blocking.extend(_check_enhancement_declarations(project_root))

    # 18. Incremental delivery phases consistency (FC-B).
    blocking.extend(_check_phases_consistency(project_root))

    # 19. Parallel execution conditions (FC-B).
    blocking.extend(_check_parallel_conditions(project_root))

    # 20. Epic completeness check (RQ-D/E/F).
    blocking.extend(_check_epic_completeness(project_root))

    # 21. Upstream input contract gate (prd-input-contract.md), conditional on docs/input/.
    blocking.extend(_check_input_contract_gate(project_root))

    # 22. Process node coverage (skill-process.json). Replays the pointer so a
    #     skipped node cannot hide behind self-reported role statuses.
    blocking.extend(_check_process_node_coverage(project_root, Path(__file__).resolve().parent.parent))

    # 23. OWL baseline traceability (development-baseline-contract.md §9). When
    #     an OWL baseline exists, the data design must keep the code->table->OWL
    #     chain. Zero entity back-links = hard fail; partial coverage is allowed
    #     because OWL->relational mapping is intentionally not 1:1.
    blocking.extend(_check_owl_traceability(project_root))

    return blocking


def _suggest_fix(reason: str) -> str:
    """P3-2: Map a blocking reason to an actionable fix suggestion."""
    r = reason.lower()
    if "process-coverage" in r:
        return ("运行 python scripts/next_step.py --skill-root <skill-root> --project-root . "
                "查看当前卡住的流程节点，按它给出的 action 补齐（派角色或跑门禁）。"
                "节点定义见 assets/config/skill-process.json。")
    if "input-contract traceability" in r:
        return ("上游追溯链断链：在定义文件中补充该编号，或修正引用处的编号。"
                "定义归属见 references/prd-input-contract.md；SC/ROLE→00、CAP→01、"
                "ENT/REL→02、ST→03、RULE→04、PROC/ND/EX/IF→05、EV→06、Q→07。"
                "修正后重跑 scripts/validate_input_contract.py。")
    if "input-contract gate" in r:
        return ("运行 python scripts/validate_input_contract.py --project-root . "
                "--gap-list-out docs/输入缺口清单.md，按输出补齐上游 docs/input/ 内容。"
                "禁止由 AI 自行补全业务规则/状态流转/验收口径。")
    if "missing" in r and "docs/" in r:
        doc_name = reason.split(":")[0].strip()
        return f"Dispatch the responsible role to produce {doc_name}. Check agent-team-config.json roles[*].expectedOutputs for ownership."
    if "unit-test coverage" in r and "%" in r:
        return "Re-run Quality Gate Engineer: increase unit test cases to cover uncovered branches. Target >=90%. Run 'mvn test' or 'npm test' with coverage flag."
    if "integration-test coverage" in r:
        return "Re-run Quality Gate Engineer: add integration test cases for untested API endpoints. Target >=80%."
    if "e2e pass-rate" in r:
        return "Re-dispatch Browser E2E Engineer to fix failing E2E cases. Ensure dev server is running and test data is seeded before execution."
    if "e2e" in r and "missing" in r:
        return "Dispatch Browser E2E Engineer in independent session with Browser subagent. This role is mandatory for every delivery."
    if "e2e" in r and "evidence" in r:
        return "Browser E2E Engineer must run real tests (not fabricate). Ensure report contains trace file path, screenshot path, and stdout log path."
    if "verdict" in r and "block" in r:
        return "Re-dispatch implementation roles (backend/frontend) to fix BLOCK findings, then re-run Quality Gate Engineer for re-review."
    if "\u6709\u6761\u4ef6\u901a\u8fc7" in reason or "conditional" in r:
        return "Verdict must be PASS or BLOCK only. Remove conditional language and re-evaluate: either all critical issues are resolved (PASS) or not (BLOCK)."
    if "placeholder" in r:
        return "Replace all placeholder tokens (<TBD>/<TODO>/\u5f85\u8865\u5145/xxx) with actual content. Re-dispatch the owning role to fill in real data."
    if "evidence-ledger" in r and "missing" in r:
        return "Orchestrator must create evidence-ledger.json via scripts/write_evidence_ledger.py before dispatching Supervisor Auditor."
    if "deliverystatus" in r or "halt" in r:
        return "Delivery is in a halted state. Produce docs/\u672a\u5b8c\u6210\u4ea4\u4ed8\u62a5\u544a.md per halt-and-resume-policy.md. Cannot pass delivery gate in halt state."
    if "rework" in r and "cap" in r:
        return "Rework cap exceeded. Set deliveryStatus=halted-pending-user and await user direction. Do not auto-rework further."
    if "coverage-artifact" in r:
        return "Run tests with coverage enabled (e.g., 'mvn verify -Pcoverage' or 'npx jest --coverage') so real coverage files exist on disk."
    if "temporal consistency" in r:
        return "Re-run roles to produce fresh documents, or verify ledger.createdAt matches actual execution window."
    if "database-migration" in r:
        return "Create versioned migration files (Flyway/Liquibase/Prisma) matching tables in \u6570\u636e\u8bbe\u8ba1\u8bf4\u660e\u4e66.md."
    if "build fail" in r:
        return "Fix compilation/build errors first. Run build command locally, resolve all errors, then re-execute tests."
    if "agent-timing" in r:
        return "Orchestrator must maintain docs/agent-timing.md with ISO 8601 timestamps for each role dispatch/completion."
    if "end-of-doc" in r or "completeness" in r:
        return "File appears truncated. Re-dispatch the owning role to regenerate the complete document with <!-- END-OF-DOC --> tail marker."
    if "fallbacktrigger" in r:
        return "Record fallbackTrigger in evidence ledger with fallbackReason, fallbackApprover, and fallbackTimestamp before proceeding."
    if "validate_delivery" in r and "\u76d1\u7763\u5ba1\u8ba1" in reason:
        return "Supervisor Auditor must paste the exact validate_delivery.py output (command + status) in docs/\u76d1\u7763\u5ba1\u8ba1.md verbatim."
    if "enhancement-declaration" in r:
        return "Orchestrator must pass enhancementDeclarations from Architect to implementing roles via handoff. Implementing roles must report receivedDeclarations in roleResult."
    if "phase-consistency" in r:
        return "Each incremental delivery phase must have independent deliveryGateEvidence and consistent handoverTo/receivedFrom chain. Re-run validate_delivery.py per phase."
    if "parallel-condition" in r:
        return "Parallel role execution requires preconditions (e.g., frozen contract for FE+BE). Record parallel justification in evidence ledger or serialize execution."
    return "Review the blocking reason and dispatch the responsible role to address the specific issue."


def validate_delivery(
    skill_root: Path,
    project_root: Path,
    ui_affected: bool,
    security_sensitive: bool,
    strict_mode: bool = True,
) -> dict:
    config = load_config(skill_root)
    plan: dict = {}
    plan_path = project_root / "docs" / "orchestration-plan.json"
    if not plan_path.is_file():
        plan_path = project_root / "orchestration-plan.json"
    if plan_path.is_file():
        try:
            loaded_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if isinstance(loaded_plan, dict):
                plan = loaded_plan
        except (OSError, json.JSONDecodeError):
            plan = {}
    required_docs = list(config.get("artifacts", {}).get("requiredDocuments", []))
    conditional_docs = []
    if ui_affected:
        conditional_docs.append(("docs/UI设计说明.md", ["docs/UI设计说明.md", "docs/UI优化说明.md"]))
    # Security review is REQUIRED by default in strict mode.
    # Only when security_sensitive == False AND strict_mode == False can it be skipped.
    if security_sensitive or strict_mode:
        conditional_docs.append(("docs/安全评审.md", ["docs/安全评审.md"]))

    checks = []
    blocking_reasons = []

    # Deterministic code-intelligence delivery gate. Legacy/docs-only ledgers
    # remain valid; an applicable code change cannot omit or downgrade evidence.
    try:
        from validate_code_intelligence import validate_phase as _validate_code_phase
        ledger_for_code = _read_evidence_ledger(project_root) or {}
        code_report = _validate_code_phase("delivery", project_root, ledger_for_code)
        checks.append({"name": "code-intelligence", "status": code_report.get("status", "fail"), "evidence": f"C-CODE-01..07 applicability={code_report.get('applicability')}"})
        if code_report.get("status") != "pass":
            for reason in code_report.get("blockingReasons", []) + code_report.get("unknownReasons", []):
                blocking_reasons.append(f"code-intelligence: {reason}")
    except (ImportError, OSError, ValueError, json.JSONDecodeError) as exc:
        checks.append({"name": "code-intelligence", "status": "fail", "evidence": type(exc).__name__})
        blocking_reasons.append("code-intelligence: validator unavailable or invalid")

    for doc in required_docs:
        ok, status = check_file(project_root, doc)
        checks.append({"name": doc, "status": "pass" if ok else "fail", "evidence": status})
        if not ok:
            blocking_reasons.append(f"{doc}: {status}")

    for label, alternatives in conditional_docs:
        passed = False
        evidence = []
        for doc in alternatives:
            ok, status = check_file(project_root, doc)
            evidence.append(f"{doc}={status}")
            passed = passed or ok
        checks.append({"name": label, "status": "pass" if passed else "fail", "evidence": "; ".join(evidence)})
        if not passed:
            blocking_reasons.append(f"{label}: missing conditional artifact")

    validation_docs = [
        "docs/单元测试报告.md",
        "docs/集成测试报告.md",
        "docs/E2E测试用例.md",
        "docs/E2E测试报告.md",
        "docs/代码评审.md",
        "docs/部署说明.md",
        "docs/监督审计.md",
    ]
    for doc in validation_docs:
        ok, status = check_file(project_root, doc)
        if not ok:
            blocking_reasons.append(f"quality evidence missing: {doc} ({status})")

    # New: content-level gates (not just file existence).
    content_blockers = validate_content_gates(project_root, skill_root)
    for reason in content_blockers:
        checks.append({"name": reason.split(":", 1)[0], "status": "fail", "evidence": reason})
    blocking_reasons.extend(content_blockers)

    # P5-5: Document structure conformance (requires skill_root for templates).
    try:
        from validate_doc_structure import validate_doc_structure as _vds
        doc_struct_report = _vds(skill_root, project_root)
        if doc_struct_report.get("status") == "fail":
            for br in doc_struct_report.get("blockingReasons", []):
                checks.append({"name": "doc-structure", "status": "fail", "evidence": br})
                blocking_reasons.append(f"doc-structure: {br}")
    except ImportError:
        pass  # validate_doc_structure.py not in path — skip

    # P7-2: Environment pre-condition check (non-blocking, advisory).
    try:
        from preflight_env_check import preflight_env_check as _pec
        env_report = _pec(project_root, plan.get("stackDetection"))
        if env_report.get("status") == "not-ready":
            for b in env_report.get("blocking", []):
                checks.append({"name": "env-preflight", "status": "warn", "evidence": b})
    except ImportError:
        pass  # preflight_env_check.py not available — skip

    # P7-5: API contract drift detection (blocking if coverage < 50%).
    try:
        from contract_drift_check import check_contract_drift as _cdc
        drift_report = _cdc(project_root)
        if drift_report.get("status") == "fail":
            for br in drift_report.get("blockingReasons", []):
                checks.append({"name": "contract-drift", "status": "fail", "evidence": br})
                blocking_reasons.append(f"contract-drift: {br}")
        elif drift_report.get("status") == "warn":
            checks.append({"name": "contract-drift", "status": "warn", "evidence": f"Coverage {drift_report.get('coveragePct', '?')}%"})
    except ImportError:
        pass  # contract_drift_check.py not available — skip

    # PRD Sync Gate: code-vs-PRD reverse drift. Triggers reverse-sync-workflow.md when code
    # introduces feature points not mapped to any FR/NFR in docs/01-需求规格书.md.
    # Composed of three sub-checks: requirement_drift_check + trace_requirements + contract_drift
    # (the last one is reported above; we re-aggregate its status here for prdSyncStatus).
    prd_sync_substatuses: list[str] = []
    try:
        from requirement_drift_check import check_requirement_drift as _rdc
        req_drift = _rdc(project_root)
        prd_sync_substatuses.append(req_drift.get("status", "skip"))
        if req_drift.get("status") == "fail":
            for br in req_drift.get("blockingReasons", []):
                checks.append({"name": "requirement-drift", "status": "fail", "evidence": br})
                blocking_reasons.append(f"requirement-drift: {br}")
        elif req_drift.get("status") == "warn":
            checks.append({
                "name": "requirement-drift",
                "status": "warn",
                "evidence": req_drift.get("reason") or f"FR coverage {req_drift.get('coveragePct', '?')}%",
            })
    except ImportError:
        prd_sync_substatuses.append("skip")
    try:
        from trace_requirements import trace_requirements as _tr
        trace_report = _tr(project_root)
        prd_sync_substatuses.append(trace_report.get("status", "skip"))
        if trace_report.get("status") == "fail":
            checks.append({
                "name": "trace-requirements",
                "status": "fail",
                "evidence": f"Source FR count {trace_report.get('sourceReqCount', 0)}, gaps={len(trace_report.get('gaps', []))}",
            })
            blocking_reasons.append(
                f"trace-requirements: PRD->downstream traceability failed with {len(trace_report.get('gaps', []))} gap(s)"
            )
        elif trace_report.get("status") == "warn":
            checks.append({
                "name": "trace-requirements",
                "status": "warn",
                "evidence": f"{len(trace_report.get('gaps', []))} downstream coverage gap(s)",
            })
    except ImportError:
        prd_sync_substatuses.append("skip")
    # Aggregate PRD Sync Gate status. Includes the upstream contract-drift status when present.
    try:
        prd_sync_substatuses.append(drift_report.get("status", "skip"))  # noqa: F821
    except NameError:
        prd_sync_substatuses.append("skip")
    if "fail" in prd_sync_substatuses:
        prd_sync_status = "fail"
    elif "warn" in prd_sync_substatuses:
        prd_sync_status = "warn"
    elif all(s == "skip" for s in prd_sync_substatuses):
        prd_sync_status = "not-run"
    else:
        prd_sync_status = "pass"
    checks.append({
        "name": "PRD Sync Gate",
        "status": prd_sync_status if prd_sync_status in {"pass", "fail", "warn", "not-run"} else "not-run",
        "evidence": f"sub-status: {prd_sync_substatuses}",
    })

    # P3-2: Generate suggestedFix for each blocking reason.
    suggested_fixes = [_suggest_fix(r) for r in blocking_reasons]

    # M2: Auto-ingest blocking failures as failure patterns for future prevention.
    if blocking_reasons:
        try:
            from memory_store import load_failure_patterns, save_failure_patterns, ingest_failure
            _stack_sig = ""
            if plan.get("stackDetection"):
                import hashlib
                _adapters = sorted(plan["stackDetection"].get("selectedAdapters", []))
                _stack_sig = hashlib.sha256("|".join(_adapters).encode()).hexdigest()[:12]
            fp = load_failure_patterns(project_root)
            for reason in blocking_reasons:
                # Classify category from reason prefix
                cat = "other"
                if "doc-structure" in reason or "missing-doc" in reason:
                    cat = "schema"
                elif "contract-drift" in reason:
                    cat = "contract-drift"
                elif "env-preflight" in reason:
                    cat = "env"
                elif "test" in reason.lower() or "coverage" in reason.lower():
                    cat = "test"
                elif "auth" in reason.lower() or "security" in reason.lower():
                    cat = "auth"
                fp = ingest_failure(
                    fp, reason, category=cat, stack_sig=_stack_sig,
                    fix_hint=_suggest_fix(reason),
                    evidence_link=f"delivery:{plan.get('deliveryId', 'unknown')}",
                )
            save_failure_patterns(project_root, fp)
        except ImportError:
            pass  # memory_store.py not available — skip
        except Exception:
            pass  # Non-critical: don’t break validation if memory write fails

    return {
        "gateName": "software-development-team delivery gate",
        "status": "pass" if not blocking_reasons else "fail",
        "checks": checks,
        "blockingReasons": blocking_reasons,
        "suggestedFixes": suggested_fixes,
        "thresholds": {
            "unitTestCoverageMin": UNIT_TEST_COVERAGE_MIN,
            "integrationTestCoverageMin": INTEGRATION_TEST_COVERAGE_MIN,
        },
        "strictMode": strict_mode,
        "prdSyncStatus": prd_sync_status,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to the skill root")
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--ui", action="store_true", help="Require UI conditional artifacts")
    parser.add_argument(
        "--security-sensitive",
        action="store_true",
        help="(Legacy) Mark task as security-sensitive. In strict mode this is the default.",
    )
    parser.add_argument(
        "--security-not-applicable",
        action="store_true",
        help="Explicitly mark security review as not applicable. "
             "Has NO effect unless BOTH --no-strict AND --security-not-applicable-evidence "
             "are provided. Self-declared skips without user-approved evidence are forbidden.",
    )
    parser.add_argument(
        "--security-not-applicable-evidence",
        default=None,
        help="Path (relative to project root) to a security-trigger-word scan report proving "
             "every word/pattern in the security trigger list was scanned and missed. "
             "REQUIRED whenever --security-not-applicable is set.",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Disable strict mode. STRONGLY DISCOURAGED. Requires BOTH --strict-waiver-justification "
             "(>=20 chars) AND --strict-waiver-approver-message-ref. Without those, --no-strict is rejected.",
    )
    parser.add_argument(
        "--strict-waiver-justification",
        default=None,
        help="Free-text justification (>=20 chars) explaining why strict mode is being waived. "
             "REQUIRED whenever --no-strict is set.",
    )
    parser.add_argument(
        "--strict-waiver-approver-message-ref",
        default=None,
        help="Reference to the human user message approving the strict waiver "
             "(e.g. conversation turn id or quoted user statement). "
             "REQUIRED whenever --no-strict is set. Orchestrator self-approval is forbidden.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args(argv)

    # --- Hard gate on strict-mode waiver: reject silent --no-strict ---
    if args.no_strict:
        justification = (args.strict_waiver_justification or "").strip()
        approver_ref = (args.strict_waiver_approver_message_ref or "").strip()
        if len(justification) < 20 or not approver_ref:
            print(
                "ERROR: --no-strict requires both --strict-waiver-justification (>=20 chars) "
                "and --strict-waiver-approver-message-ref. Refusing to run in non-strict mode "
                "without user-approved waiver evidence.",
                file=sys.stderr,
            )
            return 2

    # --- Hard gate on security-not-applicable: forbid self-declared skip ---
    if args.security_not_applicable:
        evidence_path = args.security_not_applicable_evidence
        if not args.no_strict:
            print(
                "ERROR: --security-not-applicable cannot be combined with strict mode. "
                "Strict mode always requires the security review artifact.",
                file=sys.stderr,
            )
            return 2
        if not evidence_path:
            print(
                "ERROR: --security-not-applicable requires --security-not-applicable-evidence "
                "pointing to a security-trigger-word scan report.",
                file=sys.stderr,
            )
            return 2
        full_path = (Path(args.project_root).resolve() / evidence_path)
        if not full_path.is_file():
            print(
                f"ERROR: --security-not-applicable-evidence path '{evidence_path}' "
                f"does not exist or is not a file (resolved: {full_path}).",
                file=sys.stderr,
            )
            return 2

    strict_mode = not args.no_strict
    # In strict mode, security review is always required regardless of legacy flag.
    # Outside strict mode, security review is required unless explicitly marked not-applicable
    # AND backed by an existing trigger-word scan report.
    security_sensitive = (
        True
        if strict_mode
        else (args.security_sensitive or not args.security_not_applicable)
    )

    result = validate_delivery(
        Path(args.skill_root).resolve(),
        Path(args.project_root).resolve(),
        args.ui,
        security_sensitive,
        strict_mode=strict_mode,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Gate: {result['gateName']}")
        print(f"Status: {result['status'].upper()}")
        print(f"Strict mode: {'ON' if strict_mode else 'OFF (WAIVED)'}")
        for check in result["checks"]:
            print(f"- {check['status'].upper()} {check['name']} ({check['evidence']})")
        if result["blockingReasons"]:
            print("\nBlocking reasons:")
            for reason in result["blockingReasons"]:
                print(f"- {reason}")

    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
