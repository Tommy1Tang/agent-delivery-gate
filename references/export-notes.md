# Export Notes

## Purpose
这份说明用于把 `software-development-team` 目录作为独立 skill 导出、迁移或发布时参考。

## Export Source
推荐直接以 `skills/software-development-team/` 作为导出根目录。

## Before Export
1. 确认 `assets/prompts/` 已同步最新 prompt 文件
2. 确认 `assets/config/` 已同步最新 config 文件
3. 对照 `release-checklist.md` 做一次完整检查

## If Skill Internals Changed
如果 skill 内部资源有更新，发布前需要重新确认以下内容一致：
- `assets/prompts/` 与当前统一大型项目流程规范一致
- `assets/config/agent-team-config.yaml` 与 `assets/config/agent-team-config.json` 一致
- `references/` 下的 workflow、template、governance 文档互相一致
- `references/unified-large-delivery-policy.md` 已同步并与其他文件一致
- 不存在 small / medium / large 分流残留，默认均为 unified large-delivery

## Suggested Packaging Behavior
- 保持 `SKILL.md` 为入口
- 保持 `references/` 作为说明层
- 保持 `assets/prompts/` 与 `assets/config/` 为可复用资源层

## Portability Reminder
为了让 skill 可独立导出：
- 不要依赖 workspace 内其他目录作为 canonical source
- 优先以 skill 自身的 `SKILL.md`、`references/`、`assets/prompts/`、`assets/config/` 作为完整事实来源
- 如需环境级本地规范，请在部署环境中重新配置本地 spec 路径，而不是假设固定工作区结构
