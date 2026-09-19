#!/usr/bin/env python3
"""P7-5: API contract drift detection between design docs and implementation.

Extracts endpoint definitions from 07-接口数据契约.md and compares them against
actual route/controller annotations in the codebase to detect drift.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Patterns to extract API endpoints from 07-接口数据契约.md
# Matches: GET /api/xxx, POST /api/xxx, etc. in various markdown table/heading formats
CONTRACT_ENDPOINT_PATTERN = re.compile(
    r"(?:^|\|)\s*(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s|#\]]+)",
    re.IGNORECASE | re.MULTILINE,
)
# Also match heading-style: ### GET /api/users
CONTRACT_HEADING_PATTERN = re.compile(
    r"^#{1,4}\s*(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s]+)",
    re.IGNORECASE | re.MULTILINE,
)
# Match code block style: `GET /api/users`
CONTRACT_CODE_PATTERN = re.compile(
    r"`(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s`]+)`",
    re.IGNORECASE,
)

# Patterns to extract endpoints from Java/Spring code
SPRING_MAPPING_PATTERN = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)"
    r'\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SPRING_CLASS_MAPPING = re.compile(
    r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Patterns for Express/Koa/Fastify (Node.js)
EXPRESS_ROUTE_PATTERN = re.compile(
    r"(?:app|router|server)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)

# Patterns for Python/FastAPI/Flask
PYTHON_ROUTE_PATTERN = re.compile(
    r"@(?:app|router|api)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)

# Method name normalization
METHOD_MAP = {
    "getmapping": "GET",
    "postmapping": "POST",
    "putmapping": "PUT",
    "deletemapping": "DELETE",
    "patchmapping": "PATCH",
    "requestmapping": "GET",  # default; will be overridden by method param if present
}


def extract_contract_endpoints(contract_text: str) -> list[tuple[str, str]]:
    """Extract (METHOD, path) tuples from contract document."""
    endpoints: list[tuple[str, str]] = []
    seen: set[str] = set()

    for pattern in [CONTRACT_ENDPOINT_PATTERN, CONTRACT_HEADING_PATTERN, CONTRACT_CODE_PATTERN]:
        for match in pattern.finditer(contract_text):
            method = match.group(1).upper()
            path = match.group(2).strip().rstrip("/")
            key = f"{method} {path}"
            if key not in seen:
                seen.add(key)
                endpoints.append((method, path))

    return endpoints


def extract_impl_endpoints(project_root: Path) -> list[tuple[str, str]]:
    """Extract (METHOD, path) tuples from implementation code."""
    endpoints: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Scan Java files
    java_dirs = [
        project_root / "backend" / "src" / "main" / "java",
        project_root / "src" / "main" / "java",
    ]
    for java_dir in java_dirs:
        if not java_dir.exists():
            continue
        for java_file in java_dir.rglob("*.java"):
            try:
                content = java_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Get class-level @RequestMapping prefix
            class_prefix = ""
            class_match = SPRING_CLASS_MAPPING.search(content)
            if class_match:
                class_prefix = class_match.group(1).rstrip("/")

            for match in SPRING_MAPPING_PATTERN.finditer(content):
                annotation = match.group(1).lower()
                path = match.group(2).strip()
                method = METHOD_MAP.get(annotation, "GET")
                full_path = (class_prefix + "/" + path.lstrip("/")).rstrip("/") if path != "/" else class_prefix or "/"
                if not full_path.startswith("/"):
                    full_path = "/" + full_path
                key = f"{method} {full_path}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append((method, full_path))

    # Scan TypeScript/JavaScript files (Express, Fastify, etc.)
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
                try:
                    content = ts_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for match in EXPRESS_ROUTE_PATTERN.finditer(content):
                    method = match.group(1).upper()
                    path = match.group(2).strip().rstrip("/")
                    key = f"{method} {path}"
                    if key not in seen:
                        seen.add(key)
                        endpoints.append((method, path))

    # Scan Python files (FastAPI, Flask)
    py_dirs = [
        project_root / "backend",
        project_root / "app",
        project_root / "src",
    ]
    for py_dir in py_dirs:
        if not py_dir.exists():
            continue
        for py_file in py_dir.rglob("*.py"):
            if "venv" in str(py_file) or ".venv" in str(py_file):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in PYTHON_ROUTE_PATTERN.finditer(content):
                method = match.group(1).upper()
                path = match.group(2).strip().rstrip("/")
                key = f"{method} {path}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append((method, path))

    return endpoints


def _normalize_path(path: str) -> str:
    """Normalize path for comparison (strip param names, keep structure)."""
    # /api/tickets/{id} → /api/tickets/{*}
    normalized = re.sub(r"\{[^}]+\}", "{*}", path)
    # /api/tickets/:id → /api/tickets/{*}
    normalized = re.sub(r":[a-zA-Z_]\w*", "{*}", normalized)
    return normalized.lower().rstrip("/")


def compare_endpoints(
    contract_endpoints: list[tuple[str, str]],
    impl_endpoints: list[tuple[str, str]],
) -> dict:
    """Compare contract vs implementation endpoints and find drift."""
    contract_normalized: dict[str, tuple[str, str]] = {}
    for method, path in contract_endpoints:
        key = f"{method} {_normalize_path(path)}"
        contract_normalized[key] = (method, path)

    impl_normalized: dict[str, tuple[str, str]] = {}
    for method, path in impl_endpoints:
        key = f"{method} {_normalize_path(path)}"
        impl_normalized[key] = (method, path)

    # Find endpoints in contract but not in implementation
    missing_in_impl: list[str] = []
    for key, (method, path) in contract_normalized.items():
        if key not in impl_normalized:
            missing_in_impl.append(f"{method} {path}")

    # Find endpoints in implementation but not in contract
    extra_in_impl: list[str] = []
    for key, (method, path) in impl_normalized.items():
        if key not in contract_normalized:
            extra_in_impl.append(f"{method} {path}")

    # Coverage
    matched = len(contract_normalized) - len(missing_in_impl)
    coverage_pct = (matched / len(contract_normalized) * 100) if contract_normalized else 100.0

    return {
        "contractEndpoints": len(contract_normalized),
        "implEndpoints": len(impl_normalized),
        "matched": matched,
        "coveragePct": round(coverage_pct, 1),
        "missingInImpl": sorted(missing_in_impl),
        "extraInImpl": sorted(extra_in_impl)[:20],  # Cap to avoid huge output
    }


def check_contract_drift(project_root: Path) -> dict:
    """Main entry: check API contract drift.

    Returns a report with status, coverage, and drift details.
    """
    contract_path = project_root / "docs" / "07-接口数据契约.md"
    if not contract_path.is_file():
        return {
            "status": "skip",
            "reason": "docs/07-接口数据契约.md not found — contract drift check skipped",
        }

    try:
        contract_text = contract_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"status": "skip", "reason": "Cannot read 07-接口数据契约.md"}

    contract_endpoints = extract_contract_endpoints(contract_text)
    if not contract_endpoints:
        return {
            "status": "skip",
            "reason": "No endpoints found in 07-接口数据契约.md (expected format: 'GET /api/xxx')",
            "hint": "Contract document should contain endpoints in table or heading format",
        }

    impl_endpoints = extract_impl_endpoints(project_root)
    if not impl_endpoints:
        return {
            "status": "warn",
            "reason": "Contract defines endpoints but no implementation routes found in code",
            "contractEndpoints": len(contract_endpoints),
            "endpoints": [f"{m} {p}" for m, p in contract_endpoints[:10]],
        }

    comparison = compare_endpoints(contract_endpoints, impl_endpoints)

    # Determine status based on coverage
    if comparison["coveragePct"] >= 80:
        status = "pass"
    elif comparison["coveragePct"] >= 50:
        status = "warn"
    else:
        status = "fail"

    return {
        "status": status,
        **comparison,
        "blockingReasons": (
            [f"API contract drift: only {comparison['coveragePct']}% of contract endpoints implemented. "
             f"Missing: {comparison['missingInImpl'][:5]}"]
            if status == "fail" else []
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    report = check_contract_drift(project_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Contract Drift: {report['status'].upper()}")
        if report.get("coveragePct") is not None:
            print(f"  Coverage: {report['coveragePct']}% ({report['matched']}/{report['contractEndpoints']})")
        if report.get("missingInImpl"):
            print(f"  Missing in implementation ({len(report['missingInImpl'])}):")
            for ep in report["missingInImpl"][:10]:
                print(f"    ✗ {ep}")
        if report.get("extraInImpl"):
            print(f"  Extra in implementation (undocumented, {len(report['extraInImpl'])}):")
            for ep in report["extraInImpl"][:5]:
                print(f"    + {ep}")
        if report.get("reason"):
            print(f"  {report['reason']}")
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
