# Independent Session Orchestration

Use this reference when Development Orchestrator is executed in an environment that supports spawning or dispatching role agents into separate sessions.

## Goal

Keep role boundaries real.
Development Orchestrator should coordinate the workflow, but downstream work should be executed by separate role agents in isolated sessions whenever possible.

## Required behavior

For each downstream role:
1. Prepare a focused handoff
2. Spawn or dispatch the role in an isolated session
3. Include only the required context, inputs, ownership expectations, and expected outputs
4. Wait for the role result
5. Validate whether the output is sufficient for the next handoff
6. Route to the next role

## Handoff template

Each handoff should include:
- role name
- current task summary
- workflow domain
- required inputs
- relevant files to read
- expected outputs or owned documents
- constraints from local governance
- whether the role should edit files, review files, or produce analysis only

## Example orchestration sequence

1. Product Analyst session
   - input: user request, existing docs, constraints
   - output: `docs/01-需求规格书.md`

2. Architect session
   - input: approved需求规格书
   - output: `docs/02-开发计划.md`, `docs/03-任务清单.md`, `docs/04-详细设计说明书.md`

4. Implementation role sessions
   - input: approved design and relevant contracts
   - output: code and implementation artifacts

5. Quality Gate Engineer session
   - input: implementation + requirements + acceptance criteria
   - output: test cases, test reports, code review, and security review

6. DevOps and Release Engineer / Documentation Writer / Supervisor Auditor sessions
   - route according to workflow domain and release needs

## Fallback

If isolated role sessions are unavailable in the runtime:
- explicitly disclose that the environment forced single-session execution
- still preserve role boundaries in sequence
- do not pretend the fallback is equivalent to independent session execution
