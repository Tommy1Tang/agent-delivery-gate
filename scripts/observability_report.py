#!/usr/bin/env python3
"""Generate an observability report from evidence ledgers.

Produces docs/20-可观测性报告.md in the project root.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_ledger(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def format_ms(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60_000:
        return f"{ms / 1000:.1f}s"
    else:
        return f"{ms / 60_000:.1f}min"


def compute_metrics(ledger: dict) -> dict:
    role_runs = ledger.get("roleRuns", [])
    obs = ledger.get("observability", {})
    gates = ledger.get("qualityGates", [])

    # 1. 每个 role 耗时
    role_timing: dict[str, dict] = {}
    total_ms = 0
    for rr in role_runs:
        rid = rr.get("roleId", "unknown")
        duration = rr.get("durationMs", 0)
        total_ms += duration
        if rid not in role_timing:
            role_timing[rid] = {"durationMs": 0, "count": 0}
        role_timing[rid]["durationMs"] += duration
        role_timing[rid]["count"] += 1

    for rid, data in role_timing.items():
        data["avgMs"] = data["durationMs"] // data["count"] if data["count"] else 0

    # 2. 重试次数
    retry_total = sum(rr.get("retryCount", 0) for rr in role_runs)

    # 3. 阻塞原因
    blocking = []
    for rr in role_runs:
        for reason in rr.get("blockedBy", []):
            blocking.append({"roleId": rr.get("roleId", "unknown"), "reason": reason})

    # 4. 文档缺失率 — from quality gates with gateType=document-check
    doc_expected = 0
    doc_present = 0
    doc_missing = []
    for gate in gates:
        gate_type = gate.get("gateType", "other")
        if gate_type == "document-check":
            for check in gate.get("checks", []):
                name = check.get("name", "")
                doc_expected += 1
                if check.get("status") == "pass":
                    doc_present += 1
                else:
                    doc_missing.append(name)
    doc_rate = 1.0 - (doc_present / doc_expected) if doc_expected else 0.0

    # 5. 测试通过率 — parse test quality gates by gateType
    TEST_GATE_TYPES = {"unit-test", "integration-test", "e2e-test", "performance-test"}
    test_total = 0
    test_pass = 0
    test_fail = 0
    test_blocked = 0
    test_skip = 0
    test_by_type: dict[str, dict] = {}
    for gate in gates:
        gate_type = gate.get("gateType", "other")
        if gate_type in TEST_GATE_TYPES:
            gate_total = 0
            gate_pass = 0
            gate_fail = 0
            for check in gate.get("checks", []):
                status = check.get("status", "")
                test_total += 1
                gate_total += 1
                if status == "pass":
                    test_pass += 1
                    gate_pass += 1
                elif status == "fail":
                    test_fail += 1
                    gate_fail += 1
                elif status == "blocked":
                    test_blocked += 1
                elif status in ("not-run", "skip"):
                    test_skip += 1
            test_by_type[gate_type] = {
                "total": gate_total,
                "pass": gate_pass,
                "fail": gate_fail,
                "passRate": round(gate_pass / gate_total, 3) if gate_total else 0.0,
            }
    test_rate = test_pass / test_total if test_total else 0.0

    # 6. 安全阻断次数
    sec_count = obs.get("securityBlockCount", 0)
    sec_details = obs.get("securityBlockDetails", [])

    # 7. fallback 次数
    fallback_count = sum(
        1 for rr in role_runs if rr.get("sessionMode") == "single-session-fallback"
    )

    # 8. 用户返工次数
    rework_count = obs.get("reworkCount", 0)
    rework_reasons = obs.get("reworkReasons", [])

    # 9. 变更追溯 (P1)
    change_history = ledger.get("changeHistory", [])
    change_count = len(change_history)
    open_changes = [c for c in change_history if c.get("status") not in ("applied", "verified")]

    # 10. 决策追溯 (P2)
    decision_log = ledger.get("decisionLog", [])
    decision_count = len(decision_log)

    # 11. 资源消耗 (P2)
    resource = ledger.get("resourceConsumption", {})

    # 12. 事件日志统计 (P0)
    event_log = ledger.get("eventLog", [])
    event_by_type: dict[str, int] = {}
    for evt in event_log:
        et = evt.get("eventType", "unknown")
        event_by_type[et] = event_by_type.get(et, 0) + 1

    return {
        "taskName": ledger.get("taskName", "Unnamed"),
        "createdAt": ledger.get("createdAt", ""),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalWallTimeMs": total_ms,
        "roleTiming": role_timing,
        "retryTotal": retry_total,
        "blockingReasons": blocking,
        "documentMissingRate": round(doc_rate, 3),
        "documentDetails": {
            "expected": doc_expected,
            "present": doc_present,
            "missing": doc_missing,
        },
        "testPassRate": round(test_rate, 3),
        "testDetails": {
            "total": test_total,
            "pass": test_pass,
            "fail": test_fail,
            "blocked": test_blocked,
            "skip": test_skip,
        },
        "testByType": test_by_type,
        "securityBlockCount": sec_count,
        "securityBlockDetails": sec_details,
        "fallbackCount": fallback_count,
        "reworkCount": rework_count,
        "reworkReasons": rework_reasons,
        "roleRunCount": len(role_runs),
        "changeCount": change_count,
        "openChangeCount": len(open_changes),
        "openChanges": open_changes,
        "decisionCount": decision_count,
        "resourceConsumption": resource,
        "eventLogCount": len(event_log),
        "eventByType": event_by_type,
        "traceabilityCount": len(ledger.get("traceabilityMatrix", [])),
    }


def render_markdown(metrics: dict) -> str:
    lines = []
    lines.append("# 可观测性报告\n")
    lines.append(f"**任务**：{metrics['taskName']}")
    lines.append(f"**生成时间**：{metrics['generatedAt']}")
    lines.append(f"**总耗时**：{format_ms(metrics['totalWallTimeMs'])}\n")

    # Summary table
    lines.append("## 指标汇总\n")
    lines.append("| 指标 | 值 | 状态 |")
    lines.append("| --- | --- | --- |")

    def health(value: float, threshold: float, lower_is_better: bool = False) -> str:
        if lower_is_better:
            return "🟢" if value <= threshold else "🔴"
        return "🟢" if value >= threshold else "🔴"

    lines.append(f"| 总耗时 | {format_ms(metrics['totalWallTimeMs'])} | — |")
    lines.append(f"| 角色执行次数 | {metrics['roleRunCount']} | — |")
    lines.append(f"| Fallback 次数 | {metrics['fallbackCount']} | {health(metrics['fallbackCount'], 0, True)} |")
    lines.append(f"| 重试总次数 | {metrics['retryTotal']} | {health(metrics['retryTotal'], 0, True)} |")
    lines.append(f"| 文档缺失率 | {metrics['documentMissingRate']:.1%} | {health(1 - metrics['documentMissingRate'], 1.0)} |")
    lines.append(f"| 测试通过率 | {metrics['testPassRate']:.1%} | {health(metrics['testPassRate'], 1.0)} |")
    lines.append(f"| 安全阻断次数 | {metrics['securityBlockCount']} | {health(metrics['securityBlockCount'], 0, True)} |")
    lines.append(f"| 用户返工次数 | {metrics['reworkCount']} | {health(metrics['reworkCount'], 0, True)} |")
    lines.append(f"| 需求追溯链条目数 | {metrics['traceabilityCount']} | — |")
    lines.append(f"| 变更请求数 | {metrics['changeCount']} | {health(metrics['openChangeCount'], 0, True)} |")
    lines.append(f"| 架构决策记录数 | {metrics['decisionCount']} | — |")
    lines.append(f"| 事件日志条目数 | {metrics['eventLogCount']} | — |")

    # Resource consumption (P2)
    res = metrics.get("resourceConsumption", {})
    if res:
        lines.append(f"| Token 消耗估算 | {res.get('totalTokensUsed', 0):,} | — |")
        if res.get("costEstimate"):
            lines.append(f"| 成本估算 (USD) | ${res['costEstimate']:.4f} | — |")

    # Role timing detail
    lines.append("\n## 各角色耗时\n")
    timing = metrics["roleTiming"]
    if timing:
        lines.append("| 角色 | 总耗时 | 执行次数 | 平均耗时 |")
        lines.append("| --- | --- | --- | --- |")
        for rid in sorted(timing.keys()):
            t = timing[rid]
            lines.append(f"| {rid} | {format_ms(t['durationMs'])} | {t['count']} | {format_ms(t['avgMs'])} |")
    else:
        lines.append("_无耗时数据_")

    # Blocking reasons
    lines.append("\n## 阻塞原因\n")
    blocking = metrics["blockingReasons"]
    if blocking:
        lines.append("| 角色 | 原因 |")
        lines.append("| --- | --- |")
        for b in blocking:
            lines.append(f"| {b['roleId']} | {b['reason']} |")
    else:
        lines.append("_无阻塞记录_")

    # Test details
    lines.append("\n## 测试详情\n")
    td = metrics["testDetails"]
    lines.append(f"- 总计：{td['total']}")
    lines.append(f"- 通过：{td['pass']}")
    lines.append(f"- 失败：{td['fail']}")
    lines.append(f"- 阻断：{td['blocked']}")
    lines.append(f"- 跳过：{td['skip']}")
    lines.append(f"- 通过率：{metrics['testPassRate']:.1%}")

    # Test by type breakdown (P1)
    tbt = metrics.get("testByType", {})
    if tbt:
        lines.append("\n### 按测试类型\n")
        lines.append("| 类型 | 总计 | 通过 | 失败 | 通过率 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for tt_name in sorted(tbt.keys()):
            tt = tbt[tt_name]
            lines.append(f"| {tt_name} | {tt['total']} | {tt['pass']} | {tt['fail']} | {tt['passRate']:.1%} |")

    # Event log summary (P0)
    ebt = metrics.get("eventByType", {})
    if ebt:
        lines.append("\n## 事件日志汇总\n")
        lines.append("| 事件类型 | 数量 |")
        lines.append("| --- | --- |")
        for et_name in sorted(ebt.keys()):
            lines.append(f"| {et_name} | {ebt[et_name]} |")

    # Change history (P1)
    if metrics.get("changeCount"):
        lines.append("\n## 变更追溯\n")
        lines.append(f"- 变更总数：{metrics['changeCount']}")
        lines.append(f"- 未关闭变更数：{metrics['openChangeCount']}")
        for chg in metrics.get("openChanges", [])[:10]:
            lines.append(f"  - [{chg.get('status', '?')}] {chg.get('changeId', '?')}: {chg.get('description', 'N/A')[:80]}")

    # Decision log (P2)
    if metrics.get("decisionCount"):
        lines.append(f"\n## 架构决策\n")
        lines.append(f"- 决策总数：{metrics['decisionCount']}")

    # Traceability (P0)
    if metrics.get("traceabilityCount"):
        lines.append(f"\n## 需求追溯\n")
        lines.append(f"- 追溯链条目：{metrics['traceabilityCount']}")

    # Document details
    lines.append("\n## 文档详情\n")
    dd = metrics["documentDetails"]
    lines.append(f"- 期望文档数：{dd['expected']}")
    lines.append(f"- 已交付：{dd['present']}")
    lines.append(f"- 缺失率：{metrics['documentMissingRate']:.1%}")
    if dd["missing"]:
        lines.append("- 缺失文档：")
        for doc in dd["missing"]:
            lines.append(f"  - {doc}")

    # Security blocks
    lines.append("\n## 安全阻断\n")
    if metrics["securityBlockCount"]:
        for detail in metrics["securityBlockDetails"]:
            lines.append(f"- {detail}")
    else:
        lines.append("_无安全阻断_")

    # Rework
    lines.append("\n## 用户返工\n")
    if metrics["reworkCount"]:
        for reason in metrics["reworkReasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("_无返工记录_")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="Evidence ledger JSON path")
    parser.add_argument("--output", default=None, help="Output markdown path (default: docs/20-可观测性报告.md in project root)")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    ledger_path = Path(args.ledger).resolve()
    if not ledger_path.exists():
        print(f"Ledger not found: {ledger_path}", file=sys.stderr)
        return 1

    ledger = load_ledger(ledger_path)
    metrics = compute_metrics(ledger)

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0

    md = render_markdown(metrics)

    if args.output:
        out_path = Path(args.output).resolve()
    else:
        # Default: output to project root docs/
        out_path = ledger_path.parent / "20-可观测性报告.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Observability report written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
