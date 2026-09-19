#!/usr/bin/env python3
"""Chaos/failure-injection tests for orchestration resilience."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Simulated failure scenarios
# ---------------------------------------------------------------------------

CHAOS_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "role-block-quality-gate",
        "description": "Quality Gate Engineer returns verdict=BLOCK",
        "inject": {
            "roleId": "quality-gate-engineer",
            "roleResult": {
                "status": "blocked",
                "changeSet": {"modified": [], "created": ["docs/14-代码评审.md"], "deleted": []},
                "summary": "Code review found 3 critical issues",
                "blockers": ["SQL injection in UserService.java", "Missing input validation"],
            },
        },
        "expectedBehavior": {
            "deliveryStatus": "in-progress",
            "mustNotComplete": True,
            "mustTriggerRework": True,
            "reworkTarget": ["backend-engineer", "quality-gate-engineer"],
        },
    },
    {
        "id": "e2e-unavailable",
        "description": "Browser E2E engineer session lost (Agent tool unavailable)",
        "inject": {
            "roleId": "browser-e2e-engineer",
            "error": {"code": "SESSION_LOST", "message": "Agent tool returned platform-level error"},
        },
        "expectedBehavior": {
            "mustRetry": True,
            "maxRetries": 2,
            "afterExhaustion": "halted-pending-user",
        },
    },
    {
        "id": "lockfile-conflict",
        "description": "Frontend and Backend engineer produce conflicting lockfile changes",
        "inject": {
            "roleId": "frontend-engineer",
            "roleResult": {
                "status": "completed",
                "changeSet": {"modified": ["package-lock.json"], "created": [], "deleted": []},
                "summary": "Frontend implementation complete",
                "blockers": [],
            },
            "conflictWith": {
                "roleId": "backend-engineer",
                "changeSet": {"modified": ["package-lock.json"], "created": [], "deleted": []},
            },
        },
        "expectedBehavior": {
            "mustDetectConflict": True,
            "resolution": "rework-frontend-engineer",
        },
    },
    {
        "id": "cascade-block-from-architect",
        "description": "Architect returns failed status, all downstream must be skipped",
        "inject": {
            "roleId": "architect",
            "roleResult": {
                "status": "failed",
                "changeSet": None,
                "summary": "Cannot determine architecture without clearer requirements",
                "blockers": ["Ambiguous scope: 3 interpretations possible"],
            },
        },
        "expectedBehavior": {
            "cascadeSkipped": [
                "data-contract-designer", "data-engineer", "ui-designer",
                "execution-engineer", "frontend-engineer", "backend-engineer",
                "quality-gate-engineer", "browser-e2e-engineer",
            ],
            "deliveryStatus": "halted-pending-user",
        },
    },
    {
        "id": "security-block-immediate-halt",
        "description": "Security review finds critical vulnerability, delivery must halt immediately",
        "inject": {
            "roleId": "quality-gate-engineer",
            "roleResult": {
                "status": "security-block",
                "changeSet": {"modified": [], "created": ["docs/15-安全评审.md"], "deleted": []},
                "summary": "Critical: hardcoded AWS credentials in source",
                "blockers": ["security-block: credential exposure"],
            },
        },
        "expectedBehavior": {
            "mustNotRetry": True,
            "deliveryStatus": "halted-pending-user",
            "mustNotifyUser": True,
        },
    },
    {
        "id": "multi-crash-circuit-breaker",
        "description": "3 consecutive roles crash with session-lost, circuit breaker should trigger",
        "inject": {
            "crashes": [
                {"roleId": "data-contract-designer", "error": {"code": "SESSION_LOST"}},
                {"roleId": "execution-engineer", "error": {"code": "SESSION_LOST"}},
                {"roleId": "frontend-engineer", "error": {"code": "SESSION_LOST"}},
            ],
        },
        "expectedBehavior": {
            "circuitBroken": True,
            "deliveryStatus": "halted-circuit-broken",
            "mustGenerateIncidentReport": True,
        },
    },
    {
        "id": "rework-cap-exceeded",
        "description": "Same root cause triggers 6th rework iteration (cap is 5)",
        "inject": {
            "roleId": "backend-engineer",
            "ledgerState": {
                "observability": {
                    "reworkCount": 9,
                    "reworkPerRootCause": {"null-pointer-in-payment-service": 5},
                },
            },
            "roleResult": {
                "status": "blocked",
                "blockers": ["Same null pointer issue persists"],
            },
        },
        "expectedBehavior": {
            "deliveryStatus": "halted-pending-user",
            "mustNotAutoRework": True,
            "reason": "rework-cap-exceeded-per-root-cause",
        },
    },
    {
        "id": "timeout-with-partial-output",
        "description": "Backend engineer times out but has partial output in .delivery/partial/",
        "inject": {
            "roleId": "backend-engineer",
            "error": {"code": "TIMEOUT", "elapsed": 900001, "timeoutMs": 900000},
            "partialOutput": {
                "path": ".delivery/partial/backend-engineer/",
                "files": ["src/main/java/Service.java"],
            },
        },
        "expectedBehavior": {
            "mustRetry": True,
            "mustPreservePartial": True,
            "retryHandoffIncludes": "partialOutputPath",
        },
    },
]


def validate_scenario(scenario: dict) -> list[str]:
    """Validate a single chaos scenario structure."""
    errors = []
    required_keys = ["id", "description", "inject", "expectedBehavior"]
    for key in required_keys:
        if key not in scenario:
            errors.append(f"Scenario missing required key: {key}")
    inject = scenario.get("inject", {})
    if not inject.get("roleId") and not inject.get("crashes"):
        errors.append(f"Scenario '{scenario.get('id')}': inject must have roleId or crashes")
    return errors


def _run_execution_level_checks(skill_root: Path, config: dict) -> list[dict]:
    """P4-9: Execution-level chaos simulation.

    Actually calls build_plan to verify the orchestration engine produces
    valid plans that the chaos scenarios can meaningfully target.
    """
    results: list[dict] = []

    # Add orchestrate.py's parent to sys.path so we can import build_plan.
    scripts_dir = skill_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    try:
        from orchestrate import build_plan, ROLE_TIMEOUTS, DEFAULT_RETRY_POLICY  # noqa: E402
    except ImportError as exc:
        results.append({"id": "exec-import", "status": "FAIL", "errors": [f"Cannot import orchestrate: {exc}"]})
        return results

    # Test 1: build_plan produces valid plan with all injected roles present in route.
    test_task = "从 0 实现一个完整系统，包含前后端和数据库。"
    try:
        plan = build_plan(skill_root, Path(".").resolve(), test_task, ["forward-development"])
    except Exception as exc:
        results.append({"id": "exec-build-plan", "status": "FAIL", "errors": [f"build_plan raised: {exc}"]})
        return results

    errors: list[str] = []
    route = plan.get("route", [])
    if not route:
        errors.append("build_plan returned empty route")
    # Verify all chaos-injected roles exist in route.
    for scenario in CHAOS_SCENARIOS:
        inject = scenario.get("inject", {})
        rid = inject.get("roleId")
        if rid and rid not in route:
            errors.append(f"Scenario '{scenario['id']}' injects role '{rid}' not in plan route")
        for crash in inject.get("crashes", []):
            crid = crash.get("roleId")
            if crid and crid not in route:
                errors.append(f"Scenario '{scenario['id']}' crash role '{crid}' not in plan route")
    results.append({
        "id": "exec-route-coverage",
        "status": "FAIL" if errors else "PASS",
        "errors": errors if errors else None,
    })

    # Test 2: Verify retry policy is attached to all handoffs.
    errors2: list[str] = []
    for handoff in plan.get("handoffs", []):
        role_id = handoff.get("roleId", "unknown")
        if "retryPolicy" not in handoff:
            errors2.append(f"Handoff for '{role_id}' missing retryPolicy")
        else:
            policy = handoff["retryPolicy"]
            if policy.get("maxRetries", 0) < 1:
                errors2.append(f"Handoff '{role_id}' retryPolicy.maxRetries < 1")
            if "nonRetryableErrors" not in policy:
                errors2.append(f"Handoff '{role_id}' retryPolicy missing nonRetryableErrors")
    results.append({
        "id": "exec-retry-policy",
        "status": "FAIL" if errors2 else "PASS",
        "errors": errors2 if errors2 else None,
    })

    # Test 3: Verify timeout multiplier is applied (timeout >= base).
    errors3: list[str] = []
    for handoff in plan.get("handoffs", []):
        role_id = handoff.get("roleId", "unknown")
        base = ROLE_TIMEOUTS.get(role_id, 300000)
        actual_timeout = handoff.get("timeoutMs", 0)
        if actual_timeout < base:
            errors3.append(f"Handoff '{role_id}' timeoutMs={actual_timeout} < base={base}")
    results.append({
        "id": "exec-adaptive-timeout",
        "status": "FAIL" if errors3 else "PASS",
        "errors": errors3 if errors3 else None,
    })

    # Test 4: Verify conditional role flags are populated.
    errors4: list[str] = []
    flags = plan.get("conditionalRoleFlags")
    if not isinstance(flags, dict):
        errors4.append("build_plan missing conditionalRoleFlags dict")
    elif not flags:
        errors4.append("conditionalRoleFlags is empty (expected at least one entry)")
    else:
        # For our test task mentioning '数据库', data-engineer should be True.
        if not flags.get("data-engineer"):
            errors4.append("conditionalRoleFlags['data-engineer'] should be True for DB task")
    results.append({
        "id": "exec-conditional-flags",
        "status": "FAIL" if errors4 else "PASS",
        "errors": errors4 if errors4 else None,
    })

    # Test 5: Verify parallelGroups is non-empty and well-formed.
    errors5: list[str] = []
    groups = plan.get("parallelGroups", [])
    if not groups:
        errors5.append("parallelGroups is empty")
    else:
        all_in_groups = [rid for g in groups for rid in g]
        if sorted(all_in_groups) != sorted(route):
            errors5.append("parallelGroups does not cover all route roles")
    results.append({
        "id": "exec-parallel-groups",
        "status": "FAIL" if errors5 else "PASS",
        "errors": errors5 if errors5 else None,
    })

    return results


def run_chaos_tests(skill_root: Path) -> dict:
    """Run structural validation of chaos scenarios and verify consistency with config."""
    config_path = skill_root / "assets" / "config" / "agent-team-config.json"
    if not config_path.exists():
        return {"status": "error", "message": f"Config not found: {config_path}"}

    config = json.loads(config_path.read_text(encoding="utf-8"))
    valid_roles = {role["id"] for role in config.get("roles", [])}

    results = []
    total_pass = 0
    total_fail = 0

    for scenario in CHAOS_SCENARIOS:
        errors = validate_scenario(scenario)

        # Verify injected roleId exists in config
        inject = scenario.get("inject", {})
        role_id = inject.get("roleId")
        if role_id and role_id not in valid_roles:
            errors.append(f"Injected roleId '{role_id}' not in config roles")

        crashes = inject.get("crashes", [])
        for crash in crashes:
            crid = crash.get("roleId")
            if crid and crid not in valid_roles:
                errors.append(f"Crash roleId '{crid}' not in config roles")

        # Verify expectedBehavior references valid roles
        expected = scenario.get("expectedBehavior", {})
        for skip_role in expected.get("cascadeSkipped", []):
            if skip_role not in valid_roles:
                errors.append(f"cascadeSkipped role '{skip_role}' not in config")
        for rework_role in expected.get("reworkTarget", []):
            if rework_role not in valid_roles:
                errors.append(f"reworkTarget role '{rework_role}' not in config")

        if errors:
            total_fail += 1
            results.append({"id": scenario["id"], "status": "FAIL", "errors": errors})
        else:
            total_pass += 1
            results.append({"id": scenario["id"], "status": "PASS"})

    # P4-9: Execution-level simulation — actually invoke build_plan.
    exec_results = _run_execution_level_checks(skill_root, config)
    for er in exec_results:
        if er.get("status") == "PASS":
            total_pass += 1
        else:
            total_fail += 1
        results.append(er)

    status = "PASS" if total_fail == 0 else "FAIL"
    return {
        "status": status,
        "total": len(CHAOS_SCENARIOS) + len(exec_results),
        "pass": total_pass,
        "fail": total_fail,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to skill root")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    report = run_chaos_tests(skill_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Chaos Tests: {report['status']} ({report['pass']}/{report['total']} passed)")
        for r in report["results"]:
            marker = "✓" if r["status"] == "PASS" else "✗"
            print(f"  {marker} {r['id']}")
            if r.get("errors"):
                for e in r["errors"]:
                    print(f"    → {e}")

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
