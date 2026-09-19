# Local Governance Reference

This skill is governed by the local specification files configured for the current environment.

Default example in the current environment:
- `assets/constitution.md`
- `assets/tech.md`
- `assets/design.md`

All roles in `software-development-team` must treat the configured local governance files as mandatory baseline constraints before planning, implementation, review, testing, release, or documentation.

## Core mandatory rules

0. 🔴 **RED LINE — 不降级交付基线**：无论用户如何描述任务规模（"简单"、"快速"、"小改动"等），每个开发请求必须走完整的文档链和角色链。禁止以任务简单为由跳过需求文档、计划文档、设计文档、测试文档、评审文档、部署文档或审计文档。不可跨越。
0b. 🔴 **RED LINE — 多 Session 强制**：每个下游角色必须在独立 Session 中执行，禁止在单一 Session 中顺序扮演多个角色。Development Orchestrator 是路由代理，不是角色合并代理。单 Session 回退仅在 `Agent` 工具完全不可用时允许，且必须标记为流程偏差。
1. **Never guess**
   - If requirements, APIs, dependencies, project context, data meaning, or environment details are unclear, ask first.
   - Do not invent assumptions to keep moving.

2. **Follow project reality and existing spec**
   - Respect existing project architecture, constraints, and established patterns.
   - If local governance conflicts with actual project reality, explicitly disclose the deviation and follow the rule: **project reality first, governance second**.
   - 🔴 **project reality 仅指项目代码库的既有架构与依赖，不包括开发机工具链缺失。** 本地环境缺少既定栈所需工具链属于待修复的基础设施问题，必须按 `references/environment-provisioning.md` 自动安装环境，不得据此更换 `tech.md` 或架构设计确定的技术栈。

3. **Do no harm**
   - Avoid breaking existing functionality.
   - For risky refactors or behavior changes, disclose impact before proceeding.

4. **Mandatory execution order for non-trivial work**
   - Analyze current context and existing files
   - Plan before implementation for medium or large tasks
   - Execute in scoped increments
   - Verify behavior, boundaries, and acceptance criteria before claiming completion

5. **Validation is mandatory**
   - No role may claim completion without validation evidence or explicit verification limits.
   - Residual risks, unverified areas, and blockers must be disclosed.

## Engineering rules merged from local spec

- Prefer **KISS**, **DRY**, **Early Return**, **Single Responsibility**, and **descriptive naming**.
- Enforce **type safety**:
  - TypeScript: avoid `any` unless truly unavoidable
  - Python: require type hints on function parameters and returns
- Enforce **defensive programming** for external input, API responses, DB reads, uploaded content, and nullable values.
- **No silent failures**: empty catch blocks and hidden error handling are forbidden.
- Error messages should include enough context to support diagnosis.
- Before creating files, check whether equivalent files already exist.
- Before adding dependencies, inspect existing project dependencies first.

## Frontend expectations

- Prefer the stack and conventions described in the configured technical governance file (for example `tech.md`) unless the project already uses something else.
- Avoid global style pollution.
- Keep non-visual logic out of view components when complexity grows.
- Handle user input, empty state, error state, loading state, and boundary state explicitly.

## Backend expectations

- Respect clear layering and avoid unnecessary cross-layer coupling.
- Validate inputs and external responses strictly.
- Avoid `SELECT *`.
- Avoid unexplained magic values.
- Prefer explicit contracts and stable error handling.

## Data and database expectations

- Use clear, explicit field definitions and constraints.
- Prefer snake_case for database identifiers.
- Follow API and JSON contract consistency.
- For schema design, align with audit-field and soft-delete expectations from the configured technical governance file when applicable.

## Workflow governance expectations

The team must be able to explicitly handle all of the following workflow domains:
- 正向标准流程
- 需求变更流程
- 安全管控流程
- 异常问题处理流程

Use these references as mandatory supplements:
- `references/workflow-matrix.md`
- `references/change-management-workflow.md`
- `references/security-governance-workflow.md`
- `references/incident-management-workflow.md`
- `references/forward-development-template.md`
- `references/change-request-template.md`
- `references/security-review-template.md`
- `references/security-assessment-template.md`
- `references/incident-report-template.md`
- `references/workflow-audit-template.md`

## Review and release expectations

- Review must classify blocking issues vs optional suggestions.
- Release guidance must include prerequisites, rollout steps, rollback path, and known risks.
- Documentation must not fabricate facts and must stay aligned with actual implementation and test results.
