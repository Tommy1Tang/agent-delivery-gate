# Release Checklist

在导出或发布 `software-development-team` skill 之前，检查以下内容：

## Required Files
- `SKILL.md` 存在且 frontmatter 正确
- `references/team-overview.md` 存在
- `references/team-workflow.md` 存在
- `references/workflow-matrix.md` 存在
- `references/change-management-workflow.md` 存在
- `references/security-governance-workflow.md` 存在
- `references/incident-management-workflow.md` 存在
- `references/forward-development-template.md` 存在
- `references/change-request-template.md` 存在
- `references/security-review-template.md` 存在
- `references/security-assessment-template.md` 存在
- `references/incident-report-template.md` 存在
- `references/workflow-audit-template.md` 存在
- `references/task-template.md` 存在
- `references/unified-large-delivery-policy.md` 存在
- `assets/prompts/` 下角色 prompt 文件齐全
- `assets/config/agent-team-config.yaml` 存在
- `assets/config/agent-team-config.json` 存在

## Consistency Checks
- 角色名称在 SKILL.md、config、prompt 文件中保持一致
- unified large-delivery 路径与 workflow 文档一致
- routing 规则与团队说明一致，且不再残留 small / medium / large 分流逻辑
- 四类流程域（正向、变更、安全、异常）在 SKILL、workflow、governance、config 中均已接入
- 四类流程模板与流程说明文档存在对应关系
- config 中的 promptFile 路径与 skill 内实际路径一致
- 所有任务的必备文档链路在 SKILL、workflow、prompt、config 中保持一致
- unified large-delivery policy 在 SKILL、workflow、prompt、config、checklist 中保持一致

## Packaging Checks
- skill 目录内不依赖 workspace 外部路径
- skill 内的说明文件足够让另一个 agent 理解如何使用
- 没有遗留占位文件或明显过时内容

## Optional Improvements
- 为每个角色补充更详细的输出模板
- 增加 release notes 或 version 记录
- 增加 unified large-delivery 的标准示例输入输出
