# 示例交付产物：MES Lite

本目录是一份**由本框架完整生成的示例交付**，用于展示流程实际产出的文档形态与证据链结构。

> **重要**：本目录中的文档是**演示产物**，不是本仓库（`agent-delivery-gate` 框架本身）的需求或设计。框架自身的说明见[仓库根 README](../README.md)与 [`SKILL.md`](../SKILL.md)。
>
> 示例主题为 **MES Lite** —— 一个通用离散制造业的制造执行系统，覆盖工单管理、生产排程、设备状态监控、物料批次追溯与质量检验记录。它不针对任何特定行业或企业。

## 为什么放这份示例

框架的核心主张是：**Agent 声称"完成"必须能被机械验证**。这个主张最容易用一份真实走完全流程的交付来检验。因此本目录的文档满足两个条件：

1. **结构受模板约束** —— 每份文档都由 `assets/templates/` 中的同名模板生成，章节结构可被 `scripts/validate_doc_structure.py` 校验；
2. **ID 可追踪** —— 需求 ID（`CAP-*` / `FR-*` / `AC-*`）在设计、契约、测试、评审和审计文档中被原样复用，读者可以**逐条核对**，而不必信任任何一句"已覆盖"的声明。

## 文档索引

| 文件 | 对应流程节点 | 模板 |
| --- | --- | --- |
| `01-需求规格书.md` | SP-03 需求分析 | `需求规格书.template.md` |
| `02-开发计划.md` | SP-04 架构设计 | `开发计划.template.md` |
| `03-任务清单.md` | SP-04 架构设计 | `任务清单.template.md` |
| `04-详细设计说明书.md` | SP-04 架构设计 | `详细设计说明书.template.md` |
| `06-性能优化说明.md` | SP-07 性能设计 | `性能优化说明.template.md` |
| `07-接口数据契约.md` | SP-06 接口数据契约 | `接口数据契约.template.md` |
| `08-UI设计说明.md` | SP-08 UI 设计 | `UI设计说明.template.md` |
| `10-单元测试用例.md` | SP-13 质量门禁 | `单元测试用例.template.md` |
| `11-单元测试报告.md` | SP-13 质量门禁 | `单元测试报告.template.md` |
| `12-集成测试用例.md` | SP-13 质量门禁 | `集成测试用例.template.md` |
| `13-集成测试报告.md` | SP-13 质量门禁 | `集成测试报告.template.md` |
| `14-代码评审.md` | SP-13 质量门禁 | `代码评审.template.md` |
| `15-安全评审.md` | SP-13 质量门禁 | `安全评审.template.md` |
| `16-E2E测试用例.md` | SP-14 E2E 测试 | `E2E测试用例.template.md` |
| `17-E2E测试报告.md` | SP-14 E2E 测试 | `E2E测试报告.template.md` |
| `18-部署说明.md` | SP-15 发布准备 | `部署说明.template.md` |
| `19-监督审计.md` | SP-17 监督审计 | `监督审计.template.md` |
| `可观测性报告.md` | SP-17 监督审计 | `可观测性报告.template.md` |

流程节点定义见 [`assets/config/skill-process.json`](../assets/config/skill-process.json)；节点与角色的对应关系见 [`references/team-overview.md`](../references/team-overview.md)。

## 校验这份示例

```bash
# 文档章节结构是否与模板一致
python scripts/validate_doc_structure.py --skill-root . --project-root .

# 需求 → 代码符号 → 测试 的追踪链是否完整（Must-FR 与 P0-AC 必须双链接）
python scripts/validate_code_traceability.py --help

# 交付门禁总检
python scripts/validate_delivery.py --skill-root . --project-root .
```

## 说明与边界

- 示例中的主机名、端口、账号一律为占位符（如 `${DB_PASSWORD}`、`mes-lite.example.com`），**不含任何真实地址或凭据**。
- 示例展示了流程的**产物形态**，不代表本仓库包含一个可运行的 MES 实现——本仓库是交付治理框架，不是业务系统。
- 示例文档中的测试数量与覆盖率数字用于演示报告格式；框架自身的真实测试结果请运行 `python run_tests.py`。
