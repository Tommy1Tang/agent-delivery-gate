# Unified Large Delivery Policy

This document is the explicit policy baseline for `software-development-team`.

## Policy statement

Every development request must be handled as a large-project-grade delivery workflow.

No task may be downgraded to a lighter workflow because it appears small, low-risk, short-lived, urgent, or easy to implement.

This policy applies to:
- new feature delivery
- bug fixing
- refactoring
- change requests
- security-sensitive work
- incident / exception handling
- documentation-driven delivery work

## Mandatory workflow baseline

Every task must pass through the following baseline in order unless a domain-specific workflow adds extra gates:

1. Context analysis
2. Requirement clarification and formal requirement output
3. Planning and task breakdown
4. Technical design and contract alignment
5. Incremental implementation
6. Validation and regression checks
7. Code review
8. Security review when applicable, and security boundary check even when not obviously sensitive
9. Deployment / release readiness output
10. Documentation normalization
11. Supervisor audit and closure

## Review 阶段退出条件（强制）

退出 Review 阶段并进入后续文档整理/审计阶段的**唯一条件**：
1. Code Review verdict = PASS
2. Security Review verdict = PASS（或经评估确认不适用）
3. 所有之前 BLOCK 级别的 finding 均已修复并有验证证据
4. **单元测试硬指标全部达标**：
   - 测试用例实现数 > 0（禁止「仅设计未实现」）
   - 测试编译与执行 BUILD SUCCESS
   - 单元测试覆盖率 ≥ **90%**
   - 集成测试覆盖率 ≥ 80%
   - 测试通过率 = 100%

**任何其他情况**（包括 verdict = BLOCK、存在未修复的严重/高危问题、测试硬指标任一项不达标）→ **必须循环回 Code 阶段**，不允许跳过或降级处理。

### 禁止的降级行为
- 🔴 将 BLOCK 级别问题标记为"上线前条件"然后继续推进
- 🔴 将"有条件通过"视为可以进入下一阶段的信号
- 🔴 以"本期不修复，下期处理"为由跳过返工循环
- 🔴 以"环境问题非代码缺陷"为由跳过测试覆盖率、测试执行、测试编译要求
- 🔴 将单元测试覆盖率阈值从 90% 下调（项目硬阈值，**不可覆写、不可豁免、不接受任何 Orchestrator 或用户口头批准**——如客观技术原因导致无法达标，必须按 `references/halt-and-resume-policy.md` 走 `halted-pending-user` 流程，由用户在独立轮次中决定是否调整需求/范围/工具链，禁止以 Handoff 字段或评审备注形式悄然下调）
- 🔴 以「已尽力」「环境问题无法修复」绕过返工循环上限（详见 Rework Loop Cap）

## Rework Loop Cap（返工循环上限）

返工不是无限循环。当返工迭代达到上限时，必须按 `references/halt-and-resume-policy.md` 挂起，由用户决定方向。详见 `references/retry-policy.md` 的 Rework Loop Cap 段。

硬规则：
- **同一根因（root cause）**返工 ≤ **5 次**：超出 → `deliveryStatus = halted-pending-user`
- **整个交付累计**返工 ≤ **10 次**（`observability.reworkCount`）：超出 → 同上
- evidence ledger 必须记录 `reworkPerRootCause` 对象与 `observability.reworkCount` 数值
- Supervisor Auditor 必须核对两个上限均未被突破，否则审计结论只能为「不通过，返工修复」

## Halt and Resume（中断与恢复）

详见 `references/halt-and-resume-policy.md`。一旦开发过程因下列任一情形中断，必须显式写入 `deliveryStatus`：
- 重试耗尽 / `needs-info` 升级 / `security-block` → `halted-pending-user`
- Circuit Breaker 关闭 → `halted-circuit-broken`（伴 `docs/23-事故报告.md` + 14 天 deadline → 失败转 `failed-closed`）
- 多角色 `lost-session` > 2 → `halted-multi-crash`
- 用户主动取消（含反问确认） → `halted-user-cancel`
- 任一终态（`halted-user-cancel` / `failed-closed`）必须产出 `docs/24-未完成交付报告.md`

禁止措辞：
- 🔴 「已交付」「部分交付」「基本完成」「暂时收口」「已尽力」「后续修复」——这些措辞不得用于任何 `halted-*` / `failed-closed` 状态的总结

## Mandatory document baseline

Every task must produce and maintain the following documents:
- `docs/01-需求规格书.md`
- `docs/02-开发计划.md`
- `docs/03-任务清单.md`
- `docs/04-详细设计说明书.md`
- `docs/10-单元测试用例.md`
- `docs/11-单元测试报告.md`
- `docs/12-集成测试用例.md`
- `docs/13-集成测试报告.md`
- `docs/18-部署说明.md`
- `docs/21-执行日志.md`（执行追踪日志，由 Leader 维护，记录完整执行过程、质量门禁 verdict、返工循环和关键决策）

If a document is incomplete, blocked, or pending confirmation, that status must be explicitly recorded instead of silently omitted.

## Mandatory role baseline

Every task must be orchestrated against the unified role chain:
- Development Orchestrator
- Product Analyst
- Architect
- Data Contract Designer
- Relevant implementation roles
- Quality Gate Engineer
- DevOps and Release Engineer
- Documentation Writer
- Supervisor Auditor

## Domain-specific overlays

The unified large-delivery policy does not replace domain workflows. It coexists with them.

### Requirement change workflow
If baseline scope, acceptance, design, dependency, or priority changes after work starts:
- run explicit impact analysis
- update affected baseline documents
- obtain explicit confirmation when the baseline meaningfully changes
- continue only after re-baselining

### Security governance workflow
If a task touches trust boundaries, sensitive data, permissions, deployment, public interfaces, external dependencies, file handling, or other security-sensitive scope:
- route through Quality Gate Engineer for security review
- add security test scenarios and release gates
- disclose unresolved security risks and assumptions

### Incident management workflow
If a task is an incident, emergency defect, degraded behavior, or unstable system issue:
- containment is allowed as Step 1 only and **does NOT constitute closure** — closure must satisfy the full Closure-only contract in `references/incident-management-workflow.md`
- evidence preservation is mandatory
- root-cause analysis is mandatory
- validation and regression are mandatory
- the unified document baseline (requirements, design, test reports, deployment notes, code review, audit) must be completed before closure — the incident path is NOT a shortcut around the document baseline

## Prohibited behavior

🔴 **RED LINE**：无论用户使用什么措辞描述任务（"简单"、"快速"、"随便做一下"、"小改动"、"临时方案"等），一律不改变交付基线。完整文档链和角色链不可跳过——即使行为看起来"过度工程"，也必须执行。

The following are prohibited:
- 🔴 executing multiple roles in a single session by role-playing — each role MUST run in its own independent session via the `Agent` tool
- skipping requirement output because the task seems small
- skipping planning or detailed design because implementation seems obvious
- implementing directly from a vague request without re-baselining
- omitting formal test documents because change scope looks limited
- claiming completion without validation evidence
- skipping deployment documentation because no immediate release is planned
- bypassing audit because delivery appears finished
- hiding blockers, risks, deviations, or missing artifacts

## Audit expectations

Supervisor Auditor must confirm at least:
- all required roles were invoked as needed
- all required documents exist or have explicit blocked status
- workflow domains were identified correctly
- validation evidence exists
- review conclusions exist
- release guidance exists
- residual risks and pending items are disclosed
- completion claim is justified

## Consistency requirement

`SKILL.md`, `references/`, `assets/prompts/`, and `assets/config/` must remain aligned with this policy.

If any file conflicts with this policy, the conflict must be fixed before export or release.
