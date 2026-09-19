# Deploy-Only Workflow

## 触发条件

当用户意图为**仅部署已开发好的项目到生产环境**时激活此路由。

关键词匹配（任一即触发）：
- "部署到生产环境"
- "部署到正式环境"
- "发布到正式环境"
- "上线"
- "deploy to production"
- "push and deploy"
- "发布上线"

**前提条件**：
- 项目代码已在本地开发调试完成
- 用户无新功能开发意图（无需求分析、架构设计等）
- 仅需将当前代码推送并触发自动部署

## 路由链路

```
Orchestrator → DevOps Release Engineer (deploy-only mode) → end
```

**跳过的角色**：Product Analyst, Architect, Data Engineer, Data Contract Designer, UI Designer, Execution Engineer, Frontend Engineer, Backend Engineer, Quality Gate Engineer, Browser E2E Engineer, Documentation Writer, Supervisor Auditor

## DevOps Release Engineer 在 deploy-only 模式下的职责

### 执行步骤

1. **环境预检**
   - **工具链检查（第一步，不可跳过）**：
     - 运行 `python scripts/preflight_env_check.py` 检查 Git / JDK / Node.js / Maven / Python 版本门禁
     - 缺失工具链时按 `references/environment-provisioning.md` 自动安装，**不得以“环境不支持”为由降级**
   - 确认 Git remote 已配置：`git remote -v`（远端名默认 `origin`）
   - 确认项目包含 CI 配置（`Jenkinsfile` / `.github/workflows/` / `.gitlab-ci.yml` 任一）与 `docker-compose.yml`
   - **推送认证一律使用平台自身的凭据管理**（Git credential helper、SSH key、CI Secret 或平台 Token 环境变量）。
     禁止在仓库中出现明文账号密码；若缺少凭据，挂起并询问用户

2. **代码提交与推送**
   ```bash
   git add .
   git status  # 确认变更内容
   git commit -m "deploy: release to production"
   git push origin main
   ```

3. **等待 CI 构建**
   - 推送触发 CI Pipeline 自动执行（Webhook 或平台内置触发）
   - 轮询 CI API 获取构建状态（**首次构建最多等 20 分钟**（依赖下载慢），后续构建最多 8 分钟）
   - 构建 URL 形如：`{JENKINS_URL}/job/{project-slug}/lastBuild/`
     （非 Jenkins 平台按其等价 API 查询，例如 GitHub Actions 的 `gh run view`）

4. **验证部署结果**
   - **从构建日志解析端口**（生产端口由服务器 Allocate Ports stage 统一分配，本地不可假设）：
     读取构建日志中最后一条结构化部署结果，例如
     `DEPLOY_RESULT: slug=... status=... frontend=http://...:{FP} backend=http://...:{BP}`
   - 健康检查：`curl -sf {backend}/actuator/health`（Java）或 `{backend}/health`（Node/Python）
   - 前端可访问：`curl -sf {frontend}`
   - 超时/失败则输出 CI 构建日志摘要

5. **输出部署报告**
   - 部署状态（成功/失败）
   - 访问地址
   - 构建耗时
   - 如果失败：错误原因 + 建议修复方案

### 输出格式

```
✅ 部署成功！

📦 项目：{project-slug}
🌐 前端地址：http://{DEPLOY_HOST}:{frontend_port}
🔧 后端地址：http://{DEPLOY_HOST}:{server_port}
⏱️ 构建耗时：{duration}
📋 构建记录：{JENKINS_URL}/job/{project-slug}/{build_number}/
```

或失败时：

```
❌ 部署失败

📦 项目：{project-slug}
❗ 失败阶段：{stage_name}
📋 错误信息：{error_summary}
🔗 完整日志：{JENKINS_URL}/job/{project-slug}/{build_number}/console
💡 建议：{fix_suggestion}
```

## 与完整流程的区别

| 对比项 | 完整流程 | Deploy-Only |
|---|---|---|
| 触发词 | "开发XX功能" | "部署到生产环境" |
| 角色数量 | 12+ 角色 | 仅 DevOps RE |
| 文档产出 | 19 份文档 | 无（仅输出部署报告） |
| 测试要求 | 单元/集成/E2E | 仅健康检查 |
| 预计耗时 | 30min~数小时 | 2~5 分钟 |

## 安全约束

- 如果检测到项目从未通过完整流程部署过（无 `docs/18-部署说明.md`），首次部署时发出警告但不阻塞
- 如果 `git status` 显示有未跟踪的 `.env` 或凭据文件，**禁止推送**并提示用户检查 `.gitignore`
- 推送前自动检查 `.gitignore` 是否包含 `.env`、`*.pem`、`*.key`

## 回退条件

以下情况应**回退到完整流程**而非使用 deploy-only：
- 用户同时描述了新功能需求（"加一个XX功能然后部署"）
- 项目尚不存在（需要从零创建）
- 用户明确要求代码评审或测试

## 首次部署的项目接入

如果目标项目尚未接入 CI，deploy-only 路由应先完成**一次性接入**（由用户或管理员执行）：

1. 在代码托管平台创建仓库，配置好远端
2. 在 CI 平台创建 Pipeline 并指向该仓库
3. 在 CI 平台配置部署凭据（Secret / Credential），**不要写入仓库**
4. 配置 Webhook 或平台触发规则

接入完成后，本流程只负责 push + 验证，不再涉及平台初始化。
本 Skill **不提供**任何平台专用的初始化脚本——那是平台绑定配置，属于使用方环境职责。
