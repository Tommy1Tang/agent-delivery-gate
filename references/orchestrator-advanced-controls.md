# Orchestrator Advanced Controls

Moved from `assets/prompts/development-orchestrator.prompt.md` to keep the role prompt under the doctor size threshold while preserving the full rules.

Development Orchestrator must read this file when planning or running a delivery, especially for complex routing, parallelism, context partitioning, halt/resume, evidence-ledger, and large-project controls.

## 增强声明传递协议（OC-A）

Handoff 中必须传递上游角色已产出的增强声明摘要，确保下游角色能消费和验证：

| 从角色 | 传递内容 | 给角色 | 用途 |
|---|---|---|---|
| Architect | EA1 追溯矩阵中的任务列表 | Backend/Frontend/Execution | 确认任务覆盖所有需求 |
| Architect | EA4 幂等性声明、EA8 容量规划、EA10 LMT | Backend | 实现幂等/分页/日志 |
| Architect | EA5 预期 changeSet ID | Backend/Frontend | 标注 CS-xxx |
| Architect | EA6 C4图 + EA7 依赖 DAG | Execution Engineer | 跨层协调参考 |
| Backend | BE-A~E changeSet 声明 | Quality Gate | QA-A 验证兑现 |
| Frontend | FE-A~D changeSet 声明 | Quality Gate | QA-A 验证兑现 |
| Execution | EX-A 同步点覆盖情况 | Quality Gate | 跨层一致性验证 |

Handoff 中新增可选字段 `enhancementDeclarations`：
```json
"enhancementDeclarations": {
  "sourceRole": "backend-engineer",
  "items": [
    { "id": "BE-A", "claim": "乐观锁 @Version", "evidenceFile": "TicketServiceImpl.java" },
    { "id": "BE-D", "claim": "状态机幂等", "evidenceFile": "TicketServiceImpl.java" }
  ]
}
```

Quality Gate Engineer 的 Handoff 必须合并所有实现角色的 `enhancementDeclarations`，供 QA-A 逐项验证。

## 跨角色追溯闭环检查（OC-B）

每完成一个阶段后，Orchestrator 必须验证追溯链完整性：

| 检查时机 | 检查内容 | 未通过处理 |
|---|---|---|
| Architect 完成后 | EA1 矩阵是否覆盖 PA 的所有 FR/NFR/BR | 返工 Architect 补全矩阵 |
| Implementation 完成后 | 每个 FR 是否有对应 changeSet（比对 EA1 与实际产出） | 返工对应实现角色 |
| QA 完成后 | 每个 FR 是否有对应测试用例（比对 EA1 与测试报告） | 返工 QA 补充用例 |
| Audit 前 | 全链路 FR→任务→代码→测试 是否可追溯 | 定位断裂点并回调 |

追溯检查结果记入 `evidence-ledger.json#/observability/traceabilityMatrix`。

## 返工定向回调（OC-C）

QA-C 根因归因后，Orchestrator 根据归因结果定向回调，而非全链重跑：

| QA-C 归因 | 回调目标 | 回调范围 | 后续 |
|---|---|---|---|
| 逻辑缺陷 → Architect | Architect | 仅修订详细设计相关模块 | 重跑对应实现角色 + QA 受影响子集 |
| 并发缺陷 → Backend(BE-A) | Backend Engineer | 仅修复并发策略 | 重跑 QA 并发测试用例 |
| 边界缺陷 → Backend/Frontend | 对应角色 | 仅补充防御性校验 | 重跑 QA 边界测试用例 |
| 契约缺陷 → Data Contract | Data Contract Designer | 仅修订契约 | 重跑 FE+BE 受影响接口 + QA |
| 安全缺陷 → Backend/Frontend | 对应角色 | 仅修复安全问题 | 重跑 QA 安全测试用例 |
| 性能缺陷 → Backend(BE-C) | Backend Engineer | 仅修复 N+1/慢查询 | 重跑 QA 性能相关用例 |
| UI/UX 缺陷 → Frontend | Frontend Engineer | 仅修复布局/响应式/a11y | 重跑 QA 前端用例 |

定向回调后仅重跑 QA **受影响的测试子集**，而非全量重测。回调信息记入 `evidence-ledger.json#/observability/reworkDirected[]`。

## 智能并行化规则（OC-D）

超越 FE/BE 的系统化并行判定：

| 角色组 | 可并行条件 | 必须串行条件 |
|---|---|---|
| Frontend + Backend | lockedFiles 无交集且无共享 API 变更 | 有 API 新增/变更（需 BE 先完成） |
| Data Contract + UI Designer | 始终可并行（无文件交集） | — |
| 多个 Backend 子任务 | 无共享 Entity/Service/Mapper | 有共享模块 → 串行 |
| 多个 Frontend 子任务 | 无共享组件/Store/路由 | 有共享状态 → 串行 |
| QA + Documentation Writer | 始终串行（Doc 需等 QA 结论） | 始终串行 |
| DevOps + Supervisor Auditor | 始终串行（Auditor 最后） | 始终串行 |

并行派发前必须运行 `checkLockedFileConflicts`（见 P5-6），并在 evidence ledger 中记录 `parallelDecision: { group, reason }`。

## 渐进式用户摘要（OC-E）

每完成 2 个角色后（或遇到阻塞时），向用户输出可读中间摘要：

```text
📊 进度摘要（已完成 {completed}/{total} 角色）
✅ Product Analyst: 需求规格已产出（{frCount} 个 FR + {nfrCount} 个 NFR）
✅ Architect: 开发计划已产出（{taskCount} 个任务 / {phaseCount} 个阶段）
⏳ Backend Engineer: 执行中...
📌 风险: {riskSummary}
⏱️ 预计剩余: {estimatedRemaining}
```

此摘要与 PROGRESS 行互补：PROGRESS 行供机器解析，此摘要供用户阅读。

## 交付时间预估（OC-F）

首次派发前和每次返工后更新预估：

| 因素 | 基线 | 调整系数 |
|---|---|---|
| 每个核心角色 | 3 分钟 | × complexity(1=简单, 2=中等, 3=复杂) |
| 每个 Conditional Role | +3 分钟 | — |
| 并行角色组 | 取最长者 | 不叠加 |
| 预期返工循环 | +2 分钟/次 | 基于历史平均 |
| Smoke Test + validate_delivery | +2 分钟 | 固定 |

预估公式：`totalEstimate = Σ(roleBaseline × complexity) + conditionalRoles × 3 + expectedRework × 2 + 2`

预估记入 evidence ledger 的 `observability.timeEstimate`，实际时长记入 `observability.actualDurationMs`。

## 精简路由决策（OC-G）

当且仅当以下**全部**客观条件成立时，允许跳过部分角色：

| 可跳过角色 | 客观条件（全部满足） |
|---|---|
| Product Analyst | 用户提供了完整需求描述 + 变更范围 ≤ 3 个文件 + 无新 FR + 任务类型为 bug-fix 或 config-only |
| UI Designer | 变更不涉及任何前端文件 + 无 UI 组件新增/修改 + workflow domain 不含 ui-development |
| Data Contract Designer | 无 API 新增/修改 + 无数据结构变更 + 无新 Entity/DTO |
| Execution Engineer | 任务明确属于纯前端或纯后端（无跨层） |

🔴 **禁止跳过的角色**（任何情况下不可省略）：Architect、Quality Gate Engineer、Browser E2E Engineer、Supervisor Auditor。

跳过时必须在 evidence ledger 中记录：
```json
"routeSimplification": {
  "skippedRoles": ["product-analyst"],
  "conditions": ["bug-fix", "scope<=3files", "no-new-FR"],
  "approvalBasis": "objective-conditions-all-met"
}
```

## 增量交付编排（OC-H）

大项目分阶段交付时，Orchestrator 按以下规则编排：

1. **阶段切分**：Architect 在 EA7（依赖 DAG）中标注阶段边界，每个阶段包含一组可独立交付的任务。
2. **阶段独立交付**：每阶段独立运行完整角色链（实现 → QA → DevOps），独立产出测试报告和证据。
3. **阶段间接力**：上一阶段的 changeSet 作为下一阶段的 baseline，通过 `upstreamChangeSet` 传递。
4. **阶段状态跟踪**：evidence ledger 中记录 `phases[].phaseId`、`phases[].status`、`phases[].roleRuns[]`。
5. **阶段门禁**：每阶段完成后必须通过 Smoke Test；最后阶段完成后才调用 Supervisor Auditor 进行全局审计。
6. **阶段回滚**：某阶段 QA BLOCK 时，仅回退该阶段，不影响已完成阶段。

阶段编排仅在 Architect EA7 中明确标注阶段边界时启用；否则默认为单阶段交付。

## LP-A 上下文窗口分区策略

Handoff 内容按重要性分三级，当总体积超出角色 tokenBudget 时逐级裁剪：

| 层级 | 内容 | 裁剪规则 |
|---|---|---|
| **Critical** | expectedOutputs + requiredFiles 中与角色直接相关的章节 + enhancementDeclarations | 永不裁剪 |
| **Reference** | upstreamChangeSet + 上游文档的摘要/目录章节 + governanceConstraints | 体积超限时仅保留目录和摘要 |
| **Appendix** | 全量上游文档正文 + 历史 changeSet + 参考信息 | 体积超限时完全移除，以文件路径引用替代 |

裁剪策略：
1. 计算 Handoff 预估 token 数（按 1 中文字≈ 2 token、代码按行估算）
2. 若总量 < 角色 tokenBudget 的 60% → 全量传递
3. 若总量 ≥ 60% → 移除 Appendix 层，仅保留文件路径和「请在需要时 read_file 」提示
4. 若仍超限 → Reference 层仅保留目录级摘要，正文替换为路径引用
5. 在 Handoff 中标记 `contextPartition: {level: 'trimmed-reference' | 'trimmed-appendix' | 'full', estimatedTokens: N}`

当角色收到 trimmed Handoff 时，可根据需要自行 `read_file` 被裁剪的内容，但优先完成主任务。

## LP-B 任务依赖图与关键路径调度

在 S1-6 拓扑排序基础上，进一步构建关键路径感知调度：

1. **DAG 构建**：从 `docs/03-任务清单.md` 提取任务依赖关系，建立有向无环图。
2. **关键路径计算**：按 `每任务估算轮次 = 1`（单角色任务）或 `= 2`（跨角色任务）计算最长路径。
3. **并行窗口识别**：不在关键路径上的任务可与关键路径任务并行执行（需同时满足 OC-D 并行条件）。
4. **动态重调度**：若关键路径任务因返工延迟，将原非关键路径任务提前执行以填充空闲窗口。
5. **记录**：evidence ledger 中记录：
   ```json
   "taskGraph": {
     "criticalPath": ["T1", "T3", "T5"],
     "criticalPathLength": 3,
     "parallelWindows": [["T2", "T4"], ["T6", "T7"]],
     "actualSequence": ["T1", "T2||T3", "T4||T5", "T6", "T7"]
   }
   ```

关键路径调度仅在任务数 ≥ 5 时启用；< 5 个任务时按顺序执行即可。

## Epic 感知调度（RQ-D/E/F 对齐）

当 Product Analyst 产出包含 Epic 分组时（FR ≥ 5），Orchestrator 按 Epic 感知调度：

### Epic 检测

1. 读取 `docs/01-需求规格书.md` 中的「Epic 清单」章节。
2. 检查是否存在 `docs/01.*-需求规格书-*.md` 领域子规格书。
3. 若检测到 Epic 结构，在 evidence ledger 中记录 `epics: [{epicId, domainName, frCount, status}]`。

### Handoff 增强

当存在 Epic 分组时，派发给 Architect 和 Engineer 的 Handoff 中必须增加 `epicContext` 字段：

```markdown
### Epic Context
- **Current Epic**: EP-{序号} {领域名称}
- **Epic Dependencies**: [依赖的 Epic ID 列表]
- **Spec File**: `docs/01.{序号}-需求规格书-{领域名称}.md`（子规格书）或 `docs/01-需求规格书.md`（主规格书）
- **FR Dependency Graph**: 本领域 FR 依赖关系摘要
```

### 子规格书分发策略

当子规格书存在时，Orchestrator 必须按以下规则将其分发给下游角色：

| 下游角色 | 分发内容 | 说明 |
|---|---|---|
| **Architect** | 主规格书 + 全部子规格书 | 需全局视角规划任务 |
| **Backend Engineer** | epicContext.Spec File 指定的子规格书 | 仅本领域需求，降低上下文压力 |
| **Frontend Engineer** | epicContext.Spec File 指定的子规格书 | 仅本领域需求 |
| **Execution Engineer** | epicContext.Spec File 指定的子规格书 | 仅本领域需求 |
| **Quality Gate Engineer** | 主规格书 + 全部子规格书 | 需全量 FR/AC 追踪 |
| **Data Contract Designer** | 主规格书 + 全部子规格书 | 跨 Epic 接口需全局视角 |
| **Browser E2E Engineer** | 主规格书 + 全部子规格书 | E2E 跨领域验证 |

Handoff 中的 `requiredFiles` 字段必须包含对应的子规格书路径。当 Token 预算压力超过 `CONTEXT_PRESSURE_RATIO` 时，可将子规格书内容压缩为摘要（保留 FR ID + AC 编号 + dependsOn），并在 Handoff 中标注 `_specCompressed: true`。

### Epic 并行调度规则

| 条件 | 调度策略 |
|---|---|
| 多个 Epic 无相互依赖 | 可并行走完整角色链（各 Epic 独立 session） |
| Epic A dependsOn Epic B | Epic B 的角色链先执行，完成后启动 Epic A |
| Epic 数 ≤ 2 | 按顺序执行（避免 session 膨胀） |
| Epic 数 ≥ 3 且存在无依赖 Epic | 无依赖 Epic 并行 + 有依赖 Epic 串行等待 |

### FR 依赖排序

基于 RQ-F 的 FR 依赖矩阵，在 Architect 产出任务清单后：
1. 验证任务 DAG 与 FR 依赖矩阵一致（FR-A dependsOn FR-B → 对应任务 T-A dependsOn T-B）。
2. 若不一致 → 要求 Architect 修正任务清单。
3. 执行阶段按 DAG 拓扑顺序派发 Engineer 角色。

### MoSCoW 优先级调度（EA2-B 对齐）

Orchestrator 在派发实现任务时必须遵守 MoSCoW 优先级顺序：

1. 读取 `docs/03-任务清单.md` 中各任务的优先级字段（`P0-Must` / `P1-Should` / `P2-Could`）。
2. 派发顺序：先派发全部 P0-Must 任务 → 全部完成后派发 P1-Should 任务 → 全部完成后派发 P2-Could 任务。
3. 同一优先级内按 FR 依赖 DAG 拓扑排序，无依赖的可并行。
4. 禁止跳过 Must 级任务先执行 Could 级任务。
5. 当存在返工堆积时，更低优先级任务必须等待返工完成。
6. 在 evidence ledger 中记录 `moscowSchedule: {mustCompleted, shouldCompleted, couldCompleted, currentPriority}`。

## LP-C 多模块/多服务编排

当项目包含多个独立部署单元（微服务、monorepo 多包、前后端分离）时，Orchestrator 采用模块级编排：

1. **模块识别**：通过项目结构检测模块边界：
   | 信号 | 模块边界判定 |
   |---|---|
   | 多个 `pom.xml` / `package.json` | 每个构建文件 = 一个模块 |
   | `docker-compose.yml` 多服务 | 每个 service = 一个模块 |
   | 目录约定（`packages/` / `services/` / `apps/`） | 每个子目录 = 一个模块 |
   | 前后端分离（`frontend/` + `backend/`） | 各为一个模块 |

2. **模块级并行**：无直接依赖的模块可并行走完整角色链，各模块的 Backend/Frontend Engineer 在独立 session 中完成。
3. **契约层同步**：模块间仅在 API 契约层同步，由 Data Contract Designer 统一定义模块间接口。
4. **测试分层**：
   - 模块内：单元测试 + 集成测试（模块内闭环）
   - 模块间：E2E 测试（跨模块全链路）
5. **模块状态跟踪**：evidence ledger 记录：
   ```json
   "modules": [
     {"moduleId": "backend", "status": "completed", "roleRuns": [...]},
     {"moduleId": "frontend", "status": "in-progress", "roleRuns": [...]}
   ]
   ```
6. **模块级回滚**：某模块 QA BLOCK 时，仅回退该模块，其他模块继续。

模块级编排仅在 Architect 识别出 ≥ 2 个独立部署单元时启用；单模块项目沿用标准单链路。

## LP-D 自适应返工上限

默认返工上限（累计 10 次、单因 5 次）对大项目可能过于保守。采用自适应公式：

```text
adaptiveCumulativeCap = min(10 + ceil(frCount / 10), 20)
adaptivePerRootCauseCap = min(5 + ceil(frCount / 20), 8)
```

| FR 数量 | 累计上限 | 单因上限 |
|---|---|---|
| 1–10 | 10 + 1 = 11 | 5 + 1 = 6 |
| 11–20 | 10 + 2 = 12 | 5 + 1 = 6 |
| 21–50 | 10 + 5 = 15 | 5 + 3 = 8 |
| 51–100 | 10 + 10 = 20 | 5 + 5 = 8 (capped) |

执行规则：
1. Orchestrator 在 Product Analyst 完成后统计 FR 数量，计算自适应 cap。
2. 在 evidence ledger 中记录 `adaptiveReworkCaps: {frCount, cumulativeCap, perRootCauseCap}`。
3. validate_delivery.py 读取该字段，若存在则使用自适应 cap 替代硬编码默认值。
4. 累计绝对上限不超过 20（防止无限返工）。

## 任务规模硬约束（S1-5，必选）

在拆分 `docs/03-任务清单.md` 时，每个任务必须满足：

| 约束 | 阈值 | 超阈处理 |
|---|---|---|
| 单任务估计代码量 | ≤ 300 行 | 拆分为多个子任务 |
| 单任务涉及文件数 | ≤ 8 个 | 拆分或重新划分边界 |
| 单任务跨模块依赖 | ≤ 3 个 | 抽取公共依赖为单独任务 |

拆分后必须指明：依赖关系、可并行性、输出产物。

## 任务依赖循环检测（S1-6，必选）

产出 `docs/03-任务清单.md` 后，必须进行拓扑排序验证：

1. 构建任务依赖有向图（`taskId -> dependsOn[]`）。
2. 运行拓扑排序，如检测到环 → **立即中断拆分，标记为 `halted-pending-user`**。
2. 在 evidence ledger 中记录 `taskGraph: { nodes, edges, hasCycle }`。
3. 若引入依赖循环 → 说明具体环路径并请求用户重新拆分或合并任务。

## Smoke Test 前置门禁（S2-1，必选）

在实现角色（frontend-engineer / backend-engineer）报告 `completed` 后、quality-gate-engineer 派发前，**必须**运行 smoke 检查：

```text
python scripts/smoke_test.py --project-root <project-root>
```

该脚本会检查：
- 后端：`mvn -q -DskipTests compile` / `gradle compileJava` / `npm run build`能否成功
- 前端：`npm run build` / `tsc --noEmit` 能否成功
- 然后运行 `mvn spring-boot:run` 以检查是否能启动 30 秒

**互锁**：smoke status=fail → 禁止进入评审阶段，必须先重调实现角色修复。该输出记入 `evidence-ledger.json#/observability/smokeTestResult`。

## Handoff Schema 自检（S4-1，必选）

调用 `build_handoff.py` 生成 handoff 后，**必须**运行：

```text
python scripts/validate_handoff_schema.py --handoff <generated-handoff.json>
```

或在代码中以 schemas/handoff.schema.json 验证。任何 schema 错误 → 禁止派发下游角色。

## 多重崩溃自动决策（S4-2，明确表）

表驱动，不再依赖主观判断：

| 现象 | 决策 |
|---|---|
| 1 角色 lost-session | 重试（按 retryPolicy） |
| 2 角色 lost-session | 启用单 session fallback（同一 session 连续执行） |
| ≥3 角色 lost-session | `halted-multi-crash`，升级用户，禁止「尽力继续」 |
| 同一角色 ≥3 次 lost-session | `halted-multi-crash`，启动事故报告 |
| 同一根因 returnsk ≥5 次 | Circuit breaker 触发，`halted-circuit-broken` |
| ledger 连续 2 次错误 | 从 backup 恢复，标记为 `ledger-corruption-recovered` |

决策后必须记录 `multiCrashRecoveryPlan: { trigger, decision, rationale, evidencePath }`。
