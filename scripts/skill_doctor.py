#!/usr/bin/env python3
"""Unified skill self-check (doctor) — chains all validation scripts in one pass."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


def _load_module(name: str, path: Path):
    """Dynamically load a Python module from path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(name: str, func, *args, **kwargs) -> dict:
    """Run a single check and capture result."""
    start = time.time()
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        return {"name": name, "status": "PASS", "elapsed_s": round(elapsed, 2), "detail": result}
    except SystemExit as e:
        elapsed = time.time() - start
        status = "PASS" if e.code == 0 else "FAIL"
        return {"name": name, "status": status, "elapsed_s": round(elapsed, 2), "detail": f"exit_code={e.code}"}
    except Exception as e:
        elapsed = time.time() - start
        return {"name": name, "status": "ERROR", "elapsed_s": round(elapsed, 2), "detail": str(e)}


def check_integrity(skill_root: Path) -> dict:
    """Run check_skill_integrity.py logic."""
    script = skill_root / "scripts" / "check_skill_integrity.py"
    if not script.exists():
        return {"status": "SKIP", "reason": "script not found"}
    mod = _load_module("check_skill_integrity", script)
    if mod and hasattr(mod, "check_integrity"):
        return mod.check_integrity(skill_root)
    return {"status": "SKIP", "reason": "no check_integrity function"}


def check_golden_tests(skill_root: Path) -> dict:
    """Run run_golden_tests.py logic."""
    script = skill_root / "scripts" / "run_golden_tests.py"
    if not script.exists():
        return {"status": "SKIP", "reason": "script not found"}
    mod = _load_module("run_golden_tests", script)
    if mod and hasattr(mod, "run_tests"):
        return mod.run_tests(skill_root)
    return {"status": "SKIP", "reason": "no run_tests function"}


def check_chaos_tests(skill_root: Path) -> dict:
    """Run chaos tests if available."""
    script = skill_root / "tests" / "chaos" / "run_chaos_tests.py"
    if not script.exists():
        return {"status": "SKIP", "reason": "chaos tests not found"}
    mod = _load_module("run_chaos_tests", script)
    if mod and hasattr(mod, "run_chaos_tests"):
        return mod.run_chaos_tests(skill_root)
    return {"status": "SKIP", "reason": "no run_chaos_tests function"}


def check_template_parseable(skill_root: Path) -> dict:
    """Verify all template .md files are valid UTF-8 and non-empty."""
    templates_dir = skill_root / "assets" / "templates"
    if not templates_dir.exists():
        return {"status": "SKIP", "reason": "templates dir not found"}
    errors = []
    count = 0
    for md_file in templates_dir.rglob("*.md"):
        count += 1
        try:
            content = md_file.read_text(encoding="utf-8")
            if not content.strip():
                errors.append(f"{md_file.relative_to(skill_root)}: empty file")
        except Exception as e:
            errors.append(f"{md_file.relative_to(skill_root)}: {e}")
    if errors:
        return {"status": "FAIL", "checked": count, "errors": errors}
    return {"status": "PASS", "checked": count}


def check_prompt_sizes(skill_root: Path) -> dict:
    """Report prompt file sizes and flag oversized ones (>30KB)."""
    prompts_dir = skill_root / "assets" / "prompts"
    if not prompts_dir.exists():
        return {"status": "SKIP", "reason": "prompts dir not found"}
    sizes = {}
    warnings = []
    for md_file in sorted(prompts_dir.rglob("*.md")):
        size_kb = md_file.stat().st_size / 1024
        rel = str(md_file.relative_to(skill_root))
        sizes[rel] = round(size_kb, 1)
        if size_kb > 30:
            warnings.append(f"{rel}: {size_kb:.1f}KB (exceeds 30KB threshold)")
    status = "WARN" if warnings else "PASS"
    return {"status": status, "sizes_kb": sizes, "warnings": warnings}


def check_schema_validity(skill_root: Path) -> dict:
    """Verify all .schema.json files are valid JSON."""
    schemas_dir = skill_root / "schemas"
    if not schemas_dir.exists():
        return {"status": "SKIP", "reason": "schemas dir not found"}
    errors = []
    count = 0
    for schema_file in sorted(schemas_dir.glob("*.json")):
        count += 1
        try:
            json.loads(schema_file.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{schema_file.name}: {e}")
    if errors:
        return {"status": "FAIL", "checked": count, "errors": errors}
    return {"status": "PASS", "checked": count}


def check_config_consistency(skill_root: Path) -> dict:
    """Verify JSON and YAML configs have same role count."""
    json_path = skill_root / "assets" / "config" / "agent-team-config.json"
    yaml_path = skill_root / "assets" / "config" / "agent-team-config.yaml"
    if not json_path.exists():
        return {"status": "FAIL", "reason": "JSON config not found"}
    try:
        cfg = json.loads(json_path.read_text(encoding="utf-8"))
        json_roles = len(cfg.get("roles", []))
    except Exception as e:
        return {"status": "FAIL", "reason": f"JSON parse error: {e}"}

    yaml_roles = None
    if yaml_path.exists():
        try:
            content = yaml_path.read_text(encoding="utf-8")
            # Simple count: lines starting with "  - id:"
            yaml_roles = content.count("\n  - id:")
            if yaml_roles == 0:
                yaml_roles = content.count("- id:")
        except Exception:
            pass

    result = {"status": "PASS", "jsonRoles": json_roles}
    if yaml_roles is not None:
        result["yamlRoles"] = yaml_roles
        if yaml_roles != json_roles:
            result["status"] = "WARN"
            result["warning"] = f"Role count mismatch: JSON={json_roles}, YAML={yaml_roles}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to skill root")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    if not skill_root.exists():
        print(f"ERROR: skill root not found: {skill_root}", file=sys.stderr)
        return 2

    checks = [
        ("integrity", lambda: check_integrity(skill_root)),
        ("golden-tests", lambda: check_golden_tests(skill_root)),
        ("chaos-tests", lambda: check_chaos_tests(skill_root)),
        ("template-parseable", lambda: check_template_parseable(skill_root)),
        ("prompt-sizes", lambda: check_prompt_sizes(skill_root)),
        ("schema-validity", lambda: check_schema_validity(skill_root)),
        ("config-consistency", lambda: check_config_consistency(skill_root)),
    ]

    results = []
    for name, func in checks:
        result = run_check(name, func)
        results.append(result)

    # Determine overall status
    statuses = [r["status"] for r in results]
    if "FAIL" in statuses or "ERROR" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"

    report = {
        "overall": overall,
        "checks": results,
        "summary": {s: statuses.count(s) for s in set(statuses)},
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"  Skill Doctor Report: {overall}")
        print(f"{'='*60}\n")
        for r in results:
            icon = {"PASS": "✓", "FAIL": "✗", "ERROR": "!", "WARN": "⚠", "SKIP": "○"}.get(r["status"], "?")
            print(f"  {icon} {r['name']}: {r['status']} ({r['elapsed_s']}s)")
            detail = r.get("detail")
            if isinstance(detail, dict):
                if detail.get("errors"):
                    for e in detail["errors"][:5]:
                        print(f"      → {e}")
                if detail.get("warnings"):
                    for w in detail["warnings"][:5]:
                        print(f"      ⚠ {w}")
        print(f"\n  Summary: {report['summary']}")
        print()

    return 0 if overall in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
