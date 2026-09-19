# Technical Architecture & Coding Guidelines (技术架构与开发规范)

> **[System Note for AI]**
> 1. When generating, refactoring, or reviewing code, you MUST strictly read and follow the technology stack and rules defined in this document. 
> 2. If a user's request conflicts with these guidelines, prioritize these guidelines, warn the user, and provide compliant code. Do not use outdated libraries.
> 3. **Never output partial code with `// ... existing code ...`** unless the file is huge. Provide complete, runnable code. Keep your explanations concise.
> 4. If the tech stack list below contains multiple options (e.g., Java/Python), and the user hasn't clarified, **ASK FIRST**.
> 5. 🔴 **本地开发机环境不支持本文档技术栈时，不得更换技术栈。** 缺少 Git / JDK 17 / Node.js 22 / Maven 3 / Python 3.12 等工具链时，唯一合法路径是按 `references/environment-provisioning.md` **自动安装开发环境**（Windows 首选 `winget`，版本必须按该文档钉死；全新系统 Python 不可用时先执行 `scripts/bootstrap_env.ps1` 引导），安装无需用户确认；安装不可行时挂起（`halted-pending-user`）问用户，换栈只能由用户明确授权。「环境不支持」永远不是换栈或降级交付的理由。
> 6. 🔴 **PostgreSQL 16 与 Redis 禁止在开发机本地安装**（原生安装与本地 Docker 均禁止）。开发/联调/测试一律直连**部署服务器**上的 PostgreSQL 16 与 Redis 实例；项目 dev 配置中禁止出现 `localhost:5432` / `127.0.0.1:5432` / `localhost:6379` / `127.0.0.1:6379`。

---

## 1. 技术栈选型 (Technology Stack)
> **[Instruction for User]** 以下是项目技术栈清单，在实际开发前，**请删除不相关的选项，每项只保留一个具体的技术**。

### 1.1 前端 (Frontend)
- **核心框架**: Vue 3 (严格使用 `<script setup lang="ts">` 语法)
- **开发语言**: TypeScript (Strict Mode)
- **UI 库 & 样式**: Element Plus
- **状态管理**: Pinia (Vue)
- **构建工具**: Vite

### 1.2 后端 (Backend)
- **开发语言**: Java 17+  *(示例，请二选一)*
- **核心框架**: Spring Boot 3.x
- **持久层框架**: MyBatis-Plus

### 1.3 数据库与基础设施 (Infrastructure)
- **关系型数据库**: PostgreSQL 16+（**使用部署服务器实例**，开发机不本地安装）
- **缓存**: Redis（**使用部署服务器实例**，开发机不本地安装）
- **API 规范**: RESTful API + JSON (统一返回 `Result<T>` 封装对象)

---

## 2. 核心共识 (The Golden Rules)
无论使用何种语言，所有代码必须遵循以下基本原则：

1. **命名即注释 (Naming is Documenting)**：拒绝 `a`, `temp`, `data` 等无意义命名。变量和方法名必须准确表达其业务含义。
2. **单一职责 (Single Responsibility)**：一个函数/组件只做一件事。函数超过 50 行（前端组件逻辑超过 100 行）必须评估拆分。
3. **尽早返回 (Early Return)**：拒绝深层嵌套的 `if-else`。优先校验错误和边界条件，不满足则立即 `return` 或抛出异常。
4. **消除魔法值 (No Magic Numbers)**：严禁出现未解释的硬编码数字或状态字符串，必须提取为常量 (Constants) 或枚举 (Enums)。
5. **防御性编程 (Defensive Programming)**：永远不要信任外部输入。必须进行严格的非空 (Null)、边界和类型校验。
6. **完善日志记录 (Logging)**：关键业务流转、异常捕获处必须打印日志（包含上下文参数），严禁生吞异常。

---

## 3. 后端开发规范 (Backend Guidelines)

### 3.1 架构与隔离 (Architecture & DTO)
- **RESTful 规范**: URI 强制使用全小写、名词复数、中划线分隔（如 `/api/v1/user-profiles`），禁止在路径中使用动词。
- **严格数据映射**: 严禁将数据库实体（Entity/DO）直接返回给前端。必须严格拆分入参 `DTO` (Request) 和出参 `VO` (Response)。
- **架构分层**: 严格遵守 `Controller` -> `Service` -> `Mapper/DAO` 单向调用，严禁跨层（如 Controller 直接查库）。

### 3.2 Java 特定规范
- **命名**: 类名 `UpperCamelCase`，方法/变量 `lowerCamelCase`，常量 `UPPER_SNAKE_CASE`。
- **依赖注入**: 强制使用**构造器注入**（推荐 Lombok `@RequiredArgsConstructor`），严禁使用 `@Autowired` 字段注入。
- **异常与返回**: 业务逻辑错误应抛出自定义 `BusinessException`。返回集合的方法必须返回 `Collections.emptyList()`，严禁返回 `null`。
- **事务管理**: 写操作方法必须加 `@Transactional(rollbackFor = Exception.class)`。

### 3.3 安全规范 (Security)
- **防 SQL 注入**: 强制使用 ORM 提供的参数化查询，**严禁**手动拼接 SQL 字符串。

---

## 4. 前端开发规范 (Frontend Guidelines)

### 4.1 TypeScript 与强类型
- **严禁 Any 滥用**：应使用 `unknown` 替代，或定义具体的 `interface/type`。
- **接口命名**：不要使用 `I` 作为前缀（拒绝 `IUser`），直接命名为 `User` 或 `UserProps`。

### 4.2 组件化与解耦
- **组件命名**：文件和组件名称强制使用 `PascalCase`（如 `UserProfile.vue`）。
- **逻辑抽离**：非视图逻辑（如复杂的纯计算）必须抽离为独立的 composables (Vue3)。
- **API 层抽离**：严禁在视图组件中直接写 `axios.get`，所有 API 必须统一在 `src/api/` 下封装并导出。
- **样式隔离**：禁止写全局污染的 CSS，Vue 必须使用 `<style scoped>`。

---

## 5. 数据库与 SQL 规范 (Database & SQL)

### 5.1 DDL 建表规范
- **命名**: 表名和列名强制 `snake_case`（全小写下划线），不使用数据库保留字。
- **主键**: 每张表必须有且仅有一个名为 `id` 的主键（BIGINT 雪花算法或 UUID）。
- **强制审计字段**：
  - `created_at` (TIMESTAMP), `updated_at` (TIMESTAMP)
  - `created_by` (VARCHAR/BIGINT), `updated_by` (VARCHAR/BIGINT)
  - `is_deleted` (SMALLINT, 0=未删除, 1=已删除，**强制软删除**)
- **索引策略**: `WHERE`、`ORDER BY` 及 `JOIN` 关联字段必须建索引。注意：存在软删除时，业务唯一键需与 `is_deleted` 建立联合唯一索引（可使用 PostgreSQL 部分索引 `WHERE is_deleted = 0`）。
- **注释**: 每个表和字段**必须**包含明确的 `COMMENT ON` 注释。

### 5.2 DML 查询规范
- **禁止 SELECT ***：明确写出需要查询的字段名。
- **业务逻辑前置**：禁止使用存储过程、触发器或外键级联。所有数据完整性校验在应用层实现。

---

## 6. Git 工程化工作流 (Git Workflow)
> **[Note for AI]** When generating commit messages, strictly follow this Angular convention: `<type>(<scope>): <subject>`

- `feat`: 新增功能 (Feature)
- `fix`: 修复 Bug
- `docs`: 仅文档修改
- `style`: 代码格式调整（空格、格式化，不影响逻辑）
- `refactor`: 重构代码（不新增功能也不修复 bug）
- `perf`: 性能优化
- `test`: 新增或修改测试用例
- `ci`: CI/CD 配置变动
- `chore`: 构建过程或辅助工具变动
