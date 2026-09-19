# Workflow Audit Template

Use this template when Supervisor Auditor checks workflow completeness.

## 1. 审计对象
- 任务名称：
- 任务类型：
- 适用流程域：正向标准流程 / 需求变更流程 / 安全管控流程 / 异常问题处理流程

## 2. Workflow Domain 校验

| 客观信号 | 对应 domain |
|---|---|
| 新功能开发 / 新增接口 / 新增页面 | forward-development |
| 修改已有需求 / 需求变更通知 / 新增约束 | change-management |
| CVE 修复 / 安全漏洞 / 依赖升级 / 权限加固 | security-governance |
| 线上 bug / 紧急修复 / 用户投诉 / 报错排查 | incident-management |

- Orchestrator 标注 domain：
- 任务描述中的客观信号：
- 校验结果：正确 / 误判
- 若误判，正确 domain 应为：

## 3. 角色调用审计
- 已调用角色：
- 应调用角色：
- 差异分析：
  - missing（缺失）：
  - unauthorized（越权）：
  - extra（多余）：
  - out-of-order（顺序错乱）：

## 4. 文档审计
- 应产出文档：
- 实际产出文档（磁盘 list_dir 确认）：
- evidence-ledger 中登记文档：
- 双向对账差异：
  - missing（磁盘缺失）：
  - unregistered（未在 ledger 登记）：
  - orphan（无 owner 认领）：
- 文档顺序是否合理：是 / 否

## 5. 流程审计
- 需求澄清是否完成：
- 规划是否完成：
- 验证是否完成：
- 风险是否披露：
- 是否存在跳步：

## 6. 硬指标审计

### 6.1 测试执行硬指标
| 指标 | 阈值 | 实际值 | 证据路径 | 达标 |
|---|---|---|---|---|
| 单元测试覆盖率 | ≥ 90% | | | |
| 集成测试覆盖率 | ≥ 80% | | | |
| E2E 通过率 | = 100% | | | |
| 测试编译 | BUILD SUCCESS | | | |
| 测试通过率 | = 100% | | | |

### 6.2 Validator 互锁
| 检查项 | 状态 | 证据路径 |
|---|---|---|
| deliveryGateEvidence 字段存在 | | |
| validate_delivery.py status = pass | | |
| blocking 列表为空 | | |

### 6.3 交付状态与返工
| 检查项 | 值 | 证据路径 |
|---|---|---|
| deliveryStatus | | |
| reworkCount（≤10） | | |
| reworkPerRootCause 最大值（≤5） | | |

## 7. 专项流程审计
- 需求变更流程是否完整：
- 安全管控流程是否完整：
- 异常问题处理流程是否完整：

## 8. 规范符合性
- 是否存在猜测：
- 是否存在静默失败：
- 是否遵守本地规范：
- 是否遵守技术规范：
- Code Review verdict 是否被遵守：
- Security Review verdict 是否被遵守：

## 9. 审计结论

- 主要偏差（含分类 missing/unauthorized/extra/out-of-order/evidence-gap）：
- 是否允许进入下一阶段：
- 是否允许宣称完成：
- **审计结论**：通过 / 不通过，返工修复

## 10. 修复优先级清单（仅当不通过时填写）

| 优先级 | 描述 | 负责角色 | 验收标准 |
|---|---|---|---|
| P0 | | | |
| P1 | | | |
| P2 | | | |
