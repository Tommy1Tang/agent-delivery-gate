# 单元测试报告

## 项目信息
- **项目名称**: 工单管理系统
- **测试时间**: 2026-05-20T14:30:00
- **测试框架**: JUnit 5 + Mockito
- **构建工具**: Maven 3.9

## 测试结果摘要

单元测试覆盖率：92.3%
集成测试覆盖率：85.1%
测试通过率：100%
测试总数：47
通过数：47
失败数：0
跳过数：0

## 覆盖率明细

| 模块 | 行覆盖率 | 分支覆盖率 | 方法覆盖率 |
|------|---------|-----------|-----------|
| service | 95.2% | 88.0% | 100% |
| controller | 90.1% | 82.5% | 100% |
| security | 91.8% | 85.3% | 95.0% |
| common | 88.5% | 80.0% | 92.0% |

## 测试用例列表

| # | 测试类 | 方法 | 结果 | 耗时 |
|---|--------|------|------|------|
| 1 | TicketServiceImplTest | testCreateTicket_success | PASS | 120ms |
| 2 | TicketServiceImplTest | testCreateTicket_invalidInput | PASS | 45ms |
| 3 | TicketServiceImplTest | testAssignTicket_success | PASS | 89ms |
| 4 | TicketServiceImplTest | testAssignTicket_notFound | PASS | 32ms |
| 5 | AuthServiceTest | testLogin_success | PASS | 156ms |
| 6 | AuthServiceTest | testLogin_wrongPassword | PASS | 78ms |
| ... | ... | ... | ... | ... |

## 构建验证

```
$ mvn test
[INFO] Tests run: 47, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS
[INFO] Total time: 12.345 s
```

## 执行证据

- 构建日志: `target/surefire-reports/`
- JaCoCo 报告: `target/site/jacoco/index.html`
- 截图: N/A（单元测试无 UI）
