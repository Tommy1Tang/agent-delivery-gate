# Session Failure Recovery

This document defines recovery procedures when an Agent session crashes, times out, or loses communication during `software-development-team` orchestration.

> **Coupled with `references/halt-and-resume-policy.md`.** Whenever this document says "escalate to user", "offer fallback", or "may be compromised", the corresponding halt state in halt-and-resume-policy is BINDING. Soft phrasings here are NOT optional.

## Detection Mechanisms

### 1. Timeout Detection
The Orchestrator must track wall-clock time since dispatching each role:
- If `durationMs` from initial dispatch exceeds the handoff `timeoutMs`, mark the session as `timed-out`
- Timeout detection runs every 30 seconds for active sessions

### 2. Session Crash Detection
A session is considered crashed (`lost-session`) when:
- The `Agent` tool returns an error instead of a role result
- No response is received within `timeoutMs`
- The session terminates abnormally (platform-level error)

### 3. Communication Loss
- If the Orchestrator cannot reach the spawned session, wait for `timeoutMs` before declaring `lost-session`
- Do not immediately assume crash on first communication gap

## Recovery Procedures

### Recovery Path A: Timed Out Session
```
1. Orchestrator detects timeout
2. Record timed-out in evidence ledger:
   write_evidence_ledger.py --role-run "roleId|timed-out|independent-session|Timed out after Xms|0|0|timeout"
3. Apply retry policy:
   - If retryCount < maxRetries → retry with new session after backoffMs
   - If retries exhausted → escalate to user
4. Record retry attempt in ledger
```

### Recovery Path B: Lost Session (Crash)
```
1. Orchestrator detects lost-session
2. Record in evidence ledger:
   write_evidence_ledger.py --role-run "roleId|lost-session|independent-session|Session crashed|0|0|session-crash"
3. Check partial artifacts:
   - Inspect project filesystem for any partial output the session may have written
   - Record found artifacts in ledger
4. Apply retry policy:
   - If retryable → retry with new session
   - If retries exhausted → escalate, consider single-session-fallback
5. If switching to single-session-fallback:
   - Disclose fallback explicitly
   - Supervisor Auditor must flag this deviation
```

### Recovery Path C: Agent Tool Error
```
1. Orchestrator receives error from Agent tool (not from role)
2. Classify error:
   - Network error → retryable (transient)
   - Permission denied → non-retryable (escalate)
   - Quota exceeded → non-retryable (escalate)
   - Unknown → retry once, then escalate
3. Record in evidence ledger with error context
```

## Partial Artifact Handling

When a session crashes mid-execution:

| Scenario | Handling |
|----------|----------|
| Document was fully written | Accept the artifact, record as partial success |
| Document is partially written | Backup the partial file to `.delivery/partial/`, retry produces fresh copy |
| Code was partially changed | Use git status to identify changes; revert if incomplete |
| No artifacts found | Clean retry with full handoff |

## Chain State Preservation

Before any retry, the Orchestrator must snapshot the current state:

```
.delivery/
├── evidence-ledger.json          ← main ledger
├── backups/
│   ├── evidence-ledger-before-retry-N.json  ← pre-retry snapshot
│   └── partial/                              ← partial artifacts from crashed sessions
└── orchestration-plan.json
```

## User Escalation Triggers

Escalate to user when (each trigger MUST set `deliveryStatus` per halt-and-resume-policy):

- Retries exhausted for any role (3 total attempts including initial) → `halted-pending-user` (Rule 1)
- `security-block` detected (immediate escalation) → `halted-pending-user`
- `Agent` tool reported unavailable by runtime adapter after 2 retry attempts → enter single-session-fallback per `retry-policy.md` Single-Session Fallback section (NOT a soft "offer"; only when adapter declares `agentToolAvailable: false`)
- More than 2 roles in the chain are `lost-session` → `halted-multi-crash` (Rule 3); STOP dispatch immediately, do NOT continue "best effort"
- Circuit breaker triggered for any role type → `halted-circuit-broken` (Rule 2); auto-generate `docs/23-事故报告.md`
- Core role `failed` after retry exhaustion → `halted-pending-user` (Rule 4); FORBID claiming "已交付"/"部分交付"

🔴 Forbidden phrasings when these triggers fire:
- "交付可能受损" 但继续派发下游角色
- "提供单 Session fallback" 作为主动选项
- "暂时收口" / "后续处理" 而不生成《未完成交付报告》

## Orchestrator Handoff Amendments for Recovery

When re-handoffing after a failure, add to the handoff:
```json
{
  "recoveryContext": {
    "previousAttempts": 2,
    "previousError": "timed-out after 300s",
    "partialArtifacts": [".delivery/partial/需求规格书-partial.md"],
    "resumeFrom": "last-known-good checkpoint",
    "instruction": "Retry with awareness of previous failure. If the same root cause persists, return 'blocked' instead of retrying."
  }
}
```

## Evidence Ledger Recovery Entries

Each recovery action is traceable via the evidence ledger:

```json
{
  "roleId": "product-analyst",
  "status": "timed-out",
  "durationMs": 300000,
  "retryCount": 0,
  "blockedBy": ["timeout"],
  "sessionMode": "independent-session",
  "summary": "Timed out after 300s. Retrying with new session."
}
```
