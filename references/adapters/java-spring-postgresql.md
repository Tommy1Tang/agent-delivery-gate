# Java + Spring Boot + PostgreSQL Adapter

Use this adapter only when project reality or user request explicitly uses Java, Spring Boot, and PostgreSQL.

## Architecture Defaults

- Layering: Controller -> Service -> Repository/Mapper. Cross-layer calls forbidden.
- DTO/VO separation is mandatory. Never return Entity directly to API.
- Use constructor injection (`@RequiredArgsConstructor`). `@Autowired` field injection forbidden.
- Use transactions for write operations: `@Transactional(rollbackFor = Exception.class)`.
- Business errors must throw custom `BusinessException`. Never return raw error strings.
- Collection-returning methods must return `Collections.emptyList()`, never `null`.
- PostgreSQL DDL should include `COMMENT ON` for all tables and columns, and indexes for queried fields.
- Use partial indexes (`WHERE is_deleted = 0`) for soft-delete unique constraints.
- Avoid foreign-key cascade when business logic owns integrity.
- Use `TIMESTAMP` for datetime fields, `SMALLINT` for boolean-like flags.

## 统一封装复用规则

写代码前必须先检查以下统一封装是否已存在，已有则复用：

- `Result<T>` — 统一返回封装
- `PageResult<T>` — 分页返回封装
- `BusinessException` + `ErrorCode` — 业务异常体系
- `BaseEntity` — 审计字段基类（created_at, updated_at, created_by, updated_by, is_deleted）
- `GlobalExceptionHandler` — 全局异常拦截
- 已有 Entity / DTO / VO 类 — 在现有基础上修改，禁止重复创建同名类

## 数据库变更规范

- 表结构变更必须创建 SQL 迁移脚本（放入 `src/main/resources/db/` 或项目已有迁移目录）。
- 脚本必须注明前后兼容性影响。
- 禁止在代码中直接 DDL，禁止不经脚本直接修改生产表结构。
- 大表索引创建使用 `CREATE INDEX CONCURRENTLY` 避免锁表。

## Validation Commands

- `mvn test` — 单元测试（必须执行）
- `mvn compile` — 编译检查（必须执行）
- 项目特定的构建/打包命令（以项目实际配置为准）

## Notes

- Do not apply this adapter to Python/FastAPI projects.
- Use project-local conventions before generic Spring assumptions.
- Check and reuse existing unified wrappers (Result, BusinessException, BaseEntity) before creating new ones.
- `application.yml` changes must include comments for new entries; sensitive values must use env-var placeholders.
- JDBC driver: `org.postgresql.Driver`, URL format: `jdbc:postgresql://host:5432/dbname`.
