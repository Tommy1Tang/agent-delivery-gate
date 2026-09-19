# Qoder Runtime Adapter

Use this adapter when loading `software-development-team` into a Qoder-style agent runtime.

## Qoder Runtime Characteristics

- Qoder provides the `Agent` tool for dispatching subagents (Browser, Guide) and the `Skill` tool for invoking skills.
- Qoder also exposes a `Task`-style dispatching mechanism that lets the main session delegate a fully scoped sub-task to a fresh agent context. This is the **REQUIRED** way to run downstream development roles in independent sessions.
- The `Skill` tool can be used to invoke this skill itself as a reusable workflow.

## Mapping

- Load roles from `assets/config/agent-team-config.json` or YAML.
- Bind each `promptFile` to the corresponding role definition.
- Use `mode.unified-large-delivery.route` as the default route.
- Use `harness.schemas` for structured payload validation.

## Execution Rules

### 🔴 RED LINE — Primary Strategy: Independent Sessions (MANDATORY)

- The Development Orchestrator **MUST** dispatch every downstream role into its **own independent session** via the `Task` / `Agent` dispatching mechanism.
- Each dispatched session receives its handoff payload (built by `scripts/build_handoff.py` or `scripts/orchestrate.py`) and its role prompt as the only context. It MUST NOT inherit the Orchestrator's prior conversation memory.
- After the role finishes, the Orchestrator pulls back the result, validates it against `schemas/role-result.schema.json`, appends an entry to the evidence ledger with `sessionMode: "independent-session"`, and only then dispatches the next role (or the next parallel layer per `parallelGroups`).
- The Orchestrator is forbidden from impersonating downstream roles in the main session under any of the following situations:
  - The runtime supports `Task`/`Agent` dispatching (it does in Qoder).
  - The user has not explicitly authorized fallback in writing.
  - The role is `browser-e2e-engineer` (E2E must always run in an independent Browser-equipped session).

### Secondary Strategy: Browser / Guide Subagents

- For browser-based verification (E2E user-journey execution by `browser-e2e-engineer`), use the `Agent` tool with `subagent_type: "Browser"`.
- For documentation/Qoder guidance, use the `Agent` tool with `subagent_type: "Guide"`.

### 🟡 Fallback Strategy: Single-Session Mode (RESTRICTED)

Single-session execution is a **fallback only** and requires ALL of:
1. The runtime physically cannot dispatch independent sessions (e.g. tool unavailable, sandbox denies it).
2. The user has explicitly approved single-session mode in the current conversation.
3. The orchestrator records `evidenceLedger.fallbackTrigger` with the reason, approver, and timestamp before any role is executed.
4. Each `roleRuns[*].sessionMode` is set to `"single-session-fallback"` (not `"independent-session"`).
5. The final auditor cites the fallback in `docs/19-监督审计.md` and states explicitly that delivery is NOT equivalent to independent-session execution.

If any of the five conditions fails, single-session is forbidden and the delivery must HALT pending user.

### Role-Boundary Markers (when single-session fallback is approved)

When single-session fallback is the only feasible mode, before each role transition, insert an explicit role-boundary marker:
```
--- ROLE: <role-name> | STAGE: <stage> | SESSION-MODE: single-session-fallback ---
```
Pass only the necessary handoff context (previous outputs, owned files, constraints) and record each role execution in the evidence ledger.

## Handoff Template

Each role handoff in the main session should include:
- Role name and stage
- Current task summary
- Workflow domain
- Required inputs and files to read
- Expected outputs or owned documents
- Constraints from local governance
- Whether the role should edit files, review files, or produce analysis only

## Integration with Qoder Skills

This skill can be invoked via the `Skill` tool:
```
Skill(skill="software-development-team", args="<user request>")
```

The skill entry point (`SKILL.md`) defines the full workflow. The orchestrator reads the references, routes the task, and dispatches roles as described above.

## Harness Validation

Run from the skill root:
```text
python scripts/check_skill_integrity.py <skill-root>
python scripts/validate_delivery.py --skill-root <skill-root> --project-root <project-root>
python scripts/run_golden_tests.py --skill-root <skill-root>
python scripts/compatibility_check.py <skill-root>
```

## Retry Execution Pseudocode

Orchestrator 必须按以下伪代码处理角色派发失败：

```pseudocode
function dispatchWithRetry(role, handoff):
    retryPolicy = handoff.retryPolicy   // { maxRetries, backoffMs, retryableErrors, nonRetryableErrors }
    attempt = 0
    lastError = null

    while attempt <= retryPolicy.maxRetries:
        try:
            result = Agent.dispatch(role.promptFile, handoff)
            if result.status in ["completed", "blocked", "security-block"]:
                return result
        catch error:
            lastError = error
            errorType = classifyError(error)  // -> "timeout" | "session-lost" | "transient" | "blocked" | "security-block"

            if errorType in retryPolicy.nonRetryableErrors:
                // 不可重试错误 → 立即停止
                ledger.roleRuns[role.id].status = errorType
                return { status: errorType, error: lastError }

            if errorType not in retryPolicy.retryableErrors:
                // 未知错误类型 → 视为不可重试
                ledger.roleRuns[role.id].status = "unknown-error"
                return { status: "unknown-error", error: lastError }

        // 指数退避
        waitMs = retryPolicy.backoffMs * (2 ^ attempt)
        log("Retrying {role.id} in {waitMs}ms (attempt {attempt+1}/{retryPolicy.maxRetries})")
        sleep(waitMs)
        attempt += 1

    // 重试耗尽
    ledger.roleRuns[role.id].status = "retry-exhausted"
    ledger.roleRuns[role.id].retryCount = attempt
    checkCircuitBreaker(role.id)
    return { status: "retry-exhausted", error: lastError }

function classifyError(error):
    if error.code == "TIMEOUT" or elapsed > handoff.timeoutMs:
        return "timeout"
    if error.code in ["SESSION_LOST", "AGENT_UNAVAILABLE", "CONNECTION_RESET"]:
        return "session-lost"
    if error.code in ["RATE_LIMITED", "TRANSIENT_FAILURE"]:
        return "transient"
    if error.message contains "security" or "blocked":
        return "security-block"
    return "unknown"

function checkCircuitBreaker(roleId):
    exhaustedRoles = ledger.roleRuns.filter(r => r.status == "retry-exhausted")
    if exhaustedRoles.length >= 2:
        ledger.deliveryStatus = "halted-circuit-broken"
        generateIncidentReport()
        HALT  // 停止所有后续派发
```

**规则摘要**：
- 每次重试必须记入 ledger (`retryCount++`)
- 连续 2 个角色重试耗尽 → Circuit Breaker 触发
- `security-block` 和 `blocked` 永远不重试
- 重试间隔为指数退避：5s → 10s → 20s
- 见 `references/retry-policy.md` 获取完整策略和角色特定超时
