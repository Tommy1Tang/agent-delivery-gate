#!/usr/bin/env python3
"""P6-9: Schema version migration for evidence-ledger and role-result data.

Handles forward-compatible upgrades when schema evolves between skill versions.
Detects the current data version and applies sequential migration transforms.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

# Current schema version. Bump this when adding a new migration.
CURRENT_VERSION = 2

# Migration registry: list of (from_version, to_version, transform_fn).
# Each transform_fn receives the data dict and returns the migrated dict.
MIGRATIONS: list[tuple[int, int, callable]] = []


def _register(from_v: int, to_v: int):
    """Decorator to register a migration function."""
    def decorator(fn):
        MIGRATIONS.append((from_v, to_v, fn))
        return fn
    return decorator


@_register(0, 1)
def _migrate_0_to_1(data: dict) -> dict:
    """v0 → v1: Add schemaVersion field and normalize roleRuns."""
    data["schemaVersion"] = 1
    for run in data.get("roleRuns", []):
        # Ensure changeSet is present (may be null)
        if "changeSet" not in run:
            run["changeSet"] = None
        # Normalize legacy 'complete' → 'completed'
        if run.get("status") == "complete":
            run["status"] = "completed"
    return data


@_register(1, 2)
def _migrate_1_to_2(data: dict) -> dict:
    """v1 → v2: Add observability.tokenUsage, retryPolicy fields.

    Aligns with P6-10 (partialRetry) and P6-13 (tokenBudget audit).
    """
    data["schemaVersion"] = 2

    # Ensure observability section exists
    if "observability" not in data:
        data["observability"] = {}
    obs = data["observability"]

    # P6-13: Add tokenUsage tracking structure
    if "tokenUsage" not in obs:
        obs["tokenUsage"] = {
            "totalBudget": 0,
            "totalConsumed": 0,
            "perRole": {},
        }

    # P6-10: Add partialRetry tracking for each roleRun
    for run in data.get("roleRuns", []):
        if "partialRetry" not in run:
            run["partialRetry"] = None  # null means no partial retry occurred

    return data


def detect_version(data: dict) -> int:
    """Detect schema version from data. Returns 0 for legacy unversioned data."""
    return data.get("schemaVersion", 0)


def migrate(data: dict, target_version: int = CURRENT_VERSION) -> tuple[dict, list[str]]:
    """Apply all necessary migrations to bring data to target_version.

    Returns (migrated_data, list_of_applied_migration_descriptions).
    """
    result = deepcopy(data)
    current = detect_version(result)
    applied: list[str] = []

    if current >= target_version:
        return result, []

    # Sort migrations by from_version to ensure sequential application
    sorted_migrations = sorted(MIGRATIONS, key=lambda m: m[0])

    for from_v, to_v, transform_fn in sorted_migrations:
        if current == from_v and to_v <= target_version:
            result = transform_fn(result)
            applied.append(f"v{from_v} → v{to_v}: {transform_fn.__doc__ or transform_fn.__name__}")
            current = to_v

    if current != target_version:
        applied.append(f"WARNING: could not reach v{target_version}, stopped at v{current}")

    return result, applied


def migrate_file(file_path: Path, target_version: int = CURRENT_VERSION, dry_run: bool = False) -> dict:
    """Load a JSON file, migrate it, and optionally write back.

    Returns the migration report.
    """
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"file": str(file_path), "error": str(e), "migrated": False}

    original_version = detect_version(data)
    if original_version >= target_version:
        return {
            "file": str(file_path),
            "currentVersion": original_version,
            "targetVersion": target_version,
            "migrated": False,
            "reason": "already at or above target version",
        }

    migrated_data, applied = migrate(data, target_version)

    if not dry_run:
        file_path.write_text(
            json.dumps(migrated_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "file": str(file_path),
        "fromVersion": original_version,
        "toVersion": detect_version(migrated_data),
        "migrated": True,
        "dryRun": dry_run,
        "appliedMigrations": applied,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="JSON files to migrate (evidence-ledger, role-result)")
    parser.add_argument("--target-version", type=int, default=CURRENT_VERSION,
                        help=f"Target schema version (default: {CURRENT_VERSION})")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    reports = []
    for file_arg in args.files:
        path = Path(file_arg).resolve()
        if path.is_dir():
            for child in sorted(path.glob("*.json")):
                reports.append(migrate_file(child, args.target_version, args.dry_run))
        else:
            reports.append(migrate_file(path, args.target_version, args.dry_run))

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            status = "MIGRATED" if r.get("migrated") else "SKIP"
            if r.get("error"):
                status = "ERROR"
            print(f"[{status}] {r.get('file', '?')}")
            if r.get("appliedMigrations"):
                for m in r["appliedMigrations"]:
                    print(f"  → {m}")
            if r.get("error"):
                print(f"  ERROR: {r['error']}")
            if r.get("reason"):
                print(f"  reason: {r['reason']}")

    migrated_count = sum(1 for r in reports if r.get("migrated"))
    print(f"\nTotal: {len(reports)} files, {migrated_count} migrated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
