#!/usr/bin/env python3
"""P7-7 + M5: Delivery checkpoint manager and incremental plan reuse.

Two closely related capabilities:
  P7-7 — Checkpoint: save/resume mid-delivery state so a failed delivery can
         restart from the last successful role instead of re-running everything.
  M5   — Plan reuse: when the same project receives a follow-up task, detect
         overlap with the previous plan and produce a delta-only plan.

Storage: <project_root>/.qoder/skill-state/
  delivery-checkpoint.json  — latest checkpoint state
  last-plan.json            — last successful plan (for delta detection)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_STATE_DIR = ".qoder/skill-state"
CHECKPOINT_FILE = "delivery-checkpoint.json"
LAST_PLAN_FILE = "last-plan.json"

# Roles that can be safely skipped when resuming from checkpoint.
RESUMABLE_STATUSES = {"completed", "skipped"}


def _state_dir(project_root: Path) -> Path:
    return project_root / SKILL_STATE_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── P7-7: Checkpoint Management ────────────────────────────────────────────────


def save_checkpoint(project_root: Path, delivery_id: str, plan: dict,
                    completed_roles: list[str], role_results: dict,
                    current_role: str | None = None) -> Path:
    """Save a delivery checkpoint after each role completes.

    Args:
        project_root: Path to the project root.
        delivery_id: Current delivery UUID.
        plan: The full orchestration plan.
        completed_roles: List of role IDs that have completed successfully.
        role_results: Dict of role_id → roleResult for completed roles.
        current_role: Role currently in progress (or None if between roles).
    """
    d = _state_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)

    checkpoint = {
        "schemaVersion": 1,
        "deliveryId": delivery_id,
        "taskSummary": plan.get("taskSummary", ""),
        "route": plan.get("route", []),
        "completedRoles": completed_roles,
        "currentRole": current_role,
        "roleResults": {
            role_id: _compact_result(result)
            for role_id, result in role_results.items()
        },
        "savedAt": _now_iso(),
        "resumable": True,
        "planDigest": _plan_digest(plan),
    }

    f = d / CHECKPOINT_FILE
    f.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def _compact_result(result: dict) -> dict:
    """Strip large fields from role result to keep checkpoint small."""
    return {
        "status": result.get("status", "unknown"),
        "summary": (result.get("summary") or "")[:300],
        "changeSetFiles": len(result.get("changeSet", {}).get("modified", []))
                         + len(result.get("changeSet", {}).get("created", [])),
    }


def _plan_digest(plan: dict) -> str:
    """Create a short digest of the plan for matching."""
    import hashlib
    key = f"{plan.get('taskSummary', '')}|{','.join(plan.get('route', []))}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def load_checkpoint(project_root: Path) -> dict | None:
    """Load the latest delivery checkpoint. Returns None if none exists."""
    f = _state_dir(project_root) / CHECKPOINT_FILE
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def can_resume(project_root: Path, new_plan: dict) -> dict:
    """Check if a delivery can be resumed from checkpoint.

    Returns a dict with:
      - resumable: bool
      - skipRoles: list of role IDs that can be skipped (already completed)
      - resumeFrom: the role ID to start from
      - reason: human-readable explanation
    """
    checkpoint = load_checkpoint(project_root)
    if not checkpoint:
        return {"resumable": False, "reason": "No checkpoint found"}

    if not checkpoint.get("resumable"):
        return {"resumable": False, "reason": "Checkpoint marked as non-resumable"}

    # Verify plan compatibility (same route)
    old_route = checkpoint.get("route", [])
    new_route = new_plan.get("route", [])
    if old_route != new_route:
        return {"resumable": False, "reason": f"Route changed: {len(old_route)} → {len(new_route)} roles"}

    # Determine which roles can be skipped
    completed = set(checkpoint.get("completedRoles", []))
    results = checkpoint.get("roleResults", {})
    skip_roles = []
    resume_from = None

    for role_id in new_route:
        if role_id in completed:
            status = results.get(role_id, {}).get("status", "unknown")
            if status in RESUMABLE_STATUSES:
                skip_roles.append(role_id)
            else:
                # Non-resumable status (e.g., failed) — restart from here
                resume_from = role_id
                break
        else:
            resume_from = role_id
            break

    if not resume_from and skip_roles:
        # All roles completed — nothing to resume
        return {"resumable": False, "reason": "All roles already completed in previous delivery"}

    return {
        "resumable": True,
        "skipRoles": skip_roles,
        "resumeFrom": resume_from,
        "checkpointDeliveryId": checkpoint.get("deliveryId"),
        "savedAt": checkpoint.get("savedAt"),
        "reason": f"Resume from '{resume_from}', skip {len(skip_roles)} completed roles",
    }


def clear_checkpoint(project_root: Path) -> bool:
    """Clear the checkpoint after a successful delivery."""
    f = _state_dir(project_root) / CHECKPOINT_FILE
    if f.is_file():
        f.unlink()
        return True
    return False


# ─── M5: Incremental Plan Reuse ─────────────────────────────────────────────────


def save_last_plan(project_root: Path, plan: dict) -> Path:
    """Cache the current plan for future delta detection."""
    d = _state_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)

    cache = {
        "schemaVersion": 1,
        "deliveryId": plan.get("deliveryId"),
        "taskSummary": plan.get("taskSummary", ""),
        "workflowDomains": plan.get("workflowDomains", []),
        "route": plan.get("route", []),
        "conditionalRoleFlags": plan.get("conditionalRoleFlags", {}),
        "uiAffected": plan.get("uiAffected", False),
        "securitySensitive": plan.get("securitySensitive", False),
        "stackSignature": (plan.get("stackDetection") or {}).get("selectedAdapters", []),
        "savedAt": _now_iso(),
    }

    f = d / LAST_PLAN_FILE
    f.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def load_last_plan(project_root: Path) -> dict | None:
    """Load the cached last plan."""
    f = _state_dir(project_root) / LAST_PLAN_FILE
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def compute_plan_delta(last_plan: dict, new_plan: dict) -> dict:
    """Compare two plans and identify what changed.

    Returns a delta report that can inform the orchestrator whether to
    reuse decisions or re-evaluate.
    """
    changes: list[str] = []
    reusable: list[str] = []

    # Compare domains
    old_domains = set(last_plan.get("workflowDomains", []))
    new_domains = set(new_plan.get("workflowDomains", []))
    if old_domains != new_domains:
        added = new_domains - old_domains
        removed = old_domains - new_domains
        if added:
            changes.append(f"New domains: {added}")
        if removed:
            changes.append(f"Removed domains: {removed}")
    else:
        reusable.append("workflowDomains unchanged")

    # Compare route
    old_route = last_plan.get("route", [])
    new_route = new_plan.get("route", [])
    if old_route != new_route:
        changes.append(f"Route changed: {len(old_route)} → {len(new_route)} roles")
    else:
        reusable.append("route unchanged")

    # Compare conditional flags
    old_flags = last_plan.get("conditionalRoleFlags", {})
    new_flags = new_plan.get("conditionalRoleFlags", {})
    changed_flags = {k: (old_flags.get(k), new_flags.get(k))
                     for k in set(old_flags) | set(new_flags)
                     if old_flags.get(k) != new_flags.get(k)}
    if changed_flags:
        changes.append(f"Conditional flags changed: {list(changed_flags.keys())}")
    else:
        reusable.append("conditionalRoleFlags unchanged")

    # Compare security/UI sensitivity
    for field in ("uiAffected", "securitySensitive"):
        if last_plan.get(field) != new_plan.get(field):
            changes.append(f"{field}: {last_plan.get(field)} → {new_plan.get(field)}")
        else:
            reusable.append(f"{field} unchanged")

    is_incremental = len(changes) <= 2 and len(reusable) >= 3

    return {
        "isIncremental": is_incremental,
        "changes": changes,
        "reusable": reusable,
        "previousDeliveryId": last_plan.get("deliveryId"),
        "previousTaskSummary": last_plan.get("taskSummary", "")[:100],
    }


def enrich_plan_with_delta(plan: dict, delta: dict) -> dict:
    """Enrich a plan with delta context so roles know this is incremental."""
    if delta.get("isIncremental"):
        plan["incrementalContext"] = {
            "isIncremental": True,
            "previousDeliveryId": delta.get("previousDeliveryId"),
            "previousTaskSummary": delta.get("previousTaskSummary"),
            "changes": delta.get("changes", []),
            "reusable": delta.get("reusable", []),
            "guidance": (
                "This is an incremental delivery on the same project. "
                "Reuse existing architecture decisions and conventions. "
                "Focus only on the delta changes, not a full re-implementation."
            ),
        }
    return plan


# ─── CLI ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status", help="Show checkpoint and last-plan status")
    p_status.add_argument("--project-root", default=".")
    p_status.add_argument("--json", action="store_true")

    p_clear = sub.add_parser("clear", help="Clear checkpoint")
    p_clear.add_argument("--project-root", default=".")

    p_check = sub.add_parser("can-resume", help="Check if delivery can resume")
    p_check.add_argument("--project-root", default=".")
    p_check.add_argument("--plan-json", required=True, help="Path to new plan JSON")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0

    pr = Path(args.project_root).resolve()

    if args.cmd == "status":
        cp = load_checkpoint(pr)
        lp = load_last_plan(pr)
        report = {
            "checkpoint": {
                "exists": cp is not None,
                "deliveryId": cp.get("deliveryId") if cp else None,
                "completedRoles": len(cp.get("completedRoles", [])) if cp else 0,
                "savedAt": cp.get("savedAt") if cp else None,
            },
            "lastPlan": {
                "exists": lp is not None,
                "deliveryId": lp.get("deliveryId") if lp else None,
                "taskSummary": (lp.get("taskSummary", "")[:80]) if lp else None,
                "savedAt": lp.get("savedAt") if lp else None,
            },
        }
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Checkpoint: {'EXISTS' if cp else 'NONE'}")
            if cp:
                print(f"  Delivery: {cp.get('deliveryId', '?')[:8]}...")
                print(f"  Completed: {len(cp.get('completedRoles', []))} roles")
                print(f"  Saved at: {cp.get('savedAt')}")
            print(f"\nLast Plan: {'EXISTS' if lp else 'NONE'}")
            if lp:
                print(f"  Delivery: {lp.get('deliveryId', '?')[:8]}...")
                print(f"  Task: {lp.get('taskSummary', '?')[:60]}")

    elif args.cmd == "clear":
        cleared = clear_checkpoint(pr)
        print(f"Checkpoint {'cleared' if cleared else 'not found'}")

    elif args.cmd == "can-resume":
        plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))
        result = can_resume(pr, plan)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
