# Code Intelligence Sidecar Contract

本契约把 `code-graph-rag` 的离线符号图能力接入现有 skill，但不改变需求真理源或
21 节点交付控制真理源。所有门禁事实均来自本地、规范化、内容寻址的 JSON 产物；
LLM 总结、embedding、生成式 Cypher 和在线图数据库只可用于探索，不可写成 PASS。

## Provider 锁定

- distribution / CLI：`code-graph-rag==0.0.779` / `cgr`
- version 输出：`code-graph-rag version 0.0.779`
- provider manifest：`manifest_version=1`
- codec schema sha256：`09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84`
- 离线命令：`cgr index --repo-path <repo> --output-proto-dir <dir> --split-index`
  并逐项传入 `--capture structure|calls|types|imports`；随后运行
  `cgr verify-index --index-dir <dir>`。后置比较可额外执行
  `cgr diff-index --old <before> --new <after> --json-out <file>`，但本侧车仍须独立对账。

适配器必须使用 argv list、`shell=False`；CLI、distribution 和 protobuf decoder 必须
来自同一已验证环境。命令缺失、版本/manifest/codec 漂移、非零退出、verify 失败、
protobuf 无法解码均返回稳定 `PROVIDER_*`/`INDEX_*` 诊断，核心结论为 UNKNOWN/BLOCK。
测试使用显式 `raw-graph.json` fixture 契约，不要求开发机安装 provider。

## 五类权威派生产物

1. `CodeIndexManifest`：repositoryId、HEAD/dirty、sourceDigest、configHash、provider、
   coverage、artifact/content hash。
2. `CodeIndexSnapshot`：文件哈希、SymbolRef、关系、unresolved endpoint 与 freshness。
3. `TraceBridge`：显式 requirement→SymbolRef→test exact 链接和 rejected 诊断。
4. `ImpactReport`：seed、scope、最短路径、affected、recommendedTests 与三态 verdict。
5. `IndexDiff`：file/symbol/relation/trace delta 与 changeSet reconciliation。

JSON 使用 UTF-8、对象键字典序、实体稳定排序、无 NaN/Infinity；`generatedAt`、
provider `created_at` 和 `contentHash` 自身不进内容哈希。路径只能是仓库相对 POSIX
路径；绝对路径、`..`、NUL、symlink escape 均拒绝。源码正文/snippet/凭据不写入产物。

`SymbolRef` 固定字段：`repositoryId, relativePath, qualifiedName, symbolKind,
startLine, endLine, manifestHash, symbolId`。行号 1-based 闭区间；`symbolId` 由前六项
稳定哈希生成。端点不能唯一恢复时写入 unresolved，不得用名称近似合并。

## 显式追踪语法

标记必须独占注释行：

```text
# @trace CAP-CODE-001 FR-003 AC-003 T-003
# @test-id TEST-CODE-003
```

允许 `# // /* * <!-- --` 注释前缀和匹配尾缀。`@trace` 至少含一个 CAP/FR/NFR/AC/
BR/ST ID；未知 ID、重复 ID、自由文本均 rejected。`@test-id` 在全仓唯一，且测试符号
必须同时声明 `@trace`。归属算法仅筛选同文件、包含声明行的 Function/Method/Class/
Section，再取跨度最小且唯一的符号；无候选为 orphan，并列最小为 ambiguous。
rejected/candidate 永远不能参与 C-CODE PASS。

## 受控查询与影响三态

`query_code_graph.py` 确定性支持 `definition / callers / callees / references / contains /
implements_requirement / tests_for` 七类中英文意图。返回 SymbolRef、相对路径、行区间和
关系路径；同名多候选返回 AMBIGUOUS 候选，不猜测。

影响分析先检查 UNKNOWN，再遍历 CALLS/REFERENCES/INSTANTIATES/INHERITS/IMPLEMENTS/
OVERRIDES/IMPORTS/EXPORTS 等双向关系。结论只允许 FOUND、NO_IMPACT、UNKNOWN：

| 码 | 原因 | 码 | 原因 |
| --- | --- | --- | --- |
| U-01 | INVALID_SEED | U-10 | UNRESOLVED_SYMBOL |
| U-02 | AMBIGUOUS_SEED | U-11 | UNRESOLVED_RELATIONSHIP |
| U-03 | STALE_HEAD | U-12 | TRACE_BRIDGE_STALE |
| U-04 | STALE_SOURCE_DIGEST | U-13 | UNKNOWN_REQUIREMENT_ID |
| U-05 | STALE_CONFIG | U-14 | DEPTH_TRUNCATED |
| U-06 | PROVIDER_UNAVAILABLE | U-15 | NODE_LIMIT_EXCEEDED |
| U-07 | PROVIDER_SCHEMA_MISMATCH | U-16 | TIMEOUT |
| U-08 | INDEX_INTEGRITY_FAILURE | U-17 | SOURCE_CHANGED_DURING_ANALYSIS |
| U-09 | COVERAGE_INCOMPLETE | U-18 | REPORT_SCHEMA_INVALID |

任一 U 码存在时，即使已找到局部路径也只能 UNKNOWN。NO_IMPACT 仅在 seed 唯一、
HEAD/source/config/provider/trace 新鲜、coverage 完整、无 unresolved、遍历未截断且源码
未竞态变化时成立。

## 后置对账与 C-CODE

后置对账比较文件哈希、符号、关系和 exact TraceLink。实际代码文件与声明 changeSet
双向不一致、符号超出 seed/affected/声明文件、关系端点越界、exact 链接退化或覆盖
下降均 BLOCK；前后 repository/provider/schema/config 不可比或分析期间 HEAD 变化为
UNKNOWN。

| Gate | 机械判据 | 接入点 |
| --- | --- | --- |
| C-CODE-01 | provider/version/schema/artifact/freshness | SP-10/11、SP-13、SP-18 |
| C-CODE-02 | eligible file/capture/canonical hash 完整 | SP-10/11、SP-13 |
| C-CODE-03 | marker/owner/test-id 无 rejected | SP-10/11、SP-13、SP-18 |
| C-CODE-04 | Must FR/P0 AC 均有 implementation+test | SP-13、SP-18 |
| C-CODE-05 | normal：新鲜非 UNKNOWN 影响报告；唯一 bootstrap：NOT_APPLICABLE+BOOTSTRAP_NOT_APPLICABLE | SP-10/11 entry |
| C-CODE-06 | normal：真实 after/diff 对账；bootstrap：PASS+BOOTSTRAP_BASELINE_CREATED+baseline-creation+diffClaimed=false | SP-12、SP-13、SP-18 |
| C-CODE-07 | 重算 artifact、inventory、baseline、activation、marker、token 与 ledger 绑定 | SP-18 |

CLI 统一退出码：0=SUCCESS/PASS，1=非法输入或 BLOCK，2=UNKNOWN。旧 ledger 缺
`codeIntelligence` 仍可读取；只有客观 docs-only/no eligible source 才可 not-applicable；
当前代码变更不得用 legacy-unmigrated 绕过。

## 一次性 1.0.0→1.1.0 bootstrap

共享 resolver 只依据 strict SemVer、exact `allowedChangeSet==actualChangeSet`、仓库/交付绑定、
token 与 append-only consumption history 返回 `normal|bootstrap|blocked`。bootstrap 仅覆盖本次
同 delivery 激活，不伪造 before manifest、ImpactReport 或 IndexDiff；下一 delivery 的
`startingProcessVersion=1.1.0`，C-CODE-05/06 恢复 normal。重复、范围逃逸、证据不全或
hash 不符统一 BLOCK。

同 delivery 的独立 QA 返工可能改变 after 基线。这不是第二次 bootstrap：writer 必须保留旧
activation/marker/evidence history，且只在 token、repository、delivery、starting/activated version
全部相同且 `activatedAt` 严格前进时，才允许当前指针转向新 revision。时间回退、
身份改变或丢失历史均 BLOCK。

四类对象由 `scripts/bootstrap_code_intelligence.py` 构建/验证。为消除 derived ID 与双向
引用的密码学循环，hash DAG 明确携带并验证 `hashExcludedFields`：

- Inventory：`createdAt, inventoryHash, inventoryId, baselineStatement.sha256`；仍把
  `baselineStatement.contentHash` 纳入 inventoryHash，因此绑定语义内容。
- BaselineStatement：`createdAt, contentHash, inventoryHash, statementId`；最终对象仍须满足
  `baseline.inventoryHash == recomputed inventory.inventoryHash`，且 inventory 引用其 contentHash。
- ActivationRecord：`recordHash, activationRecordId`；ConsumedMarker：`markerHash`。

任一排除列表漂移或最终双向引用篡改均为 `BOOTSTRAP_HASH_MISMATCH`。这是对冻结契约中循环
依赖的实现期澄清，需由 Architect/Data Contract Designer 在下一次文档回写中同步。

## LAW-8 边界

禁止的是用图数据库替代 21 节点交付控制真源。允许的是可删除重建、离线、规范化的
代码分析侧车。侧车不复制进 skill ontology 的代码符号节点，只登记 artifact refs、
C-CODE verdict 和显式 `requiredCodeGates`；删除侧车不改变需求或交付历史事实。

<!-- END-OF-DOC -->
