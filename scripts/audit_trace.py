#!/usr/bin/env python3
"""Auto-generate a workflow audit report from the evidence ledger.

Reads the evidence ledger, compares expected vs actual roles and artifacts,
and outputs a structured audit markdown to docs/19-监督审计.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Expected roles per workflow domain ──────────────────────────────────
# These define which roles are mandatory for each workflow domain.
# Format: role_id -> role display name
BASE_ROLES: dict[str, str] = {
    "product-analyst": "Product Analyst",
    "architect": "Architect",
    "execution-engineer": "Execution Engineer",
    "quality-gate-engineer": "Quality Gate Engineer",
    "browser-e2e-engineer": "Browser E2E Engineer",
    "devops-release-engineer": "DevOps Release Engineer",
    "documentation-writer": "Documentation Writer",
    "supervisor-auditor": "Supervisor Auditor",
}

CONDITIONAL_ROLES: dict[str, str] = {
    "data-engineer": "Data Engineer",
    "frontend-engineer": "Frontend Engineer",
    "backend-engineer": "Backend Engineer",
    "performance-engineer": "Performance Engineer",
    "data-contract-designer": "Data Contract Designer",
    "design-ui-designer": "UI Designer",
}

# ── Expected artifacts per role ─────────────────────────────────────────
ROLE_ARTIFACTS: dict[str, list[str]] = {
    "product-analyst": ["docs/01-需求规格书.md"],
    "architect": ["docs/02-开发计划.md", "docs/03-任务清单.md", "docs/04-详细设计说明书.md"],
    "data-engineer": ["docs/05-数据设计说明书.md"],
    "data-contract-designer": ["docs/07-接口数据契约.md"],
    "performance-engineer": ["docs/06-性能优化说明.md"],
    "design-ui-designer": ["docs/08-UI设计说明.md"],
    "quality-gate-engineer": [
        "docs/10-单元测试用例.md",
        "docs/11-单元测试报告.md",
        "docs/12-集成测试用例.md",
        "docs/13-集成测试报告.md",
        "docs/14-代码评审.md",
    ],
    "browser-e2e-engineer": [
        "docs/16-E2E测试用例.md",
        "docs/17-E2E测试报告.md",
    ],
    "devops-release-engineer": ["docs/18-部署说明.md"],
    "supervisor-auditor": ["docs/19-监督审计.md"],
}

# Additional artifacts when security-sensitive scope
SECURITY_ARTIFACTS: list[str] = [
    "docs/15-安全评审.md",
]

# E2E artifacts — MANDATORY for every delivery (no opt-out). Always included via
# BASE_ROLES['browser-e2e-engineer']. FRONTEND_ARTIFACTS kept for backward compat
# but no longer adds anything beyond what is already required.
FRONTEND_ARTIFACTS: list[str] = [
    "docs/16-E2E测试用例.md",
    "docs/17-E2E测试报告.md",
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_expected_roles(ledger: dict) -> dict[str, str]:
    """Determine expected roles from the ledger's workflow domains and roles actually invoked."""
    expected = dict(BASE_ROLES)

    # Check if any invoked role implies conditional roles are needed
    invoked_ids = {rr.get("roleId", "") for rr in ledger.get("roleRuns", [])}
    artifacts = set(ledger.get("artifacts", []))

    if "frontend-engineer" in invoked_ids or "design-ui-designer" in invoked_ids:
        expected["frontend-engineer"] = "Frontend Engineer"
        expected["design-ui-designer"] = "UI Designer"

    if "backend-engineer" in invoked_ids:
        expected["backend-engineer"] = "Backend Engineer"

    if any(
        a.startswith("docs/数据设计") or a.startswith("docs/数据库")
        for a in artifacts
    ):
        expected["data-engineer"] = "Data Engineer"

    if any("接口" in a or "契约" in a or "contract" in a.lower() for a in artifacts):
        expected["data-contract-designer"] = "Data Contract Designer"

    if any("性能" in a or "performance" in a.lower() for a in artifacts):
        expected["performance-engineer"] = "Performance Engineer"

    return expected


def get_expected_artifacts(expected_roles: dict[str, str], ledger: dict) -> list[str]:
    """Compute the full set of expected artifacts."""
    expected_artifacts: list[str] = []
    for role_id in expected_roles:
        expected_artifacts.extend(ROLE_ARTIFACTS.get(role_id, []))

    # Check if security scope
    gates = ledger.get("qualityGates", [])
    has_security = any(
        g.get("gateType") == "security-review" for g in gates
    )
    if has_security:
        expected_artifacts.extend(SECURITY_ARTIFACTS)

    # E2E artifacts are MANDATORY for every delivery (added via
    # ROLE_ARTIFACTS['browser-e2e-engineer']); historical FRONTEND_ARTIFACTS branch
    # is preserved for backward-compat but is now a no-op since they are already
    # included unconditionally.
    invoked_ids = {rr.get("roleId", "") for rr in ledger.get("roleRuns", [])}
    if "frontend-engineer" in invoked_ids:
        for art in FRONTEND_ARTIFACTS:
            if art not in expected_artifacts:
                expected_artifacts.append(art)

    return expected_artifacts


def build_audit(ledger: dict, expected_roles: dict[str, str]) -> dict:
    """Build the audit comparison structure."""
    invoked_roles: list[dict] = []
    for rr in ledger.get("roleRuns", []):
        invoked_roles.append({
            "roleId": rr.get("roleId", "unknown"),
            "status": rr.get("status", "?"),
            "durationMs": rr.get("durationMs", 0),
            "sessionMode": rr.get("sessionMode", "?"),
            "retryCount": rr.get("retryCount", 0),
        })

    invoked_ids = {r["roleId"] for r in invoked_roles}
    expected_ids = set(expected_roles.keys())

    missing_roles = expected_ids - invoked_ids
    extra_roles = invoked_ids - expected_ids

    # Artifact audit
    expected_artifacts = get_expected_artifacts(expected_roles, ledger)
    present_artifacts = set(ledger.get("artifacts", []))
    missing_artifacts = [a for a in expected_artifacts if a not in present_artifacts]

    # Flow audit
    role_order = list(expected_roles.keys())
    invoked_order = [r["roleId"] for r in invoked_roles if r["roleId"] in expected_ids]
    order_violations = []
    last_idx = -1
    for rid in invoked_order:
        try:
            idx = role_order.index(rid)
        except ValueError:
            continue
        if idx < last_idx:
            order_violations.append(f"{rid} 在预期顺序之前被调用")
        last_idx = max(last_idx, idx)

    # Fallback violations
    fallback_roles = [r for r in invoked_roles if r.get("sessionMode") == "single-session-fallback"]

    # Retry analysis
    retried_roles = [r for r in invoked_roles if r.get("retryCount", 0) > 0]

    # Quality gate summary
    gates = ledger.get("qualityGates", [])
    failed_gates = [g for g in gates if g.get("status") not in ("pass", "not-run")]

    return {
        "taskName": ledger.get("taskName", "Unnamed"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "expectedRoles": {k: v for k, v in expected_roles.items()},
        "invokedRoles": invoked_roles,
        "missingRoles": sorted(missing_roles),
        "extraRoles": sorted(extra_roles),
        "expectedArtifacts": expected_artifacts,
        "presentArtifacts": sorted(present_artifacts),
        "missingArtifacts": missing_artifacts,
        "orderViolations": order_violations,
        "fallbackRoles": fallback_roles,
        "retriedRoles": retried_roles,
        "failedGates": failed_gates,
        "totalWallTimeMs": ledger.get("observability", {}).get("totalWallTimeMs", 0),
        "changeCount": len(ledger.get("changeHistory", [])),
        "decisionCount": len(ledger.get("decisionLog", [])),
        "eventLogCount": len(ledger.get("eventLog", [])),
        "traceabilityCount": len(ledger.get("traceabilityMatrix", [])),
    }


def format_ms(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60_000:
        return f"{ms / 1000:.1f}s"
    else:
        return f"{ms / 60_000:.1f}min"


def render_markdown(audit: dict) -> str:
    lines = []
    lines.append("# 监督审计\n")
    lines.append(f"**任务名称**：{audit['taskName']}")
    lines.append(f"**审计生成时间**：{audit['generatedAt']}")
    lines.append(f"**总耗时**：{format_ms(audit['totalWallTimeMs'])}\n")

    # ── 1. 审计对象 ──
    lines.append("## 1. 审计对象\n")
    lines.append(f"- 任务名称：{audit['taskName']}")
    lines.append(f"- 变更请求数：{audit['changeCount']}")
    lines.append(f"- 架构决策数：{audit['decisionCount']}")
    lines.append(f"- 事件日志条目数：{audit['eventLogCount']}")
    lines.append(f"- 需求追溯链条目：{audit['traceabilityCount']}\n")

    # ── 2. 角色调用审计 ──
    lines.append("## 2. 角色调用审计\n")
    lines.append(f"- 应调用角色：{len(audit['expectedRoles'])} 个")
    for rid, rname in audit["expectedRoles"].items():
        lines.append(f"  - {rid} ({rname})")
    lines.append(f"\n- 已调用角色：{len(audit['invokedRoles'])} 个")
    for r in audit["invokedRoles"]:
        flags = []
        if r.get("sessionMode") == "single-session-fallback":
            flags.append("⚠️ fallback")
        if r.get("retryCount", 0) > 0:
            flags.append(f"🔄 重试{r['retryCount']}次")
        flag_str = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"  - {r['roleId']} [{r['status']}]{flag_str} ({format_ms(r['durationMs'])})")

    if audit["missingRoles"]:
        lines.append(f"\n- ⚠️ 缺失角色：{len(audit['missingRoles'])} 个")
        for rid in audit["missingRoles"]:
            lines.append(f"  - {rid} ({audit['expectedRoles'].get(rid, '?')})")
    else:
        lines.append("\n- ✅ 无缺失角色")

    if audit["extraRoles"]:
        lines.append(f"\n- 额外角色（未在预期中）：{len(audit['extraRoles'])} 个")
        for rid in audit["extraRoles"]:
            lines.append(f"  - {rid}")
    else:
        lines.append("- ✅ 无越权角色")

    # ── 3. 文档审计 ──
    lines.append("\n## 3. 文档审计\n")
    lines.append(f"- 应产出文档：{len(audit['expectedArtifacts'])} 个")
    for a in audit["expectedArtifacts"]:
        present = "✅" if a in audit["presentArtifacts"] else "❌ 缺失"
        lines.append(f"  - {present}: {a}")
    if audit["missingArtifacts"]:
        lines.append(f"\n- ⚠️ 缺失文档数：{len(audit['missingArtifacts'])}")
    else:
        lines.append("\n- ✅ 文档顺序是否合理：是")

    # ── 4. 流程审计 ──
    lines.append("\n## 4. 流程审计\n")
    lines.append(f"- 需求澄清是否完成：{'✅' if 'product-analyst' in {r['roleId'] for r in audit['invokedRoles']} else '⚠️ 未检测到'}")
    lines.append(f"- 规划是否完成：{'✅' if 'architect' in {r['roleId'] for r in audit['invokedRoles']} else '⚠️ 未检测到'}")
    lines.append(f"- 验证是否完成：{'✅' if 'quality-gate-engineer' in {r['roleId'] for r in audit['invokedRoles']} else '⚠️ 未检测到'}")

    if audit["orderViolations"]:
        lines.append("- ⚠️ 存在跳步：")
        for v in audit["orderViolations"]:
            lines.append(f"  - {v}")
    else:
        lines.append("- ✅ 不存在跳步")

    # ── 5. 专项流程审计 ──
    lines.append("\n## 5. 专项流程审计\n")
    lines.append(f"- 需求变更流程是否完整：{'✅' if audit['changeCount'] == 0 else '📋 有变更记录，请人工核查变更管理流程是否完整'}")
    if audit["failedGates"]:
        lines.append("- ⚠️ 质量门禁失败：")
        for g in audit["failedGates"]:
            lines.append(f"  - {g.get('gateName', '?')} [{g.get('status', '?')}]")
    else:
        lines.append("- ✅ 质量门禁全部通过或未运行")

    # ── 6. 规范符合性 ──
    lines.append("\n## 6. 规范符合性\n")
    if audit["fallbackRoles"]:
        lines.append(f"- ⚠️ 单 Session 回退：{len(audit['fallbackRoles'])} 个角色使用了 fallback 模式")
        for r in audit["fallbackRoles"]:
            lines.append(f"  - {r['roleId']}")
    else:
        lines.append("- ✅ 无单 Session 回退")
    lines.append(f"- 重试角色数：{len(audit['retriedRoles'])}")
    if audit["retriedRoles"]:
        for r in audit["retriedRoles"]:
            lines.append(f"  - {r['roleId']}（重试 {r['retryCount']} 次）")

    # ── 7. 审计结论 ──
    lines.append("\n## 7. 审计结论\n")
    deviations = []
    if audit["missingRoles"]:
        deviations.append(f"缺失角色: {', '.join(audit['missingRoles'])}")
    if audit["missingArtifacts"]:
        deviations.append(f"缺失文档: {', '.join(audit['missingArtifacts'])}")
    if audit["orderViolations"]:
        deviations.append(f"顺序违规: {'; '.join(audit['orderViolations'])}")
    if audit["fallbackRoles"]:
        deviations.append("存在单 Session 回退（标记为流程偏差）")

    if deviations:
        lines.append("- 主要偏差：")
        for d in deviations:
            lines.append(f"  - {d}")
        lines.append("- 是否允许进入下一阶段：⚠️ 需人工决策")
        lines.append("- 是否允许宣称完成：⚠️ 需人工决策")
    else:
        lines.append("- 主要偏差：无")
        lines.append("- 是否允许进入下一阶段：✅ 是")
        lines.append("- 是否允许宣称完成：✅ 是（建议人工最终确认）")

    lines.append("\n- 后续建议：")
    lines.append("  - 请人工复核上述自动审计结果")
    lines.append("  - 确认所有偏差均已合理处理或记录")
    if audit["changeCount"] > 0:
        lines.append("  - 核查变更管理流程中所有变更是否均已关闭")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="Evidence ledger JSON path")
    parser.add_argument("--output", default=None, help="Output audit markdown path (default: docs/19-监督审计.md)")
    parser.add_argument("--json", action="store_true", help="Emit JSON audit data only")
    args = parser.parse_args()

    ledger_path = Path(args.ledger).resolve()
    if not ledger_path.exists():
        print(f"Ledger not found: {ledger_path}", file=sys.stderr)
        return 1

    ledger = load_json(ledger_path)
    expected_roles = get_expected_roles(ledger)
    audit = build_audit(ledger, expected_roles)

    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0

    md = render_markdown(audit)

    if args.output:
        out_path = Path(args.output).resolve()
    else:
        out_path = ledger_path.parent / "19-监督审计.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Audit report written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
