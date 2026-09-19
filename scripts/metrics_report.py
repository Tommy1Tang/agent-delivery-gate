#!/usr/bin/env python3
"""Summarize metrics from evidence ledgers with baseline comparison."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Baseline storage path (relative to skill root or absolute)
DEFAULT_BASELINE_FILENAME = "metrics-baseline.json"
MAX_BASELINE_HISTORY = 10  # Keep last N deliveries
DEGRADATION_THRESHOLD = 1.5  # 50% slower than P50 triggers warning


def load_ledgers(paths: list[Path]) -> list[dict]:
    ledgers = []
    for path in paths:
        if path.is_dir():
            for child in sorted(path.glob("*.json")):
                ledgers.append(json.loads(child.read_text(encoding="utf-8")))
        else:
            ledgers.append(json.loads(path.read_text(encoding="utf-8")))
    return ledgers


def summarize(ledgers: list[dict]) -> dict:
    roles_counter = Counter()
    fallback_count = 0
    command_count = 0
    gate_count = 0
    failed_gate_count = 0
    retry_total = 0
    security_block_count = 0
    rework_total = 0
    blocking_reasons = []
    role_timing: dict[str, dict] = {}
    # P6-13: Token budget audit tracking.
    token_audit: dict[str, dict] = {}  # roleId -> {budget, consumed, overBudget}
    total_token_budget = 0
    total_token_consumed = 0

    for ledger in ledgers:
        for role_run in ledger.get("roleRuns", []):
            role_id = role_run.get("roleId", "unknown")
            roles_counter[role_id] += 1
            if role_run.get("sessionMode") == "single-session-fallback":
                fallback_count += 1

            # Timing
            duration = role_run.get("durationMs", 0)
            if role_id not in role_timing:
                role_timing[role_id] = {"durationMs": 0, "count": 0}
            role_timing[role_id]["durationMs"] += duration
            role_timing[role_id]["count"] += 1

            # Retry
            retry_total += role_run.get("retryCount", 0)

            # Blocking reasons
            for reason in role_run.get("blockedBy", []):
                blocking_reasons.append({"roleId": role_id, "reason": reason})

            # P6-13: Token usage per role
            tu = role_run.get("tokenUsage")
            if isinstance(tu, dict):
                budget = tu.get("budget", 0)
                consumed = tu.get("consumed", 0)
                total_token_budget += budget
                total_token_consumed += consumed
                if role_id not in token_audit:
                    token_audit[role_id] = {"budget": 0, "consumed": 0}
                token_audit[role_id]["budget"] += budget
                token_audit[role_id]["consumed"] += consumed

        command_count += len(ledger.get("commands", []))
        gates = ledger.get("qualityGates", [])
        gate_count += len(gates)
        failed_gate_count += sum(1 for gate in gates if gate.get("status") != "pass")

        # Observability section
        obs = ledger.get("observability", {})
        security_block_count += obs.get("securityBlockCount", 0)
        rework_total += obs.get("reworkCount", 0)

        # P6-13: Token usage from observability section (ledger-level)
        obs_tokens = obs.get("tokenUsage", {})
        if isinstance(obs_tokens, dict) and obs_tokens.get("totalBudget"):
            total_token_budget += obs_tokens.get("totalBudget", 0)
            total_token_consumed += obs_tokens.get("totalConsumed", 0)

    # Compute per-role averages
    per_role = {}
    total_ms = 0
    for role_id, data in role_timing.items():
        total_ms += data["durationMs"]
        per_role[role_id] = {
            "durationMs": data["durationMs"],
            "count": data["count"],
            "avgMs": data["durationMs"] // data["count"] if data["count"] else 0,
        }

    # P6-13: Compute token utilization and over-budget warnings
    token_over_budget_roles: list[str] = []
    for role_id, ta in token_audit.items():
        if ta["budget"] > 0 and ta["consumed"] > ta["budget"]:
            token_over_budget_roles.append(role_id)
        ta["utilizationPct"] = round(ta["consumed"] / ta["budget"] * 100, 1) if ta["budget"] > 0 else 0.0

    return {
        "ledgerCount": len(ledgers),
        "roleRunCount": sum(roles_counter.values()),
        "fallbackCount": fallback_count,
        "commandCount": command_count,
        "qualityGateCount": gate_count,
        "failedGateCount": failed_gate_count,
        "roleTiming": {
            "totalMs": total_ms,
            "perRole": per_role,
        },
        "retryTotal": retry_total,
        "blockingReasons": blocking_reasons,
        "documentMissingRate": 0.0,
        "documentDetails": {"expected": 0, "present": 0, "missing": []},
        "testPassRate": 0.0,
        "testDetails": {"total": 0, "pass": 0, "fail": 0, "blocked": 0, "skip": 0},
        "securityBlockCount": security_block_count,
        "securityBlockDetails": [],
        "reworkCount": rework_total,
        "reworkReasons": [],
        "roles": dict(sorted(roles_counter.items())),
        # P6-13: Token budget audit summary
        "tokenAudit": {
            "totalBudget": total_token_budget,
            "totalConsumed": total_token_consumed,
            "utilizationPct": round(total_token_consumed / total_token_budget * 100, 1) if total_token_budget > 0 else 0.0,
            "overBudgetRoles": token_over_budget_roles,
            "perRole": token_audit,
        },
    }


def load_baseline(baseline_path: Path) -> dict:
    """Load existing baseline or return empty structure."""
    if baseline_path.exists():
        try:
            return json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"deliveries": [], "p50": {}, "p95": {}}


def update_baseline(baseline_path: Path, metrics: dict) -> dict:
    """Append current metrics to baseline history and compute percentiles.

    P5-7: On first run (no existing baseline), bootstraps a new baseline file
    and emits a 'bootstrapped' flag so callers can inform the user.
    """
    is_bootstrap = not baseline_path.exists()
    baseline = load_baseline(baseline_path)
    entry = {
        "totalMs": metrics.get("roleTiming", {}).get("totalMs", 0),
        "roleRunCount": metrics.get("roleRunCount", 0),
        "retryTotal": metrics.get("retryTotal", 0),
        "reworkCount": metrics.get("reworkCount", 0),
        "failedGateCount": metrics.get("failedGateCount", 0),
    }
    baseline["deliveries"].append(entry)
    # Keep only last N
    baseline["deliveries"] = baseline["deliveries"][-MAX_BASELINE_HISTORY:]

    # Compute P50 and P95 for key metrics
    deliveries = baseline["deliveries"]
    for key in ("totalMs", "roleRunCount", "retryTotal", "reworkCount"):
        values = sorted(d.get(key, 0) for d in deliveries)
        n = len(values)
        if n > 0:
            baseline["p50"][key] = values[n // 2]
            baseline["p95"][key] = values[min(int(n * 0.95), n - 1)]

    # P5-7: Mark bootstrap event for downstream reporting.
    if is_bootstrap:
        baseline["bootstrappedAt"] = metrics.get("_reportedAt", "")
        baseline["bootstrapNote"] = (
            "Baseline auto-created on first delivery. Degradation detection "
            "requires >=3 historical entries to be meaningful."
        )

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline


def detect_degradation(metrics: dict, baseline: dict) -> list[str]:
    """Compare current metrics against baseline P50; return warnings."""
    warnings = []
    p50 = baseline.get("p50", {})
    if not p50:
        return warnings

    current_total_ms = metrics.get("roleTiming", {}).get("totalMs", 0)
    baseline_total_ms = p50.get("totalMs", 0)
    if baseline_total_ms > 0 and current_total_ms > baseline_total_ms * DEGRADATION_THRESHOLD:
        warnings.append(
            f"DEGRADATION: totalMs={current_total_ms} > {DEGRADATION_THRESHOLD}x baseline P50={baseline_total_ms}"
        )

    current_retry = metrics.get("retryTotal", 0)
    baseline_retry = p50.get("retryTotal", 0)
    if baseline_retry > 0 and current_retry > baseline_retry * DEGRADATION_THRESHOLD:
        warnings.append(
            f"DEGRADATION: retryTotal={current_retry} > {DEGRADATION_THRESHOLD}x baseline P50={baseline_retry}"
        )

    current_rework = metrics.get("reworkCount", 0)
    baseline_rework = p50.get("reworkCount", 0)
    if baseline_rework > 0 and current_rework > baseline_rework * DEGRADATION_THRESHOLD:
        warnings.append(
            f"DEGRADATION: reworkCount={current_rework} > {DEGRADATION_THRESHOLD}x baseline P50={baseline_rework}"
        )

    # P6-13: Token over-budget warning
    token_audit = metrics.get("tokenAudit", {})
    over_budget_roles = token_audit.get("overBudgetRoles", [])
    if over_budget_roles:
        warnings.append(
            f"TOKEN-OVERBUDGET: {len(over_budget_roles)} role(s) exceeded token budget: {over_budget_roles}"
        )
    utilization = token_audit.get("utilizationPct", 0)
    if utilization > 120:
        warnings.append(
            f"TOKEN-OVERBUDGET: overall utilization {utilization}% exceeds 120% threshold"
        )

    return warnings


def detect_systemic_issues(baseline: dict) -> list[dict]:
    """P8-12: Identify systemic issues across multiple deliveries.

    Analyzes the baseline history to find recurring patterns that indicate
    structural problems rather than one-off failures.
    """
    deliveries = baseline.get("deliveries", [])
    if len(deliveries) < 3:
        return []  # Need at least 3 data points

    issues: list[dict] = []

    # 1. Persistent retry escalation: retries trending upward
    recent = deliveries[-5:]
    retries = [d.get("retryTotal", 0) for d in recent]
    if len(retries) >= 3 and all(retries[i] <= retries[i + 1] for i in range(len(retries) - 1)) and retries[-1] > retries[0] > 0:
        issues.append({
            "type": "retry-escalation",
            "severity": "high",
            "summary": f"Retry count trending up: {retries[0]} → {retries[-1]} over last {len(retries)} deliveries",
            "recommendation": "Investigate root causes of retries; may indicate degrading prompt quality or environment instability",
        })

    # 2. Chronic rework: rework count > 0 in > 60% of deliveries
    rework_counts = [d.get("reworkCount", 0) for d in deliveries]
    rework_rate = sum(1 for r in rework_counts if r > 0) / len(rework_counts)
    if rework_rate > 0.6 and len(deliveries) >= 3:
        issues.append({
            "type": "chronic-rework",
            "severity": "medium",
            "summary": f"Rework in {rework_rate:.0%} of deliveries ({sum(1 for r in rework_counts if r > 0)}/{len(rework_counts)})",
            "recommendation": "Review quality gate thresholds or add pre-validation checks",
        })

    # 3. Duration inflation: P95 > 2x P50 (high variance)
    p50 = baseline.get("p50", {})
    p95 = baseline.get("p95", {})
    p50_ms = p50.get("totalMs", 0)
    p95_ms = p95.get("totalMs", 0)
    if p50_ms > 0 and p95_ms > p50_ms * 2:
        issues.append({
            "type": "duration-variance",
            "severity": "medium",
            "summary": f"P95 ({p95_ms}ms) > 2x P50 ({p50_ms}ms) — high delivery time variance",
            "recommendation": "Investigate outlier deliveries; consider timeout tuning",
        })

    # 4. Consistent token over-budget
    recent_metrics = deliveries[-3:]
    over_budget_streak = sum(1 for d in recent_metrics if d.get("tokenUtilizationPct", 0) > 100)
    if over_budget_streak >= 2:
        issues.append({
            "type": "token-budget-chronic",
            "severity": "high",
            "summary": f"Token over-budget in {over_budget_streak}/{len(recent_metrics)} recent deliveries",
            "recommendation": "Increase role token budgets or compress handoff payloads",
        })

    # 5. Stagnant pattern: identical metrics = no progress
    role_run_counts = [d.get("roleRunCount", 0) for d in recent]
    if len(set(retries)) == 1 and retries[0] > 0 and len(set(role_run_counts)) == 1:
        issues.append({
            "type": "stagnant-pattern",
            "severity": "low",
            "summary": "Identical metrics across recent deliveries suggest retry without progress",
            "recommendation": "Check if retries address the root cause or just repeat the same operation",
        })

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Ledger JSON files or directories")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--baseline", help="Path to baseline file (default: <first-ledger-dir>/metrics-baseline.json)")
    parser.add_argument("--no-baseline", action="store_true", help="Skip baseline update and comparison")
    args = parser.parse_args()

    ledgers = load_ledgers([Path(path).resolve() for path in args.paths])
    metrics = summarize(ledgers)
    metrics["_reportedAt"] = datetime.now(timezone.utc).isoformat()

    # Baseline handling
    degradation_warnings: list[str] = []
    baseline_data: dict = {}
    is_bootstrap = False
    if not args.no_baseline:
        if args.baseline:
            baseline_path = Path(args.baseline).resolve()
        else:
            first_path = Path(args.paths[0]).resolve()
            baseline_path = (first_path.parent if first_path.is_file() else first_path) / DEFAULT_BASELINE_FILENAME
        is_bootstrap = not baseline_path.exists()
        baseline_data = update_baseline(baseline_path, metrics)
        degradation_warnings = detect_degradation(metrics, baseline_data)
        metrics["baseline"] = {
            "path": str(baseline_path),
            "historyCount": len(baseline_data.get("deliveries", [])),
            "p50": baseline_data.get("p50", {}),
            "p95": baseline_data.get("p95", {}),
            "bootstrapped": is_bootstrap,
        }
        if degradation_warnings:
            metrics["degradationWarnings"] = degradation_warnings

        # P8-12: Cross-delivery systemic issue detection.
        systemic_issues = detect_systemic_issues(baseline_data)
        if systemic_issues:
            metrics["systemicIssues"] = systemic_issues

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print("Harness metrics")
        for key, value in metrics.items():
            if key in ("baseline", "degradationWarnings"):
                continue
            print(f"{key}: {value}")
        if degradation_warnings:
            print("\n\u26a0\ufe0f  DEGRADATION WARNINGS:")
            for w in degradation_warnings:
                print(f"  \u2192 {w}")
        if is_bootstrap:
            print("\n\u2139\ufe0f  BASELINE BOOTSTRAPPED: First delivery recorded.")
            print("   Degradation detection requires >=3 historical entries.")
        if baseline_data:
            print(f"\nBaseline: {len(baseline_data.get('deliveries', []))} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
