#!/usr/bin/env python3
"""Build a product-grade orchestration plan for software-development-team."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from detect_stack import detect_stack  # type: ignore
except Exception:  # pragma: no cover - fallback when invoked from outside scripts/
    import importlib.util

    _ds_spec = importlib.util.spec_from_file_location(
        "detect_stack", Path(__file__).resolve().parent / "detect_stack.py"
    )
    if _ds_spec and _ds_spec.loader:
        _ds_module = importlib.util.module_from_spec(_ds_spec)
        _ds_spec.loader.exec_module(_ds_module)  # type: ignore[union-attr]
        detect_stack = _ds_module.detect_stack  # type: ignore[assignment]
    else:
        detect_stack = None  # type: ignore[assignment]

try:
    from memory_store import load_project_memory  # type: ignore
except ImportError:
    load_project_memory = None  # type: ignore[assignment]

try:
    from memory_integration import generate_pre_delivery_queries  # type: ignore
except ImportError:
    generate_pre_delivery_queries = None  # type: ignore[assignment]

try:
    from delivery_checkpoint import (  # type: ignore
        can_resume, load_last_plan, compute_plan_delta,
        enrich_plan_with_delta, save_last_plan,
    )
except ImportError:
    can_resume = None  # type: ignore[assignment]
    load_last_plan = None  # type: ignore[assignment]
    compute_plan_delta = None  # type: ignore[assignment]
    enrich_plan_with_delta = None  # type: ignore[assignment]
    save_last_plan = None  # type: ignore[assignment]

try:
    from design_system_loader import detect_design_system, build_handoff_binding  # type: ignore
except ImportError:
    detect_design_system = None  # type: ignore[assignment]
    build_handoff_binding = None  # type: ignore[assignment]


WORKFLOW_KEYWORDS = {
    "change-management": ["变更", "change", "baseline", "重基线", "scope change", "调整范围", "重构", "refactor"],
    "security-governance": [
        "安全", "security", "auth", "permission", "权限", "漏洞", "密钥", "token",
        "加密", "encrypt", "csrf", "xss", "sql注入", "注入", "sso", "oauth", "jwt",
        "身份认证", "鉴权", "脱敏", "会话劫持", "越权",
    ],
    "incident-management": [
        "事故", "incident", "紧急", "故障", "bug", "线上", "回滚", "修复",
        "crash", "崩溃", "宕机", "异常", "down", "报错", "500", "错误",
        "emergency", "失败", "不可用", "hotfix",
    ],
}

UI_KEYWORDS = [
    "ui", "ux", "界面", "页面", "视觉", "组件", "响应式", "element plus",
    "前端", "前后端", "frontend", "front-end", "view", "列表页", "详情页",
    "表单", "布局", "layout", "css", "html", "vue", "react", "交互", "点击",
]


def load_config(skill_root: Path) -> dict:
    return json.loads((skill_root / "assets" / "config" / "agent-team-config.json").read_text(encoding="utf-8"))


def classify_domains(task_summary: str, explicit_domains: list[str]) -> list[str]:
    domains = set(explicit_domains or [])
    text = task_summary.lower()
    for domain, keywords in WORKFLOW_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            domains.add(domain)
    if not domains:
        domains.add("forward-development")
    return sorted(domains)


def is_ui_affected(task_summary: str) -> bool:
    text = task_summary.lower()
    return any(keyword.lower() in text for keyword in UI_KEYWORDS)


def is_security_sensitive(domains: list[str], task_summary: str) -> bool:
    if "security-governance" in domains:
        return True
    text = task_summary.lower()
    return any(keyword.lower() in text for keyword in WORKFLOW_KEYWORDS["security-governance"])


def determine_conditional_roles(task_summary: str, stack_snapshot: dict, domains: list[str]) -> dict[str, bool]:
    """P3-6: Programmatically determine which conditional roles should be included.

    Returns a dict of {roleId: should_include} for conditional roles only.
    """
    flags: dict[str, bool] = {}
    text = task_summary.lower()

    # data-engineer: triggered by DB/migration/data-model signals
    data_keywords = [
        "数据库", "迁移", "表结构", "schema", "migration", "数据模型",
        "redis", "elasticsearch", "mongo", "索引", "分库分表", "database",
        "mysql", "postgresql", "sqlite", "持久化", "orm", "mybatis", "jpa",
    ]
    has_db = bool(stack_snapshot.get("migrationDirs"))
    has_db_infra = bool((stack_snapshot.get("infrastructure") or {}).get("database"))
    has_db_keywords = any(kw in text for kw in data_keywords)
    flags["data-engineer"] = has_db or has_db_infra or has_db_keywords

    # performance-engineer: triggered by SLA/perf/concurrency signals
    perf_keywords = [
        "性能", "sla", "并发", "吐将量", "响应时间", "缓存",
        "performance", "latency", "throughput", "流量", "压测", "load",
        "优化", "benchmark", "qps", "tps", "耗时",
    ]
    flags["performance-engineer"] = any(kw in text for kw in perf_keywords)

    # ui-designer: triggered by UI/visual/frontend signals
    flags["ui-designer"] = is_ui_affected(task_summary)

    return flags


ROLE_TIMEOUTS = {
    "product-analyst": 300000,
    "architect": 600000,
    "data-engineer": 600000,
    "performance-engineer": 600000,
    "data-contract-designer": 300000,
    "ui-designer": 600000,
    "execution-engineer": 600000,
    "frontend-engineer": 900000,
    "backend-engineer": 900000,
    "quality-gate-engineer": 900000,
    "browser-e2e-engineer": 1800000,
    "devops-release-engineer": 300000,
    "documentation-writer": 300000,
    "supervisor-auditor": 300000,
}

IMPLICIT_GOVERNANCE_FILES = [
    "assets/constitution.md",
    "assets/tech.md",
    "assets/design.md",
    "references/local-governance.md",
    "references/team-overview.md",
    "references/team-workflow.md",
]

# Roles that need workflowDomains in their Handoff
WORKFLOW_DOMAIN_ROLES = {
    "product-analyst",
    "architect",
    "quality-gate-engineer",
    "supervisor-auditor",
}

# Role-specific extra governance files (beyond implicit defaults)
ROLE_EXTRA_GOVERNANCE = {
    "product-analyst": ["references/workflow-matrix.md"],
    "architect": ["references/workflow-matrix.md"],
    "quality-gate-engineer": [
        "references/security-governance-workflow.md",
        "references/security-assessment-template.md",
    ],
    "browser-e2e-engineer": [
        "references/autonomous-update-policy.md",
    ],
    "supervisor-auditor": [
        "references/workflow-matrix.md",
        "references/workflow-audit-template.md",
    ],
    "devops-release-engineer": ["references/release-checklist.md"],
    "documentation-writer": ["references/export-notes.md"],
    "ui-designer": ["references/autonomous-update-policy.md", "assets/design.md"],
    "frontend-engineer": ["assets/design.md"],
}

DEFAULT_RETRY_POLICY = {
    "maxRetries": 2,
    "backoffMs": 5000,
    "retryableErrors": ["timeout", "session-lost", "transient"],
    "nonRetryableErrors": ["blocked", "security-block", "cancelled"],
}

# P3-3: Default token budgets per role category.
ROLE_TOKEN_BUDGETS = {
    "product-analyst": 8000,
    "architect": 12000,
    "data-engineer": 10000,
    "performance-engineer": 10000,
    "data-contract-designer": 8000,
    "ui-designer": 10000,
    "execution-engineer": 15000,
    "frontend-engineer": 15000,
    "backend-engineer": 15000,
    "quality-gate-engineer": 12000,
    "browser-e2e-engineer": 8000,
    "devops-release-engineer": 8000,
    "documentation-writer": 10000,
    "supervisor-auditor": 10000,
}

# P3-4: Complexity multiplier thresholds for adaptive timeout.
# Based on projectLayout from detect_stack output.
COMPLEXITY_TIERS = [
    # (max_file_count, multiplier)
    (50, 1.0),     # small project
    (150, 1.3),    # medium project
    (500, 1.7),    # large project
    (9999999, 2.2),  # very large project
]

# P7-3: Maximum items per changeSet array before truncation.
# Prevents handoff token explosion in large projects.
MAX_CHANGESET_ITEMS = 50

# P7-1: Estimated tokens per character (conservative for mixed CJK/ASCII).
# Used for context window overflow protection.
CHARS_PER_TOKEN_ESTIMATE = 2.5
# Safety threshold: compress upstreamChangeSet when estimated total exceeds this ratio of tokenBudget.
CONTEXT_PRESSURE_RATIO = 0.7

# P5-6: Files exclusively owned by each role (parallel conflict prevention).
# During parallel dispatch, Orchestrator must verify no overlap in lockedFiles.
ROLE_LOCKED_FILES = {
    "frontend-engineer": ["frontend/", "package.json", "package-lock.json", "tsconfig.json"],
    "backend-engineer": ["backend/", "pom.xml", "build.gradle", "requirements.txt"],
    "data-engineer": ["db/", "migrations/", "prisma/"],
    "ui-designer": ["docs/08-UI设计说明.md", "docs/09-UI优化说明.md"],
    "devops-release-engineer": ["Dockerfile", ".github/", "k8s/", "deploy/"],
    "documentation-writer": ["docs/README.md"],
}

# P5-1: Valid roleResult status values (from schemas/role-result.schema.json).
VALID_ROLE_RESULT_STATUSES = {
    "completed", "blocked", "failed", "skipped",
    "lost-session", "timed-out", "cancelled", "security-block",
}

ROUTE_DEPENDENCIES = {
    # Each key depends on all values (upstream roles that must complete first)
    "architect": ["product-analyst"],
    "data-engineer": ["architect"],
    "performance-engineer": ["architect"],
    "data-contract-designer": ["architect"],
    "ui-designer": ["architect"],
    "execution-engineer": ["architect", "data-contract-designer"],
    "frontend-engineer": ["execution-engineer", "ui-designer"],
    "backend-engineer": ["execution-engineer", "data-contract-designer"],
    "quality-gate-engineer": ["frontend-engineer", "backend-engineer"],
    "browser-e2e-engineer": ["quality-gate-engineer"],
    "devops-release-engineer": ["browser-e2e-engineer"],
    "documentation-writer": ["devops-release-engineer"],
    "supervisor-auditor": ["documentation-writer"],
}


def _preflight_check(task_summary: str) -> dict | None:
    """P5-2: Validate task summary quality before planning.

    Returns None if valid, or a dict with status='needs-clarification' and questions.
    """
    issues: list[str] = []

    # Check minimum length
    stripped = task_summary.strip()
    if len(stripped) < 10:
        issues.append("任务描述过短（<10字），无法确定范围")

    # Check for at least one verb-like action word
    action_words = [
        "实现", "开发", "构建", "创建", "修复", "优化", "重构", "迁移", "添加", "删除",
        "变更", "部署", "集成", "设计", "测试", "审查", "配置", "升级", "回滚",
        "新增", "修改", "补充", "统一", "处理", "构造", "引入", "移除",
        "调整", "改造", "完善", "拓展", "增强", "安装", "制作",
        "implement", "build", "create", "fix", "optimize", "refactor",
        "migrate", "add", "remove", "deploy", "integrate", "design",
    ]
    text_lower = stripped.lower()
    if not any(w in text_lower for w in action_words):
        issues.append("任务描述缺少动作动词，无法确定具体操作")

    # Check for contradictory signals
    contradictions = [
        ("新增", "删除"),
        ("从0开始", "已有"),
        ("简单", "全量"),
    ]
    for a, b in contradictions:
        if a in stripped and b in stripped:
            issues.append(f"任务描述存在矛盾信号：'{a}' 与 '{b}' 同时出现")

    if issues:
        return {
            "status": "needs-clarification",
            "preflightIssues": issues,
            "questions": ["请提供更具体的任务描述（至少 10 字，包含明确动作）"],
        }
    return None


def validate_role_result(role_result: dict, role_id: str) -> list[str]:
    """P5-1: Validate roleResult against schema value constraints.

    Returns a list of validation errors (empty = valid).
    """
    errors: list[str] = []

    # Status must be a valid enum value
    status = role_result.get("status")
    if not isinstance(status, str) or status not in VALID_ROLE_RESULT_STATUSES:
        errors.append(
            f"roleResult[{role_id}].status='{status}' not in valid set: {sorted(VALID_ROLE_RESULT_STATUSES)}"
        )

    # changeSet structure validation
    cs = role_result.get("changeSet")
    if cs is not None:
        if not isinstance(cs, dict):
            errors.append(f"roleResult[{role_id}].changeSet must be dict or null")
        else:
            for key in ("modified", "created", "deleted"):
                arr = cs.get(key)
                if arr is None:
                    errors.append(f"roleResult[{role_id}].changeSet.{key} is missing")
                elif not isinstance(arr, list):
                    errors.append(f"roleResult[{role_id}].changeSet.{key} must be array")
                else:
                    for item in arr:
                        if not isinstance(item, str):
                            errors.append(f"roleResult[{role_id}].changeSet.{key} contains non-string")
                            break

    # Summary length check (max 200 chars)
    summary = role_result.get("summary", "")
    if isinstance(summary, str) and len(summary) > 200:
        errors.append(
            f"roleResult[{role_id}].summary length={len(summary)} exceeds 200 char limit"
        )

    # Blockers must be array of strings
    blockers = role_result.get("blockers")
    if blockers is not None:
        if not isinstance(blockers, list):
            errors.append(f"roleResult[{role_id}].blockers must be array")
        else:
            for b in blockers:
                if not isinstance(b, str):
                    errors.append(f"roleResult[{role_id}].blockers contains non-string")
                    break

    return errors


def _compute_complexity_multiplier(stack_snapshot: dict) -> float:
    """P3-4: Compute timeout multiplier based on project complexity."""
    layout = stack_snapshot.get("projectLayout", {})
    file_count = layout.get("totalFiles", 0) + layout.get("sourceFiles", 0)
    if file_count == 0:
        # Fallback: check if we have any layout info at all
        file_count = sum(v for v in layout.values() if isinstance(v, int))
    for max_count, multiplier in COMPLEXITY_TIERS:
        if file_count <= max_count:
            return multiplier
    return COMPLEXITY_TIERS[-1][1]


def _truncate_changeset(change_set: dict) -> dict:
    """P7-3: Truncate changeSet arrays that exceed MAX_CHANGESET_ITEMS.

    Prevents token explosion when passing large changeSets to downstream roles.
    Preserves structure but limits each array to MAX_CHANGESET_ITEMS entries.
    """
    if not isinstance(change_set, dict):
        return change_set

    result = {}
    for key in ("modified", "created", "deleted"):
        arr = change_set.get(key, [])
        if not isinstance(arr, list):
            result[key] = arr
            continue
        if len(arr) <= MAX_CHANGESET_ITEMS:
            result[key] = arr
        else:
            result[key] = arr[:MAX_CHANGESET_ITEMS]
            result[f"_{key}Truncated"] = True
            result[f"_{key}OriginalCount"] = len(arr)

    # Preserve any extra keys (e.g., summary, _compressed)
    for k, v in change_set.items():
        if k not in result:
            result[k] = v

    total_original = sum(
        len(change_set.get(k, [])) for k in ("modified", "created", "deleted")
        if isinstance(change_set.get(k), list)
    )
    if total_original > MAX_CHANGESET_ITEMS:
        result["_truncationNote"] = (
            f"changeSet truncated: {total_original} total items → max {MAX_CHANGESET_ITEMS} per array. "
            "Full list available in evidence-ledger."
        )

    return result


def determine_edit_mode(role: dict) -> str:
    role_id = role.get("id", "")
    if role_id in {"execution-engineer", "frontend-engineer", "backend-engineer"}:
        return "write-code"
    if role_id == "quality-gate-engineer":
        return "validate-and-review"
    if role_id == "browser-e2e-engineer":
        return "execute-and-write-docs"
    if role_id == "supervisor-auditor":
        return "review-only"
    return "write-docs"


def _topo_groups(route: list[str]) -> list[list[str]]:
    """Group route roles into parallel layers based on ROUTE_DEPENDENCIES.

    Each layer is a list of role ids that may run concurrently because all of their
    upstream dependencies have been completed in earlier layers. Roles outside
    ROUTE_DEPENDENCIES (e.g. development-orchestrator) form the first layer.
    """
    remaining = list(route)
    completed: set[str] = set()
    layers: list[list[str]] = []
    safety = 0
    while remaining and safety < 50:
        safety += 1
        layer = [
            role_id
            for role_id in remaining
            if all(dep in completed or dep not in route for dep in ROUTE_DEPENDENCIES.get(role_id, []))
        ]
        if not layer:
            # Cycle or unresolved dependency: dump remaining as a single layer to avoid hang.
            layer = list(remaining)
        layers.append(layer)
        for role_id in layer:
            remaining.remove(role_id)
            completed.add(role_id)
    return layers


def build_handoff(config: dict, role: dict, task_summary: str, domains: list[str], upstream_change_set: dict | None = None, allowed_adapters: list[str] | None = None, complexity_multiplier: float = 1.0) -> dict:
    role_id = role["id"]
    # P3-4: Adaptive timeout based on project complexity.
    base_timeout = ROLE_TIMEOUTS.get(role_id, 300000)
    timeout = int(base_timeout * complexity_multiplier)
    depends_on = ROUTE_DEPENDENCIES.get(role_id, [])

    # Role-specific IO: only pass files this role actually needs (P0-1/P0-2).
    expected_inputs = role.get("expectedInputs", [])
    expected_outputs = role.get("expectedOutputs", [])

    # governanceConstraints: only role-specific extra files (implicit governance not repeated)
    extra_governance = ROLE_EXTRA_GOVERNANCE.get(role_id, [])

    # workflowDomains: only for planning/review roles
    handoff_domains = domains if role_id in WORKFLOW_DOMAIN_ROLES else None

    # P3-3: Token budget for context trimming.
    token_budget = ROLE_TOKEN_BUDGETS.get(role_id, 10000)

    # P5-6: Locked files for parallel conflict prevention.
    locked_files = ROLE_LOCKED_FILES.get(role_id, [])

    handoff = {
        "roleId": role_id,
        "roleName": role["name"],
        "taskSummary": task_summary,
        "governanceConstraints": extra_governance,
        "requiredFiles": expected_inputs,
        "expectedOutputs": expected_outputs,
        "prohibitedOverreach": [
            "Do not exceed the role scope defined in the role prompt.",
            "Do not claim completion without validation evidence.",
            "Do not hide risks, blockers, missing inputs, or deviations.",
            "Do not stop for manual confirmation when a clear non-destructive update can be completed within role scope.",
        ],
        "outputResponsibilities": [role.get("purpose", "")],
        "completionStandards": "参见角色 prompt 的验证清单章节",
        "risksAndQuestions": [],
        "upstreamPendingItems": [],
        "editMode": determine_edit_mode(role),
        "timeoutMs": timeout,
        "tokenBudget": token_budget,
        "lockedFiles": locked_files,
        "retryPolicy": DEFAULT_RETRY_POLICY,
        "dependsOn": depends_on,
        **({
            "workflowDomains": handoff_domains} if handoff_domains else {}),
    }
    # P0-3: Attach upstream changeSet so downstream roles know what was modified.
    # P7-3: Truncate changeSet if it exceeds MAX_CHANGESET_ITEMS to prevent token explosion.
    if upstream_change_set:
        handoff["upstreamChangeSet"] = _truncate_changeset(upstream_change_set)
    # P1-7: Restrict adapter reading to detected stack only.
    if allowed_adapters is not None:
        handoff["allowedAdapters"] = allowed_adapters

    # P7-1: Context window overflow protection.
    # Estimate total handoff token consumption; if pressure is high, compress further.
    handoff_json_len = len(json.dumps(handoff, ensure_ascii=False))
    estimated_tokens = int(handoff_json_len / CHARS_PER_TOKEN_ESTIMATE)
    if estimated_tokens > token_budget * CONTEXT_PRESSURE_RATIO:
        # Compress: strip upstreamChangeSet details, keep only counts
        if "upstreamChangeSet" in handoff:
            ucs = handoff["upstreamChangeSet"]
            handoff["upstreamChangeSet"] = {
                "_compressed": True,
                "modifiedCount": len(ucs.get("modified", [])),
                "createdCount": len(ucs.get("created", [])),
                "deletedCount": len(ucs.get("deleted", [])),
                "note": "Full changeSet available in evidence-ledger. Compressed due to context pressure.",
            }
        handoff["_contextPressure"] = {
            "estimatedTokens": estimated_tokens,
            "tokenBudget": token_budget,
            "action": "upstreamChangeSet compressed",
        }

    return handoff


def build_plan(skill_root: Path, project_root: Path, task_summary: str, explicit_domains: list[str]) -> dict:
    # P5-2: Pre-flight check on task summary quality.
    preflight = _preflight_check(task_summary)
    if preflight is not None:
        return preflight

    config = load_config(skill_root)
    domains = classify_domains(task_summary, explicit_domains)
    route = config["mode"]["unified-large-delivery"]["route"]
    roles_by_id = {role["id"]: role for role in config["roles"]}
    stack_snapshot = detect_stack(project_root) if detect_stack else {
        "selectedAdapters": [], "adapterEvidence": {}, "infrastructure": {},
        "migrationDirs": [], "projectLayout": {}, "deterministic": False,
    }
    # P3-4: Compute complexity multiplier for adaptive timeouts.
    complexity_multiplier = _compute_complexity_multiplier(stack_snapshot)
    # P3-6: Determine conditional role inclusion.
    conditional_flags = determine_conditional_roles(task_summary, stack_snapshot, domains)
    handoffs = [build_handoff(config, roles_by_id[role_id], task_summary, domains, allowed_adapters=stack_snapshot.get("selectedAdapters"), complexity_multiplier=complexity_multiplier) for role_id in route]
    # P6-12: Unique delivery ID for namespace isolation.
    delivery_id = str(uuid.uuid4())

    # M1-M4: Load project memory and generate memory-aware context.
    project_memory = None
    memory_queries = None
    if load_project_memory is not None:
        try:
            project_memory = load_project_memory(project_root, stack_snapshot, task_summary)
        except Exception:
            project_memory = None

    if generate_pre_delivery_queries is not None:
        try:
            memory_queries = generate_pre_delivery_queries(
                task_summary,
                stack_snapshot.get("selectedAdapters"),
                domains,
            )
        except Exception:
            memory_queries = None

    # Design System Binding: detect skill-level or project-level design system and inject into handoffs.
    design_system = None
    design_binding = None
    if detect_design_system is not None:
        try:
            design_system = detect_design_system(project_root, skill_root=skill_root)
            if design_system and build_handoff_binding is not None:
                design_binding = build_handoff_binding(design_system)
        except Exception:
            design_system = None
            design_binding = None

    # Inject design system binding into UI Designer and Frontend Engineer handoffs.
    if design_binding and design_binding.get("bound"):
        ds_file = design_binding["designSystemFile"]
        for h in handoffs:
            role_id = h.get("roleId", "")
            if role_id in ("ui-designer", "frontend-engineer"):
                # Add design system file to required reads
                required = h.get("requiredFiles", [])
                if ds_file not in required:
                    required.insert(0, ds_file)
                    h["requiredFiles"] = required
                # Inject binding context
                h["designSystemBinding"] = design_binding

    # Inject memory context into handoffs.
    if project_memory and project_memory.get("hasMemory"):
        conventions = project_memory.get("conventions", [])
        pattern_hints = project_memory.get("failurePatternHints", [])
        adr_hints = project_memory.get("adrHints", [])
        for h in handoffs:
            if conventions:
                h.setdefault("governanceConstraints", []).extend(
                    [f"[Project Convention] {c}" for c in conventions[:5]]
                )
            if pattern_hints:
                h.setdefault("risksAndQuestions", []).extend(
                    [f"[Past Failure FP] {p['summary']} — fix: {p.get('fixHint', 'N/A')}" for p in pattern_hints[:3]]
                )
            if adr_hints:
                h.setdefault("risksAndQuestions", []).extend(
                    [f"[ADR {a['id']}] {a['title']}: {a['decision'][:100]}" for a in adr_hints[:3]]
                )
            h["memoryEvidence"] = {
                "injected": True,
                "conventions": len(conventions),
                "failurePatterns": len(pattern_hints),
                "adrs": len(adr_hints),
            }

    # P7-7 + M5: Checkpoint resume detection and incremental plan delta.
    resume_info = None
    delta_info = None
    plan_partial = {
        "route": route, "taskSummary": task_summary,
        "workflowDomains": domains,
        "conditionalRoleFlags": conditional_flags,
        "uiAffected": is_ui_affected(task_summary),
        "securitySensitive": is_security_sensitive(domains, task_summary),
    }
    if can_resume is not None:
        try:
            resume_info = can_resume(project_root, plan_partial)
        except Exception:
            resume_info = None
    if load_last_plan is not None and compute_plan_delta is not None:
        try:
            last = load_last_plan(project_root)
            if last:
                delta_info = compute_plan_delta(last, plan_partial)
        except Exception:
            delta_info = None

    result_plan = {
        "deliveryId": delivery_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "skillRoot": str(skill_root),
        "projectRoot": str(project_root),
        "taskSummary": task_summary,
        "workflowDomains": domains,
        "uiAffected": is_ui_affected(task_summary),
        "securitySensitive": is_security_sensitive(domains, task_summary),
        "conditionalRoleFlags": conditional_flags,
        "route": route,
        "parallelGroups": _topo_groups(route),
        "handoffs": handoffs,
        "requiredDocuments": config.get("artifacts", {}).get("requiredDocuments", []),
        "conditionalDocuments": config.get("artifacts", {}).get("conditionalDocuments", []),
        "mandatoryE2E": config.get("artifacts", {}).get("mandatoryE2E", {}),
        "stackDetection": stack_snapshot,
        "designSystem": {
            "detected": bool(design_system and design_system.get("detected")),
            "filePath": design_system["filePath"] if design_system else None,
            "bindingLevel": design_binding["bindingLevel"] if design_binding and design_binding.get("bound") else None,
            "completeness": design_system["completeness"] if design_system else None,
        } if design_system else None,
        "projectMemory": {
            "stats": project_memory.get("memoryStats") if project_memory else None,
            "searchQueries": memory_queries,
        } if project_memory or memory_queries else None,
        "runtimeNote": "This script builds the orchestration plan and handoff payloads. Runtime-specific adapters execute the role sessions in independent sessions where possible (see references/runtime-adapters/qoder.md). Downstream roles MUST only read adapters listed in stackDetection.selectedAdapters; ignore the rest to save tokens and avoid drift.",
    }

    # P7-7 + M5: Enrich with delta context and attach resume/delta metadata.
    if delta_info and enrich_plan_with_delta is not None:
        try:
            result_plan = enrich_plan_with_delta(result_plan, delta_info)
        except Exception:
            pass
    if resume_info and resume_info.get("resumable"):
        result_plan["checkpointResume"] = resume_info
    if delta_info:
        result_plan["planDelta"] = delta_info

    # M5: Cache this plan for future delta detection.
    if save_last_plan is not None:
        try:
            save_last_plan(project_root, result_plan)
        except Exception:
            pass

    return result_plan


def initial_ledger(plan: dict) -> dict:
    created_at = plan["createdAt"]
    ledger = {
        "taskName": plan["taskSummary"],
        "createdAt": created_at,
        "deliveryStatus": "in-progress",
        "deliveryGateEvidence": {
            "status": "fail",
            "blockingReasons": ["Delivery validation has not run."],
            "runAt": created_at,
            "strictMode": True,
            "command": "not-run: scripts/validate_delivery.py",
        },
        "roleRuns": [
            {
                "roleId": role_id,
                "status": "planned",
                "sessionMode": "planned-independent",
                "summary": "Planned by orchestrate.py",
                "durationMs": 0,
                "retryCount": 0,
                "blockedBy": [],
                "expectedOutputs": next(
                    (h["expectedOutputs"] for h in plan["handoffs"] if h["roleId"] == role_id),
                    [],
                ),
                "changeSet": None,
            }
            for role_id in plan["route"]
        ],
        "commands": [],
        "artifacts": plan["requiredDocuments"],
        "qualityGates": [],
        "observability": {},
    }
    if plan.get("deliveryId"):
        ledger["deliveryId"] = plan["deliveryId"]
    return ledger


def write_plan(plan: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "handoffs").mkdir(exist_ok=True)
    (output_dir / "orchestration-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    for handoff in plan["handoffs"]:
        path = output_dir / "handoffs" / f"{handoff['roleId']}.json"
        path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "evidence-ledger.json").write_text(json.dumps(initial_ledger(plan), ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to the skill root")
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--task-summary", required=True, help="Task summary")
    parser.add_argument(
        "--workflow-domain",
        action="append",
        default=[],
        choices=["forward-development", "change-management", "security-governance", "incident-management"],
        help="Explicit workflow domain. Can be repeated.",
    )
    parser.add_argument("--output-dir", help="Directory to write orchestration plan and handoffs")
    parser.add_argument("--json", action="store_true", help="Print plan JSON")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    project_root = Path(args.project_root).resolve()
    plan = build_plan(skill_root, project_root, args.task_summary, args.workflow_domain)

    if args.output_dir:
        write_plan(plan, Path(args.output_dir).resolve())

    if args.json or not args.output_dir:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"Wrote orchestration plan to {Path(args.output_dir).resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
