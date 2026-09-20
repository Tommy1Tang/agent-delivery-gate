# agent-delivery-gate

**语言 / Language：** [English](README.md) · **简体中文**

> **一个真正能交付的 vibe-coding skill。** 用自然语言描述你要什么 —— 15 个 agent 角色把它从需求一路做到经过测试、评审、文档齐备、可部署的交付物。确定性门禁负责判定它到底*完成没有*。

[![tests](https://github.com/Tommy1Tang/agent-delivery-gate/actions/workflows/tests.yml/badge.svg)](https://github.com/Tommy1Tang/agent-delivery-gate/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#自己验证)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 这是什么

一个面向 AI 编码 Agent 的**可复用软件交付 skill**。你给它一句自然语言需求，它跑完整条交付流水线，产出项目真正需要的交付物：

```text
你的需求
      │
      ▼
  环境预检 → 输入契约 → 需求分析
  → 架构设计 → 数据 / 接口契约 / 性能 / UI 设计
  → 编码实现 → 单元 + 集成测试 → E2E
  → 代码评审 → 安全评审 → 发布准备
  → 文档整理 → 独立审计 → 交付门禁
      │
      ▼
  docs/01..19 + 证据账本 + 机械推导出的 PASS 或 BLOCK
```

它**不是**一个聊天壳子。它是 21 个流程节点、15 份角色契约、35 个文档模板和 22 份 JSON Schema 契约，由一个**每轮都被脚本重新读取**的流程模型驱动。

---

## 为什么要门禁，而不是「Agent 说它做完了」

Vibe coding 只有一个真正的失效模式：**你分不清「做完了」和「说得很自信」**。一次运行通常以这句话结束 ——「功能我已经实现了，一切正常。」这句话无法被证伪：它到底实现了哪条需求？哪个测试覆盖了它？改动有没有超出批准范围？「测试全过」是实测的还是猜的？

所以这个 skill 负责干活，而**由确定性脚本掌握判定权**。

> **核心不变量：** LLM 总结、embedding 或生成式查询可以*辅助探索*，但**永远不能**作为门禁的 `PASS` 证据提交。

这正是无人值守交付能够可信的原因：**Agent 不能给自己批改作业。**

---

## 快速开始

```bash
git clone https://github.com/Tommy1Tang/agent-delivery-gate.git
cd agent-delivery-gate

# 1. 只依赖标准库 —— 不需要 pytest、不需要安装、不需要联网、不需要任何服务
#    要求 Python 3.11+（代码用到 datetime.UTC）。CI 覆盖 Linux 3.11/3.12 + Windows 3.12
python run_tests.py
```

> **Windows 提示：** 交付文档使用中文文件名，运行 CLI 前请设置 UTF-8 ——
> `$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"`（或加 `-X utf8`）。
> 否则非 UTF-8 的控制台代码页会让报告输出抛 `UnicodeEncodeError`。

预期输出：

```text
================================================================
agent-delivery-gate test suite
  modules  : 10
  tests    : 83
  failures : 0
  errors   : 0
  skipped  : 0
================================================================
RESULT: OK
```

然后驱动一次交付：

```bash
# 2. 把需求变成路由计划 + handoff 载荷
python scripts/orchestrate.py \
  --skill-root . \
  --project-root /path/to/your-project \
  --task-summary "给订单系统增加批量导入功能" \
  --output-dir .qoder/skill-state --json

# 3. 问流程模型下一步是什么 —— 每一轮都重算，绝不靠记忆
python scripts/next_step.py --skill-root . --project-root . --json

# 4. 最后，由交付门禁裁决
python scripts/validate_delivery.py --skill-root . --project-root /path/to/your-project
```

在你的 Agent 运行时里把本目录注册为 skill，然后用一句需求调用它 —— 完整契约见 [`SKILL.md`](SKILL.md)。

---

## 三个让它跑得起来的能力

### 1 · 自动生成代码图谱

在任何改动之前，skill 会为你的仓库构建**符号与关系图谱**，并保存为规范化、按内容哈希寻址的快照。回答「这段代码到底在做什么」靠的是这张图，而不是让 LLM 猜。

```bash
# 构建图谱（离线、确定性、按内容哈希）
python scripts/build_code_index.py \
  --project-root /path/to/your-project \
  --output-dir .qoder/code-index \
  --config assets/config/code-intelligence.json --json
```

然后就可以用**中文或英文自然语言**查询 —— 七种确定性意图，链路中没有任何模型参与：

| Intent | 你可以问 |
|---|---|
| `definition` | `X 在哪里定义？` / `where is X defined?` |
| `callers` | `谁调用 X？` / `who calls X?` |
| `callees` | `X 调用了谁？` / `what does X call?` |
| `references` | `谁引用 X？` |
| `contains` | `模块 X 包含什么？` |
| `implements_requirement` | `FR-003 由什么实现？` |
| `tests_for` | `哪些测试覆盖 X？` |

下面是**真实输出**，可用 [`demo_code_graph.py`](demo_code_graph.py) 复现：

```console
$ python demo_code_graph.py
fixture graph: 2 symbols, 1 relationships

$ query_code_graph.py --intent definition --target app.worker
{ "queryStatus": "ANSWERED", ... "definition returned 1 exact symbol(s)" }

$ query_code_graph.py --intent callers --target app.worker
{ "queryStatus": "ANSWERED", ... "callers returned 1 exact symbol(s)" }

$ query_code_graph.py --intent implements_requirement --target FR-001
{ "queryStatus": "ANSWERED", ... "implements_requirement returned 1 exact symbol(s)" }

$ query_code_graph.py --intent tests_for --target app.worker
{ "queryStatus": "ANSWERED", ... "tests_for returned 1 exact symbol(s)" }
```

符号有歧义时返回**候选列表**，而不是替你抛硬币。快照过期或覆盖不完整时返回 `UNKNOWN`，而不是给一个看起来合理的答案。

### 2 · 自动验证

交付做出的每一个声明都由脚本核查，而不是由模型自述。图谱产出两个硬事实：

**改动前的影响面：**

```bash
python scripts/analyze_code_impact.py \
  --snapshot .qoder/code-index/code-index-snapshot.json \
  --trace-bridge .qoder/code-index/code-trace-bridge.json \
  --requirement FR-003 --artifact-root . --json
```

它只回答三者之一：`FOUND` / `NO_IMPACT` / `UNKNOWN`。`NO_IMPACT` 只有在种子唯一、快照新鲜、覆盖完整且遍历未被截断时才成立 —— 否则返回 `UNKNOWN`，而 `UNKNOWN` 会**阻断**。

**改动后的范围对账：**

```bash
python scripts/reconcile_code_changes.py ...   # 实际改动 vs 批准的 changeSet
```

改动是否仍在批准的文件、符号和关系范围内？任何未声明的文件、符号或关系回退都会让对账失败。随后由七道门禁（`C-CODE-01..07`）和 `validate_delivery.py` 给出最终裁决。

### 3 · 自动测试

测试在这里不是可选项 —— 它是**门禁输入**。流水线把测试用例和测试报告作为一等交付物产出，`validate_delivery.py` 在交付可以通过之前强制执行硬阈值：

| 阈值 | 要求 |
|---|---|
| 单元测试覆盖率 | ≥ 90% |
| 集成测试覆盖率 | ≥ 80% |
| 测试通过率 | 100% |
| E2E 通过率 | 100%，且 P0 验收标准全覆盖 |

测试 ID 全仓稳定且唯一，图谱把每条需求链接到覆盖它的测试（`--intent tests_for`）—— 所以「它被测过了」是一个**查询结果**，不是一句声明。[`docs/`](docs/) 里的示例交付展示了完整一套：单元测试用例与报告、集成测试用例与报告、E2E 用例与报告。

---

## 交付物会落到你的项目里

流水线写出的是真实交付物，不是一份摘要。本仓库的 [`docs/`](docs/) 包含一份由该流程产出的**完整示例交付**，主题是 *MES Lite* —— 一个通用离散制造业的制造执行系统，涵盖需求、设计、接口契约、UI 说明、测试用例与报告、代码与安全评审、部署、可观测性和独立审计。

需求携带稳定 ID（`CAP-001`、`FR-001`、`AC-001`），并在设计、契约、测试和审计文档中被原样复用 —— 所以可追溯性主张可以**靠阅读来核对**，而不必信任。

---

## 四条工作流

| 工作流 | 触发条件 |
|---|---|
| `forward-development` | 开发新功能或整个项目 |
| `change-management` | 需求或基线发生变更 |
| `security-governance` | 安全评估与整改 |
| `incident-management` | 异常、事故与恢复 |

路由由流程模型决定，不由 Agent 的心情决定。

---

## 架构：三图一桥

```text
需求语义图 ─────┐
                ├──► TraceBridge ──► 代码符号图
交付控制图 ─────┘                        │
                                         └──► tests / impact / diff
```

| 层 | 权威内容 | 约束 |
|---|---|---|
| 需求语义图 | PRD；存在时还包括 `model-spec` / RDF / BPMN / OWL | 需求的真理源 |
| 交付控制图 | `assets/config/skill-process.json` + 证据账本 | 流程与门禁的真理源 |
| 代码符号图 | 离线符号索引规范化后的 manifest/snapshot | 可删除、可重建 —— 永远不是权威 |
| TraceBridge | 显式的 需求 → 符号 → 测试 链接 | 只有显式、唯一、可验证的链接才能进入门禁 |

### 门禁

| 门禁 | 机械判据 |
|---|---|
| `C-CODE-01` | Provider 版本 / 分发身份 / schema 与产物哈希可信且新鲜 |
| `C-CODE-02` | 合格文件与采集完整；内部关系全解析；关系总量守恒 |
| `C-CODE-03` | 追踪标记严格合法 —— 无孤儿、歧义或重复的测试 ID |
| `C-CODE-04` | 每条 Must-FR 与 P0-AC 都同时具备精确实现链接和测试链接 |
| `C-CODE-05` | 改前：修改代码之前必须存在当前的影响分析 |
| `C-CODE-06` | 改后：必须通过真实的 before/after 对账 |
| `C-CODE-07` | inventory、baseline、activation 与账本引用可重放 |

门禁返回 `PASS`、`BLOCK`、`UNKNOWN` 或 `NOT_APPLICABLE`。**`UNKNOWN` 不是软通过** —— 它会阻断，并附上原因码和修复建议。这里刻意不存在任何一条让「Agent 当时很自信」变成 `PASS` 的路径。

每一次角色运行、命令、产物和门禁裁决都会追加到**只追加的证据账本**（`scripts/write_evidence_ledger.py`）—— 这正是交付事后可审计的原因。

---

## 仓库内容

```text
scripts/        53 个 Python 模块（约 16k 行）—— 确定性机制
schemas/        22 份 JSON Schema 契约（handoff、角色结果、质量门、审计、账本）
assets/
  config/       流程模型（21 节点 / 15 角色 / 4 工作流）、本体
  prompts/      15 份角色契约
  templates/    35 个交付文档模板
  design.md     可复用设计系统规范（46 个颜色 token，29 个小节）
references/     43 份治理与流程文档
docs/           一份通用 MES 的完整示例交付（19 份文档）
tests/          83 个测试，覆盖门禁逻辑、确定性与策略
demo_code_graph.py   上文代码图谱查询的可运行 demo
```

---

## 设计原则

1. **Agent 干活，脚本判定是否干完。** 裁决永不自我签发。
2. **流程模型是可执行的。** `next_step.py` 每轮从模型和文件系统重新推导当前节点 —— 流程绝不从聊天记录里回忆。
3. **`UNKNOWN` 优于猜测。** 证据不足时阻断，而不是通过。
4. **返工是定向的。** 门禁失败会路由到对根因负责的角色，并按根因设置重试上限。
5. **门禁无法被说服。** 只有当 `validate_delivery.py` 退出码为 `0` 时，交付才算完成。

---

## 适用范围与如实说明的局限

- **产出的是交付物，不是可运行的应用。** 该 skill 为目标项目产出设计、契约、代码改动、测试和证据。本仓库是 skill 本身加一份完整示例 —— 它不是托管服务，也不含 UI。
- **静态、单仓库分析。** 动态派发、反射和运行时依赖注入无法完全解析；当覆盖无法被证明时，框架返回 `UNKNOWN` 而不是猜测。
- **示例交付仅用于演示。** [`docs/`](docs/) 中的测试数量与覆盖率数字用于展示报告格式。框架自身的真实结果是 `python run_tests.py` 的 83/83。
- **运行时适配器有差异。** 不同 Agent 运行时的派发行为不同（隔离子会话 vs 单会话降级）；见 `references/runtime-adapters/`。

---

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
