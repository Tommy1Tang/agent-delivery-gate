 Task Template Reference

Use this in-skill task intake template when structuring software development requests.
When user input is vague or incomplete, use the **progressive elicitation framework** below to gather information in stages.

## Quick Capture (always fill)

- Task summary
- Goal
- Scope
- Not in scope
- Constraints
- Affected areas
- Interface or data contract
- Acceptance criteria
- Test scenarios
- Delivery mode
- Applicable workflow domain (正向标准流程 / 需求变更流程 / 安全管控流程 / 异常问题处理流程 / 需求梳理流程)
- Risk notes and open questions

## Progressive Elicitation Framework（渐进式需求采集框架）

When user input is insufficient to produce a quality PRD, use this 3-layer framework. **Never ask more than 5 questions per round.**

### Layer 1: Core Questions（必答层，5 个核心问题）

These must be answered before ANY PRD work begins:

| # | Question | Purpose | If unanswered |
|---|---|---|---|
| L1-1 | **做什么？**（用一句话描述你想要系统实现的核心能力） | 确定 FR 范围 | 阻塞：无法开始 |
| L1-2 | **给谁用？**（主要用户角色，每个角色的核心诉求） | 确定利益相关者 | 推断：默认单一角色 |
| L1-3 | **解决什么问题？**（现状痛点 + 量化数据） | 确定背景与目标 | 推断：标注为「背景待确认」 |
| L1-4 | **什么时候要？**（期望上线时间 + 是否有硬截止日期） | 确定时间敏感性 | 推断：默认下一迭代 |
| L1-5 | **做到什么程度算完？**（你最在意的 1-3 个验收标准） | 确定核心 AC | 推断：由 PA 提供候选 AC 让用户确认 |

### Layer 2: Context Questions（按需层，根据 Layer 1 答案动态生成）

仅当 Layer 1 答案触发以下信号时追问：

| 触发信号 | 追问方向 | 示例问题 |
|---|---|---|
| 涉及多角色 | 角色权限与交互 | 不同角色的操作范围？谁能看到什么？ |
| 涉及状态变化 | 状态机与流程 | 有几种状态？怎么流转？能否回退？ |
| 涉及已有系统 | 集成与依赖 | 和现有系统怎么对接？有哪些接口？ |
| 涉及数据处理 | 数据模型与存储 | 数据从哪来？保留多久？谁能删？ |
| 涉及外部用户 | 安全与合规 | 有个人信息吗？有支付吗？受什么法规约束？ |
| 涉及性能敏感 | 非功能需求 | 同时多少人用？多快算快？能挂多久？ |
| 涉及变更现有功能 | 影响范围 | 原来的逻辑怎么处理？有人正在用吗？ |

### Layer 3: Deep-dive Questions（深挖层，仅大需求 FR ≥ 5 时）

| 领域 | 典型问题 |
|---|---|
| 业务规则 | 有什么不能违反的硬规定？有例外吗？ |
| 异常场景 | 网络断了/并发冲突/用户误操作时怎么办？ |
| 度量指标 | 上线后怎么知道做对了？用什么数字衡量？ |
| 优先级 | 如果资源只够做一半，哪些功能先做？ |
| 备选方案 | 有没有其他实现路径？各自优缺点？ |

### Recommended Defaults（推荐默认值）

When users cannot provide specific values, offer these as starting points:

| 项目 | 推荐默认值 | 适用场景 |
|---|---|---|
| 接口响应时间 | 95% 请求 ≤ 200ms | 中小型业务系统 |
| 页面加载时间 | 95% ≤ 1 秒（首屏） | 普通 Web 页面 |
| 系统可用性 | 99.9%（月停机 ≤ 43 分钟） | 内部业务系统 |
| 并发承载 | 日常 100 人在线，峰值 500 人 5 分钟 | 中小型团队工具 |
| 数据保留 | 业务数据永久；操作日志 ≥ 180 天 | 一般合规要求 |
| 单测覆盖率 | ≥ 90%（项目硬阈值） | 所有项目 |
| 集测覆盖率 | ≥ 80%（项目硬阈值） | 所有项目 |

### Domain-Specific Question Bank（领域适配问题库）

When user input contains domain keywords, auto-append these questions to Layer 2:

| 领域关键词 | 额外必问 |
|---|---|
| 工单 / 客服 / 支持 | 工单类型几种？有 SLA 吗？自动分配规则？升级策略？ |
| 订单 / 支付 / 结算 | 支付方式？退款流程？对账周期？超时自动取消？ |
| 审批 / 流程 / OA | 审批层级？能撤回吗？代审批？会签/或签？超时默认通过？ |
| 报表 / 统计 / 分析 | 实时还是 T+1？数据源？导出格式？权限粒度？ |
| 用户 / 注册 / 认证 | 注册方式？多因子？密码策略？第三方登录？ |
| 消息 / 通知 / 推送 | 渠道（站内信/邮件/短信/推送）？模板管理？限频策略？ |
| 权限 / 角色 / 组织 | RBAC 还是 ABAC？多租户？数据隔离级别？ |

## Elicitation Rules（采集规则）

1. **每轮最多 5 个问题**：超过 5 个问题时，按阻塞程度排序，先问最阻塞下游的。
2. **给推荐值而非空白**：对用户可能不知道的技术性问题（NFR），附上推荐默认值让用户选择"用这个 / 改成 X"。
3. **允许「不确定」**：用户回答「不确定」时，PA 在 PRD 中标为「推断项：XXX，待用户确认」，不要猜测填充。
4. **骨架优先**：Layer 1 收集完毕后先产出 PRD 骨架（见 PRD Generation Protocol），用户确认方向后再深入细节。
5. **不过度追问**：如果用户表示"其他你来定"，PA 可以基于领域常识填写推断值，但必须全部标注为「推断项」。
