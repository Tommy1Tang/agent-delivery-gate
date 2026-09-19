# Pull Request Template

> 所有由 software-development-team skill 产出的 PR 必须使用本模板。任意一项「必填」缺失都会被
> Quality Gate Engineer 判定为 BLOCK，无法合并。

## 概述

- 任务类型：<!-- feat / fix / refactor / perf / docs / security / hotfix -->
- 关联需求：<!-- REQ-xxx / Issue #xxx -->
- 影响范围：<!-- backend / frontend / 数据库 / 部署 / 配置 / ... -->

## 背景与目标（必填）

> 简述要解决的问题、用户价值、不做的事情。

## 改动清单（必填）

| 模块 | 文件 | 变更说明 |
| --- | --- | --- |
|  |  |  |

## 角色派发记录（必填）

> 列出本次交付涉及的角色与对应的 handoff/产出文档；缺位的强制角色必须解释原因。

| 角色 | 是否参与 | 产出 / 证据 |
| --- | --- | --- |
| product-manager |  | docs/01-需求规格书.md |
| solution-architect |  | docs/04-详细设计说明书.md |
| backend-engineer |  |  |
| frontend-engineer |  |  |
| qa-engineer |  | docs/11-单元测试报告.md / docs/13-集成测试报告.md |
| **browser-e2e-engineer** | **必填** | docs/16-E2E测试用例.md / docs/17-E2E测试报告.md |
| security-engineer |  | docs/15-安全评审.md |
| quality-gate-engineer |  | docs/14-代码评审.md |
| devops-release-engineer |  | docs/18-部署说明.md |

## 自动化结果（必填）

| 检查项 | 结果 | 链接 / 证据 |
| --- | --- | --- |
| Lint / 静态扫描 | PASS / FAIL |  |
| 单元测试（≥ 90%） | PASS / FAIL |  |
| 集成测试（≥ 80%） | PASS / FAIL |  |
| **E2E 真实运行**（trace + 截图 + stdout 至少 2 项） | PASS / FAIL |  |
| 安全扫描（SAST/SCA） | PASS / FAIL |  |
| `validate_delivery.py` | PASS / BLOCK |  |

## 风险与回滚（必填）

- 主要风险：
- 回滚方案：
- 数据库变更回滚：

## Breaking Change

- 是否存在 Breaking Change：是 / 否
- 如是，迁移步骤：

## 关联证据

- 交付证据账本：`docs/22-交付证据账本.md`
- E2E 测试报告：`docs/17-E2E测试报告.md`
- 代码评审：`docs/14-代码评审.md`
- 部署说明：`docs/18-部署说明.md`

## Reviewer 检查清单

- [ ] 已阅读交付证据账本，所有 roleRuns.status = completed
- [ ] E2E 报告含真实 trace/截图/stdout（拒绝 AI 代笔）
- [ ] `validate_delivery.py` 输出 verdict=PASS
- [ ] 没有占位符（TBD / TODO / xxx）残留
- [ ] CHANGELOG / 版本号已同步
