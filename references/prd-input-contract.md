# PRD Input Contract（上游输入契约）

当用户已完成业务调研、业务建模和能力抽象（需求工程方法论的阶段 1-3），本 skill 工作流从阶段 4（功能 PRD）开始接力。本文件定义上游必须提供什么、以什么格式提供、skill 各角色如何消费。

## 输入目录约定

上游产物统一放在项目根目录的 `docs/input/` 下：

```
project-root/
└── docs/
    └── input/
        ├── 00-项目概述.md            ← 必须
        ├── 01-能力目录.md            ← 必须
        ├── 02-领域模型.md            ← 必须
        ├── 03-状态机.md              ← 必须（有状态实体时）
        ├── 04-业务规则.md            ← 必须（有判定逻辑时）
        ├── 05-流程模型.md            ← 建议
        ├── 06-调研台账摘要.md        ← 可选
        └── 07-待确认问题.md          ← 可选（强烈建议）
```

模板文件位于 `assets/templates/project-input/`，上游按模板格式填写即可。

## 各文件消费角色

| 输入文件 | Product Analyst | Architect | Data Engineer | Data Contract Designer | Quality Gate |
|----------|:-:|:-:|:-:|:-:|:-:|
| 00-项目概述 | ✅ 背景/范围/NFR | ✅ 全局约束 | — | — | ✅ 验收范围 |
| 01-能力目录 | ✅ FR 组织主线 | ✅ 模块划分 | — | ✅ API 边界 | ✅ 测试范围 |
| 02-领域模型 | ✅ 数据对象引用 | ✅ 数据架构 | ✅ 建表 | ✅ 字段契约 | ✅ 数据验证 |
| 03-状态机 | ✅ 状态约束 | ✅ 设计 | ✅ 状态字段 | — | ✅ 路径覆盖 |
| 04-业务规则 | ✅ BR 编号 | ✅ 规则引擎 | — | — | ✅ 规则测试 |
| 05-流程模型 | ✅ 场景覆盖 | ✅ 端到端路径 | — | ✅ 调用顺序 | ✅ E2E 路径 |
| 06-调研台账 | ✅ 事实追溯 | — | — | — | — |
| 07-待确认问题 | ✅ 待确认项 | ✅ 风险 | — | — | ✅ mock 策略 |

## 输入完整性门禁

当 `docs/input/` 存在时，skill 不应仅凭 `01-能力目录.md` 存在就直接跳过需求引导。必须先执行输入完整性检查。

### 执行方式（机械校验，不是人工判断）

🔴 本门禁**必须通过脚本执行**，禁止靠读文档“目测”得出结论——追溯链断链需要在 8 个文件间交叉对账上百个编号引用，LLM 肉眼核对必漏：

```text
python scripts/validate_input_contract.py --project-root <project-root> --json \
    --gap-list-out docs/输入缺口清单.md
```

退出码：`0` = pass / not-applicable，`1` = partial，`2` = fail。

脚本机械校验的内容：

| 校验类型 | 具体检查 |
|----------|----------|
| 文件层 | 00/01/02 必须存在且非空；有 `ST-` 引用则 03 必须存在；有 `RULE-` 引用则 04 必须存在 |
| **追溯链** | 提取全部 SC/ROLE/PROC/ND/ENT/REL/ST/RULE/IF/EX/EV/Q/CAP 引用，逐个回查定义文件，输出 `file:line` 级断链清单 |
| 能力完整性 | 每个 Must capability 的 8 项要素（业务目标/触发角色/输入/输出/正常流程≥2步/异常流程≥1条/Given-When-Then 验收/不包含范围） |
| 分级与关联 | 每个 capability 有 MoSCoW；已关联 node_id 或标注为全局/横切 |
| 领域模型 | 实体有唯一标识、有字段表且含 字段/类型/必填 列；关系有基数 |
| 状态机 | 每条转换有 state_id、当前/目标状态、触发事件，且有触发节点或触发角色 |
| 业务规则 | 每条规则有类型、有详细段、且「输入条件」与「输出结果」表非空 |
| 范围与问题 | 00 的「本期不包含」非空；07 中阻塞程度=高的问题有当前假设与 mock/暂缓策略 |

占位符识别：包含 `xxx`/`XXX` 的编号视为未填写；全角/半角括号包裹的提示文本视为空值。因此直接拿模板跑会得到 fail，这是预期行为。

### 门禁结论

| 结论 | 处理方式 |
|------|----------|
| 通过 | Product Analyst 可跳过 Progressive Elicitation，直接基于 `docs/input/` 生成 PRD |
| 部分通过 | Product Analyst 先输出《输入缺口清单》，仅对信息充分的 capability 生成 PRD 草案 |
| 不通过 | 不得直接生成 PRD，必须先补充上游输入 |

### 不可绕过的双重拦截

1. Product Analyst 必须在 roleResult 回传 `inputGate`（`verdict` + `command`，partial/fail 时还需 `gapListPath`），见 `schemas/role-result.schema.json`。
2. `scripts/validate_delivery.py` 的第 21 项门禁会**重跑同一校验**：verdict = fail，或 partial 但缺 `docs/输入缺口清单.md`，或存在 brokenRefs → 交付门禁 BLOCK。

因此“声称通过但实际不通过”必定在交付验收阶段被抓到。

### Must 级门禁

以下任一项不满足，视为“部分通过”或“不通过”：

- 每个 Must capability 有业务目标、触发角色、输入、输出、正常流程、至少 1 条异常流程、验收标准、不包含范围
- 每个 capability 关联至少一个 `node_id`，或明确标注为“全局/横切能力”
- 每个 capability 关联必要的 `entity_id`、`rule_id`、`state_id`、`interface_id`，无关联时需说明原因
- 核心实体已列出唯一标识、关键字段、字段类型、必填、关系和基数
- 有状态实体已定义状态机，至少包含当前状态、目标状态、触发事件、触发节点或角色
- 判定、路由、计算、分配、审批、生成、留存逻辑已提取为规则，至少包含 `rule_id`、输入条件、输出结果
- 范围外事项已明确声明
- 阻塞程度=高的问题已标注当前假设和 mock/暂缓策略

### AI 行为规则

当上游输入不完整时：

1. 必须先输出《输入缺口清单》，不得直接生成完整 PRD。
2. 不得根据常识补全业务规则、状态流转、权限、接口字段或验收口径。
3. 所有推断必须标记为“AI 推断”。
4. 所有高阻塞问题必须进入 PRD 的“待确认项”，并给出 mock、暂缓或阻塞处理策略。
5. 如果 capability 信息充分但部分规则待确认，可只生成该 capability 的 PRD 草案，并明确待确认边界。

## 必须满足的质量门槛

上游输入交给 skill 前，必须自检通过：

- [ ] 已完成输入完整性门禁检查
- [ ] 每个 capability 有：业务目标、触发角色、输入/输出、正常流程、≥1 异常流程、验收标准（Given/When/Then）、不包含范围
- [ ] 每个 capability 有 MoSCoW 优先级（Must / Should / Could）
- [ ] 每个 capability 关联 `node_id` 或明确为全局能力
- [ ] 每个 capability 关联必要的 `entity_id`、`rule_id`、`state_id`、`interface_id`
- [ ] 核心实体已列出关键字段和关系（至少：字段名、类型、必填、说明）
- [ ] 有状态的实体已定义完整状态机（当前状态、目标状态、触发事件、触发角色）
- [ ] 判定/路由/计算逻辑已提取为规则（rule_id + 输入条件 + 输出结果）
- [ ] 范围外事项已明确声明
- [ ] 高阻塞待确认问题已标注当前假设和 mock/暂缓策略
- [ ] **追溯链无断链**：各模板中引用的 SC/ROLE/PROC/ND/ENT/REL/ST/RULE/IF/EX/EV/Q 编号，在其定义模板中均能找到对应条目（scenario/role 定义在 00，能力在 01，实体/关系在 02，状态在 03，规则在 04，节点/异常/接口在 05，证据在 06，问题在 07）

## 编号前缀规范（无歧义设计）

全部前缀构成一个**前缀无包含关系（prefix-free）**的集合，因此机械匹配不依赖顺序，不会出现误匹配：

| 前缀 | 含义 | 定义文件 | 示例 |
|------|------|----------|------|
| `SC-` | 业务场景 | 00-项目概述 | `SC-ORD-001` |
| `ROLE-` | 用户角色 | 00-项目概述 | `ROLE-OP-001` |
| `CAP-` | 业务能力 | 01-能力目录 | `CAP-TASK-CREATE` |
| `ENT-` | 领域实体 | 02-领域模型 | `ENT-TASK-001` |
| `REL-` | 实体关系 | 02-领域模型 | `REL-ORD-001` |
| `ST-` | 状态转换 | 03-状态机 | `ST-TASK-001` |
| `RULE-` | 业务规则 | 04-业务规则 | `RULE-APPROVAL-001` |
| `PROC-` | 业务流程 | 05-流程模型 | `PROC-ORD-001` |
| `ND-` | 流程节点 | 05-流程模型 | `ND-ORD-001-03` |
| `EX-` | 异常分支 | 05-流程模型 | `EX-ORD-001` |
| `IF-` | 外部接口 | 05-流程模型 | `IF-ERP-001` |
| `EV-` | 证据材料 | 06-调研台账摘要 | `EV-SOP-001` |
| `Q-` | 待确认问题 | 07-待确认问题 | `Q-PROCESS-001` |

🔴 **业务规则一律用 `RULE-`，禁止用 `R-`**。原因：`R-` 是 `ROLE-`、`REL-` 的前缀，使机械匹配依赖正则分支顺序（脆弱），也容易误碰需求规格书内部的 `FR-`/`BR-`/`NFR-` 编号。`scripts/validate_input_contract.py` 在导入时会断言前缀集合仍为 prefix-free，若未来有人重新引入歧义前缀会直接报错。

> 上游方法论文档如果仍用 `R-APPROVAL-001` 写法，迁入 `docs/input/` 时需统一改为 `RULE-APPROVAL-001`。

## 编号映射规则

上游编号与 skill 内部编号的映射：

| 上游编号 | Skill 内部编号 | 映射方式 |
|----------|---------------|---------|
| `scenario_id` | FR 的「业务场景」字段 | 每个 FR 标注来源场景，定义见 00-项目概述 |
| `capability_id` | Epic | 一个 capability = 一个 Epic 或 Epic 下的功能组 |
| 能力目录中的功能点 | `FR-xxx` | Product Analyst 按能力拆分 FR |
| `rule_id` | `BR-xxx` | 直接映射，保留原始 rule_id 作为追溯字段 |
| `entity_id` / `relation_id` | 详细设计中的数据实体 | Architect 引用 |
| `state_id`（状态机） | 需求规格书「状态与流程」章节 | 直接引入，保留 state_id |
| `interface_id` | 接口数据契约的外部接口章节 | Data Contract Designer 引用 |
| 验收标准 | `AC-xxx` | Product Analyst 格式化为 Given/When/Then |
| `evidence_id` | 需求规格书中的事实依据标注 | 可信度低的条目标为「推断项」 |
| `question_id` | 需求规格书「待确认项」 | 原样保留 |

## Product Analyst 行为变化

当检测到 `docs/input/` 目录存在且包含 `01-能力目录.md` 时：

1. **先执行输入完整性门禁**：检查 00-07 输入文件是否满足 Must 级门槛
2. **门禁通过后跳过 Progressive Elicitation**：不再向用户追问基础业务信息
3. **门禁未完全通过时先输出缺口清单**：不得直接生成完整 PRD
4. **门禁通过时进入 Phase B**：基于能力目录全量产出需求规格书
5. **门禁部分通过时限制输出范围**：仅对信息充分的 capability 生成 PRD 草案，其他部分进入《输入缺口清单》
6. **FR 组织方式**：按 capability_id 分组，每个 capability 映射为一组 FR + AC
7. **BR 映射**：将 `04-业务规则.md` 中的 rule_id 映射为 BR-xxx
8. **状态机引入**：将 `03-状态机.md` 直接引入需求规格书的状态与流程章节
9. **待确认项保留**：将 `07-待确认问题.md` 原样纳入需求规格书
10. **不重复调研**：不猜测、不重新引导、不质疑上游已确认的业务事实

## Orchestrator 启动指令模板

用户启动交付时，任务描述中应包含：

```
本项目已完成业务调研和能力建模。上游输入在 docs/input/ 目录下。
Product Analyst 必须先运行 scripts/validate_input_contract.py 执行输入完整性门禁，并在 roleResult 中回传 inputGate；
门禁 verdict = pass 后，基于 docs/input/01-能力目录.md 按 capability_id 组织 FR，不需要重新做需求引导。
领域模型见 docs/input/02-领域模型.md，状态机见 docs/input/03-状态机.md，业务规则见 docs/input/04-业务规则.md。
待确认问题见 docs/input/07-待确认问题.md，其中标注为"阻塞程度=高"的问题需要在 PRD 中明确 mock 策略。
```

## 与现有工作流的关系

- 本契约不改变 skill 的角色链和交付物要求
- 仅改变 Product Analyst 的输入来源（从用户口述 → 结构化文件）
- Architect 及下游角色的工作方式不变，但它们能直接从 `docs/input/` 获取更精确的上游信息
- 变更管理仍走 `references/change-management-workflow.md`，变更时上游输入文件也应同步更新
