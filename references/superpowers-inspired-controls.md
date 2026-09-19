# Superpowers-Inspired Delivery Controls

This reference adapts portable workflow controls from `obra/superpowers` into the
software-development-team skill. It is intentionally tool-neutral: use these
rules with Qoder, Codex subagents, or the single-session fallback.

## Planning Discipline

- Plans and task lists must assume the executor has no hidden context.
- Before implementation, map the relevant file structure and name the exact
  files to create, modify, test, or inspect.
- Break implementation work into independently verifiable slices. A normal slice
  should be small enough for one focused action and should end with a check.
- Each implementation slice should state:
  - objective and acceptance signal
  - files to read first
  - files allowed to change
  - Red, Green, and Refactor steps when code behavior changes
  - exact verification command or manual verification path
- Do not leave placeholder instructions such as "implement the rest" or
  "add tests later".

## Execution Discipline

- Code-changing roles use test-driven development by default.
- Red: write or identify the failing test first and record the command plus the
  expected failure.
- Green: make the smallest production change that passes the failing test.
- Refactor: clean up while keeping the same tests green.
- If a role cannot use TDD, it must record the reason and provide equivalent
  regression evidence before claiming completion.

## File Handoff Discipline

Use file handoffs when context pressure, role count, or delivery size makes inline
handoffs fragile.

- Brief path pattern: `docs/handoffs/{roleId}/task-{taskId}-brief.md`
- Report path pattern: `docs/handoffs/{roleId}/task-{taskId}-report.md`
- Review package pattern: `docs/handoffs/{roleId}/task-{taskId}-review-package.md`
- Progress ledger: `docs/handoffs/progress.md`

The brief is the single source of task requirements. The report should return
only status, changed files, verification evidence, blockers, risks, and next-role
notes.

## Review Discipline

- Run a pre-flight review of the plan before the first implementation task.
- After each implementation slice, review both spec compliance and code quality.
- Critical or important findings require a fix and a re-review before the next
  dependent role proceeds.
- Run one final whole-delivery review before release, documentation, or audit
  closure.

## Verification Before Completion

- Do not claim completion from memory, intent, or an agent report alone.
- Identify the relevant verification command or inspection.
- Run it freshly.
- Read the result.
- Record the command, exit code, summary, and artifact path where applicable.
- Completion claims without fresh evidence must be treated as blocked.

## Workspace And Closure Discipline

- Detect whether the task is already running in an isolated workspace before
  changing branch or worktree strategy.
- Prefer the runtime's native isolation mechanism when it exists.
- Before merge, PR, release, or discard recommendations, verify tests and inspect
  the current diff.
- Never discard local work without explicit user confirmation.
- At closure, present the concrete outcome and any remaining risk instead of a
  generic "done" claim.
