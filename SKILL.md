---
name: software-development-team-v2
description: Reusable multi-agent software development team for Qoder (v2). Turns development requests into routed workflows with planning, architecture, implementation, validation, review, release, and documentation. Use when building features, fixing bugs, designing technical solutions, planning implementation, or setting up role-based software delivery workflows.
---

# Software Development Team

Use this skill as a reusable software delivery team skeleton.

## Mandatory local governance

This skill must incorporate and obey the local development specifications configured for the current environment.

Default example in the current environment:
- `assets/constitution.md`
- `assets/tech.md`
- `assets/design.md`

Read and apply `references/local-governance.md` as the normalized governance summary for this skill.
Read and apply `references/autonomous-update-policy.md` as the default execution policy for direct updates.
Read and apply `references/superpowers-inspired-controls.md` for plan granularity, TDD execution, file handoffs, review loops, and verification-before-completion discipline.

Before any software-development response, implementation, review, or planning step, treat the configured local governance files as mandatory governance, not optional references.

## Autonomous update policy

When the user asks to update, optimize, fix, implement, or apply recommendations, proceed with the update directly when the requested scope is clear and the action is non-destructive.

Do not stop for manual confirmation for ordinary local edits or validation. Ask only when the action is destructive, externally irreversible, blocked by permissions, or genuinely ambiguous after inspecting local context.

## Core workflow

1. Read `references/team-overview.md` for the canonical role map and mandatory full-delivery path
2. Read `assets/config/skill-process.json` — the **process truth source** (21 nodes, gates, transitions, rework edges). Run `scripts/next_step.py` each round instead of recalling the workflow from memory
3. Read `references/graph-engineering-laws.md` before changing the process/ontology models — LAW-1..8 are non-negotiable and each is bound to a mechanical gate (C-SDT-01..11)
4. Read `references/team-workflow.md` for the mandatory large-project workflow and handoff flow
5. Read `references/workflow-matrix.md` to determine whether the task is in the forward-development, change-management, security-governance, or incident-handling path
6. Apply the mandatory governance from the environment-configured local governance files
7. Apply `references/autonomous-update-policy.md` so clear non-destructive updates proceed without manual confirmation
8. Read `references/task-template.md` when the request needs structured intake
9. Default every development request to the full formal document chain, validation chain, review chain, release-readiness chain, and audit chain
10. Use prompt files under `assets/prompts/` to bind role-specific agents
   - UI/UX or visual-interface work should include the UI Designer prompt `assets/prompts/design-ui-designer.md` before Frontend Engineer implementation
11. Use `assets/templates/` as the default document skeletons for formal delivery artifacts
12. Use `schemas/` when a runtime needs machine-checkable handoff, role result, artifact manifest, quality gate, audit, or evidence-ledger contracts
13. Use `scripts/check_skill_integrity.py` to validate the skill harness after prompt, config, schema, or template changes
14. Use `scripts/validate_delivery.py` to check whether a project delivery satisfies required and conditional artifact gates
15. When the project supplies `docs/input/` (upstream research already done), run `scripts/validate_input_contract.py` BEFORE Product Analyst starts — see `references/prd-input-contract.md`; verdict `fail` forbids PRD generation. If `docs/input/models/` also carries BPMN/OWL/RDF assets, the same script runs baseline-package gates C-INPUT-01..04 (hash + projection consistency) — see `references/development-baseline-contract.md`; use `scripts/build_baseline_slice.py --capability CAP-X` to compute per-slice inputs
16. Use `scripts/build_handoff.py` to generate a structured handoff payload for a configured role
17. Use `scripts/orchestrate.py` to build a full route plan, handoff payloads, and initial evidence ledger
18. Use `scripts/write_evidence_ledger.py` to append role, command, artifact, and quality-gate evidence
19. Use `scripts/run_golden_tests.py` to regression-test orchestration behavior
20. Use `scripts/observability_report.py` to generate `docs/可观测性报告.md` from the evidence ledger after each delivery
21. Use `references/adapters/` to align with the actual project technology stack
22. Use `references/runtime-adapters/qoder.md` to choose Qoder-specific dispatch behavior when running inside Qoder
23. For non-Qoder environments, use `references/runtime-adapters/codex-subagents.md` or `references/runtime-adapters/single-session-fallback.md`
24. When acting as Development Orchestrator, dispatch every downstream role in its own isolated session when the runtime supports it; otherwise use sequential in-session roles with explicit role-boundary markers
25. Use config files under `assets/config/` when integrating with an agent system

## Routing guide

- All development tasks -> use the full large-project route with requirements, planning, architecture, implementation, validation, review, release, documentation, and audit
- **Deploy-only tasks** (user intent is "部署到生产环境" / "部署到正式环境" / "发布到正式环境" / "deploy to production" / "上线" without new development intent, project code is already locally debugged and ready) -> use the deploy-only fast route: Orchestrator → DevOps Release Engineer (push + verify) → end. See `references/deploy-only-workflow.md`. No Product Analyst, Architect, or implementation roles dispatched.
- PRD-only / requirement analysis tasks (user intent is "help me write PRD" / "analyze requirements" without implementation intent) -> use the demand-analysis-only route: Orchestrator → Product Analyst (interactive elicitation + skeleton + full PRD) → end. No Architect or downstream roles dispatched.
- Requirement change after baseline established -> additionally apply `references/change-management-workflow.md`
- Security-sensitive work -> additionally apply `references/security-governance-workflow.md` and route through Quality Gate Engineer for explicit security review before completion or release
- Production issue / unstable behavior / emergency defect -> additionally apply `references/incident-management-workflow.md`, but still return to the full formal delivery and closure path after containment

## Handoff 文件传递模式（大型项目使用，借鉴 superpowers 的 file handoff）

当项目满足以下任一条件时，Handoff 采用**文件传递模式**代替上下文全量内联：

- Epic ≥ 3
- FR ≥ 20
- 预估总交付文档量 ≥ 10 份

### Brief 文件

Orchestrator 用 `scripts/build_handoff.py --mode=file` 为每个角色生成独立 Brief 文件：
`docs/handoffs/role-{角色名}-brief.md`

Brief 文件包含：
- 当前角色任务范围（仅本角色需要知道的 FR/AC/Epic）
- 上游产物的**文件路径引用**（不内联内容）
- 接口契约/数据契约的关键字段（精简版，仅本角色相关部分）
- 特殊约束或偏离标准流程的说明

### Handoff Prompt 精简

文件模式下，Handoff Prompt 精简为：

```
角色：{角色名} | 阶段：{阶段}
读取 Brief：docs/handoffs/role-{角色名}-brief.md（先读这个——你的完整需求都在里面）
全局约束：隐式必读见 team-overview.md，技术栈见 tech.md
{仅当有特殊警示时追加}
```

### Report 文件

角色完成后写入：
`docs/handoffs/role-{角色名}-report.md`

Report 文件包含：
- changeSet 清单（含自审结论）
- 执行的验证命令与结果
- 给下游角色的关注点
- 风险与阻塞

Orchestrator 先读 report 摘要决定下一步派发，详细内容按需深入读取。

### 规则

- Brief 和 Report 文件在项目完结后统一归档至 evidence ledger
- Handoff 文件模式不影响原有角色 Prompt 的执行逻辑——只是**传递方式**从"全量内联"改为"文件路径引用"
- FR < 20 的小型项目维持原直接 Handoff 模式，不强制文件模式

## Important rules

- 🔴 **RED LINE (红线)**：无论用户如何描述任务（包括但不限于"简单"、"快速"、"随便做一下"、"小改动"、"临时方案"等用语），每个开发请求都必须走完整的文档基线和角色链（需求分析→计划→设计→实现→测试→评审→部署→审计），任何角色不得跳过。这条红线不容跨越，即使看起来"过度工程"也必须遵守。
- 🔴 **RED LINE (多 Session 强制)**：每个下游角色必须在独立 Session 中通过 `Agent` 工具派发执行，禁止在单一 Session 中顺序扮演多个角色。Development Orchestrator 是路由和 handoff 代理，不是角色合并代理。单 Session 回退仅在 `Agent` 工具完全不可用时允许，且必须在审计中标记为流程偏差。
- 🔴 **RED LINE (质量门禁强制返工)**：当 Quality Gate Engineer 或 Security Review 输出 verdict = BLOCK 时，Leader **禁止**标记任务完成、禁止进入文档整理或监督审计阶段。**必须**派发修复任务并重新执行 Code → Verify → Review 循环，直到所有 BLOCK 级别问题清零且 verdict = PASS。
- 🔴 **RED LINE (完成前门禁检查)**：进入"文档整理"和"监督审计"阶段前，Leader 必须确认以下全部为真，否则禁止推进：
  1. Code Review verdict = PASS
  2. Security Review verdict = PASS（或经评估确认不适用）
  3. 所有 BLOCK 级别 finding 均已有对应修复并通过验证
  4. **单元测试硬指标全部达标**：
     - 测试用例实现数 > 0（禁止「仅设计未实现」）
     - `mvn test` / `npm test` 等价命令 BUILD SUCCESS
     - 单元测试覆盖率 ≥ **90%**（项目硬阈值，禁止下调）
     - 集成测试覆盖率 ≥ 80%（项目硬阈值）
     - 测试通过率 = 100%（已运行用例无 fail/error）
     - 「环境问题 / JDK 兼容性 / 工具链不兼容」不能作为跳过指标的理由
  5. **E2E 测试硬指标全部达标（每个项目必须，无例外）**：
     - `docs/E2E测试用例.md` 与 `docs/E2E测试报告.md` 都存在且非空
     - E2E 用例总数 ≥ 1，必须覆盖需求规格书中全部 P0 验收条目（AC P0）
     - E2E 测试通过率 = **100%**（项目硬阈值，禁止下调）
     - 报告中必须包含 `E2E测试通过率：XX.X%` 与 `E2E测试总数：N` 两行机器可读字段
     - E2E 必须由 `browser-e2e-engineer` 在独立 session 中使用 Browser 子代理实际运行，禁止「只设计不执行」「仅手工描述」「环境不可用故跳过」
     - 纯后端交付同样适用：必须通过公开入口（CLI / HTTP）运行至少一个端到端场景并录入 E2E 报告
- 🔴 **RED LINE (自动修复，无需确认)**：当 Quality Gate 或 Security Review 输出 verdict = BLOCK 时，Leader **必须立即自动派发修复任务**，无需向用户询问确认或请示。修复→验证→评审循环必须自动执行，直到 verdict = PASS。禁止将 BLOCK 级别问题呈报给用户并等待指示——这是 Leader 的自动化职责，不是用户决策点。
- 🔴 **RED LINE (返工循环上限)**：返工循环并非无限。详见 `references/retry-policy.md` Rework Loop Cap：
  1. 同一根因（root cause）的返工迭代上限 **5 次**；超出 → `deliveryStatus = halted-pending-user`，必须挂起等用户裁决方向
  2. 整个交付累计返工上限 **10 次**（`observability.reworkCount ≤ 10`）；超出 → 同上挂起
  3. evidence ledger 必须记录 `reworkPerRootCause[根因ID]` 与 `observability.reworkCount`
  4. 🔴 禁止以「已尽力」「环境问题无法修复」「下期处理」绕过上限
- 🔴 **RED LINE (中断与暂停)**：开发过程一旦因重试耗尽 / Circuit Breaker / 多角色 lost-session / 用户取消等触发中断，必须按 `references/halt-and-resume-policy.md` 写入 `deliveryStatus`（halted-pending-user / halted-circuit-broken / halted-multi-crash / halted-user-cancel / failed-closed），不得以「已交付」「部分交付」「基本完成」「暂时收口」措辞包装为完成。
- 🔴 **RED LINE (E2E 全项目必做)**：每个交付都必须派发 `browser-e2e-engineer` 独立 session 运行 E2E 测试，并产出 `docs/E2E测试用例.md` 与 `docs/E2E测试报告.md` 两份交付物。禁止以「项目太小」「仅后端」「无 UI 交互」「问题环境」等理由跳过。Leader 在 validation-and-review 阶段未派发 `browser-e2e-engineer` 或未产出上述两份文档均为交付门禁 BLOCK，必须返工补齐。
- 🔴 **RED LINE (增强声明传递强制)**：当 Architect 产出增强声明（enhancement declarations）时，Orchestrator 必须将声明传递给对应实现角色和 QA。实现角色必须在 roleResult 中回传 `receivedDeclarations`，QA 必须回传 `verifiedDeclarations`。声明未兑现率超过 50% 且无豁免理由时为交付门禁 BLOCK。
- 🔴 **RED LINE (增量交付阶段独立验证)**：采用增量交付编排（OC-H）时，每个阶段必须独立运行 `validate_delivery.py` 并记录独立的 `deliveryGateEvidence`。阶段间必须有明确接力证据（handoverTo/receivedFrom）。回滚范围不得超出当前阶段边界。
- 🔴 **RED LINE (并行执行前置条件)**：并行派发前端和后端角色前，Data Contract Designer 必须已完成且接口契约已冻结。多个同类角色（多 BE 或多 FE）并行时，子任务必须无共享状态依赖。违反并行条件时由 Supervisor Auditor 裁定为 P1 返工。
- 🔴 **RED LINE (环境缺失自动安装，禁止换栈)**：环境预检或任何角色发现开发机缺少既定技术栈所需工具链（Git / JDK 17 / Node.js 22 / Maven 3 / Python 3.12，版本不符视同缺失）时，**必须**按 `references/environment-provisioning.md` 自动安装开发环境（Windows 首选 `winget`，可运行 `scripts/provision_env.py`；全新系统 Python 不可用时先执行 `scripts/bootstrap_env.ps1` 零依赖引导），安装无需用户确认。**禁止**以「环境不支持」「工具链缺失」为由更换 `tech.md` 或架构设计已确定的技术栈。仅当自动安装不可行（无权限 / 无网络 / 需用户交互 / 重试 3 次失败）时写入 `deliveryStatus = halted-pending-user` 问用户，换栈只能由用户明确授权。**PostgreSQL 16 与 Redis 不属于自动安装范围——禁止在开发机本地安装（原生与本地 Docker 均禁止），必须直连部署服务器实例，预检对二者执行的是远程连通性检查。**
- 🔴 **RED LINE (不可跳过角色)**：Architect、Quality Gate Engineer、Browser E2E Engineer、Supervisor Auditor 四个角色在任何场景下不可跳过。其他角色的跳过必须基于 `references/workflow-matrix.md` 中定义的客观条件，禁止以主观描述（如「项目规模较小」「不需要」）作为跳过依据。
- Route before action
- Do not skip planning, even for small changes
- Do not downgrade delivery rigor based on task size
- Do not claim completion without validation
- Do not require manual confirmation for clear non-destructive updates
- Surface divergence instead of hiding it
- Every role must comply with the merged local constitution and technical guidelines
- Development Orchestrator must invoke each downstream role in a separate isolated session with its own role prompt and explicit handoff context
- Every development request must be handled as a large-project-grade delivery workflow

## Resource map

### DO NOT TRIGGER (反例)

以下场景**不应**触发本 skill 的完整交付流程：

1. “帮我看看这段代码” / “解释一下这个函数” — 纯阅读理解，无交付物
2. “改个 typo” / “修改一行配置” — 单文件单行编辑，无需多角色協作
3. “翻译一下这段文字” / “帮我缩写” — 纯文本处理
4. “这个报错是什么意思” — 答疑而非开发任务
5. “帮我生成一个单独的工具函数” — 单函数生成，无需需求/设计/测试链条
6. “运行一下测试” / “帮我执行这个命令” — 纯运维操作，无代码产出
7. “让我看看项目结构” / “查找某个文件” — 纯探索而非开发
8. “对比两个方案的优劣” — 咨询分析而非实施
9. “更新 README” / “加一行注释” — 文档微调，无需 14 角色链条
10. “查一下服务状态” / “查日志” — 纯运维诊断

→ 以上场景应直接由 Agent Mode 处理，不应调用本 skill。

### ASK_USER_TRIGGERS (必须问用户的场景)

当以下场景发生时，Orchestrator **必须**暂停并使用 `ask_user_question` 向用户确认，禁止自行决定：

1. **数据库破坏性操作**：DROP TABLE / 数据迁移不可逆 / 清空生产数据
2. **License 选型**：引入 GPL/AGPL 等传染性协议的依赖
3. **公网暴露**：将 API/端口直接暴露到公网无鉴权
4. **账号凭据**：需要用户提供密钥/token/证书等敏感信息
5. **技术栈重大变更**：替换核心框架（如 Vue→React / PostgreSQL→MySQL）；**新项目首次选型偏离 `tech.md` 基线同样属于本条**。注意：本地环境缺工具链**不触发本条**——那种情况必须先按 `references/environment-provisioning.md` 自动安装环境，只有安装不可行挂起后，才由用户在「装环境 / 换栈」之间裁决
6. **范围溢出**：任务调研发现实际工作量超出原始请求 3 倍以上
7. **不可逆外部操作**：发布到 npm/PyPI、推送到 main、发送群发邮件

→ 其他场景默认按 `autonomous-update-policy.md` 直接执行，不用问。

### References
- `references/team-overview.md`
- `references/team-workflow.md`
- `references/independent-session-orchestration.md`
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
- `references/task-template.md`
- `references/release-checklist.md`
- `references/export-notes.md`
- `references/local-governance.md`
- `references/autonomous-update-policy.md`
- `references/environment-provisioning.md`
- `references/prd-input-contract.md`
- `references/development-baseline-contract.md` — 开发基线包契约（BPMN/OWL/RDF 随 `docs/input/models/` 交付；机器模型只读，防失真门禁 C-INPUT-01..04）
- `references/graph-engineering-laws.md` — 图工程定律（LAW-1..8），修改流程/本体前必读；每条定律绑定机械门禁（C-SDT-01..11）
- `references/orchestrator-advanced-controls.md`
- `references/quality-gate-advanced-controls.md`
- `references/superpowers-inspired-controls.md`
- `references/unified-large-delivery-policy.md`
- `references/adapters/`
- `references/runtime-adapters/qoder.md`
- `references/runtime-adapters/codex-subagents.md`
- `references/runtime-adapters/single-session-fallback.md`

### Assets
- `assets/prompts/` role-specific prompt files
- `assets/templates/` formal delivery document templates
- 技术栈脚手架不随本 Skill 分发：`references/adapters/` 中的适配器描述各栈的目录结构、Dockerfile、docker-compose 与 CI 配置约定，由执行角色按适配器生成，避免绑定特定部署平台
- `assets/templates/project-input/` 上游输入模板（业务调研→能力目录→领域模型→状态机→规则→流程，见 `references/prd-input-contract.md`）
- `assets/config/agent-team-config.yaml`
- `assets/config/agent-team-config.json`
- `assets/config/skill-process.json` 流程真理源（21 节点 / 门禁 / 转移 / 返工边），人类编辑孪生 `skill-process.yaml`
- `assets/config/skill-ontology.json` 受控本体（类/关系/约束，封闭世界假设），人类编辑孪生 `skill-ontology.yaml`

### Schemas
- `schemas/handoff.schema.json`
- `schemas/role-result.schema.json`
- `schemas/artifact-manifest.schema.json`
- `schemas/quality-gate.schema.json`
- `schemas/audit-record.schema.json`
- `schemas/evidence-ledger.schema.json`
- `schemas/metrics.schema.json`
- `schemas/migration-report.schema.json`

### Scripts
- `scripts/check_skill_integrity.py`
- `scripts/validate_delivery.py`
- `scripts/validate_prd_quality.py`
- `scripts/validate_input_contract.py` — 上游输入契约机械校验（`docs/input/` 存在时）：追溯链断链检测 + Must 能力完整性；`docs/input/models/` 存在时附加基线包门禁 C-INPUT-01..04（sha256 哈希 + BPMN/OWL 投影一致性，见 `references/development-baseline-contract.md`）；退出码 0=pass / 1=partial / 2=fail，可 `--gap-list-out docs/输入缺口清单.md`
- `scripts/build_baseline_slice.py` — 按 `capability_id` 机械推导开发切片输入（固定全局 + 切片相关 BPMN/OWL/owner 文档），依据 01-能力目录追溯字段，无 AI 判断
- `scripts/check_input_consumers.py` — 上游输入消费矩阵审计：每个 `docs/input/` 输入与 `models/` 资产必须有角色消费（或在脚本消费白名单），拦截“契约承诺但角色 prompt 未接”的输入断链；已纳入 `check_skill_integrity.py`
- `scripts/next_step.py` — **流程指针推导（状态外置）**：读 `assets/config/skill-process.json` + evidence-ledger + 文件系统，回答“当前节点 / 下一动作”；`--check` 做模型自洽性校验（含 C-SDT-08 守卫语法、C-SDT-09 图物化），`--mermaid-out` 生成派生流程图，`--graph` 导出物化本体图，`--impact X` 查影响面（“某交付物/角色缺失会阻塞谁”），`--record-pointer` 把指针与遍历轨迹写回台账
- `scripts/build_handoff.py`
- `scripts/orchestrate.py`
- `scripts/write_evidence_ledger.py`
- `scripts/observability_report.py`
- `scripts/run_golden_tests.py`
- `scripts/metrics_report.py`
- `scripts/compatibility_check.py`
- `scripts/skill_doctor.py`
- `scripts/preflight_env_check.py` — 工具链就绪预检（Git / JDK 17 / Node 22 / Maven 3 / Python 3.12 版本门禁 + 数据库/缓存连通性 + 本地库配置守卫）；发现缺失时按 `references/environment-provisioning.md` 自动安装，禁止换栈
- `scripts/provision_env.py` — 工具链自动安装器（winget 钉版安装、PATH 刷新、重试 3 次、JSON 记证；内置 PostgreSQL/Redis 本地安装禁令）
- `scripts/bootstrap_env.ps1` — 全新系统零依赖引导（仅需 PowerShell：winget 装 Python 3.12，无 winget 时自动直连 python.org 官方安装包 → 接力 provision_env.py；解决"安装脚本本身需要 Python"的引导问题）
- `scripts/preflight_server_check.py` — 服务器可达性预检（地址由 `DEPLOY_SERVER_IP` 配置）
- `scripts/diagnose.py` — 一键环境诊断（通俗中文提示）
- `scripts/health_monitor.py` — 部署后健康监控

### Tests
- `tests/golden/` orchestration regression cases + environment regression cases（`env-preflight-*` 版本门禁/远程库连通/本地库守卫，`env-provision-*` 安装计划与 PostgreSQL/Redis 本地安装禁令）
- `tests/chaos/` failure injection scenarios

## 执行追踪日志（强制）

每次使用本 skill 执行项目时，**必须**在项目根目录维护两个文件：
1. `docs/agent-timing.md` — Agent 执行时间追踪的原始记录，实时更新
2. `docs/执行日志.md` — 完整的执行过程日志，最终审计阶段生成

### Agent 时间追踪文件（docs/agent-timing.md）

Leader **必须**在项目中维护 `docs/agent-timing.md`，作为 Agent 时间追踪的原始记录文件。该文件在每次派发或完成 Agent 时实时更新。

#### 格式模板

```markdown
# Agent 执行时间追踪

| # | Agent 名称 | 角色 | 任务描述 | 开始时间 | 结束时间 | 运行时间 | 状态 |
|---|-----------|------|---------|---------|---------|---------|------|
| 1 | Sam | Product Analyst | 需求分析 | 2026-05-19T09:22:00 | 2026-05-19T09:27:42 | 5m 42s | 完成 |
| 2 | Felix | Solution Architect | 架构设计 | 2026-05-19T09:28:15 | 2026-05-19T09:34:30 | 6m 15s | 完成 |
| 3 | Iris | Frontend Engineer | 前端实现 | 2026-05-19T09:35:00 | | | 进行中 |
```

#### 维护规则
- Leader 在**派发 Agent 前**必须记录当前时间作为开始时间（使用系统提供的当前时间），在 `docs/agent-timing.md` 中追加一行，状态为「进行中」
- Leader 在**收到 Agent 完成消息时**必须记录结束时间（从系统消息的 Timestamp 获取），更新对应行的结束时间、运行时间和状态
- 运行时间 = 结束时间 - 开始时间，格式为 `Xm Ys`（如 `5m 30s`、`2m 15s`、`1h 12m 30s`）
- `docs/agent-timing.md` 是实时更新的追踪文件，每派发/完成一个 Agent 就更新一次，不得延迟批量更新

### 执行日志文件（docs/执行日志.md）

该文件由 Leader 在最终审计阶段生成，整合 `docs/agent-timing.md` 的完整时间数据。

#### 日志格式

```markdown
# 执行日志

## 项目信息
- **项目名称**: [项目名]
- **启动时间**: [ISO 8601 时间戳]
- **完成时间**: [ISO 8601 时间戳 或 "进行中"]
- **最终状态**: [通过/不通过/进行中]

## 执行记录

| # | 阶段 | 角色/Agent | 开始时间 | 结束时间 | 运行时间 | 任务描述 | verdict | 产出物 | 备注 |
|---|------|-----------|---------|---------|---------|---------|---------|--------|------|
| 1 | 需求分析 | Product Analyst / Sam | 2026-05-19T09:22:00 | 2026-05-19T09:27:42 | 5m 42s | 需求分析与规格书编写 | - | docs/需求规格书.md | |
| 2 | 架构设计 | Solution Architect / Felix | 2026-05-19T09:28:15 | 2026-05-19T09:34:30 | 6m 15s | 技术方案与详细设计 | - | docs/详细设计说明书.md | |
| ... | | | | | | | | | |

## 质量门禁记录

| # | 评审类型 | verdict | BLOCK 原因 | 修复轮次 | 最终通过时间 |
|---|---------|---------|-----------|---------|------------|
| 1 | Code Review | PASS/BLOCK | [原因] | [次数] | [ISO 8601 时间戳] |
| 2 | Security Review | PASS/BLOCK | [原因] | [次数] | [ISO 8601 时间戳] |

## 返工循环记录（如有）

| # | 触发原因 | 修复 Agent | 修复内容摘要 | 重新验证结果 |
|---|---------|-----------|------------|------------|

## 关键决策记录

| # | 决策点 | 可选方案 | 最终选择 | 理由 |
|---|-------|---------|---------|------|
```

### 统一维护规则
- Leader 在**派发 Agent 前**必须记录当前时间作为开始时间（使用系统提供的当前时间），在 `docs/agent-timing.md` 中追加一行
- Leader 在**收到 Agent 完成消息时**必须记录结束时间（从系统消息的 Timestamp 获取），更新 `docs/agent-timing.md` 对应行的结束时间、运行时间和状态
- 运行时间 = 结束时间 - 开始时间，格式为 `Xm Ys`（如 `5m 30s`、`2m 15s`、`1h 12m 30s`）
- `docs/agent-timing.md` 是实时更新的追踪文件，每派发/完成一个 Agent 就更新一次，不得延迟批量更新
- `docs/执行日志.md` 在最终审计阶段生成时，必须包含从 `docs/agent-timing.md` 整合的完整时间数据
- 执行记录表中所有时间字段必须使用 **ISO 8601 格式**（如 `2026-05-19T09:22:00`），确保精确到秒
- Leader 在每个阶段的 Agent 完成后，必须更新执行日志
- 质量门禁的 verdict 必须如实记录，包括 BLOCK 原因
- 返工循环的每一轮必须记录
- 关键技术决策（架构选型、方案取舍）必须记录
- 该文件是项目交付的必需产物之一，Supervisor Auditor 必须检查其完整性，包括时间追踪数据的完整性

