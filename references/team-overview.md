# Team Overview

This file is the in-skill canonical team overview for `software-development-team`.

This skill is governed by local development specifications configured for the environment.

Current environment default example:
- `assets/constitution.md`
- `assets/tech.md`
- `assets/design.md`

Read `references/local-governance.md` as the normalized governance summary used by all roles.
Read `references/unified-large-delivery-policy.md` as the explicit single-mode delivery baseline used by all roles.
Use `assets/templates/` as the default document skeletons.
Use `schemas/` and `scripts/` as the engineering harness for machine-checkable handoffs, role results, evidence, quality gates, and delivery validation.

## 全局治理文件隐式必读

以下 6 个文件为所有角色隐式必读，无需在 Handoff 中重复声明：

1. `assets/constitution.md` — 团队章程
2. `assets/tech.md` — 技术栈规范
3. `assets/design.md` — UI 设计系统规范
4. `references/local-governance.md` — 本地治理摘要
5. `references/team-overview.md` — 团队概览（本文件）
6. `references/team-workflow.md` — 团队工作流参考

各角色 prompt 中已统一替换为 `全局治理文件（隐式必读，见 team-overview.md）`。如角色有额外治理文件（如 Quality Gate Engineer 的安全相关文件），在角色 prompt 和 Handoff 的 `governanceConstraints` 中单独列出。注意：`assets/design.md` 同时作为 `ui-designer` 和 `frontend-engineer` 的额外治理文件，确保 UI 相关角色必读。

This skill wraps the following roles:
- Development Orchestrator
- Product Analyst
- Architect
- Data Engineer
- Performance Engineer
- Execution Engineer
- Frontend Engineer
- Backend Engineer
- Quality Gate Engineer
- Browser E2E Engineer
- Data Contract Designer
- DevOps and Release Engineer
- Documentation Writer
- Supervisor Auditor

## Document Ownership

> 🔴 **文档命名基准（唯一规范）**：交付文档一律用**数字前缀**形式 `docs/NN-名称.md`（如 `docs/01-需求规格书.md`），与 `references/team-workflow.md` 的文档流及 `assets/config/agent-team-config.json` 的 `roles[].expectedOutputs` 保持一致。
>
> 无编号形式（`docs/需求规格书.md`）仅作为**历史别名**兼容：`scripts/validate_delivery.py` 的 `_resolve_doc_alias()` 与 `assets/config/skill-process.json` 的 `outputs[].paths` 多路径均接受两种形式，不会因命名变体误判缺失。**新项目请统一用有编号形式。**

以下列表使用简名，实际文件名以带编号为准（编号对应关系见 `references/team-workflow.md`）：

- Product Analyst -> `docs/需求规格书.md`
- Architect -> `docs/开发计划.md`, `docs/任务清单.md`, `docs/详细设计说明书.md`
- Data Engineer -> `docs/数据设计说明书.md`（when data model is complex, migration required, or large data volume）
- Performance Engineer -> `docs/性能优化说明.md`（when performance SLA exists or high load scenarios）
- Data Contract Designer -> `docs/接口数据契约.md`
- UI Designer -> `docs/UI设计说明.md` when UI/UX is affected
- Quality Gate Engineer -> `docs/单元测试用例.md`, `docs/单元测试报告.md`, `docs/集成测试用例.md`, `docs/集成测试报告.md`, `docs/代码评审.md`, `docs/安全评审.md` (when security-sensitive scope is affected)
- Browser E2E Engineer -> `docs/E2E测试用例.md`, `docs/E2E测试报告.md` (MANDATORY for every delivery, no opt-out)
- DevOps and Release Engineer -> `docs/部署说明.md`
- Documentation Writer -> 协助统一文档格式、目录结构和最终交付整理
- Supervisor Auditor -> `docs/监督审计.md`

## PRD-Code 双向同步

本团队同时维护正向（PRD → 代码）与反向（代码 → PRD）两条同步链路：

- 正向：变更需求时遵循 [`references/change-management-workflow.md`](change-management-workflow.md)，模板见 [`references/change-request-template.md`](change-request-template.md)。
- 反向：代码 / schema / UI / 配置先行变化时遵循 [`references/reverse-sync-workflow.md`](reverse-sync-workflow.md)，模板见 [`references/reverse-sync-template.md`](reverse-sync-template.md)。

反向同步由质量门禁中的 PRD Sync Gate 强制保障：
- 触发脚本：`scripts/contract_drift_check.py` + `scripts/requirement_drift_check.py` + `scripts/trace_requirements.py`
- 基线机制：`scripts/baseline_snapshot.py` 在每次 release 后写入 `_test_output/baseline/{version}.json`，后续漂移检测仅比对增量
- 闭环角色：`product-analyst`（FR 归属判定）→ `documentation-writer`（下游级联）→ `quality-gate-engineer`（重跑漂移检测）→ `supervisor-auditor`（`prdDriftClosed: true` 复核）
- 角色 Handoff 中可携带 `reverseSyncTasks[]` 字段；Role Result 中通过同名字段回传执行结果
- 证据账本通过 `reverse_sync_event` 事件类型记录闭环轨迹

禁止行为：仅修改代码不更新文档即合并；用 commit message 代替 PRD 回写；将用户可见行为变更归类为 "内部优化" 以绕过 PRD Sync Gate。

## Team Delivery Mode
- Unified full-delivery mode
- Every request is treated as a large-project-grade delivery workflow
- No small / medium / large mode split is allowed during execution
- Development Orchestrator is a routing and handoff agent, not a role-merging agent
- 🔴 **RED LINE**：Downstream role execution MUST occur in independent sessions. Each role must be dispatched via the `Agent` tool in its own isolated session. Single-session role-playing is prohibited.

## Mandatory baseline for every task
For every development request, the orchestrator must default to the same baseline:
- Product Analyst produces `docs/需求规格书.md`
- Architect produces `docs/开发计划.md`, `docs/任务清单.md`, and `docs/详细设计说明书.md`
- Data Engineer produces `docs/数据设计说明书.md` when data model is complex, migration required, or large data volume
- Performance Engineer produces `docs/性能优化说明.md` when performance SLA exists or high load scenarios
- Data Contract Designer produces `docs/接口数据契约.md`
- UI Designer produces `docs/UI设计说明.md` when UI/UX is affected
- Relevant engineering roles implement according to the approved plan and design
- Quality Gate Engineer produces test cases, test reports, code review, and security review (when security-sensitive scope is affected)
- Browser E2E Engineer produces `docs/E2E测试用例.md` and `docs/E2E测试报告.md` for **every** delivery (MANDATORY, no opt-out; pure-backend deliveries must run end-to-end via the public entry point)
- DevOps and Release Engineer produces `docs/部署说明.md`
- Documentation Writer normalizes delivery documents and packaging
- Supervisor Auditor produces `docs/监督审计.md` and verifies role coverage, document completeness, workflow correctness, validation evidence, risk disclosure, and closure readiness
- Supervisor Auditor produces `docs/可观测性报告.md` (generated via `scripts/observability_report.py` from the evidence ledger) covering role timing, retry, blocking, document missing rate, test pass rate, security blocks, fallback count, and rework count

For agent-runtime integrations, each owned step above should be executed by the corresponding role agent in a separate session with explicit handoff context and expected deliverables.

## Handoff 规范

Handoff 采用精简模式，遵循以下规则：

1. **全局治理文件隐式必读**：constitution.md, tech.md, local-governance.md, team-overview.md, team-workflow.md 无需在 Handoff 中重复声明。`governanceConstraints` 仅用于角色特殊治理约束。
2. **workflowDomains 条件化**：仅 Product Analyst、Architect、Quality Gate Engineer、Supervisor Auditor 的 Handoff 中包含 workflowDomains，其他角色省略。
3. **completionStandards 引用格式**：默认为 `"参见角色 prompt 的验证清单章节"`，仅在有任务特殊标准时补充具体条目。
4. **retryPolicy 全局默认**：maxRetries=2, backoffMs=5000, retryableErrors=[timeout, session-lost, transient], nonRetryableErrors=[blocked, security-block, cancelled]，仅在特殊需求时覆盖。
5. **requiredFiles 最小必要原则**：每个角色的必读项目文件仅保留其真正需要的，避免冗余传递。
6. **enhancementDeclarations 传递（OC-A）**：当 Architect 产出增强声明时，Orchestrator 必须在实现角色和 QA 的 Handoff 中包含 `enhancementDeclarations` 字段，格式如下：
   ```json
   {
     "enhancementDeclarations": [
       {"id": "BE-A", "source": "architect", "target": "backend-engineer", "description": "并发与线程安全策略"},
       {"id": "FE-A", "source": "architect", "target": "frontend-engineer", "description": "WCAG 2.1 AA 可访问性"}
     ]
   }
   ```
   实现角色必须在 roleResult 中回传 `receivedDeclarations`、`fulfilledDeclarations`、`unfulfilledDeclarations`。

## Harness Resources

- `schemas/handoff.schema.json` defines the Orchestrator handoff contract
- `schemas/role-result.schema.json` defines downstream role result structure
- `schemas/quality-gate.schema.json` defines quality gate output
- `schemas/audit-record.schema.json` defines supervisor audit records
- `schemas/evidence-ledger.schema.json` defines the delivery evidence ledger
- `schemas/metrics.schema.json` defines harness metrics output
- `schemas/migration-report.schema.json` defines compatibility check output
- `scripts/check_skill_integrity.py` validates skill internals
- `scripts/validate_delivery.py` validates project delivery artifacts
- `scripts/build_handoff.py` generates structured role handoff payloads
- `scripts/orchestrate.py` builds the full route plan and initial evidence ledger
- `scripts/write_evidence_ledger.py` appends execution evidence
- `scripts/run_golden_tests.py` regression-tests orchestration behavior
- `scripts/metrics_report.py` summarizes evidence-ledger metrics
- `scripts/compatibility_check.py` checks config version compatibility
- `references/adapters/` contains technology stack adapters
- `references/runtime-adapters/` contains runtime dispatch adapters

