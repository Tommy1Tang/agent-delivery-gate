# Workflow Matrix Reference

This matrix defines the six mandatory workflow domains that `software-development-team` must cover:
1. 正向标准流程
2. 需求变更流程
3. 安全管控流程
4. 异常问题处理流程
5. 需求梳理流程
6. 仅部署流程（deploy-only）

All workflows are governed by:
- `assets/constitution.md`
- `assets/tech.md`
- `references/local-governance.md`

## 1. 正向标准流程

Applicable when building new features, fixing scoped defects, refactoring with approval, or delivering planned work.

Standard path:
1. Intake and context analysis
2. Requirement clarification
3. Scope and plan definition
4. Technical design and contract alignment
5. Incremental implementation
6. Verification and regression checks
7. Code review
8. Release readiness / deployment preparation
9. Documentation normalization
10. Supervisor audit and closure

## 2. 需求变更流程

Applicable when user requests scope change, acceptance criteria change, priority change, schedule change, design change, or dependency change after work has started.

Required path:
1. Record the change request and source
2. Reconfirm changed goal, unchanged goal, and reason
3. Run impact analysis across scope, design, tasks, interfaces, tests, schedule, and risks
4. Mark whether current baseline documents must be updated
5. Ask for explicit confirmation when change affects delivery baseline
6. Update spec/plan/design/tasks/tests before implementation continues
7. Re-verify impacted areas and regression scope
8. Auditor checks whether change handling was explicit and complete

## 3. 安全管控流程

Applicable when work touches authentication, authorization, user data, file upload, external APIs, infra, deployment, secrets, admin operations, or any security-sensitive path.

Required path:
1. Identify whether the task is security-sensitive
2. Classify sensitive data, permissions, trust boundaries, and exposed interfaces
3. Check authentication, authorization, input validation, output encoding, secret handling, dependency risk, auditability, and rollback controls
4. Add security test scenarios and release gates when applicable
5. Explicitly disclose unresolved security risks or assumptions
6. Auditor checks whether security review was skipped, partial, or complete

## 4. 异常问题处理流程

Applicable when system behavior is broken, unstable, degraded, inconsistent, or user reports online incidents / production issues / repeated failures.

Required path:
1. Identify symptom, impact, severity, and affected scope
2. Stop harm first when needed: rollback, isolate, disable risky path, or add guardrail
3. Preserve evidence: logs, inputs, outputs, time window, environment, reproduction steps
4. Perform root-cause analysis instead of guess-based patching
5. Implement fix with verification and regression checks
6. Record residual risk, monitoring need, and prevention action
7. If needed, produce post-incident summary and follow-up tasks
8. Auditor checks whether incident handling was evidence-based and properly closed

## Routing guidance by workflow type

- 正向标准流程 -> always use the unified full large-project-grade routing
- 需求变更流程 -> route through Product Analyst + Architect before further implementation, update baseline documents, then continue through the same full delivery chain
- 安全管控流程 -> require Architect, Quality Gate Engineer (for security review), Backend Engineer / Frontend Engineer, and Auditor security checks within the same full delivery chain
- 异常问题处理流程 -> allow fast containment path, but still require evidence, fix verification, regression checks, missing document补齐, and auditor closure within the same full delivery chain
- 需求梳理流程 -> route only through Product Analyst (interactive elicitation + skeleton confirmation + full PRD). No Architect or downstream roles. Transition to 正向标准流程 when user subsequently requests implementation.
- **仅部署流程 (deploy-only)** -> route only through DevOps Release Engineer (deploy-only mode): git push → Jenkins auto-build → health check → deployment report. No other roles dispatched. Triggered when user intent is pure deployment without new development. See `references/deploy-only-workflow.md`.

## Minimum closure criteria across all workflows

A workflow is not complete unless:
- expected changes or outputs exist
- verification was performed or explicit verification limits were disclosed
- risks / blockers / deviations were disclosed
- affected documents were updated when baseline changed
- Supervisor Auditor approved workflow completeness (except deploy-only, which closes with deployment report)

## Deploy-Only 快速闭环条件

Deploy-only workflow is complete when:
- `git push origin main` succeeded
- Jenkins build completed (SUCCESS status)
- Health check passed (`/actuator/health` returns UP)
- Deployment report delivered to user

No Supervisor Auditor required for deploy-only. No formal documents required.

## 精简路由条件（OC-G 对齐）

以下角色在满足客观条件时可被 Orchestrator 跳过，但必须在 evidence-ledger 中记录 `reasonForSkip` 和客观条件引用：

| 可跳过角色 | 客观跳过条件 |
|---|---|
| product-analyst | 用户直接提供完整 FR 列表（`userProvidedFR: true`） |
| ui-designer | changeSet 无 .vue/.tsx/.css/.scss 文件且无新增 UI 页面 |
| data-contract-designer | changeSet 无 Controller/DTO 文件且无新增/修改 API 接口 |
| execution-engineer | 所有任务可由专职角色独立完成（无跨层时序依赖） |
| data-engineer | 无复杂数据模型、无迁移、无大数据量场景 |
| performance-engineer | 无性能 SLA、无高负载场景 |

🔴 **不可跳过角色（硬约束）**：
- **Architect** — 架构设计是所有实现的基础，任何场景不可跳过
- **Quality Gate Engineer** — 测试验证是交付门禁必要条件
- **Browser E2E Engineer** — E2E 测试全项目强制
- **Supervisor Auditor** — 审计是交付闭环必要条件

任何尝试跳过上述角色的行为均为交付门禁 BLOCK。
