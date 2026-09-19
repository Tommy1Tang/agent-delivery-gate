# Reverse Sync Task Template

Use this template for 反向同步任务（code → PRD back-fill）。Pair with `references/reverse-sync-workflow.md`.

## 1. 漂移基本信息
- 任务标题：
- 漂移来源（driftSource）：commit hash / PR 号 / hotfix 单号
- 漂移类型（driftType）：api | schema | ui-flow | config | behavior
- 发现方式：contract_drift_check | requirement_drift_check | trace_requirements | manual-review | code-review
- 发现时间：
- 责任发起角色：

## 2. 漂移项明细
- 漂移单元：
  - API：`{method} {path}`
  - schema：`{table}.{column}`
  - ui-flow：`{routeName} / {action}`
  - config：`{configKey}` `{oldValue}` → `{newValue}`
  - behavior：自由描述
- 影响范围说明：
- 现有代码位置：
- 是否紧急：是 / 否

## 3. PRD 归属判定
- 关联 FR/NFR id（originFRId）：FR-xxx / NFR-xxx / 新建 / 不适用
- 关联依据：
- 闭环路径：
  - [ ] Path A — 既有 FR 验收准则修订
  - [ ] Path B — 新增 FR/NFR
  - [ ] Path C — 写入 `docs/19-内部变更登记.md`（仅限纯内部、无用户可见行为变更）
- Path C 必填：用户可见行为变更证据已排查清单：

## 4. 回写章节清单（prdSections）
- `docs/01-需求规格书.md`：
- `docs/04-详细设计说明书.md`：
- `docs/07-接口数据契约.md`：
- `docs/10-单元测试用例.md`：
- `docs/12-集成测试用例.md`：
- `docs/16-E2E测试用例.md`：
- `docs/18-部署说明.md`：
- `docs/19-内部变更登记.md`（仅 Path C）：

## 5. 受影响下游清单（traceabilityImpact）
- 测试用例需重写：
- 测试报告需回归：
- 已发布契约需通知消费方：
- 部署/运维变更：
- 数据迁移影响：

## 6. 闭环准则（closureCriteria）
- [ ] `scripts/contract_drift_check.py` → pass
- [ ] `scripts/requirement_drift_check.py` → pass
- [ ] `scripts/trace_requirements.py` → pass
- [ ] product-analyst 确认 FR 归属
- [ ] documentation-writer 完成下游级联
- [ ] supervisor-auditor 复核 `prdDriftClosed: true`
- [ ] evidence ledger 已写入 `reverse_sync_event` closure 记录

## 7. 决策与确认
- 推荐处理方案：
- 用户/责任人确认：
- 是否允许并入下一发布：是 / 否
- 残余风险：

## 8. 闭环执行结果
- 提交回写 commit：
- 重新运行漂移检测结果：
- 审计结论：
- 闭环时间：
