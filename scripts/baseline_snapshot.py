#!/usr/bin/env python3
"""Baseline snapshot writer for delivery-time PRD/contract/schema state.

After a quality-gate pass, this script captures the current PRD FR-id set,
contract endpoint list, and schema fingerprint into
`_test_output/baseline/{version}.json`. Subsequent drift checks read the latest
baseline and only flag *new* drift (delta), avoiding re-reporting historical
issues.

Usage:
    python scripts/baseline_snapshot.py write --project-root . --version v1.2.0
    python scripts/baseline_snapshot.py latest --project-root .
    python scripts/baseline_snapshot.py diff --project-root . [--against v1.1.0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the same patterns used by drift checkers so the baseline stays consistent.
REQ_ID_PATTERN = re.compile(r"\b((?:FR|NFR|REQ|UC|US)-\d{1,4})\b", re.IGNORECASE)
CONTRACT_ENDPOINT_PATTERN = re.compile(
    r"(?:^|\|)\s*(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s|#\]]+)",
    re.IGNORECASE | re.MULTILINE,
)
CONTRACT_HEADING_PATTERN = re.compile(
    r"^#{1,4}\s*(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s]+)",
    re.IGNORECASE | re.MULTILINE,
)
CONTRACT_CODE_PATTERN = re.compile(r"`(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s`]+)`", re.IGNORECASE)

SQL_TABLE_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?\s*\(([^;]*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def _baseline_dir(project_root: Path) -> Path:
    return project_root / "_test_output" / "baseline"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _extract_fr_block(prd_text: str, fr_id: str) -> str:
    """Return the text block describing this FR id, used for acceptance-criteria hashing."""
    pattern = re.compile(
        rf"\b{re.escape(fr_id)}\b(.{{0,800}}?)(?=\b(?:FR|NFR|REQ|UC|US)-\d{{1,4}}\b|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(prd_text)
    return m.group(1).strip() if m else ""


def collect_prd_fingerprint(project_root: Path) -> dict:
    prd_path = project_root / "docs" / "01-需求规格书.md"
    if not prd_path.is_file():
        return {"present": False, "frs": []}
    text = _read(prd_path)
    fr_ids = sorted({m.group(1).upper() for m in REQ_ID_PATTERN.finditer(text)})
    frs = [
        {"id": fr_id, "criteriaHash": _hash(_extract_fr_block(text, fr_id))}
        for fr_id in fr_ids
    ]
    return {"present": True, "frs": frs, "frCount": len(frs)}


def collect_contract_fingerprint(project_root: Path) -> dict:
    contract_path = project_root / "docs" / "07-接口数据契约.md"
    if not contract_path.is_file():
        return {"present": False, "endpoints": []}
    text = _read(contract_path)
    seen: set[str] = set()
    endpoints: list[str] = []
    for pattern in (CONTRACT_ENDPOINT_PATTERN, CONTRACT_HEADING_PATTERN, CONTRACT_CODE_PATTERN):
        for m in pattern.finditer(text):
            key = f"{m.group(1).upper()} {m.group(2).strip().rstrip('/')}"
            if key not in seen:
                seen.add(key)
                endpoints.append(key)
    return {"present": True, "endpoints": sorted(endpoints), "endpointCount": len(endpoints)}


def collect_schema_fingerprint(project_root: Path) -> dict:
    sql_dirs = [
        project_root / "backend" / "src" / "main" / "resources" / "db",
        project_root / "db" / "migration",
        project_root / "migrations",
        project_root / "prisma" / "migrations",
    ]
    tables: dict[str, str] = {}
    for sql_dir in sql_dirs:
        if not sql_dir.exists():
            continue
        for sql_file in sql_dir.rglob("*.sql"):
            content = _read(sql_file)
            if not content:
                continue
            for m in SQL_TABLE_PATTERN.finditer(content):
                table = m.group(1).lower()
                # Aggregate table body hash (latest declaration wins; stable enough for drift detection).
                tables[table] = _hash(m.group(2))
    return {
        "present": bool(tables),
        "tables": [{"name": t, "bodyHash": h} for t, h in sorted(tables.items())],
        "tableCount": len(tables),
    }


def build_snapshot(project_root: Path, version: str) -> dict:
    return {
        "version": version,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "prd": collect_prd_fingerprint(project_root),
        "contract": collect_contract_fingerprint(project_root),
        "schema": collect_schema_fingerprint(project_root),
    }


def write_snapshot(project_root: Path, version: str) -> Path:
    bdir = _baseline_dir(project_root)
    bdir.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(project_root, version)
    out = bdir / f"{version}.json"
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    # Maintain a "latest" pointer for drift checkers.
    (bdir / "latest.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def load_latest(project_root: Path) -> dict | None:
    latest = _baseline_dir(project_root) / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def diff_against(project_root: Path, against_version: str | None) -> dict:
    if against_version:
        prev_path = _baseline_dir(project_root) / f"{against_version}.json"
        if not prev_path.is_file():
            return {"status": "skip", "reason": f"baseline {against_version} not found"}
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
    else:
        prev = load_latest(project_root)
        if not prev:
            return {"status": "skip", "reason": "no previous baseline"}

    current = build_snapshot(project_root, version="HEAD")

    prev_frs = {fr["id"]: fr["criteriaHash"] for fr in prev.get("prd", {}).get("frs", [])}
    cur_frs = {fr["id"]: fr["criteriaHash"] for fr in current["prd"]["frs"]}
    fr_added = sorted(set(cur_frs) - set(prev_frs))
    fr_removed = sorted(set(prev_frs) - set(cur_frs))
    fr_modified = sorted(
        fid for fid in (set(prev_frs) & set(cur_frs)) if prev_frs[fid] != cur_frs[fid]
    )

    prev_eps = set(prev.get("contract", {}).get("endpoints", []))
    cur_eps = set(current["contract"]["endpoints"])
    ep_added = sorted(cur_eps - prev_eps)
    ep_removed = sorted(prev_eps - cur_eps)

    prev_tables = {t["name"]: t["bodyHash"] for t in prev.get("schema", {}).get("tables", [])}
    cur_tables = {t["name"]: t["bodyHash"] for t in current["schema"]["tables"]}
    table_added = sorted(set(cur_tables) - set(prev_tables))
    table_removed = sorted(set(prev_tables) - set(cur_tables))
    table_modified = sorted(
        t for t in (set(prev_tables) & set(cur_tables)) if prev_tables[t] != cur_tables[t]
    )

    drift_count = (
        len(fr_added) + len(fr_removed) + len(fr_modified)
        + len(ep_added) + len(ep_removed)
        + len(table_added) + len(table_removed) + len(table_modified)
    )

    return {
        "status": "drift" if drift_count else "stable",
        "againstVersion": prev.get("version", "latest"),
        "fr": {"added": fr_added, "removed": fr_removed, "modified": fr_modified},
        "contract": {"added": ep_added, "removed": ep_removed},
        "schema": {"added": table_added, "removed": table_removed, "modified": table_modified},
        "driftCount": drift_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["write", "latest", "diff"])
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--version", default=None)
    parser.add_argument("--against", default=None, help="Baseline version to diff against (default: latest)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.action == "write":
        version = args.version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = write_snapshot(project_root, version)
        if args.json:
            print(json.dumps({"ok": True, "snapshot": str(path), "version": version}, ensure_ascii=False))
        else:
            print(f"Wrote baseline snapshot: {path}")
        return 0

    if args.action == "latest":
        latest = load_latest(project_root)
        if latest is None:
            print("No baseline found", file=sys.stderr)
            return 1
        print(json.dumps(latest, ensure_ascii=False, indent=2))
        return 0

    if args.action == "diff":
        report = diff_against(project_root, args.against)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Baseline diff: {report['status'].upper()} ({report.get('driftCount', 0)} drift items)")
            for category in ("fr", "contract", "schema"):
                section = report.get(category) or {}
                for change_type, items in section.items():
                    if items:
                        print(f"  {category}.{change_type}: {items[:5]}")
            if report.get("reason"):
                print(f"  {report['reason']}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
