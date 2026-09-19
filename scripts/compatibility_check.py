#!/usr/bin/env python3
"""Check software-development-team config compatibility and migration readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SUPPORTED_VERSIONS = [4]
MIGRATION_HINTS = {
    1: [
        "Add unified-large-delivery mode and independent-session orchestration fields.",
        "Add role promptFile entries for all configured roles.",
        "Upgrade directly to version 3 harness resources.",
    ],
    2: [
        "Add harness.schemas, harness.scripts, and harness.templates.",
        "Add data-contract, UI, code-review, security-review, and supervisor-audit artifact ownership.",
        "Add scripts/check_skill_integrity.py, validate_delivery.py, build_handoff.py, orchestrate.py, write_evidence_ledger.py, run_golden_tests.py, metrics_report.py, compatibility_check.py.",
    ],
    3: [
        "Add P0 orchestrate.py and write_evidence_ledger.py.",
        "Add P1 tests/golden and references/adapters.",
        "Add P2 references/runtime-adapters, metrics_report.py, compatibility_check.py, metrics.schema.json, and migration-report.schema.json.",
        "Upgrade agent-team-config to version 4.",
    ],
}


def check(skill_root: Path) -> dict:
    config = json.loads((skill_root / "assets" / "config" / "agent-team-config.json").read_text(encoding="utf-8"))
    version = int(config.get("version", 0))
    findings = []
    actions = []
    if version in SUPPORTED_VERSIONS:
        status = "compatible"
        findings.append(f"Config version {version} is supported.")
    elif version in MIGRATION_HINTS:
        status = "migration-needed"
        findings.append(f"Config version {version} can be migrated.")
        actions.extend(MIGRATION_HINTS[version])
    else:
        status = "unsupported"
        findings.append(f"Config version {version} is unsupported.")
        actions.append("Review config manually and migrate to version 3.")

    required_harness_keys = ["schemas", "scripts", "templates"]
    harness = config.get("harness", {})
    for key in required_harness_keys:
        if key not in harness:
            findings.append(f"Missing harness.{key}")
            if status == "compatible":
                status = "migration-needed"
    return {
        "currentVersion": version,
        "supportedVersions": SUPPORTED_VERSIONS,
        "status": status,
        "findings": findings,
        "recommendedActions": actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_root", help="Path to the skill root")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    report = check(Path(args.skill_root).resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Compatibility: {report['status']}")
        for finding in report["findings"]:
            print(f"- {finding}")
        if report["recommendedActions"]:
            print("Recommended actions:")
            for action in report["recommendedActions"]:
                print(f"- {action}")
    return 0 if report["status"] == "compatible" else 1


if __name__ == "__main__":
    sys.exit(main())
