#!/usr/bin/env python3
"""
SQL 迁移破坏性检查（S2-2）

扫描 SQL 迁移脚本目录，识别破坏性 / 高风险语句，按 P0 / P1 分级。

调用：
    python scripts/migration_safety_check.py --migrations-dir <path> [--allow-destructive]

退出码：
    0  无 P0 阻断（可能含 P1 告警）
    1  存在 P0 阻断且未携带 --allow-destructive
    2  使用错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# 各规则：(severity, pattern, label)
RULES: List = [
    ("P0", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "DROP TABLE"),
    ("P0", re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE), "DROP SCHEMA"),
    ("P0", re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE), "DROP DATABASE"),
    ("P0", re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE), "TRUNCATE TABLE"),
    ("P0", re.compile(r"\bALTER\s+TABLE[^;]+\bDROP\s+COLUMN\b", re.IGNORECASE), "DROP COLUMN"),
    # UPDATE / DELETE without WHERE - heuristic, looks for the keyword without WHERE before semicolon
    ("P0", re.compile(r"\bDELETE\s+FROM\s+\w+\s*;", re.IGNORECASE), "DELETE without WHERE"),
    ("P0", re.compile(r"\bUPDATE\s+\w+\s+SET\s+[^;]+;(?![^;]*WHERE)", re.IGNORECASE | re.DOTALL), "UPDATE without WHERE"),
    ("P1", re.compile(r"\bALTER\s+TABLE[^;]+\bDROP\s+CONSTRAINT\b", re.IGNORECASE), "DROP CONSTRAINT"),
    ("P1", re.compile(r"\bALTER\s+TABLE[^;]+\bRENAME\s+COLUMN\b", re.IGNORECASE), "RENAME COLUMN"),
    ("P1", re.compile(r"\bALTER\s+TABLE[^;]+\bMODIFY\s+COLUMN\b", re.IGNORECASE), "MODIFY COLUMN type"),
    ("P1", re.compile(r"NOT\s+NULL(?![^,;]*DEFAULT)", re.IGNORECASE), "NOT NULL without DEFAULT"),
    ("P1", re.compile(r"\bCREATE\s+UNIQUE\s+INDEX\b", re.IGNORECASE), "CREATE UNIQUE INDEX (may fail on existing duplicates)"),
]


def scan_file(path: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    # 去掉单行/块注释，避免误报
    sanitized = re.sub(r"--[^\n]*", "", text)
    sanitized = re.sub(r"/\*.*?\*/", "", sanitized, flags=re.DOTALL)

    for severity, pattern, label in RULES:
        for match in pattern.finditer(sanitized):
            line_no = sanitized.count("\n", 0, match.start()) + 1
            snippet = match.group(0).strip().replace("\n", " ")
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            findings.append({
                "file": str(path),
                "line": line_no,
                "severity": severity,
                "rule": label,
                "snippet": snippet,
            })
    return findings


def collect_files(root: Path) -> List[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*.sql"))


def main() -> int:
    parser = argparse.ArgumentParser(description="SQL migration safety check (S2-2)")
    parser.add_argument("--migrations-dir", required=True, help="迁移脚本目录或单个 .sql 文件")
    parser.add_argument("--allow-destructive", action="store_true", help="显式允许 P0 破坏性语句")
    args = parser.parse_args()

    root = Path(args.migrations_dir).resolve()
    if not root.exists():
        print(f"[migration_safety_check] not found: {root}", file=sys.stderr)
        return 2

    files = collect_files(root)
    findings: List[Dict[str, Any]] = []
    for f in files:
        findings.extend(scan_file(f))

    p0 = [f for f in findings if f["severity"] == "P0"]
    p1 = [f for f in findings if f["severity"] == "P1"]

    blocked = bool(p0) and not args.allow_destructive

    summary = {
        "status": "block" if blocked else ("warn" if p1 or p0 else "pass"),
        "migrationsDir": str(root),
        "fileCount": len(files),
        "p0Count": len(p0),
        "p1Count": len(p1),
        "allowDestructive": args.allow_destructive,
        "findings": findings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
