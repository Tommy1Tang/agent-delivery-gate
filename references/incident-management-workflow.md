# Incident Management Workflow

Use this workflow when handling defects, service degradation, online incidents, repeated failures, unstable behavior, or emergency bug fixing.

## Trigger conditions
- Production issue
- Repeated runtime error
- Data inconsistency
- Integration outage
- Severe user-facing bug
- Failed deployment or rollback event
- Unknown regression after change

## Closure-only contract（不允许仅 containment 后宣告关闭）

Incident handling 是**临时通道**，不是替代正式交付链的捷径。Containment 仅停止伤害扩大，**不构成 closure**。任何事故必须走完以下闸：

1. Containment（步骤 2）落实并记录证据 — 仅是阶段 1，不是结束
2. Root cause 已查明（步骤 4），不允许「待查」「无法定位」长期挂起
3. 结构性修复已实施（步骤 5）或 deferral 三字段齐全（`deferralDeadline` / `deferralOwner` / `deferralJustification`）
4. Verification（步骤 6）已运行：复现前后对比 + 关键路径回归
5. 文档基线已补齐（如果事故修复跨越正式交付链，**必须**回到 `references/unified-large-delivery-policy.md` 的完整文档基线，包括 `docs/01-需求规格书.md` / `docs/04-详细设计说明书.md` / `docs/11-单元测试报告.md` / `docs/13-集成测试报告.md` / `docs/18-部署说明.md` / `docs/14-代码评审.md` / `docs/19-监督审计.md`）
6. `scripts/validate_delivery.py --strict` 输出 `status == pass` 并写入 evidence ledger 的 `deliveryGateEvidence`
7. Supervisor Auditor 出审计结论「通过」（不允许「有条件通过」）

禁止行为：
- 🔴 在 containment 完成后立即宣告 incident 关闭
- 🔴 把 incident 当作「绕过完整文档链」的理由
- 🔴 跳过 validator 因为「事故工单已关」
- 🔴 用 `docs/23-事故报告.md` 替代 `docs/19-监督审计.md`

如果事故触发了 Circuit Breaker（`references/retry-policy.md`），必须按 `references/halt-and-resume-policy.md` Rule 2 处理（`deliveryStatus = halted-circuit-broken` + 14 天 deadline → 否则 `failed-closed`）。

## Mandatory steps
1. Identify incident basics
   - symptom
   - severity
   - affected users / scope
   - start time / detection source
2. Contain impact first when necessary
   - rollback
   - feature flag off
   - traffic isolation
   - write protection
   - temporary guardrail
3. Preserve evidence
   - logs
   - request / response samples
   - environment info
   - reproduction inputs
   - timeline
4. Root-cause analysis
   - do not patch by guess only
   - confirm the actual failure mechanism
5. Implement fix safely
   - minimal necessary change first
   - avoid introducing secondary damage
6. Verify
   - reproduce before fix when possible
   - confirm fix after change
   - run regression on nearby critical paths
7. Close and follow up
   - disclose residual risk
   - add prevention actions
   - define monitoring / alerting need
   - record follow-up tasks if structural fix is deferred
   - **MANDATORY when structural fix is deferred**:
     - record `deferralDeadline` (ISO 8601 absolute date, max 14 days from incident close) in evidence ledger
     - record `deferralOwner` (responsible role) in evidence ledger
     - record `deferralJustification` (why hotfix is acceptable + risk if not structurally fixed)
     - Supervisor Auditor must verify all three fields exist and the deadline is concrete; missing any field → incident **cannot be closed**
     - if `deferralDeadline` passes without structural fix, the incident automatically reopens and propagates BLOCK to the next delivery using the affected module

## Minimum incident output
- Incident summary
- Impact assessment
- Containment action
- Root cause
- Fix summary
- Verification result
- Residual risk / follow-up actions

## Cascade Block Propagation

When an upstream role fails with `blocked` or `failed` (retries exhausted), the Orchestrator must propagate cascade blocks to downstream roles:

1. Orchestrator receives `roleResult.status = "blocked"` with `cascadeBlock` payload
2. All downstream roles in `cascadeBlock.cascadedRoleIds` are immediately marked as `skipped` with reason `"Cascade blocked by upstream: {blockedRoleId}"`
3. Evidence ledger records the cascade:
   ```bash
   write_evidence_ledger.py --role-run "architect|skipped|N/A|Cascade blocked by product-analyst|0|0|cascade-block"
   ```
4. Supervisor Auditor records cascade impact in `docs/19-监督审计.md`

## Session Failure Recovery

If an Agent session crashes or times out during incident handling:

1. Refer to `references/session-failure-recovery.md` for recovery procedures
2. Incident evidence preservation takes priority — snapshot logs before retry
3. If `Agent` tool is unavailable, fall back to `references/runtime-adapters/single-session-fallback.md` with explicit disclosure

## Prohibited behavior
- Silent retry loops instead of identifying cause
- Declaring incident resolved without evidence
- Skipping regression after emergency fix
- Losing incident evidence before analysis
- Ignoring cascade blocks and continuing downstream roles (Red Line violation)
- Retrying `security-block` or `blocked` statuses (must escalate, not retry)
- 🔴 Treating containment as closure — closure requires the full Closure-only contract above
- 🔴 Skipping the unified document baseline because "the incident workflow is faster"
- 🔴 Skipping `validate_delivery.py` because "this is an incident path"
- 🔴 Using `docs/23-事故报告.md` as a replacement for `docs/19-监督审计.md`
