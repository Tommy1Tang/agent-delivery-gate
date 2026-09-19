# Change Management Workflow

Use this workflow when a requirement changes after planning or implementation has already started.

## Trigger conditions
- Scope changes
- Acceptance criteria changes
- UI/UX direction changes
- Interface or data contract changes
- Priority changes
- Milestone or release-date changes
- Dependency or environment changes

## Mandatory steps
1. Capture the requested change
   - what changed
   - who requested it
   - why it changed
   - when it was raised
2. Clarify baseline impact
   - what remains unchanged
   - what is invalidated
   - whether current implementation must stop or can continue partially
3. Perform structured impact analysis
   - requirement scope
   - architecture/design
   - task breakdown
   - interfaces / contracts
   - tests / acceptance criteria
   - release plan / deployment
   - risks / cost / timeline
4. Re-baseline artifacts when needed
   - `docs/01-需求规格书.md`
   - `docs/02-开发计划.md`
   - `docs/03-任务清单.md`
   - `docs/04-详细设计说明书.md`
   - test docs under `docs/`
   - `docs/18-部署说明.md`
5. Obtain explicit user confirmation for non-trivial change impact
6. Resume implementation only after changed baseline is clear
7. Re-verify changed and affected areas
8. Auditor checks change traceability and completeness

## Output expectations
- Changed items
- Impact summary
- Replanned tasks
- Risks and tradeoffs
- Updated acceptance criteria
- Updated document list

## Prohibited behavior
- Quietly implementing change without impact analysis
- Continuing with outdated plan after major scope change
- Claiming completion against obsolete acceptance criteria
