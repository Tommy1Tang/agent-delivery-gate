# Graph Engineering Laws（图工程定律）

本文件是 `software-development-team` 流程/本体建模的**不可协商定律**。任何对
`assets/config/skill-process.json`、`assets/config/skill-ontology.json`、
`scripts/next_step.py` 的修改都必须同时满足全部定律。

定律不是建议，也不是最佳实践清单。**每条定律都绑定一个机械门禁**：违反即
`scripts/next_step.py --check` 报错，`scripts/check_skill_integrity.py` 随之 FAIL。
没有门禁的"定律"只是散文，不写进本文件。

---

## LAW-1 单一真理源（Single Source of Truth）

流程与本体各只有一个机器消费的真理源，其余一切都是派生或孪生。

| 角色 | 文件 | 可手工编辑 |
|------|------|-----------|
| 机器真理源 | `assets/config/skill-process.json` / `skill-ontology.json` | 是（但须同步孪生） |
| 人类编辑孪生 | `skill-process.yaml` / `skill-ontology.yaml` | 是 |
| 派生视图 | `references/skill-process-flowchart.md`、`references/skill-graph.json` | **否** |

- 脚本**只**读 JSON。YAML 不被任何脚本消费——因为 PyYAML 非标准库，本 skill 全部脚本零第三方依赖。
- 派生视图头部必须带 `AUTO-GENERATED ... DO NOT EDIT BY HAND` 标记。
- **禁止**在 prompt 或 reference 里另写一套流程步骤。prompt 只能引用真理源。

> 门禁：`check_skill_integrity.py` 的 `EXPECTED_PROCESS_MODELS`（四文件存在且非空）
> + `--check` 的孪生缺失告警。

---

## LAW-2 封闭世界（Closed World）

台账里没有记录，就是没做。文件系统里没有产物，就是没产出。

- 这是刻意选择，也是**不采用 OWL/RDF 的技术原因**：开放世界假设拒绝下"未记录 ⇒ 未完成"的结论，而门禁恰恰必需这个结论。
- 角色自报 `status: completed` **不足以**推进指针；`outputs[].paths` 必须实际落盘且非空。
- `skipped` 必须带白名单 `reasonForSkip`；`objective-conditions-met` 还必须带 `objectiveConditionsRef`。

> 门禁：`next_step._node_satisfied()`；`validate_delivery.py` 第 22 项
> `_check_process_node_coverage()` 在验收时重放指针。

---

## LAW-3 声明优先于推断（Declared, Not Inferred）

模型必须**显式声明**语义。脚本不猜测字符串的含义。

具体禁令：

| 禁止 | 必须 |
|------|------|
| 靠 `inputs: ["docs/**"]` 的 glob 让脚本"领悟"该节点消费所有产物 | 显式写 `consumesAllArtifacts: true` |
| 靠 nodeId 后缀（如 `endswith("A")`）判定修复节点 | 显式写 `repairFor: "<nodeId>"` |
| 靠节点声明顺序当作执行顺序 | 显式写 `transitions[].to`，由拓扑排序推导 |
| 靠注释描述并行关系 | 显式写 `parallelGroup` + 多条 fork 边 |

理由：glob / 命名约定 / 声明顺序都是**人类可读的暗示**，不是机器语义。让脚本
解释暗示，等于把判断权交还给启发式——而这套体系存在的意义正是消除启发式。

> 门禁：C-SDT-10（交付目录 glob 必须伴随 `consumesAllArtifacts`；非
> role-dispatch 节点不得声明该字段）。

---

## LAW-4 不推断裁决（No Inference of Verdicts）

守卫变量必须有**原生字段**可读。读不到就是 `UNKNOWN`，不允许由旁证反推。

- `verdict` 读 `schemas/quality-gate.schema.json#/verdict`（`PASS` | `BLOCK`）。
  **不得**由 `checks[].status` 或 `status` 反推——那是脚本在替治理角色做裁决。
- `exit` 读 `commands[].exitCode`。仅有 `status` 时只能判定 `exit==0` / `exit!=0`，
  `exit==1` 与 `exit==2` 一律返回 `UNKNOWN`。
- `passRate` 读 E2E 报告中 RED LINE 要求的机器可读行 `E2E测试通过率：XX.X%`。
  没有该行即 `UNKNOWN`，**不从散文里估算**。
- 求值器 `_eval_guard()` 是**三态**：`True` / `False` / `None`。`None` 必须原样上报，
  不得降级为 `False`（那会把"不知道"伪装成"不满足"）。

> 门禁：C-SDT-11（每个被使用的守卫变量，其原生字段必须在对应 schema 中定义）。

---

## LAW-5 守卫可执行（Guards Are Executable）

边上的 `on` 是可求值谓词，不是图示标签。

- 语法固定：`<var> <op> <value>`，`var ∈ {exit, status, verdict, passRate, retries}`，
  `op ∈ {==, !=, >=, <=, >, <}`。
- 变量按节点类型分型：`gate` 只能用 `exit`/`retries`；`role-dispatch` 只能用
  `status`/`verdict`/`passRate`/`retries`。
- 每条非 terminal 的 transition 都**必须**有 `on`。
- 求值结果落入 `processPointer.traversedPath[].via`，可审计"实际走了哪条边"。

> 门禁：C-SDT-08（语法 + 变量分型）。

---

## LAW-6 图不变量可机械校验（Invariants Are Checked, Not Trusted）

图的结构性质必须由脚本验证，而非由人承诺。

现行不变量：

| 约束 | 内容 |
|------|------|
| C-SDT-01 | `role-dispatch` 节点的 role 存在于 `agent-team-config.json#/roles` |
| C-SDT-02 | 节点的 `promptFile` 实际存在 |
| C-SDT-03 | 每条 transition 的 `to` 是已定义 nodeId 或保留字 |
| C-SDT-04 | 不可跳过角色对应节点 `skippable: false` |
| C-SDT-05 | `phases` 与节点 `phase` 字段一致 |
| C-SDT-06 | `gate` 节点有 `command` 与 `satisfiedBy.commandContains` |
| C-SDT-07 | 从 entry 可达 SP-DONE，且无孤立节点 |
| C-SDT-08 | 守卫语法与变量分型（LAW-5） |
| C-SDT-09 | 本体可物化为属性图；产物所有权唯一；非终端产物有消费边 |
| C-SDT-10 | 无 glob 隐式依赖（LAW-3） |
| C-SDT-11 | 守卫变量有原生字段（LAW-4） |

上游输入基线包的不变量（`validate_input_contract.py`）：

| 约束 | 内容 |
|------|------|
| C-INPUT-01 | `baseline-manifest.json` 的 sha256 内容哈希与实际文件一致（发现独立改动） |
| C-INPUT-02 | `05-流程模型.md` 的 `ND-*` 集合 == BPMN 各 task/gateway id 集合（流程投影一致） |
| C-INPUT-03 | `02-领域模型.md` 的 `ENT-*` 集合 ⊆ OWL 类集合（领域投影一致） |
| C-INPUT-04 | `model-spec.json` 的 capability/process/entity 清单 == 00-07 对应集合（规范源权威） |

新增语义时，**先加门禁，再加语义**。语义没有门禁保护，等于没有。

> 门禁：`next_step.py --check`（内联进 `check_skill_integrity.py`）。

---

## LAW-7 状态外置且双向（Externalised State, Both Ways）

Orchestrator 不记流程状态；读侧问脚本，写侧回写台账。

- 读：`next_step.py` 从真理源 + 台账 + 文件系统重放指针。**重放始终权威。**
- 写：`next_step.py --record-pointer` 写入 `evidence-ledger.json#/processPointer`
  （`currentNode` / `state` / `traversedPath[]` / `reworkedNodes[]`）。
- 写侧是**可审计痕迹**，不是缓存：返工再入（`occurrences > 1`）与实际触发的边
  由此可查，而不只是"可重算"。
- 执行循环固定三步：跑 `next_step.py` → 执行 action → 回写台账 + `--record-pointer`。

> 门禁：`evidence-ledger.schema.json#/processPointer`；
> `validate_delivery.py` 第 22 项重放对齐。

---

## LAW-8 拒绝过度工程（Refuse Over-Engineering）

形式化程度必须匹配**实际执行器**。

> 🔴 **本定律仅约束交付层（skill 自身的 21 节点交付管道）**。交付层的执行器是
> Python 脚本 + LLM，不是流程引擎或推理机，所以不引入 BPMN/OWL。
> **不得拿本定律反对业务层的 BPMN/OWL** —— 两者层次不同，见 LAW-9。

交付层已明确拒绝并记录理由的方案：

| 方案 | 拒绝理由 |
|------|---------|
| BPMN XML（描述**交付流程**） | 无流程引擎执行；LLM 读 XML token 量约 3-5 倍且识别更差；所需语义（网关/边界错误事件/泳道）已用 `bpmnType` + `transitions` 表达 |
| OWL / RDF（描述**交付本体**） | 开放世界假设与 LAW-2 冲突；规模仅 8 类 10 关系，属受控词表；无 SPARQL 消费方 |
| 图数据库 / Cypher（作为**交付控制真源**） | 21 节点规模；宪法「对抗过度工程」；不得替代 `skill-process.json`/ledger |
| 独立查询 DSL | 同上；`--impact` 覆盖当前全部查询需求 |

本条不禁止 `references/code-intelligence-contract.md` 定义的**派生代码分析侧车**。
代码仓库的符号/关系规模与 21 节点交付图不同，允许用锁定 provider 生成可删除重建的
离线快照；但代码图、Memgraph、LLM 和 Cypher 均无交付裁决权。机械门禁只消费规范化
JSON、显式 TraceLink、确定性影响/差异算法和 ledger 中 C-CODE-01..07 的原生 verdict。
门禁：`validate_code_intelligence.py`、`next_step.requiredCodeGates`、`validate_delivery.py`。
唯一 `1.0.0→1.1.0` bootstrap 也不改变真理源归属：它只用精确 inventory、不可重复
token/history 和可复算 hash DAG 建立首份 after baseline；只让 C-CODE-05 返回
`BOOTSTRAP_NOT_APPLICABLE`，不得制造 before 图或 diff。后续 delivery 恢复 normal 门禁。

**拒绝也要留痕**：理由写在 `skill-ontology.json#/formatDecision`，避免后人重复讨论。
未来若真接入企业 BPM 引擎，从 JSON **单向导出** BPMN，不手写、不双向同步。

---

## LAW-9 模型分层（Model Layering）

**业务层**与**交付层**是两个独立的建模层次，各有真理源，互不越界。

| | 业务层（上游） | 交付层（本 skill） |
|---|---|---|
| 建模对象 | 业务流程、领域本体、业务规则 | 21 节点交付管道 |
| 真理源 | `docs/input/models/spec/model-spec.json` | `assets/config/skill-process.json` |
| 形式化 | **BPMN + OWL + RDF 合理且推荐** | JSON + 受控词表 |
| 执行器 | 上游建模工具链 + 领域专家 | Python 脚本 + LLM |
| 世界假设 | 可为开放（OWL 推理） | **必为封闭**（LAW-2） |

硬规则：

- 业务模型**不得**规定交付流程（不得越权决定派哪个角色、跑哪个门禁）。
- 交付流程**不得**重写业务语义（不得把 BPMN 的业务节点搬进 `skill-process.json`）。
- 上游的 BPMN/OWL 不得为了适配本 skill 而**降级为 markdown**——降级会丢失
  网关类型、边界事件、消息流、类层级、基数约束、逆关系等机器模型信息。
  正确做法是以原格式随基线包交付，见 `references/development-baseline-contract.md`。

> 门禁：C-INPUT-04（`model-spec.json` 与 00-07 集合一致）；
> `validate_input_contract.py --baseline`。

---

## LAW-10 外部语义只读（External Semantics Are Read-Only）

上游的 BPMN / OWL / RDF / 推理报告是**语义依据**，不是**门禁判据**。

| 用途 | 允许 |
|------|------|
| 读 BPMN 确定网关类型、异常边界、消息流，指导流程编排实现 | ✅ |
| 读 OWL 确定类层级、基数、逆关系，指导实体/表/API 设计 | ✅ |
| 用推理报告/SHACL 结果**提示可能遗漏**（输出 warning） | ✅ |
| 用推理结论**判定门禁通过** | ❌ 禁止（违反 LAW-2 + LAW-4） |
| 下游 AI **自己跑** SPARQL / OWL 推理 | ❌ 禁止（且零依赖原则不允许装 rdflib） |
| 下游修改 BPMN / OWL / TTL / model-spec.json | ❌ 禁止（只读；需变更回上游） |

理由：OWL 推理是**开放世界**的，它不会得出「未记录 ⇒ 不存在」。把推理结论当门禁
依据，等于把裁决权交给推理机——这正是 LAW-4 禁止的事。

**门禁判据永远是**：`docs/input/00-07` + `evidence-ledger` + 文件系统（封闭世界）。

> 门禁：C-INPUT-01..03（基线哈希 + 投影一致性）；**门禁脚本**对 BPMN/OWL 只做
> **集合比对**，不做语义解析（`xml.etree.ElementTree` 标准库即足）。
> ⚠️ 这里的「不解析语义」仅指门禁脚本；**LLM 角色仍读完整语义**来写代码。
> 两个消费者的分工见 `references/development-baseline-contract.md` §1.1。

---

## 修改本文件的规则

1. 新增定律必须同时给出机械门禁（约束编号 + 检查位置）。
2. 删除定律必须说明原有门禁如何处置，不得只删文档留下悬空检查。
3. 定律与 `SKILL.md` 的 RED LINE 冲突时，**RED LINE 优先**——本文件约束建模，
   RED LINE 约束交付。
4. 引用 LAW-8 前必须先确认层次：约束的是**交付层**还是**业务层**（LAW-9）。
   拿 LAW-8 反对上游业务侧的 BPMN/OWL 是误用。
