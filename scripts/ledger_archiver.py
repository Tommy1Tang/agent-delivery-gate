#!/usr/bin/env python3
"""P8-13: Evidence ledger archival and compaction.

Over time, evidence ledgers accumulate and consume disk space. This module:
  - Archives old ledgers (compress to gzip)
  - Compacts archived ledgers (extract summary, discard raw events)
  - Enforces retention policies (max age, max count)
  - Provides ledger listing and statistics
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Retention defaults
MAX_ACTIVE_LEDGERS = 5       # Keep last N ledgers unarchived
MAX_ARCHIVED_LEDGERS = 20    # Keep last N archived ledgers
MAX_ARCHIVE_AGE_DAYS = 90    # Delete archives older than this

LEDGER_GLOB = "evidence-ledger*.json"
ARCHIVE_DIR = ".qoder/skill-state/ledger-archive"
SUMMARY_FILE = "ledger-summaries.jsonl"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def find_ledgers(project_root: Path) -> list[Path]:
    """Find all evidence ledger files in the project, sorted by mtime."""
    candidates: list[Path] = []
    # Check common locations
    for search_dir in [project_root, project_root / "docs", project_root / ".qoder"]:
        if search_dir.is_dir():
            for f in search_dir.glob(LEDGER_GLOB):
                if f.is_file():
                    candidates.append(f)
    # Deduplicate
    seen: set[str] = set()
    unique: list[Path] = []
    for c in candidates:
        resolved = str(c.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(c)
    unique.sort(key=lambda p: p.stat().st_mtime)
    return unique


def _extract_summary(ledger: dict) -> dict:
    """Extract a compact summary from a full ledger."""
    role_runs = ledger.get("roleRuns", [])
    role_summary = {}
    for run in role_runs:
        role_id = run.get("roleId", "unknown")
        role_summary[role_id] = {
            "status": run.get("status", "unknown"),
            "durationMs": run.get("durationMs"),
        }

    gate = ledger.get("deliveryGateEvidence", {})

    return {
        "deliveryId": ledger.get("deliveryId", "unknown"),
        "deliveryStatus": ledger.get("deliveryStatus", "unknown"),
        "createdAt": ledger.get("createdAt", ""),
        "taskSummary": ledger.get("taskSummary", "")[:200],
        "totalRoles": len(role_runs),
        "roleSummary": role_summary,
        "gateStatus": gate.get("status"),
        "blockingReasons": gate.get("blockingReasons", [])[:5],
    }


def archive_ledger(ledger_path: Path, archive_dir: Path) -> Path | None:
    """Compress a ledger to gzip in the archive directory."""
    if not ledger_path.is_file():
        return None
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{ledger_path.stem}.json.gz"

    try:
        content = ledger_path.read_bytes()
        with gzip.open(archive_path, "wb") as gz:
            gz.write(content)
        return archive_path
    except (OSError, gzip.BadGzipFile):
        return None


def compact_and_archive(project_root: Path, dry_run: bool = False) -> dict:
    """Run the full archival and compaction pipeline.

    1. Find all ledgers
    2. Keep the last MAX_ACTIVE_LEDGERS unarchived
    3. Archive older ones (gzip)
    4. Extract summaries to SUMMARY_FILE
    5. Delete original (non-archived) ledger files
    6. Enforce retention on archive dir
    """
    ledgers = find_ledgers(project_root)
    archive_dir = project_root / ARCHIVE_DIR
    summary_path = archive_dir / SUMMARY_FILE

    archived: list[str] = []
    summaries_written: list[str] = []
    deleted_archives: list[str] = []
    errors: list[str] = []

    if len(ledgers) <= MAX_ACTIVE_LEDGERS:
        return {
            "status": "skip",
            "reason": f"Only {len(ledgers)} ledger(s) found, threshold is {MAX_ACTIVE_LEDGERS}",
            "ledgerCount": len(ledgers),
        }

    # Determine which to archive (all but the last MAX_ACTIVE_LEDGERS)
    to_archive = ledgers[:-MAX_ACTIVE_LEDGERS]
    to_keep = ledgers[-MAX_ACTIVE_LEDGERS:]

    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)

    for ledger_path in to_archive:
        try:
            content = ledger_path.read_text(encoding="utf-8")
            ledger_data = json.loads(content)
            summary = _extract_summary(ledger_data)

            if not dry_run:
                # Archive (gzip)
                archive_result = archive_ledger(ledger_path, archive_dir)
                if archive_result:
                    archived.append(str(archive_result.name))

                    # Write summary
                    with open(summary_path, "a", encoding="utf-8") as sf:
                        sf.write(json.dumps(summary, ensure_ascii=False) + "\n")
                    summaries_written.append(summary.get("deliveryId", "?"))

                    # Remove original
                    ledger_path.unlink()
                else:
                    errors.append(f"Failed to archive: {ledger_path.name}")
            else:
                archived.append(f"[dry-run] {ledger_path.name}")
                summaries_written.append(summary.get("deliveryId", "?"))

        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"Error processing {ledger_path.name}: {str(e)[:100]}")

    # Enforce retention on archive dir
    if not dry_run and archive_dir.is_dir():
        gz_files = sorted(archive_dir.glob("*.json.gz"), key=lambda p: p.stat().st_mtime)
        # Remove excess archives
        if len(gz_files) > MAX_ARCHIVED_LEDGERS:
            for old in gz_files[:-MAX_ARCHIVED_LEDGERS]:
                try:
                    old.unlink()
                    deleted_archives.append(old.name)
                except OSError:
                    pass
        # Remove old archives by age
        cutoff = _now() - timedelta(days=MAX_ARCHIVE_AGE_DAYS)
        for gz in gz_files:
            try:
                mtime = datetime.fromtimestamp(gz.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff and gz.name not in deleted_archives:
                    gz.unlink()
                    deleted_archives.append(gz.name)
            except OSError:
                pass

    return {
        "status": "done" if not errors else "partial",
        "ledgersFound": len(ledgers),
        "archived": archived,
        "summariesWritten": summaries_written,
        "activeLedgersKept": len(to_keep),
        "deletedArchives": deleted_archives,
        "errors": errors,
        "dryRun": dry_run,
    }


def list_archive_summaries(project_root: Path) -> list[dict]:
    """Read all archived ledger summaries."""
    summary_path = project_root / ARCHIVE_DIR / SUMMARY_FILE
    if not summary_path.is_file():
        return []
    summaries = []
    try:
        for line in summary_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                summaries.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return summaries


def archive_stats(project_root: Path) -> dict:
    """Get archive statistics."""
    archive_dir = project_root / ARCHIVE_DIR
    active_ledgers = find_ledgers(project_root)
    archived = list(archive_dir.glob("*.json.gz")) if archive_dir.is_dir() else []
    summaries = list_archive_summaries(project_root)

    total_archive_size = sum(f.stat().st_size for f in archived) if archived else 0

    return {
        "activeLedgers": len(active_ledgers),
        "archivedLedgers": len(archived),
        "summaryEntries": len(summaries),
        "archiveSizeBytes": total_archive_size,
        "archiveSizeKB": round(total_archive_size / 1024, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run archival and compaction")
    p_run.add_argument("--project-root", default=".")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--json", action="store_true")

    p_stats = sub.add_parser("stats", help="Show archive statistics")
    p_stats.add_argument("--project-root", default=".")
    p_stats.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="List archived summaries")
    p_list.add_argument("--project-root", default=".")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0

    pr = Path(args.project_root).resolve()

    if args.cmd == "run":
        result = compact_and_archive(pr, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Archival: {result['status'].upper()}")
            print(f"  Found: {result.get('ledgersFound', 0)} ledgers")
            print(f"  Archived: {len(result.get('archived', []))}")
            print(f"  Active kept: {result.get('activeLedgersKept', 0)}")
            if result.get("errors"):
                for e in result["errors"]:
                    print(f"  ERROR: {e}")

    elif args.cmd == "stats":
        stats = archive_stats(pr)
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            print(f"Active ledgers: {stats['activeLedgers']}")
            print(f"Archived: {stats['archivedLedgers']}")
            print(f"Summaries: {stats['summaryEntries']}")
            print(f"Archive size: {stats['archiveSizeKB']} KB")

    elif args.cmd == "list":
        for s in list_archive_summaries(pr):
            status = s.get("gateStatus", "?")
            did = s.get("deliveryId", "?")[:8]
            task = s.get("taskSummary", "")[:50]
            print(f"  {did}... [{status}] {task}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
