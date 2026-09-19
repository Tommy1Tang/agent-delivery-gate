# Codex Subagents Runtime Adapter

Use this adapter when the runtime supports spawning separate role sessions.

## Mapping

- Development Orchestrator remains in the parent session.
- Each downstream role is dispatched to a separate subagent/session.
- The handoff payload should follow `schemas/handoff.schema.json`.
- The result should follow `schemas/role-result.schema.json` when the runtime supports structured return.

## Execution Rules

- Pass only role-specific context.
- Assign file ownership clearly.
- Wait for role result before next dependent role.
- Record role run into the evidence ledger.
- If subagents are unavailable, disclose `single-session-fallback`.

