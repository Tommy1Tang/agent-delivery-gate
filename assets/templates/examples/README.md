# Template Examples

> 本目录存放各模板的参考样例。角色仅在**明确需要参考时**按需读取，不自动内联到 prompt。

## 目录结构

- `需求规格书-example.md` — 需求规格书完整样例（含 AC P0 列表、角色、非功能需求、范围排除）
- `单元测试报告-example.md` — 单元测试报告样例（含机器可读字段格式）
- `E2E测试报告-example.md` — E2E 报告样例（含 trace/screenshot/stdout 格式）

## 使用方式

角色 prompt 中声明：
```
如需参考样例格式，read_file: assets/templates/examples/<文件名>
```

不在 handoff 中传递示例内容，节省 token。
