# Retry Policy

This document defines the retry strategy for `software-development-team` role execution.

> **Coupled with `references/halt-and-resume-policy.md`** — every "escalate to user" / "retries exhausted" path in this file MUST trigger the corresponding halt state defined there. Softer phrasings such as "may escalate", "consider fallback", "offer fallback" are non-binding and overridden by the halt policy.

## Error Classification

| Error Type | Category | Retry Strategy | Max Retries | Escalation |
|-----------|----------|---------------|-------------|------------|
| `timeout` | Transient | Exponential backoff | 2 | After exhaustion → set `deliveryStatus = halted-pending-user`; ask user (see halt-and-resume-policy Rule 1) |
| `session-lost` | Transient | Immediate retry with new session | 2 | After exhaustion → ONLY when runtime reports `Agent` tool unavailable, follow halt-and-resume-policy Rule 3; otherwise halted-pending-user. Fallback is NOT a soft "offer" — see Rule on Single-Session Fallback below |
| `transient` | Transient | Exponential backoff | 2 | After exhaustion → halted-pending-user |
| `needs-info` | Clarify | Orchestrator MUST first exhaust local context (governance + upstream artifacts + ledger) before raising to user; re-handoff once with clarification | 1 | After exhaustion → halted-pending-user (Rule 1) |
| `failed` | Semi-retryable | Retry once with error context | 1 | After exhaustion → if role is in **core role list** (product-analyst, architect, quality-gate-engineer, supervisor-auditor, execution-engineer-when-implementation-required), set `deliveryStatus = halted-pending-user` and FORBID claiming "已交付"/"部分交付"/"基本完成". Non-core roles may cascade-block downstream. |
| `blocked` | Non-retryable | Do NOT retry; cascade block downstream | 0 | Orchestrator triggers cascadeBlock; if blocked role is core → halted-pending-user |
| `security-block` | Non-retryable | Do NOT retry; block entire delivery chain | 0 | Immediate escalation to Quality Gate Engineer + user; `deliveryStatus = halted-pending-user` |
| `cancelled` | Terminal | Do NOT retry; terminate delivery chain | 0 | **MUST originate from a user message** (see halt-and-resume-policy Rule 5). Orchestrator self-cancellation is FORBIDDEN. Preserve artifacts, set `deliveryStatus = halted-user-cancel`, produce `docs/24-未完成交付报告.md` |

## Backoff Strategy

When retry is applicable, use exponential backoff:

```
attempt=1: wait 5s  (backoffMs)
attempt=2: wait 10s (backoffMs * 2)
attempt=3: escalate (maxRetries exceeded)
```

Default configuration per handoff:
- `maxRetries`: 2
- `backoffMs`: 5000
- `retryableErrors`: `["timeout", "session-lost", "transient"]`

## Role-Specific Timeouts

| Role | Default timeoutMs | Rationale |
|------|-------------------|-----------|
| product-analyst | 300000 (5 min) | Requirement analysis is bounded |
| architect | 600000 (10 min) | Planning and architecture design may require deeper analysis |
| data-engineer | 600000 (10 min) | Data modeling may be complex |
| data-contract-designer | 300000 (5 min) | Contract design is bounded |
| ui-designer | 600000 (10 min) | UI design may require visual iteration |
| execution-engineer | 600000 (10 min) | Implementation coordination is bounded |
| frontend-engineer | 900000 (15 min) | Frontend implementation may require multiple files |
| backend-engineer | 900000 (15 min) | Backend implementation may span multiple modules |
| quality-gate-engineer | 900000 (15 min) | Quality gate covers testing, code review, and security review |
| devops-release-engineer | 300000 (5 min) | Deployment documentation is bounded |
| documentation-writer | 300000 (5 min) | Documentation normalization is bounded |
| supervisor-auditor | 300000 (5 min) | Audit is bounded |

## Circuit Breaker

When a single role type fails more than 3 times across any delivery (cumulative `retryCount` across all roleRuns), the Orchestrator must:

1. Mark the role as `circuit-broken` in the evidence ledger
2. Set `deliveryStatus = halted-circuit-broken` (see `references/halt-and-resume-policy.md` Rule 2)
3. Auto-generate `docs/23-事故报告.md` summarizing the failure pattern
4. Record the failure pattern in `observability`
5. Surface to the Supervisor Auditor as a process deviation
6. Do NOT dispatch any further instances of that role until the user explicitly clears the circuit breaker (`circuitBreakerCleared` evidence required)
7. 🔴 Forbidden during halted-circuit-broken: writing "最终汇总", calling Auditor for verdict = 通过, marking delivery as `completed`
8. If the user does not clear within 14 days → auto-transition to `failed-closed` and produce `docs/24-未完成交付报告.md`

## Single-Session Fallback (硬规则，不是软建议)

When `Agent` tool is reported unavailable by the runtime adapter:

1. Single-session fallback is **NOT** "offered" or "suggested" — it is the ONLY allowed degradation, AND only when `references/runtime-adapters/<runtime>.md` reports `agentToolAvailable: false`
2. Orchestrator MUST register `fallbackTrigger`, `fallbackEnvironment`, and `fallbackEnteredAt` in evidence ledger BEFORE dispatching any role in fallback mode
3. Orchestrator MUST run `python scripts/validate_delivery.py` in **strict mode** (no `--no-strict`); status MUST be `pass` before completion is claimed
4. Supervisor Auditor MUST flag the fallback as a process deviation
5. 🔴 Forbidden: switching to fallback because of "为了方便" / "CI 环境" / "快起动" / single failed `Agent` call (must retry per maxRetries first)

## Rework Loop Cap (返工循环上限)

The Code → Verify → Review rework loop triggered by Quality Gate / Security Review verdict = BLOCK is bounded:

- `maxReworkIterations`: 5 (per delivery, counted across all BLOCK verdicts)
- After 5 unresolved iterations on the SAME root cause: Orchestrator MUST set `deliveryStatus = halted-pending-user`, generate an incident report, and request user direction
- 5 iterations on DIFFERENT root causes is allowed and counted separately, but cumulative iterations > 10 across the whole delivery also trigger halted-pending-user
- 🔴 Forbidden: silent abandonment of rework with phrasing such as "已尽力" / "后续处理" / "环境问题无法修复" — must transition to halted-pending-user via the explicit ledger entry

## Orchestrator Decision Matrix

| Upstream Role Status | Downstream Action |
|---------------------|-------------------|
| `completed` | Proceed to next role |
| `skipped` | Proceed only if the skipped role is **non-core and explicitly opted-out by Orchestrator with reasonForSkip recorded in evidence ledger**. Core delivery roles (Product Analyst, Architect, Quality Gate Engineer, Supervisor Auditor) are NEVER skippable. Cascade-blocked downstream roles must remain in `skipped` state and the entire pipeline halts at the cascade point — they MUST NOT proceed to the next role. |
| `failed` + retry exhausted (core role) | Set `deliveryStatus = halted-pending-user`; FORBID claiming completion; produce `docs/24-未完成交付报告.md` if user accepts closure |
| `failed` + retry exhausted (non-core role) | Cascade block downstream roles; record in ledger |
| `blocked` | Cascade block downstream roles immediately; if blocked role is core → halted-pending-user |
| `timed-out` | Mark as `lost-session`; retry with backoff per policy. If > 2 roles in chain are `lost-session` → set `deliveryStatus = halted-multi-crash` and STOP dispatch (Rule 3 of halt-and-resume-policy) |
| `lost-session` | Retry with new session per policy. After cumulative > 2 in same delivery → halted-multi-crash |
| `needs-info` | Orchestrator MUST first exhaust local context, then clarify and re-handoff. If still unresolved after 1 retry → halted-pending-user (NOT silent skip) |
| `security-block` | Halt entire chain; notify Quality Gate Engineer + user; `deliveryStatus = halted-pending-user` |
| `cancelled` | User-originated only (see halt-and-resume-policy Rule 5); Halt chain; preserve artifacts; produce closure report |

## Skippable Role Whitelist (可跳过角色白名单)

Only the following roles are eligible for `skipped` status, and ONLY when the Orchestrator records a structured `reasonForSkip` in the evidence ledger that satisfies the role's objective opt-out criteria (see each role's prompt):

- `data-engineer` — when no data model / migration / cross-table consistency change
- `data-contract-designer` — when no new/changed external interface or message schema
- `ui-designer` — when no UI/UX, visual hierarchy, responsive layout, or component behavior change
- `performance-engineer` — when project has no SLA in `docs/01-需求规格书.md` AND no performance regression risk identified by Architect
- `frontend-engineer` — when task scope is backend-only
- `backend-engineer` — when task scope is frontend-only

**Forbidden to skip under any circumstance**: product-analyst, architect, execution-engineer (when implementation needed), quality-gate-engineer, devops-release-engineer, documentation-writer, supervisor-auditor.
