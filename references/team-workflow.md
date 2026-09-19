# Team Workflow Reference

This file is the in-skill canonical workflow and document routing reference for `software-development-team`.

This workflow is additionally governed by the mandatory local specs:
- `assets/constitution.md`
- `assets/tech.md`
- `assets/design.md`

Read `references/local-governance.md` as the normalized governance summary before routing or execution.
Read `references/autonomous-update-policy.md` as the default policy for direct non-destructive updates.
Read `references/unified-large-delivery-policy.md` as the explicit single-mode delivery policy for all tasks.
Use `assets/templates/` as the default skeletons for formal documents.
Use `schemas/` and `scripts/` when machine-checkable handoff, role-result, quality-gate, audit, or delivery validation is needed.
Use `references/adapters/` for project technology stack alignment.
Use `references/runtime-adapters/` for runtime-specific dispatch behavior.

> **全局治理文件隐式必读**：constitution.md, tech.md, design.md, local-governance.md, team-overview.md, team-workflow.md 为所有角色隐式必读，无需在 Handoff 中重复声明。详见 `references/team-overview.md` 中的 Handoff 规范章节。

Use the unified full-delivery path for every development task.
Do not use fast-path or reduced-document paths based on task size.
Treat every request as production-grade in workflow rigor, validation rigor, review rigor, release rigor, and audit rigor.

Also determine whether the current request falls into one or more of these workflow domains:
- 正向标准流程 -> see `references/workflow-matrix.md` + `references/forward-development-template.md`
- 需求变更流程 -> see `references/change-management-workflow.md` + `references/change-request-template.md`
- 安全管控流程 -> see `references/security-governance-workflow.md` + `references/security-review-template.md` + `references/security-assessment-template.md`
- 异常问题处理流程 -> see `references/incident-management-workflow.md` + `references/incident-report-template.md`

## Mandatory execution order
For every task, the workflow must reflect:
1. Analyze current context and existing files
2. Produce requirements, plan, task breakdown, and technical design before implementation
3. Execute in scoped increments
4. Verify results, edge cases, and acceptance criteria
5. Perform code review and security review when applicable
6. Prepare deployment / release guidance
7. Complete documentation normalization and supervisor audit before claiming completion

If requirements, APIs, dependencies, or project context are unclear, inspect local context first and make a conservative decision when the requested update remains clear. Ask only when ambiguity would cause incompatible outcomes, data loss, destructive action, or permission/approval blockers.

## Autonomous Update Rule

When the user requests an update, optimization, fix, implementation, or asks to apply report recommendations, agents should proceed directly if the scope is clear and non-destructive.

Do not use manual confirmation as a routine workflow gate. Human confirmation is reserved for destructive operations, external irreversible actions, credential/account decisions, permission blockers, or genuinely incompatible choices.

## Independent-session orchestration requirement
When this skill is integrated with an agent runtime that supports spawning or dispatching other sessions, the Development Orchestrator must:
- run each downstream role in its own isolated session
- pass only the necessary handoff context, required inputs, expected outputs, and file ownership expectations to that session
- wait for the role result, then decide the next role handoff
- keep role boundaries explicit instead of simulating multiple roles in one assistant response

Default expectation:
- Product Analyst, Architect, Data Engineer, Performance Engineer, Data Contract Designer, UI Designer, Execution Engineer, Frontend Engineer, Backend Engineer, Quality Gate Engineer, Browser E2E Engineer, DevOps and Release Engineer, Documentation Writer, and Supervisor Auditor should each execute in separate sessions when invoked

Fallback rule:
- Only collapse role execution into one session when the environment does not support session spawning or dispatch, and disclose that fallback explicitly in the result

## Required document workflow
For tasks that require formal delivery documents, the orchestrator should ensure the following ownership and order:

1. Product Analyst outputs `docs/01-需求规格书.md`
2. Architect outputs `docs/02-开发计划.md`, `docs/03-任务清单.md`, and `docs/04-详细设计说明书.md`
3. Data Engineer outputs `docs/05-数据设计说明书.md` when data model is complex, migration required, or large data volume
4. Data Contract Designer outputs `docs/07-接口数据契约.md`
5. Performance Engineer outputs `docs/06-性能优化说明.md` when performance SLA exists or high load scenarios (may run in parallel with implementation or after implementation)
6. UI Designer outputs `docs/08-UI设计说明.md` when user-facing interface behavior or visual hierarchy is affected
7. Quality Gate Engineer outputs `docs/10-单元测试用例.md`, `docs/11-单元测试报告.md`, `docs/12-集成测试用例.md`, `docs/13-集成测试报告.md`, `docs/14-代码评审.md`, `docs/15-安全评审.md` (when security-sensitive scope is affected)
8. **Browser E2E Engineer outputs `docs/16-E2E测试用例.md` and `docs/17-E2E测试报告.md` for EVERY delivery (MANDATORY, no opt-out)**
9. DevOps and Release Engineer outputs `docs/18-部署说明.md`
10. Documentation Writer normalizes document structure, naming, and final delivery package
11. Supervisor Auditor outputs `docs/19-监督审计.md`

## Routing expectations
- Every task requires `docs/01-需求规格书.md`, `docs/02-开发计划.md`, `docs/03-任务清单.md`, `docs/04-详细设计说明书.md`,  `docs/07-接口数据契约.md`, relevant test documents, `docs/14-代码评审.md`, `docs/18-部署说明.md`, and `docs/19-监督审计.md`
- `docs/05-数据设计说明书.md` is required when data model complexity, migration needs, or large data volume is present
- `docs/06-性能优化说明.md` is required when performance SLA, high concurrency, or large data volume scenarios exist
- 🔴 **RED LINE (E2E MANDATORY for every delivery)**: `docs/16-E2E测试用例.md` and `docs/17-E2E测试报告.md` are REQUIRED for EVERY task without exception. Leader MUST dispatch `browser-e2e-engineer` in an isolated session during validation-and-review. Subjective opt-outs (「项目太小」「仅后端」「无 UI 交互」「环境不可用」) are forbidden. Pure-backend deliveries MUST run end-to-end through the public entry point (CLI / HTTP) and document the run as E2E cases.
- Every task must pass through the full requirements -> planning -> design -> implementation -> validation -> review -> release -> documentation -> audit chain
- Requirement change tasks: must run explicit impact analysis and re-baseline affected docs before continuing
- Security-sensitive tasks: must run explicit security checks, must route through Quality Gate Engineer for security review, and must add security validation / release gates where needed
- Incident / exception tasks: may take a fast containment path first, but cannot skip evidence preservation, root-cause analysis, fix verification, regression checks, and the remaining formal delivery documents needed for closure

## Cross-role engineering constraints
- All roles must avoid silent failures and surface enough error context
- All roles must prefer simple, maintainable, non-duplicated solutions
- Type safety and explicit contracts are required where the language supports them
- Defensive checks are required for external input and nullable data
- Database and API design should follow the naming and contract rules from `tech.md`
- Do not introduce dependencies or files without checking whether equivalents already exist

At the end of each path, require Supervisor Auditor to check whether the expected roles were actually invoked, whether required documents were produced, whether the relevant workflow domain was applied correctly, and whether the workflow was followed exactly. Use `references/workflow-audit-template.md` when a structured audit output is needed. For formal security reviews, use `references/security-assessment-template.md`.

Always validate before claiming completion.

## Harness validation

For product-grade delivery, the runtime or orchestrator should run:

```text
python scripts/check_skill_integrity.py <skill-root>
python scripts/validate_delivery.py --skill-root <skill-root> --project-root <project-root>
python scripts/run_golden_tests.py --skill-root <skill-root>
python scripts/compatibility_check.py <skill-root>
```

Use `scripts/build_handoff.py` when a structured handoff payload is needed for a role session.
Use `scripts/orchestrate.py` to generate a full route plan and initial evidence ledger.
Use `scripts/write_evidence_ledger.py` and `scripts/metrics_report.py` for evidence and observability.
Project infrastructure (code host repository, CI pipeline, database, Git remote) is provisioned once by the user or platform administrator; this skill does not ship platform-specific bootstrap scripts.

## Zero-Config Deployment Flow

When a project follows one of the stack adapters in `references/adapters/`, the following automated flow is enabled:

1. **Execution Engineer** completes implementation and auto-pushes to `origin main`
2. **Gitea webhook** notifies Jenkins on push
3. **Jenkins Pipeline** (`Jenkinsfile`) auto-executes:
   - Creates project database if not exists
   - Runs DDL migration scripts
   - Builds backend (Maven multi-stage Docker)
   - Builds frontend (Node + Nginx Docker)
   - Deploys via `docker compose up -d`
   - Runs health check
4. **DevOps Release Engineer** produces `docs/18-部署说明.md` with access URL

Business users need ZERO manual intervention in this flow. All infrastructure is pre-provisioned by `infrastructure/docker-compose.yml`.

