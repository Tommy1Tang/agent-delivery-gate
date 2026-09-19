# Autonomous Update Policy

This policy defines how `software-development-team` agents should behave when a user asks for updates, optimization, fixes, or implementation work.

## Default Behavior

Agents should update directly when the requested change is clear, local context is available, and the action is non-destructive.

Do not pause for manual confirmation for ordinary work such as:

- editing prompts, references, templates, schemas, scripts, docs, or project code within the requested scope
- applying recommendations from a previous report
- running local validation commands
- installing missing development toolchains required by the established tech stack (per `references/environment-provisioning.md` — pinned versions only: JDK 17 / Node.js 22 / Maven 3 / Python 3.12 via `winget install`; PostgreSQL/Redis are NEVER installed locally — dev machines connect to the deployment server instances instead)
- updating generated delivery artifacts or evidence records
- making conservative implementation choices that follow existing project or skill patterns

## When To Ask

Ask the user only when continuing would be risky or impossible without a human decision:

- destructive actions such as deleting user work, resetting history, or overwriting unrelated changes
- credentials, secrets, account access, or irreversible external operations
- ambiguous scope where two or more reasonable choices would produce incompatible outcomes
- missing inputs that cannot be inferred from local files, reports, or the current request
- actions blocked by sandbox, permissions, or required approval from the runtime

## Execution Standard

When direct update is allowed:

1. inspect the relevant local files first
2. make the smallest sufficient change
3. preserve unrelated user changes
4. run the applicable validation scripts
5. update evidence or reports when the work changes delivery status
6. disclose what changed, what was validated, and any remaining risks

## Orchestrator Requirement

Development Orchestrator must pass this policy in every handoff. Downstream roles must treat it as a governance constraint and must not return "please confirm" as a blocker when the requested update can be safely performed.
