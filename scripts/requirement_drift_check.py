#!/usr/bin/env python3
"""Requirement drift detection between code feature points and 01-需求规格书.md.

Companion to contract_drift_check.py. Where contract_drift_check.py compares
07-接口数据契约.md vs implementation routes, this script compares
01-需求规格书.md FR / NFR coverage vs implementation feature points
(controllers, scheduled tasks, message consumers, frontend routes/pages,
data entities, migration scripts).

Output:
- unmappedFeatures: code features not referenced by any FR/NFR  → reverse-sync needed
- unimplementedFRs: FRs declared in PRD but no matching code feature → forward-development needed
- coveragePct: matched / total FRs

Exit code 1 when unmappedFeatures is non-empty (PRD reverse sync required).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQ_ID_PATTERN = re.compile(r"\b((?:FR|NFR|REQ|UC|US)-\d{1,4})\b", re.IGNORECASE)

# FR entry block pattern: heading or table row that contains an FR id and a short name.
FR_ENTRY_PATTERN = re.compile(
    r"((?:FR|NFR|REQ|UC|US)-\d{1,4})\s*[:：\-\|]\s*([^\n\|]{2,80})",
    re.IGNORECASE,
)

# Backend feature point patterns (Spring / FastAPI / Express).
SPRING_CONTROLLER_PATTERN = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)"
    r'\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SPRING_SCHEDULED_PATTERN = re.compile(r"@Scheduled\s*\([^)]*\)\s*public\s+\w[\w<>]*\s+(\w+)", re.IGNORECASE)
SPRING_KAFKA_PATTERN = re.compile(
    r'@(?:KafkaListener|RabbitListener|RocketMQMessageListener)\s*\([^)]*topics?\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
PY_ROUTE_PATTERN = re.compile(
    r"@(?:app|router|api)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
EXPRESS_ROUTE_PATTERN = re.compile(
    r"(?:app|router|server)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)

# Frontend route/page patterns (Vue Router / React Router).
VUE_ROUTE_PATTERN = re.compile(
    r"\{\s*path\s*:\s*['\"]([^'\"]+)['\"]\s*,\s*(?:name\s*:\s*['\"]([^'\"]+)['\"])?",
    re.IGNORECASE,
)
REACT_ROUTE_PATTERN = re.compile(
    r"<Route\s+[^>]*path\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# Data entity & migration patterns.
JPA_ENTITY_PATTERN = re.compile(r"@Entity\s*(?:\([^)]*\))?\s*public\s+class\s+(\w+)", re.IGNORECASE)
SQL_TABLE_PATTERN = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?", re.IGNORECASE)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def extract_prd_fr_index(prd_text: str) -> dict[str, str]:
    """Return {FR-id: short-name} extracted from 01-需求规格书.md."""
    index: dict[str, str] = {}
    for match in FR_ENTRY_PATTERN.finditer(prd_text):
        fr_id = match.group(1).upper()
        name = match.group(2).strip().rstrip("|").strip()
        # Prefer the longest description seen for this id.
        if fr_id not in index or len(name) > len(index[fr_id]):
            index[fr_id] = name
    # Also include FR ids that only appear as bare references (no description).
    for match in REQ_ID_PATTERN.finditer(prd_text):
        fr_id = match.group(1).upper()
        index.setdefault(fr_id, "")
    return index


def collect_backend_features(project_root: Path) -> list[dict]:
    features: list[dict] = []

    java_dirs = [
        project_root / "backend" / "src" / "main" / "java",
        project_root / "src" / "main" / "java",
    ]
    for java_dir in java_dirs:
        if not java_dir.exists():
            continue
        for java_file in java_dir.rglob("*.java"):
            content = _read(java_file)
            if not content:
                continue
            for m in SPRING_CONTROLLER_PATTERN.finditer(content):
                features.append({
                    "kind": "api",
                    "key": f"{m.group(1).replace('Mapping', '').upper()} {m.group(2)}",
                    "file": str(java_file.relative_to(project_root)).replace("\\", "/"),
                    "frRefs": _scan_nearby_fr_refs(content, m.start()),
                })
            for m in SPRING_SCHEDULED_PATTERN.finditer(content):
                features.append({
                    "kind": "scheduled",
                    "key": f"scheduled:{m.group(1)}",
                    "file": str(java_file.relative_to(project_root)).replace("\\", "/"),
                    "frRefs": _scan_nearby_fr_refs(content, m.start()),
                })
            for m in SPRING_KAFKA_PATTERN.finditer(content):
                features.append({
                    "kind": "consumer",
                    "key": f"consumer:{m.group(1)}",
                    "file": str(java_file.relative_to(project_root)).replace("\\", "/"),
                    "frRefs": _scan_nearby_fr_refs(content, m.start()),
                })
            for m in JPA_ENTITY_PATTERN.finditer(content):
                features.append({
                    "kind": "entity",
                    "key": f"entity:{m.group(1)}",
                    "file": str(java_file.relative_to(project_root)).replace("\\", "/"),
                    "frRefs": _scan_nearby_fr_refs(content, m.start()),
                })

    py_dirs = [project_root / "backend", project_root / "app", project_root / "src"]
    for py_dir in py_dirs:
        if not py_dir.exists():
            continue
        for py_file in py_dir.rglob("*.py"):
            if "venv" in str(py_file) or ".venv" in str(py_file):
                continue
            content = _read(py_file)
            if not content:
                continue
            for m in PY_ROUTE_PATTERN.finditer(content):
                features.append({
                    "kind": "api",
                    "key": f"{m.group(1).upper()} {m.group(2)}",
                    "file": str(py_file.relative_to(project_root)).replace("\\", "/"),
                    "frRefs": _scan_nearby_fr_refs(content, m.start()),
                })

    ts_dirs = [
        project_root / "backend" / "src",
        project_root / "src" / "routes",
        project_root / "src" / "api",
        project_root / "server",
    ]
    for ts_dir in ts_dirs:
        if not ts_dir.exists():
            continue
        for ext in ("*.ts", "*.js"):
            for ts_file in ts_dir.rglob(ext):
                if "node_modules" in str(ts_file):
                    continue
                content = _read(ts_file)
                if not content:
                    continue
                for m in EXPRESS_ROUTE_PATTERN.finditer(content):
                    features.append({
                        "kind": "api",
                        "key": f"{m.group(1).upper()} {m.group(2)}",
                        "file": str(ts_file.relative_to(project_root)).replace("\\", "/"),
                        "frRefs": _scan_nearby_fr_refs(content, m.start()),
                    })

    return features


def collect_frontend_features(project_root: Path) -> list[dict]:
    features: list[dict] = []
    fe_dirs = [project_root / "frontend" / "src", project_root / "src"]
    for fe_dir in fe_dirs:
        if not fe_dir.exists():
            continue
        for ext in ("*.ts", "*.tsx", "*.js", "*.jsx", "*.vue"):
            for fe_file in fe_dir.rglob(ext):
                if "node_modules" in str(fe_file):
                    continue
                content = _read(fe_file)
                if not content:
                    continue
                # Vue Router-style entries.
                for m in VUE_ROUTE_PATTERN.finditer(content):
                    name = m.group(2) or m.group(1)
                    features.append({
                        "kind": "ui-route",
                        "key": f"route:{m.group(1)}",
                        "label": name,
                        "file": str(fe_file.relative_to(project_root)).replace("\\", "/"),
                        "frRefs": _scan_nearby_fr_refs(content, m.start()),
                    })
                # React Router <Route path=...>.
                for m in REACT_ROUTE_PATTERN.finditer(content):
                    features.append({
                        "kind": "ui-route",
                        "key": f"route:{m.group(1)}",
                        "label": m.group(1),
                        "file": str(fe_file.relative_to(project_root)).replace("\\", "/"),
                        "frRefs": _scan_nearby_fr_refs(content, m.start()),
                    })
    # Deduplicate by key+file.
    seen: set[str] = set()
    deduped: list[dict] = []
    for f in features:
        sig = f"{f['key']}|{f['file']}"
        if sig not in seen:
            seen.add(sig)
            deduped.append(f)
    return deduped


def collect_data_features(project_root: Path) -> list[dict]:
    features: list[dict] = []
    sql_dirs = [
        project_root / "backend" / "src" / "main" / "resources" / "db",
        project_root / "db" / "migration",
        project_root / "migrations",
        project_root / "prisma" / "migrations",
    ]
    for sql_dir in sql_dirs:
        if not sql_dir.exists():
            continue
        for sql_file in sql_dir.rglob("*.sql"):
            content = _read(sql_file)
            if not content:
                continue
            for m in SQL_TABLE_PATTERN.finditer(content):
                features.append({
                    "kind": "schema",
                    "key": f"table:{m.group(1).lower()}",
                    "file": str(sql_file.relative_to(project_root)).replace("\\", "/"),
                    "frRefs": _scan_nearby_fr_refs(content, m.start()),
                })
    return features


def _scan_nearby_fr_refs(text: str, position: int, window: int = 400) -> list[str]:
    """Look in a +/- window of characters around position for inline FR-id references.

    Many teams annotate code with line comments such as // FR-001 or docstring
    references like FR-002. We treat those as a strong signal that the feature is
    already mapped to a PRD entry.
    """
    start = max(0, position - window)
    end = min(len(text), position + window)
    snippet = text[start:end]
    return sorted({m.group(1).upper() for m in REQ_ID_PATTERN.finditer(snippet)})


def check_requirement_drift(project_root: Path) -> dict:
    prd_path = project_root / "docs" / "01-需求规格书.md"
    if not prd_path.is_file():
        return {
            "status": "skip",
            "reason": "docs/01-需求规格书.md not found — requirement drift check skipped",
        }
    prd_text = _read(prd_path)
    fr_index = extract_prd_fr_index(prd_text)
    if not fr_index:
        return {
            "status": "skip",
            "reason": "No FR/NFR ids found in 01-需求规格书.md (expected format: 'FR-001: ...')",
        }

    features: list[dict] = []
    features.extend(collect_backend_features(project_root))
    features.extend(collect_frontend_features(project_root))
    features.extend(collect_data_features(project_root))

    if not features:
        return {
            "status": "warn",
            "reason": "PRD has FRs but no scannable code features were found (controllers / routes / entities / migrations)",
            "frCount": len(fr_index),
        }

    mapped_fr_ids: set[str] = set()
    unmapped: list[dict] = []
    for feat in features:
        refs_in_prd = [r for r in feat["frRefs"] if r in fr_index]
        if refs_in_prd:
            mapped_fr_ids.update(refs_in_prd)
        else:
            unmapped.append({
                "kind": feat["kind"],
                "key": feat["key"],
                "file": feat["file"],
            })

    unimplemented = sorted(set(fr_index.keys()) - mapped_fr_ids)
    coverage_pct = (len(mapped_fr_ids) / len(fr_index) * 100) if fr_index else 0.0

    if coverage_pct >= 80 and not unmapped:
        status = "pass"
    elif unmapped:
        status = "fail"
    else:
        status = "warn"

    blocking: list[str] = []
    if unmapped:
        blocking.append(
            f"Requirement drift: {len(unmapped)} code feature(s) have no FR/NFR mapping. "
            f"Reverse sync required for: {[u['key'] for u in unmapped[:5]]}"
        )

    return {
        "status": status,
        "frCount": len(fr_index),
        "mappedFRCount": len(mapped_fr_ids),
        "coveragePct": round(coverage_pct, 1),
        "unmappedFeatures": unmapped[:50],
        "unmappedFeatureCount": len(unmapped),
        "unimplementedFRs": unimplemented[:50],
        "unimplementedFRCount": len(unimplemented),
        "blockingReasons": blocking,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    report = check_requirement_drift(project_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Requirement Drift: {report['status'].upper()}")
        if report.get("coveragePct") is not None:
            print(f"  FR coverage: {report['coveragePct']}% ({report['mappedFRCount']}/{report['frCount']})")
        if report.get("unmappedFeatures"):
            print(f"  Unmapped code features ({report['unmappedFeatureCount']}):")
            for feat in report["unmappedFeatures"][:10]:
                print(f"    ! {feat['kind']}: {feat['key']}  ({feat['file']})")
        if report.get("unimplementedFRs"):
            print(f"  Unimplemented FRs ({report['unimplementedFRCount']}): {report['unimplementedFRs'][:5]}")
        if report.get("reason"):
            print(f"  {report['reason']}")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
