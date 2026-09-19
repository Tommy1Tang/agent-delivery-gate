# Vue 3 + Element Plus Adapter

Use this adapter when the frontend project uses Vue 3, TypeScript, Vite, and Element Plus.

## Architecture Defaults

- Use `<script setup lang="ts">`.
- Keep API calls in `src/api/` or the existing API layer. Never write `axios.get`/`fetch` directly in `.vue` files.
- Keep reusable state in Pinia or existing composables.
- Use Element Plus components before introducing custom controls.
- Preserve scoped styles unless the existing system uses another pattern.
- New/modified data structures must sync to `src/types/`.
- New pages/views must update `router/index.ts` (route path, component import, menu item, auth guard).

## Element Plus 组件使用规范

- **反馈提示**：操作成功用 `ElMessage.success()`，操作失败用 `ElMessage.error()`，重要确认用 `ElMessageBox.confirm()`。
- **表格**：`ElTable` + `ElPagination` 组合使用，支持服务端分页、排序和加载态。
- **表单**：`ElForm` + `ElFormItem` + `rules` 验证，提交前调用 `formRef.validate()`。
- **对话框**：`ElDialog` 配合 `v-model` 控制，关闭时重置表单状态。
- **加载态**：使用 `v-loading` 指令或 `ElSkeleton`。
- **空态**：使用 `ElEmpty` 组件，私有描述文案。
- **状态标签**：`ElTag` 配合语义色 `type` 属性（success/warning/danger/info）。
- **样式覆写**：Element Plus 变量覆写集中在 `src/styles/element-overrides.scss` 或单一文件，禁止散落在组件中。

## Validation Commands

- `npm run typecheck` — TypeScript 类型检查（必须执行）
- `npm run build` — 构建检查（必须执行）
- `npm run test` — 单元测试（如项目配置了测试）

## UI Notes

- Use clear loading (`v-loading`), empty (`ElEmpty`), error (`ElMessage.error`), disabled, and success (`ElMessage.success`) states.
- Keep tables, filters, forms, dialogs, and pagination consistent with Element Plus conventions.
- Avoid decorative landing-page patterns for operational systems.
- Verify responsive behavior for dense management interfaces.
- Use CSS variables for theme tokens; keep variable overrides centralized.

