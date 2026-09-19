# Halt and Resume Policy

This document defines how `software-development-team` MUST handle interrupts, escalations, and pending-user states so that no task can silently be declared complete after being interrupted.

This policy is **mandatory** and overrides any softer wording in `retry-policy.md`, `session-failure-recovery.md`, `runtime-adapters/*`, or role prompts.

## Halt States (新增交付级状态)

The Orchestrator MUST track delivery-level state in the evidence ledger under `deliveryStatus`.

| Value | Meaning | Allowed transitions |
|-------|---------|---------------------|
| `in-progress` | Normal execution | → `halted-pending-user` / `halted-circuit-broken` / `halted-multi-crash` / `halted-user-cancel` / `completed` / `failed-closed` |
| `halted-pending-user` | Awaiting user clarification or decision (needs-info / retries exhausted) | → `in-progress` (after user reply) / `halted-user-cancel` |
| `halted-circuit-broken` | One role exceeded circuit-breaker threshold | → `in-progress` (after explicit user clearance) / `halted-user-cancel` |
| `halted-multi-crash` | More than 2 roles in `lost-session` | → `in-progress` (after explicit recovery plan) / `halted-user-cancel` |
| `halted-user-cancel` | User explicitly stopped the task | terminal — must produce `docs/24-未完成交付报告.md` |
| `failed-closed` | Core role failed beyond recovery and the user accepted closure as failed | terminal — must produce `docs/24-未完成交付报告.md` |
| `completed` | All gates passed, Auditor verdict = 通过 | terminal |

**Forbidden value transitions**:
- 🔴 Any halted-* state → `completed` directly. Must first return to `in-progress` and pass the full closing chain.
- 🔴 Any halted-* state must NOT be silently rewritten to `in-progress` without an evidence ledger entry recording the resume trigger.

## Rule 1 — Retries Exhausted / `needs-info` Escalation (修复 #1, #7)

When ANY role's retries are exhausted, OR returns `needs-info`, the Orchestrator MUST:

1. Mark `deliveryStatus = halted-pending-user` in evidence ledger.
2. Record `pendingUser`:
   ```json
   {
     "roleId": "<role>",
     "trigger": "<retry-exhausted|needs-info>",
     "questionsForUser": ["..."],
     "exhaustedLocalContext": ["constitution.md", "tech.md", "<docs read>"],
     "raisedAt": "<ISO 8601>",
     "responseDeadline": "<ISO 8601, +48h>"
   }
   ```
3. **Before asking the user**, the Orchestrator MUST exhaust local context first:
   - Read `references/local-governance.md`, `references/team-overview.md`, `references/team-workflow.md`
   - Read upstream role outputs and prior `evidence-ledger.json`
   - Search the project for similar prior decisions
   - Only when none of the above resolves the ambiguity may the question be raised to the user
4. While `halted-pending-user` is set:
   - 🔴 The Orchestrator MUST NOT call Supervisor Auditor.
   - 🔴 The Orchestrator MUST NOT write a "最终汇总" or claim completion.
   - 🔴 `validate_delivery.py` MUST output FAIL (see content-gate rules) until the user resumes.
5. If `responseDeadline` passes with no user reply:
   - Auto-transition to `failed-closed`
   - Generate `docs/24-未完成交付报告.md` per Rule 6

## Rule 2 — Circuit Breaker Closure (修复 #2)

When a role triggers `circuit-broken`, the Orchestrator MUST:

1. Set `deliveryStatus = halted-circuit-broken`.
2. Auto-generate `docs/23-事故报告.md` (incident report) summarizing the failure pattern (per `references/incident-report-template.md`).
3. Surface to Supervisor Auditor — Auditor MUST record this as a process deviation in `docs/19-监督审计.md`.
4. 🔴 Forbidden: writing "最终汇总", calling Auditor for verdict = 通过, or marking the delivery as `completed`.
5. Resume requires:
   - User explicit clearance message recorded in evidence ledger (`circuitBreakerCleared: { user: "...", reason: "...", clearedAt: "<ISO>" }`)
   - The previously-broken role MUST be re-dispatched with a fresh handoff
   - All downstream roles MUST re-run, NOT skip
6. If user does not clear within 14 days → auto-transition to `failed-closed` with mandatory Rule 6 closure report.

## Rule 3 — Multi-Role Crash (修复 #4)

When more than 2 roles in the chain are `lost-session`, the Orchestrator MUST (NOT "may"):

1. Immediately set `deliveryStatus = halted-multi-crash`.
2. STOP all dispatch — no new role handoffs allowed.
3. Surface to user with a structured recovery plan request.
4. 🔴 Forbidden: continuing to dispatch downstream roles "best effort".
5. Resume requires user-approved recovery plan recorded in ledger as `multiCrashRecoveryPlan`.

## Rule 4 — Core Role `failed` After Retry (修复 #5)

When ANY of the following core roles ends with `failed` after retry exhaustion:

- `product-analyst`
- `architect`
- `quality-gate-engineer`
- `supervisor-auditor`
- `execution-engineer` (when implementation is required)

The Orchestrator MUST:

1. Set `deliveryStatus = halted-pending-user` (not `completed`).
2. 🔴 Forbidden: writing "最终汇总" with phrasing such as "已交付"/"部分交付"/"基本完成".
3. Generate `docs/24-未完成交付报告.md` per Rule 6 if user accepts closure.

## Rule 5 — User-Initiated Cancellation (修复 #6, #9)

`cancelled` status MUST satisfy ALL of the following — otherwise it is rejected:

1. Originated from a user message (NOT Orchestrator self-judgment, NOT runtime auto-decision).
2. Recorded in evidence ledger with `cancellationOrigin: "user"`, `userMessageRef: "<conversation turn id or quote>"`, `cancelledAt: "<ISO>"`.
3. The Orchestrator MUST set `deliveryStatus = halted-user-cancel`.
4. The Orchestrator MUST produce `docs/24-未完成交付报告.md` per Rule 6 BEFORE surfacing any final summary.
5. 🔴 Forbidden: Orchestrator self-cancelling for any reason. Runtime errors → use `lost-session` / `timed-out` / `circuit-broken`. Scope shrink → use change-management workflow, not cancellation.

User signals like "先这样吧", "算了", "差不多了", "停一下" MUST be treated as a request that REQUIRES explicit confirmation before being recorded as cancellation. The Orchestrator MUST ask back: "请确认是否取消本次交付。取消后会生成《未完成交付报告》并标记为 halted-user-cancel。" The recorded answer (yes/no) is the cancellation evidence.

## Rule 6 — Mandatory Closure Report on Halt

For `halted-user-cancel`, `failed-closed`, `halted-circuit-broken` (>14d), or `halted-multi-crash` (no recovery plan), the Orchestrator MUST produce `docs/24-未完成交付报告.md` containing:

- `deliveryStatus` value and reason
- Halted role(s) and last successful role
- Roles that ran vs. were skipped
- Documents that were produced vs. missing
- Validation evidence collected so far
- Known risks and unresolved blockers
- Required follow-up actions
- Confirmation that NO "通过" verdict was issued

🔴 Forbidden alternatives:
- "已完成（部分）"
- "暂时收口" without a closure report
- silently leaving the ledger in `in-progress`

## Rule 7 — Auditor and Validator Behavior on Halt

- `validate_delivery.py` MUST output `status=fail` whenever evidence ledger has `deliveryStatus != "completed" / "in-progress"`. (See `validate_delivery.py` content-gate `_scan_delivery_status_halted`.)
- Supervisor Auditor MUST refuse to issue verdict = 通过 when `deliveryStatus` starts with `halted-` or equals `failed-closed`.
- Documentation Writer MUST NOT mark delivery as final while `deliveryStatus` is non-terminal.

## Schema Anchor

The corresponding schema fields live in:

- `schemas/role-result.schema.json` → `cancellationOrigin` (limited to `"user"`)
- `schemas/evidence-ledger.schema.json` → `deliveryStatus`, `pendingUser`, `circuitBreakerCleared`, `multiCrashRecoveryPlan`, `cancellationEvidence`

If those schema fields are missing in a runtime, the Orchestrator MUST still record them as free-form keys; missing the keys is itself a process deviation that the Auditor MUST flag.
