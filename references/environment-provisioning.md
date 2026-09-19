# Environment Provisioning Policy (环境自动安装策略)

当环境预检(`scripts/preflight_env_check.py` 或角色自行检测)发现**既定技术栈所需工具链缺失或版本不符**时,本策略是唯一合法的处理路径。

## 核心规则

🔴 **RED LINE — 环境缺失 ≠ 换栈理由**:开发机缺少 JDK、Maven、Node、Python 等工具链时,**禁止**以此为由更换 `tech.md` / 架构设计已确定的技术栈。唯一合法路径按以下顺序执行:

1. **自动安装**(默认,无需向用户确认)
2. 安装不可行时 → **挂起问用户**(`deliveryStatus = halted-pending-user`)

🔴 **RED LINE — PostgreSQL / Redis 禁止本地安装**:开发机上**永远不安装** PostgreSQL 16 与 Redis(既不用 winget/choco 原生安装,也不用本地 Docker 容器)。开发、联调、测试应当直连**团队共享的**数据库/缓存实例,而不是每台开发机各装一套。实例地址必须通过环境变量配置(`DB_HOST` / `REDIS_HOST`,或项目的 `.env`),以 `scripts/preflight_server_check.py` 的检查结果为准;**禁止把真实地址写进仓库**。发现缺“数据库/缓存”时的正确动作是**检查服务器实例连通性**,而不是在开发机装一个。

"project reality first, governance second" 中的 project reality 指**项目代码库的既有架构与依赖**,不包括开发机工具链的临时缺失。环境缺失是待修复的基础设施问题,不是可以改变选型的"项目现实"。

## 工具链版本基线(必须精确满足)

| 工具链 | 版本要求 | 判定规则 |
|--------|---------|---------|
| Git | 2.x | `git --version` 主版本 ≥ 2(交付流程强依赖:代码推送、commit、CI) |
| JDK | 17 | `java -version` 主版本 ≥ 17(以 17 为基线安装) |
| Node.js | 22 | `node --version` 主版本 == 22 |
| Maven | 3.x | `mvn --version` 主版本 == 3(禁止装 Maven 4) |
| Python | 3.12 | `python --version` == 3.12.x |

只装了工具但版本不符(如 Node 18、Python 3.10)与"未安装"同等对待:走自动安装流程补装正确版本,用版本管理器隔离,**禁止卸载或覆盖用户已装版本**。

## 全新系统引导(Bootstrap,第 0 步)

预检和安装脚本本身是 Python 写的,**全新 Windows 没有 Python**(`python` 命令只是打开微软商店的假 stub)。因此当 `python`/`py -3.12` 不可用或无法输出真实版本号时,必须先执行零依赖引导脚本(只依赖系统自带的 PowerShell + winget):

```
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_env.ps1
```

它会:检测 winget → 用户级静默安装 Python 3.12(失败自动回退默认作用域)→ 刷新 PATH → 自动接力执行 `provision_env.py` 完成其余工具链。

**无 winget 兜底(LTSC / Server / 组策略禁用)**:winget 不可用**不是**挂起理由。bootstrap 自动改从 python.org 直接下载官方安装包静默安装 Python;`provision_env.py` 检测到无 winget 时自动切换 **direct 直连模式**,其余工具链改用官方安装包/压缩包:

| 工具 | 直连来源 | 安装方式 |
|------|---------|---------|
| Git | github.com/git-for-windows 官方 exe | `/VERYSILENT /NORESTART` |
| JDK 17 | `aka.ms/download-jdk`(微软官方 zip) | 解压至 `%USERPROFILE%\tools`,写入用户 PATH + JAVA_HOME |
| Node 22 | nodejs.org 官方 zip | 解压至 `%USERPROFILE%\tools`,写入用户 PATH |
| Maven 3.9 | archive.apache.org 官方 zip | 解压至 `%USERPROFILE%\tools`,写入用户 PATH |
| Python 3.12 | python.org 官方 exe | `/quiet InstallAllUsers=0 PrependPath=1` |

direct 模式只依赖网络。winget 与直连下载**都**失败(通常意味着无网络或下载域被防火墙拦截)时,bootstrap 以退出码 2 结束,按挂起条件处理。

**权限说明**:Python(用户级)、nvm-windows、Git 通常无需管理员权限;JDK 17 是机器级 MSI,未提权会话可能触发 UAC 或失败——失败即按挂起条件 #2 问用户,禁止换栈。

## 自动安装流程

1. **检测**:运行 `python scripts/preflight_env_check.py --json` 获取缺失/版本不符清单(含部署服务器 PostgreSQL/Redis 连通性检查;默认按“新终端视角”刷新 PATH 后检查)
2. **安装**:运行 `python scripts/provision_env.py`(推荐,内置命令映射/重试/验证/PATH 刷新),或按下表手工执行。所有 winget 命令必须附带静默参数:`--silent --accept-package-agreements --accept-source-agreements`

   | 缺失项 | Windows 安装命令(首选 → 备选) |
   |--------|------------------------------|
   | Git | `winget install Git.Git --silent --accept-package-agreements --accept-source-agreements` |
   | JDK 17 | `winget install Microsoft.OpenJDK.17 --silent --accept-package-agreements --accept-source-agreements` |
   | Node.js 22 | 已有其他版本 Node 时:`winget install CoreyButler.NVMforWindows` 后 `nvm install 22 && nvm use 22`;干净机器:`winget install OpenJS.NodeJS.LTS --version 22.20.0 --silent --accept-package-agreements --accept-source-agreements`(先用 `winget show OpenJS.NodeJS.LTS --versions` 确认 22.x 可用版本号,LTS 包主版本漂移时改用 nvm 路径) |
   | Maven 3 | `winget install Apache.Maven --silent --accept-package-agreements --accept-source-agreements`(安装后必须验证主版本为 3;若 winget 源已升到 4.x,改为下载 Maven 3.9.x 二进制包解压至 `%USERPROFILE%\tools\maven` 并写入 PATH) |
   | Python 3.12 | `winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements`(与已有其他版本共存,项目内用 `py -3.12 -m venv .venv` 指定解释器) |
   | PostgreSQL 16 | ❌ **禁止本地安装**。改为验证部署服务器 5432 连通,项目 dev 配置直连服务器实例 |
   | Redis | ❌ **禁止本地安装**。改为验证部署服务器 6379 连通,项目 dev 配置直连服务器实例 |

   - macOS: `brew install openjdk@17 maven python@3.12`,Node 用 `nvm install 22`
   - Linux: `apt-get install openjdk-17-jdk maven` / `dnf` 按发行版,Node 用 nvm,Python 用 pyenv/deadsnakes
3. **刷新 PATH 再验证**:winget 安装的工具**不会出现在当前会话的 PATH 中**。安装后必须先刷新再验证,否则会误判失败:
   - `provision_env.py` 已内置(从注册表重读机器+用户 PATH)
   - 手工场景(PowerShell):`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`
4. **多版本共存隔离**(禁止卸载/覆盖已有版本):
   - Node 多版本 → nvm-windows(`nvm use 22` 仅影响当前机器默认,记录原版本以便说明)
   - JDK 多版本 → 会话级设置 `JAVA_HOME` 指向 JDK 17 安装目录,并把 `%JAVA_HOME%\bin` 置于 PATH 前部;不改动用户全局 JAVA_HOME
   - Python 多版本 → 不动系统默认 `python`,项目统一用 `py -3.12 -m venv .venv` 创建虚拟环境
5. **验证**:重新运行 `preflight_env_check.py`,确认 `status = ready`(四件工具链版本全部达标 + 服务器 PostgreSQL 可达)才继续派发角色
6. **记证**:把「检测到的缺失项、执行的安装命令、验证结果」写入 evidence ledger(`envProvisioning` 字段)与 `docs/执行日志.md` 关键决策记录

## 数据库与缓存:一律使用部署服务器实例

- 后端项目的 `application-dev.yml` / `.env` 等开发配置,datasource / redis 地址**必须**指向部署服务器,**禁止**出现 `localhost:5432`、`127.0.0.1:5432`、`localhost:6379`、`127.0.0.1:6379`
- 数据库按项目分库、按用户隔离账号(见 `infrastructure/` 的 PostgreSQL 初始化机制),不与其他项目混用库
- 预检发现开发机上已装有本地 PostgreSQL/Redis 时:**不卸载**(可能是用户自用),但本次交付的项目配置不得连接它,并在预检报告中给出 warning
- 服务器 PostgreSQL 5432 不可达 → blocking,按挂起条件处理;Redis 6379 不可达 → warning(记录并提示,不阻塞纯 DB 项目)

## 授权边界

- 自动安装属于 `autonomous-update-policy.md` 定义的**非破坏性操作**,不需要用户确认
- 安装范围仅限:Git / JDK 17 / Node.js 22 / Maven 3 / Python 3.12 及其版本管理器(nvm-windows、SDKMAN、pyenv),官方包管理器分发版
- 禁止:安装 PostgreSQL/Redis 到开发机、修改系统全局配置以外的无关软件、卸载已有版本、覆盖用户手工安装的工具链(存在多版本冲突时用版本管理器隔离)

## 挂起条件(halted-pending-user)

以下情形自动安装不可行,必须写入 `deliveryStatus = halted-pending-user` 并问用户,**仍然禁止自行换栈**:

1. winget 与直连官方下载均不可行(通常为无网络或下载域被防火墙拦截;仅 winget 缺失不构成挂起,自动走 direct 直连模式)
2. 安装需要管理员权限且当前会话无法提权
3. 需要用户交互的安装步骤(如许可协议、账号登录)
4. 同一工具链安装重试 3 次仍验证失败
5. 磁盘空间不足等宿主机资源问题
6. 部署服务器 PostgreSQL(5432)不可达且按 `preflight_server_check.py` 的用户指引仍无法恢复(此时问用户协调服务器/网络,**不是**在本地装 PostgreSQL)

挂起时向用户呈现两个选项:「协助完成安装/恢复服务器连通」或「明确授权更换技术栈」。只有用户**明确授权**后,换栈才合法,且必须按 change-management-workflow 记录变更。

## 与其他规则的关系

- 本策略优先于 `local-governance.md` 第 2 条的"project reality first"解释
- ASK_USER_TRIGGERS #5(技术栈重大变更必须问用户)同时覆盖:替换已有基线,**以及**新项目首次选型偏离 `tech.md`
- 红线「环境问题不能作为跳过测试指标的理由」与本策略配套:环境修好后测试门禁照常执行,不降级
- 部署服务器基础设施(Gitea/Jenkins/PostgreSQL/Redis)的搭建与修复属于 `infrastructure/` 与 `preflight_server_check.py` 的职责,不在开发机 provisioning 范围内
