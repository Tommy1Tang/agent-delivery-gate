# Development Baseline Contract（开发基线包契约）

上游若已完成 BPMN 流程建模与 OWL 领域建模，**不应把这些资产降级为 markdown**
再交给下游（LAW-9）。本契约定义如何以原格式随基线包交付，以及下游 AI 的读取顺序、
切片规则与防失真门禁。

> 前置阅读：`references/prd-input-contract.md`（00-07 入口契约）、
> `references/graph-engineering-laws.md`（LAW-9 模型分层 / LAW-10 外部语义只读）。

---

## 1. 为什么需要基线包

`docs/input/00-07` 是**开发人员可读的业务需求入口**，表达充分，但作为 markdown
表格会损失机器模型信息：

| 损失内容 | 原始载体 |
|---------|---------|
| 精确执行路径、网关类型、消息流、异常边界 | BPMN |
| 类层级、公理、基数约束、逆关系、推理语义 | OWL |
| 跨对象关系、PROV-O 来源链 | RDF 统一需求图 |
| SHACL 校验、SPARQL 查询、推理验证结果 | 上游验证产物 |

因此给下游 AI 的应当是**开发基线包**，而不只是 00-07。

---

## 1.1 谁消费什么（两个消费者）

BPMN/OWL 有**两个消费者**，用法完全不同。混淆两者会得出「既然不解析语义，
要 BPMN/OWL 何用」的错误结论——实际上「不解析语义」只适用于门禁脚本。

| 消费者 | 怎么用 BPMN/OWL | 要语义吗 | 依赖 |
|--------|----------------|---------|------|
| **LLM 角色**（PA / Architect / Backend） | 读**完整 XML 语义**，据此写流程编排、实体/表/API 设计 | **全要**——网关类型、边界事件、消息流、类层级、基数、逆关系 | 无（LLM 直接读 XML 原文） |
| **门禁脚本** `validate_input_contract.py` | 只提取 **id 集合**，比对 00-07 投影与模型是否漂移 | **不要**——它只管防篡改/防失真 | `xml.etree.ElementTree`（标准库） |

三层价值各就各位：

```text
BPMN/OWL 原文  ──读语义──>  LLM 角色      → 写出正确的流程编排 / 数据模型 / API
     │
     └─提 id 集合─>  门禁脚本        → 防止 BPMN 与 00-07 偷偷对不上（防失真）
     │
     └──sha256────>  manifest 校验   → 防止有人单独改某个文件（防篡改）
```

**脚本不理解语义是刻意的**：防失真不需要理解业务，只需确认投影没漂移；理解业务
是 LLM 的职责，而 LLM 读原文零依赖。两者分工，不是二选一。

不给 BPMN/OWL 时 AI 会漏掉的典型信息：

| 场景 | markdown 表格 | BPMN/OWL 原文 |
|------|--------------|--------------|
| 审批后分两路 | 只能写「分两条路」，不知是二选一还是同时跑 | `<exclusiveGateway>` 排他 vs `<parallelGateway>` 并行，一标签定死 |
| 任务关联样本 | 「任务关联样本」，不知一对一还是一对多 | `owl:maxCardinality 1` 一对一；无上限则一对多（决定表结构） |
| 样本与批次关系 | 平表撑不住双向关系 | `owl:inverseOf` / `rdfs:subClassOf` 精确表达 |

---

## 2. 目录结构

基线包整体位于 `docs/input/`，`models/` 为机器模型层：

```text
docs/input/
├── 00-项目概述.md              ← 主入口（业务场景、角色）
├── 01-能力目录.md              ← 主入口（能力清单，Must/Should/Could）
├── 02-领域模型.md
├── 03-状态机.md
├── 04-业务规则.md
├── 05-流程模型.md
├── 06-调研台账摘要.md
├── 07-待确认问题.md
└── models/                     ← 机器模型层（只读）
    ├── baseline-manifest.json      文件版本与 sha256 哈希
    ├── spec/
    │   └── model-spec.json         业务模型唯一规范源
    ├── bpmn/
    │   └── *.bpmn                  流程行为依据
    ├── ontology/
    │   └── *.owl                   领域语义依据
    └── graph/
        ├── requirements-graph.ttl       统一需求图
        ├── graph-validation-report.json SHACL 校验结果
        ├── reasoning-report.json        推理结果
        └── sparql-results.json          预跑查询结果
```

`models/` 缺失时基线校验判为 `not-applicable`，00-07 契约照常生效——
**基线包是增量能力，不是新的准入门槛**。

---

## 3. 权威层级

```text
model-spec.json  （业务模型唯一规范源）
      │
      ├──> 00-07 markdown      受控投影（人类阅读入口）
      ├──> *.bpmn              受控投影（流程行为）
      ├──> *.owl               受控投影（领域语义）
      └──> requirements-graph.ttl  受控投影（跨对象关系）
```

硬规则：

- `model-spec.json` 是**业务模型**的规范源，其余皆为受控投影。
- 它**不覆盖** `assets/config/skill-process.json`（交付流程真理源）——两者分属
  不同层次，互不越界（LAW-9）。
- 00-07、BPMN、OWL、TTL **不得独立修改**。任何变更从 `model-spec.json` 出发，
  重新生成全部投影并更新 manifest 哈希。
- 下游对基线包**只读**（LAW-10）。需变更时停止并回上游，不得自行修补。

---

## 4. baseline-manifest.json 格式

```json
{
  "baselineId": "BL-LIMS-20260729-01",
  "generatedAt": "2026-07-29T10:00:00+08:00",
  "specSource": "models/spec/model-spec.json",
  "hashAlgorithm": "sha256",
  "files": [
    {"path": "00-项目概述.md", "sha256": "a1b2c3...", "role": "projection"},
    {"path": "models/spec/model-spec.json", "sha256": "d4e5f6...", "role": "spec-source"},
    {"path": "models/bpmn/task-create.bpmn", "sha256": "7a8b9c...", "role": "projection"}
  ]
}
```

- `sha256` 是**内容哈希**，不是时间戳——时间戳无法发现内容篡改。
- `path` 相对 `docs/input/`。
- manifest 自身**不列入** `files`（避免自引用）。
- `role` 取 `spec-source` | `projection` | `evidence`。

---

## 5. 下游 AI 读取顺序

1. **先校验基线**：`validate_input_contract.py --baseline`。哈希或投影不一致 ⇒
   **停止**，不得自行选择版本或推断哪个文件更新（LAW-10）。
2. 读 `00-项目概述.md` + `01-能力目录.md`，建立系统全局认识。
3. 按开发切片读取相关的 02-07。
4. **实现流程编排时必须读相关 BPMN**（网关类型、异常边界、消息流）。
5. **设计实体 / 数据库 / API / 状态模型时必须读 OWL + 02 + 03**（类层级、基数、逆关系）。
6. 判断跨流程复用、影响范围、证据来源时查 `requirements-graph.ttl` 与
   `sparql-results.json`（读上游预跑结果，**不自己跑 SPARQL**）。
7. PRD、任务、代码、测试必须保留 `capability_id` / `process_id` / `node_id` /
   `entity_id` / `rule_id` 等稳定 ID。

---

## 6. 切片输入规则（不交给 AI 判断）

不需要每个切片都塞入全部文件，但**必须保证 AI 能访问完整基线包**。
切片内容由脚本机械推导，不由 AI 自行挑选：

```text
python scripts/build_baseline_slice.py --project-root <proj> --capability CAP-XXX
```

| 类别 | 内容 |
|------|------|
| **固定全局输入** | `00-项目概述.md`、`01-能力目录.md`、`models/spec/model-spec.json`、`models/baseline-manifest.json` |
| **切片相关输入** | 该能力关联的 `PROC-*` 对应 BPMN；关联 `ENT-*` 对应 OWL；02/03/04/05 相关章节；07 中影响该能力的 `Q-*`；相关图查询结果 |

推导依据是 00-07 中已有的追溯字段（`capability_id → process_id / entity_id /
rule_id`），纯集合运算，无启发式判断（LAW-3）。

---

## 7. 防失真门禁（C-INPUT-01..04）

| 约束 | 校验内容 | 违反后果 |
|------|---------|---------|
| **C-INPUT-01** | manifest 中每个文件的 sha256 与实际内容一致；无遗漏、无多余 | `fail` |
| **C-INPUT-02** | `05-流程模型.md` 的 `ND-*` 集合 == BPMN 各 `task`/`gateway` id 集合 | `fail` |
| **C-INPUT-03** | `02-领域模型.md` 的 `ENT-*` 集合 ⊆ OWL 类集合 | `fail` |
| **C-INPUT-04** | `model-spec.json` 的 capability/process/entity 清单 == 00-07 对应集合 | `fail` |

实现约束：

- BPMN/OWL 只做**集合比对**，不做语义解析——`xml.etree.ElementTree`（标准库）
  提取 id 即足，不引入 rdflib（零依赖原则）。
- SHACL / 推理报告若存在且含 violation，输出 **warning**，**不参与 verdict 判定**
  （LAW-10：推理结论不得当门禁判据）。

---

## 8. 开发前后各跑一次

| 时机 | 命令 | 目的 |
|------|------|------|
| 开发前（SP-02 门禁） | `validate_input_contract.py --baseline` | 确认基线自洽，追溯链无断裂 |
| 交付验收（SP-18） | 同上 + `trace_requirements.py` | 确认代码/测试回链到 `capability_id` 未丢失 |

`validate_delivery.py` 第 21 项门禁在 `docs/input/` 存在时自动纳入基线校验。

---

## 9. ID 回链要求

代码模块、API、页面、测试用例都要回链到稳定 ID：

| 交付物 | 必须携带 |
|--------|---------|
| PRD（`docs/01-需求规格书.md`） | `capability_id`、`scenario_id` |
| 任务清单（`docs/03-任务清单.md`） | `capability_id`、`process_id` |
| 代码（注释或模块头） | `capability_id`、相关 `entity_id`/`rule_id` |
| 测试用例 | `capability_id`、`node_id`、`rule_id` |

回链缺失由 `scripts/trace_requirements.py` 与
`validate_input_contract.py` 的断链检测共同覆盖。
