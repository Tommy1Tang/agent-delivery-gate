#!/usr/bin/env python3
"""Build a structured Orchestrator handoff for a configured role."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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


def load_config(skill_root: Path) -> dict:
    return json.loads((skill_root / "assets" / "config" / "agent-team-config.json").read_text(encoding="utf-8"))


def find_role(config: dict, role_id: str) -> dict | None:
    for role in config.get("roles", []):
        if role.get("id") == role_id:
            return role
    return None


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


def build_handoff(config: dict, role: dict, task_summary: str, workflow_domains: list[str], upstream_change_set: dict | None = None, allowed_adapters: list[str] | None = None, token_budget: int | None = None) -> dict:
    role_id = role["id"]

    # Role-specific IO: only pass files this role actually needs (P0-1/P0-2).
    expected_inputs = role.get("expectedInputs", [])
    expected_outputs = role.get("expectedOutputs", [])

    # governanceConstraints: only role-specific extra files (implicit governance not repeated)
    extra_governance = ROLE_EXTRA_GOVERNANCE.get(role_id, [])

    # workflowDomains: only for planning/review roles
    handoff_domains = workflow_domains if role_id in WORKFLOW_DOMAIN_ROLES else None

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
            "Do not stop for manual confirmation when a clear non-destructive update can be completed within role scope."
        ],
        "outputResponsibilities": [
            role.get("purpose", "")
        ],
        "completionStandards": "参见角色 prompt 的验证清单章节",
        "risksAndQuestions": [],
        "upstreamPendingItems": [],
        "editMode": determine_edit_mode(role),
        **({"workflowDomains": handoff_domains} if handoff_domains else {}),
        "retryPolicy": DEFAULT_RETRY_POLICY,
    }
    # P3-3: Token budget for context trimming.
    if token_budget is not None:
        handoff["tokenBudget"] = token_budget
    # P0-3: Attach upstream changeSet so downstream roles know what was modified.
    if upstream_change_set:
        handoff["upstreamChangeSet"] = upstream_change_set
    # P1-7: Restrict adapter reading to detected stack only.
    if allowed_adapters is not None:
        handoff["allowedAdapters"] = allowed_adapters
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to the skill root")
    parser.add_argument("--role", required=True, help="Role id from agent-team-config.json")
    parser.add_argument("--task-summary", required=True, help="Task summary to include in handoff")
    parser.add_argument(
        "--workflow-domain",
        action="append",
        default=[],
        choices=["forward-development", "change-management", "security-governance", "incident-management"],
        help="Workflow domain. Can be passed multiple times.",
    )
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    config = load_config(skill_root)
    role = find_role(config, args.role)
    if role is None:
        print(f"Unknown role: {args.role}", file=sys.stderr)
        return 2

    handoff = build_handoff(
        config,
        role,
        args.task_summary,
        args.workflow_domain or ["forward-development"],
    )
    print(json.dumps(handoff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
