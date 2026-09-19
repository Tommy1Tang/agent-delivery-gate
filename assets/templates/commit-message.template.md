# Commit Message Template

> 所有由 software-development-team skill 产出的提交都必须遵循 Conventional Commits 1.0，并在 footer
> 关联交付证据。Quality Gate Engineer / DevOps Release Engineer 在合并前必须校验本格式。

## 格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

## 字段约束

| 字段 | 取值 | 约束 |
| --- | --- | --- |
| type | feat / fix / refactor / perf / docs / test / build / ci / chore / revert / security / hotfix | 必须使用枚举内的值，禁止自创 |
| scope | 模块或子系统名（小写，- 分隔） | 必填；多 scope 用 `,` 分隔 |
| subject | 祈使句，<= 72 字 | 不以句号结尾；中英文均可 |
| body | 说明 What/Why/How | 至少 1 段；说明动机与影响范围 |
| footer | 关联 issue、证据、Breaking Change | 见下文 |

## Footer 必填项

```
Refs: <需求 ID 或 issue 链接>
Evidence-Ledger: docs/22-交付证据账本.md
Quality-Gate: PASS | BLOCK
E2E-Report: docs/17-E2E测试报告.md
Reviewed-by: <quality-gate-engineer 等角色>
```

如果存在破坏性变更，必须额外声明：

```
BREAKING CHANGE: <说明影响、迁移步骤、回滚路径>
```

## 示例

```
feat(ticket-api): 引入工单批量分派接口

新增 POST /api/tickets/batch-assign，支持一次性把多个工单分派给同一处理人，
减少调度员重复操作。后台使用乐观锁防止并发冲突。

Refs: REQ-2026-031
Evidence-Ledger: docs/22-交付证据账本.md
Quality-Gate: PASS
E2E-Report: docs/17-E2E测试报告.md
Reviewed-by: quality-gate-engineer, browser-e2e-engineer
```

## 校验

- `validate_delivery.py` 不直接检查提交信息，但要求 `docs/18-部署说明.md`、`docs/22-交付证据账本.md`
  与提交保持一致；任何缺位都会导致门禁 BLOCK。
- 若使用 commit hook，请在仓库根目录配置 `commitlint`（或等价工具）以强制本模板。
