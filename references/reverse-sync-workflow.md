# Reverse Sync Workflow（PRD 反向同步工作流）

Use this workflow when code, schema, UI, or runtime behavior has been modified and the corresponding PRD / design / contract / test documents are NOT yet updated. This is the inverse of `change-management-workflow.md`: the source of change is the implementation, and the obligation is to back-fill `docs/`.

This workflow exists because "边测边改 / hotfix" is a common pattern that silently desynchronizes PRD from code, leading to:
- Auditors signing off on obsolete acceptance criteria
- Downstream contract / test artifacts drifting from reality
- New iterations starting from a stale baseline

## Trigger conditions

Reverse sync MUST be triggered when ANY of the following is detected:

1. **Code-level signals**
   - New / changed / deleted Controller endpoints, REST/RPC routes, scheduled tasks, message consumers
   - New / changed / deleted database tables, columns, indexes, migration scripts
   - New / changed / deleted user-facing pages, routes, or interaction flows
   - New / changed / deleted configuration items that affect runtime behavior
   - Hotfix commits, "边测边改" commits, on-the-fly behavioral changes
2. **Drift-detector signals**
   - `scripts/contract_drift_check.py` returns `warn` or `fail`
   - `scripts/requirement_drift_check.py` returns `warn` or `fail`
   - `scripts/trace_requirements.py` reports gaps for documents that previously passed
3. **Baseline signals**
   - `scripts/baseline_snapshot.py` shows new contract endpoints / FR-ids / schema fields not present in the latest baseline

## Mandatory steps

1. **Lock the drift item**
   - Record the exact drift unit: `(method, path)` for APIs, `(table, column)` for schema, `(routeName, action)` for UI flow, `(configKey, oldValue→newValue)` for config.
   - Capture commit hash / PR id as `driftSource`.
2. **Determine origin against `docs/01-需求规格书.md`**
   - Find the closest existing FR / NFR by keyword + role + action.
   - Choose ONE of the three closure paths below.
3. **Choose closure path**
   - **Path A — Existing FR amendment**: the drift is a refinement of an existing requirement. Update the affected FR's acceptance criteria in `docs/01-需求规格书.md`.
   - **Path B — New FR/NFR creation**: the drift introduces user-visible behavior with no existing FR. Allocate a new FR/NFR id (continue the existing numbering scheme), and add a full FR entry.
   - **Path C — Internal-only change**: the drift has no user-visible behavior change (pure refactor, internal optimization). Append a row to `docs/19-内部变更登记.md` with commit hash, motivation, and risk note. NEVER use this path to hide a behavior-affecting change.
4. **Cascade to downstream documents**
   - `docs/04-详细设计说明书.md` (always)
   - `docs/07-接口数据契约.md` (when API/contract drift)
   - `docs/10-单元测试用例.md`, `docs/12-集成测试用例.md`, `docs/16-E2E测试用例.md` (when behavior drift)
   - `docs/18-部署说明.md` (when config / deployment drift)
5. **Re-run drift checks**
   - `scripts/contract_drift_check.py` MUST return `pass`
   - `scripts/requirement_drift_check.py` MUST return `pass`
   - `scripts/trace_requirements.py` MUST return `pass`
6. **Supervisor-Auditor closure check**
   - Verify FR id mapping is complete
   - Verify all cascaded documents are updated
   - Append a `reverse_sync_event` entry to the evidence ledger with closure timestamp
   - Set `prdDriftClosed: true` in the audit record

## Output expectations

- `reverseSyncTasks[]` entries on the role results that performed the back-fill
- Updated `docs/01-需求规格书.md` (Path A or B) OR `docs/19-内部变更登记.md` (Path C)
- Updated downstream documents (per Step 4)
- Drift-check reports attached to evidence ledger as `qualityGates`
- Audit record with `prdDriftClosed: true`

## Prohibited behavior

- **Silent merge**: code changes merged without any PRD/design/contract update is FORBIDDEN. Such commits MUST be blocked at the PRD Sync Gate.
- **Commit message as substitute**: commit messages, PR descriptions, or chat messages are NEVER an acceptable substitute for PRD back-fill.
- **Using Path C as escape hatch**: routing a behavior-affecting change to `19-内部变更登记.md` to avoid PRD work is FORBIDDEN. Auditor MUST cross-check Path C entries against drift detector output and reject misclassification.
- **Closing reverse-sync task without re-running drift checks**: closure requires fresh `pass` status from all three drift scripts.

## Role responsibilities

- **product-analyst**: owns Path A / Path B execution. Decides FR mapping, writes/updates FR entries.
- **documentation-writer**: owns cascade to `04 / 07 / 10 / 12 / 16 / 18`.
- **architect**: consulted when drift impacts architecture / data model.
- **quality-gate-engineer**: re-runs drift checks; gates closure.
- **supervisor-auditor**: final closure check; populates `reverse_sync_event` in evidence ledger.
- **development-orchestrator**: dispatches reverse-sync tasks when PRD Sync Gate fails; blocks `devops-release-engineer` until all tasks closed.

## Relationship with other workflows

- `change-management-workflow.md` — forward direction (PRD → code). Reverse sync is its mirror.
- `forward-development-template.md` — used when Path B creates a new FR; the new FR still goes through the standard forward template at refinement stage.
- `incident-management-workflow.md` — incident hotfixes ALWAYS trigger reverse sync after the incident is contained. Hotfix closure is incomplete until reverse sync closes.
