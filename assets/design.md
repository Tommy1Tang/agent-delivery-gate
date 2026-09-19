# 设计系统规范（Design System Specification）

> **适用范围**：面向制造与运营领域的企业级管理控制台（dashboard、数据密集表格、工单/设备/排产作业界面）。
> **文件性质**：本文件是 UI Designer 与 Frontend Engineer 的**唯一视觉真理源**。所有颜色、字体、字号、间距、圆角、阴影、布局骨架与组件视觉规格**必须**从本文件逐字取值，禁止近似替换、禁止自创替代值。
> **违反判定**：出现任何未在本文件登记的色值、字号或间距档位即视为违规（由 `scripts/design_system_lint.py` 检出）。
> **版本**：v1.0.0（`design-system-version`）。新增 token bump minor；修改既有 token 值属 BREAKING CHANGE，bump major。
> **设计原则**：① 信息密度优先——控制台的目标是"一屏看完"；② 数值可比——数字列等宽右对齐；③ 状态三重编码——颜色 + 图标 + 文字；④ 克制装饰——阴影只表达层级；⑤ 一次定义处处引用——组件内禁止硬编码。

---

## 1. 色彩系统（Color System）

颜色是**语义 token**，不是调色板。组件必须引用语义变量（如 `var(--color-text-primary)`），禁止使用色阶变量，禁止任何未登记色值。全部色值以 §1.5 的 CSS 自定义属性为唯一登记处。

### 1.1 语义色映射表（Canvas / Surface / Border / Text / Primary）

| 语义 token | CSS 变量 | 色值 | 用途 |
| --- | --- | --- | --- |
| canvas | `--color-canvas` | `#F4F6F9` | 页面最底层背景 |
| surface | `--color-surface` | `#FFFFFF` | 卡片、表格、弹层内容面 |
| surface-sunken | `--color-surface-sunken` | `#EEF1F6` | 只读区、表头底色、斑马纹 |
| surface-hover | `--color-surface-hover` | `#F7F9FC` | 行/卡悬停态 |
| surface-selected | `--color-surface-selected` | `#EFF4FF` | 行选中态 |
| surface-selected-hover | `--color-surface-selected-hover` | `#E4EDFF` | 选中行悬停态 |
| surface-disabled | `--color-surface-disabled` | `#F2F4F7` | 禁用控件底色 |
| border-subtle | `--color-border-subtle` | `#E9ECF2` | 表格内部分隔线 |
| border | `--color-border` | `#DFE3EB` | 卡片描边、输入框边框 |
| border-strong | `--color-border-strong` | `#C6CCD8` | 分组分隔、输入框悬停 |
| border-accent | `--color-border-accent` | `#B9C6DA` | 强调容器描边 |
| text-primary | `--color-text-primary` | `#1B2430` | 正文、表格单元格 |
| text-secondary | `--color-text-secondary` | `#495364` | 次要说明、列辅助信息 |
| text-muted | `--color-text-muted` | `#666F7E` | 占位符、时间戳、单位（白底 5.07:1） |
| text-disabled | `--color-text-disabled` | `#98A1AF` | 仅用于禁用态，不得承载信息 |
| text-inverse | `--color-text-inverse` | `#FFFFFF` | 深色底上的文本 |
| selection-fg | `--color-selection-fg` | `#123A9E` | 选中行文字 |
| focus-ring | `--color-focus-ring` | `rgba(37, 99, 235, 0.32)` | 焦点环 |

### 1.2 品牌主色与语义色（Primary / Semantic）

每个语义色三档：base 用于文字与图标，strong 用于 hover/active 与描边，subtle 用于浅底标签与横幅。

| 语义 | base | strong | subtle |
| --- | --- | --- | --- |
| Primary（品牌） | `#2563EB` | `#1D4ED8`（hover）/ `#1E40AF`（active） | `#DCE7FF` |
| Success | `#067647` | `#05603A` | `#E7F6EE` |
| Warning | `#B45309` | `#8A3F07` | `#FDF3E2` |
| Danger | `#B42318` | `#8F1D13` | `#FDECEA` |
| Info | `#0E7490` | `#0B5C73` | `#E4F4F8` |

### 1.3 制造状态色（Manufacturing State Colors）

设备 / 工单 / 批次状态**必须**使用下表映射，不允许各页面自行配色。`idle` 刻意使用中性灰而非绿色，避免"待机"被误读为正常运行。

| 状态 | 中文 | 语义映射 | 文字/图标色 | 底色 | 描边 | 图标 |
| --- | --- | --- | --- | --- | --- | --- |
| `running` | 运行中 | success | `#067647` | `#E7F6EE` | `#B7E3CC` | `PlayCircle` |
| `idle` | 待机 / 空闲 | neutral（`--color-state-neutral: #5A6472`） | `#5A6472` | `#EEF1F6` | `#D3DAE4` | `PauseCircle` |
| `fault` | 故障 / 报警 | danger | `#B42318` | `#FDECEA` | `#F3C3BD` | `AlertOctagon` |
| `maintenance` | 维护中 | warning | `#B45309` | `#FDF3E2` | `#F0D6A8` | `Wrench` |
| `offline` | 离线 | muted | `#666F7E` | `#F4F6F9` | `#DDE2EA` | `PlugZap` |

### 1.4 深色导航壳层与图表色序（Dark Shell / Chart Series）

侧边栏与顶栏使用深色壳层，内容区始终为浅色；壳层内禁止复用 §1.1 的浅色 token。
`--color-shell-bg: #16202E` / `--color-shell-elevated: #1F2B3B` / `--color-shell-border: #2C3A4D` / `--color-shell-text: #E6EAF2` / `--color-shell-text-muted: #9AA7BC` / `--color-shell-accent: #4F86F7`。

图表按固定顺序取色，同一指标跨页面颜色恒定，不得用于控件（`#7C3AED` 仅限多序列图表）：
`#2563EB` → `#0E7490` → `#B45309` → `#7C3AED` → `#067647` → `#B42318`（`--chart-1` … `--chart-6`）

### 1.5 色值 Token Block

```css
:root {
  --color-canvas: #F4F6F9;           --color-surface: #FFFFFF;
  --color-surface-sunken: #EEF1F6;   --color-surface-hover: #F7F9FC;
  --color-surface-selected: #EFF4FF; --color-surface-selected-hover: #E4EDFF;
  --color-surface-disabled: #F2F4F7; --color-state-neutral: #5A6472;
  --color-border-subtle: #E9ECF2;    --color-border: #DFE3EB;
  --color-border-strong: #C6CCD8;    --color-border-accent: #B9C6DA;
  --color-text-primary: #1B2430;     --color-text-secondary: #495364;
  --color-text-muted: #666F7E;       --color-text-disabled: #98A1AF;
  --color-text-inverse: #FFFFFF;     --color-selection-fg: #123A9E;
  --color-primary: #2563EB;          --color-primary-hover: #1D4ED8;
  --color-primary-active: #1E40AF;   --color-primary-subtle: #DCE7FF;
  --color-focus-ring: rgba(37, 99, 235, 0.32);
  --color-success: #067647;          --color-success-strong: #05603A;
  --color-success-subtle: #E7F6EE;   --color-warning: #B45309;
  --color-warning-strong: #8A3F07;   --color-warning-subtle: #FDF3E2;
  --color-danger: #B42318;           --color-danger-strong: #8F1D13;
  --color-danger-subtle: #FDECEA;    --color-info: #0E7490;
  --color-info-strong: #0B5C73;      --color-info-subtle: #E4F4F8;
  --color-shell-bg: #16202E;         --color-shell-elevated: #1F2B3B;
  --color-shell-border: #2C3A4D;     --color-shell-text: #E6EAF2;
  --color-shell-text-muted: #9AA7BC; --color-shell-accent: #4F86F7;
  --chart-1: #2563EB; --chart-2: #0E7490; --chart-3: #B45309;
  --chart-4: #7C3AED; --chart-5: #067647; --chart-6: #B42318;
  /* 主题变量覆写：集中于 src/styles/element-overrides.scss，禁止散落组件内 */
  --el-color-primary: var(--color-primary);        --el-color-success: var(--color-success);
  --el-color-primary-light-3: var(--color-primary-hover); --el-color-warning: var(--color-warning);
  --el-color-primary-dark-2: var(--color-primary-active); --el-color-danger: var(--color-danger);
  --el-color-error: var(--color-danger);           --el-color-info: var(--color-info);
  --el-text-color-primary: var(--color-text-primary);   --el-font-family: var(--font-family-base);
  --el-text-color-regular: var(--color-text-secondary); --el-border-color: var(--color-border);
  --el-text-color-secondary: var(--color-text-muted);   --el-border-color-light: var(--color-border-subtle);
  --el-fill-color-blank: var(--color-surface);          --el-bg-color-page: var(--color-canvas);
}
```

---

## 2. 排版（Typography）

字族：`--font-family-base: "Inter", "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif`；`--font-family-mono: "JetBrains Mono", "Cascadia Mono", "SFMono-Regular", Consolas, "Courier New", monospace`。中文正文与界面文案使用 base，禁止引入未列出的 Web Font；数值列、指标数字、业务编号（工单号、设备编号）使用 mono 或 `font-variant-numeric: tabular-nums`；最小字号 `11px`。字重变量 `--font-weight-regular: 400` / `--font-weight-medium: 500` / `--font-weight-semibold: 600`。

字号阶梯：字重仅允许 `400 / 500 / 600`（正文 / 标签与强调 / 标题与数字），禁止 `700` 及以上。

| 层级 | Token（`--font-size-*` / `--line-height-*`） | size | wt | lh | 用途 |
| --- | --- | --- | --- | --- | --- |
| metric-xl | `metric-xl` | `38px` | `600` | `46px` | 仪表盘首屏主指标数字 |
| metric-lg | `metric-lg` | `28px` | `600` | `36px` | 指标卡数字（默认） |
| metric-md | `metric-md` | `22px` | `600` | `30px` | 卡内次级指标、汇总行 |
| page-title | `page-title` | `20px` | `600` | `28px` | 页面标题（每路由唯一） |
| section-title | `section-title` | `16px` | `600` | `24px` | 区块 / 卡片标题 |
| body-lg | `body-lg` | `15px` | `400` | `24px` | 详情页只读字段值 |
| body | `body` | `14px` | `400` | `22px` | **默认正文**、输入框、表格单元格 |
| table-header | `table-header` | `13px` | `600` | `18px` | 表头、工具条次要按钮 |
| label | `label` | `13px` | `500` | `18px` | 表单 label、筛选器标签 |
| caption | `caption` | `12px` | `400` | `16px` | 辅助说明、时间戳、单位 |
| caption-xs | `caption-xs` | `11px` | `500` | `14px` | 状态标签内文字、表格角标 |

命名规则：字号变量为 `--font-size-<层级>`，行高变量为 `--line-height-<层级>`。指标数字（仪表盘大数字）规格固定，禁止页面自行调整：

```css
.metric-value { font-family: var(--font-family-mono); font-size: var(--font-size-metric-lg);
  line-height: var(--line-height-metric-lg); font-weight: var(--font-weight-semibold);
  font-variant-numeric: tabular-nums; color: var(--color-text-primary); }
.metric-unit { margin-left: 4px; font-size: var(--font-size-caption);   /* 单位：小一号、muted */
  font-weight: var(--font-weight-regular); color: var(--color-text-muted); }
.metric-delta-up   { color: var(--color-success); font-size: var(--font-size-caption); }
.metric-delta-down { color: var(--color-danger);  font-size: var(--font-size-caption); }
```

---

## 3. 间距、布局栅格与骨架（Spacing & Layout Grid）

### 3.1 间距阶梯（Spacing Scale）

基准 `--space-unit: 4px`；所有内外边距与间隙**必须**取自下表，禁止 5px / 7px / 10px 等野生值。

| Token | 值 | 用途 | Token | 值 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `--space-0` | `0` | — | `--space-5` | `20px` | 卡片内边距（default） |
| `--space-1` | `4px` | 图标与文字间隙 | `--space-6` | `24px` | 卡片内边距（comfortable） |
| `--space-2` | `8px` | 单元格水平内边距 | `--space-8` | `32px` | 区块分隔、空态留白 |
| `--space-3` | `12px` | 表单行内间隙 | `--space-10` / `-12` / `-16` | `40px` / `48px` / `64px` | 分节 / 空态区 / 全页留白 |
| `--space-4` | `16px` | 卡片内边距（compact）、gutter | | | |

### 3.2 应用骨架（App Shell）

标准骨架：**固定左侧边栏（展开 `232px` / 折叠 `64px`）+ 固定顶栏 `56px` + 流式内容区**。

| 元素 | 值 | 元素 | 值 |
| --- | --- | --- | --- |
| `--layout-sidebar-width` / `-collapsed-width` | `232px` / `64px` | `--layout-card-header-height` | `48px` |
| `--layout-header-height` / `--layout-subheader-height` | `56px` / `44px` | `--layout-pagination-height` | `56px` |
| `--layout-content-padding` / `-max-width` | `24px` / `1680px` | `--layout-drawer-width` / `-lg` | `480px` / `720px` |
| `--layout-toolbar-height` | `48px` | `--layout-master-min-width` / `--table-action-col-width` | `240px` / `120px` |
- 侧边栏与顶栏 `position: fixed`；内容区是唯一滚动容器，`margin-left` 在 `232px` / `64px` 间切换，过渡 `160ms`。
- 内容区**流式**自适应，不使用固定宽度居中容器；仅在 ≥ 1920px 时以 `1680px` 约束并左对齐。
- 顶栏左侧为折叠按钮（`32px × 32px`）+ 面包屑，右侧为用户区与全局操作；侧边栏菜单项高 `40px`，图标与文字间距 `--space-3`，一/二级缩进 `--space-4` / `--space-8`。

### 3.3 栅格与断点（Grid & Breakpoints）

12 列流式栅格，gutter 固定 `--space-4`（16px）。

| 断点 | 范围 | 布局适配 |
| --- | --- | --- |
| `--bp-sm` | 320px – 767px | 侧边栏折叠为 64px；指标卡单列；表格横向滚动 |
| `--bp-md` | 768px – 1023px | 指标卡 2 列；三栏工作台降级为上下两段 |
| `--bp-lg` | 1024px – 1439px | 指标卡 3 列；主从布局 280px + 自适应 |
| `--bp-xl` | 1440px – 1919px | 指标卡 4 列；全宽表格完整展示 |
| `--bp-2xl` | ≥ 1920px | 内容区受 `--layout-content-max-width` 约束 |

### 3.4 密度模式（Density）

由根元素属性统一切换，**不逐组件调整**：

```css
:root[data-density="default"] { --control-height: 32px; --table-row-height: 40px; --card-padding: var(--space-5); }
:root[data-density="compact"] { --control-height: 28px; --table-row-height: 36px; --card-padding: var(--space-4); }
```

控件高度档位：`--control-height-sm: 24px` / `--control-height: 32px` / `--control-height-lg: 40px`。可点击元素最小 `32px × 32px`，触屏场景 ≥ `44px`。

---

## 4. 圆角、边框、阴影与动效（Radius / Border / Elevation / Motion）

### 4.1 圆角（Radius）

| Token | 值 | 用途 | Token | 值 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `--radius-xs` | `2px` | 状态标签、角标、复选框 | `--radius-lg` | `8px` | 抽屉、模态 |
| `--radius-sm` | `4px` | 按钮、输入框、下拉 | `--radius-full` | `999px` | 头像、计数徽章 |
| `--radius-md` | `6px` | 卡片、表格容器、弹层 | — | — | 禁止胶囊形按钮 |

### 4.2 边框（Border）

`border: 1px solid var(--color-border)`（默认）；表格内部分隔仅横向 `border-bottom: 1px solid var(--color-border-subtle)`；强调容器 `1px solid var(--color-border-accent)`；聚焦态 `border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-focus-ring)`。表格禁止竖向网格线与外框加粗，只用横向分隔线。

### 4.3 阴影、层级与动效（Shadow / Z-Index / Motion）

```css
:root {
  --shadow-xs: 0 1px 2px rgba(16, 24, 40, 0.05);
  --shadow-sm: 0 1px 3px rgba(16, 24, 40, 0.08), 0 1px 2px rgba(16, 24, 40, 0.04);
  --shadow-md: 0 4px 12px rgba(16, 24, 40, 0.10), 0 2px 4px rgba(16, 24, 40, 0.05);
  --shadow-lg: 0 12px 28px rgba(16, 24, 40, 0.14), 0 4px 8px rgba(16, 24, 40, 0.06);
  --shadow-focus: 0 0 0 3px var(--color-focus-ring);
  --shadow-inset: inset 0 1px 2px rgba(16, 24, 40, 0.06);
  --duration-instant: 80ms;  --duration-fast: 160ms;
  --duration-base: 240ms;    --duration-slow: 320ms;
  --easing-standard: cubic-bezier(0.2, 0, 0.38, 0.9);
  --easing-exit: cubic-bezier(0.4, 0, 1, 1);
}
@media (prefers-reduced-motion: reduce) { * { transition-duration: 1ms !important; animation-duration: 1ms !important; } }
```

层级用法：L0 无阴影（表格、页面容器，用边框区分）→ L1 `--shadow-xs`（静态卡片、指标卡）→ L2 `--shadow-sm`（卡片 hover、吸顶表头）→ L3 `--shadow-md`（下拉、Popover、Tooltip）→ L4 `--shadow-lg`（模态、抽屉、全局通知）。
z-index 只允许：`--z-sticky: 10` / `--z-header: 100` / `--z-sidebar: 110` / `--z-dropdown: 1000` / `--z-modal: 2000` / `--z-toast: 3000`。
动效时长：hover 变色 `160ms`、侧边栏折叠 `240ms`、抽屉/模态进入 `240ms`、提示弹出 `160ms`、退出 `80ms`。仅允许动画透明度、位移（≤ 8px）、背景色、高度展开；禁止入场缩放、超过 `320ms` 的过渡与循环装饰动效。数据刷新不得整表闪烁，只更新变化单元格并以 `--color-primary-subtle` 底做 `600ms` 高亮渐隐。

---

## 5. 布局拓扑（Layout Topologies）

以下 4 种拓扑覆盖本领域绝大多数界面，页面必须复用其一，不得自创骨架。

**T1 — 指标卡仪表盘（Dashboard Metric Grid）**：`固定侧栏 232px` │ `顶栏 56px`（时间区间 + 刷新）→ `指标卡 ×4` → `图表卡 span 8（高 320px）+ Top-N 排行 span 4`。
指标卡区 `grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--space-4)`；指标卡高 `104px`（单行）或 `128px`（含环比与迷你趋势），内边距 `var(--card-padding)`；卡片排序以主指标（产量 / 达成率 / 设备综合效率 / 告警数）优先，禁止把筛选器塞进指标卡；图表卡高度固定 `320px`（含 `48px` 头部），避免加载后布局跳动。

**T2 — 主从布局（Master–Detail）**：左侧列表/树（`280px` 固定、可拖拽，最小 `240px`、最大 40%）+ 右侧详情。主区与从区之间用 `1px solid var(--color-border)` 分隔，禁止卡片嵌套卡片；从区顶部固定 `56px` 详情头（编码 + 状态标签 + 主操作），下方为可滚动描述列表（两列，`label-width: 112px`）；主区列表项高 `52px`（两行：标题 + 次要信息），选中态底色 `--color-surface-selected` + 左侧 `2px solid var(--color-primary)`；< 1024px 降级为"列表 → 抽屉详情"。

**T3 — 三栏审核工作台（Three-Panel Review Workspace）**：`左导航 232px` + `中列表 360px` + `右详情自适应`，三栏各自独立滚动，无整页滚动条。顶部统一 `56px` 工作台头承载批次/日期范围，选中 ≥ 1 项时出现批量动作条（高 `48px`，底色 `--color-primary-subtle`）；中栏列表支持键盘上下移动（`↑` / `↓`），`Enter` 在右栏打开详情；右栏底部固定操作条（高 `64px`，`border-top: 1px solid var(--color-border)`），主操作右对齐；< 1280px 时中栏折叠为下拉选择器，< 1024px 时改为单栏步进。

**T4 — 全宽数据表 + 吸顶操作列（Full-Width Data Table）**：`工具条 48px` → `表头 40px（sticky top）` → `行区滚动（max-height: calc(100vh - 220px)）` → `分页条 56px`；操作列 `sticky right`。表格容器是唯一 surface，自带 `1px` 边框 + `--radius-md`，行内不再套卡片；操作列 `position: sticky; right: 0`，宽 `120px`（2 个操作）/ `160px`（3 个），背景 `var(--color-surface)`，选中行时同步为 `--color-surface-selected`，左侧加 `1px solid var(--color-border)` 作遮罩；表头 `position: sticky; top: 0`，`z-index: var(--z-sticky)`；行点击进入详情，"操作"列内按钮必须 `@click.stop`，避免误触发导航。

---

## 6. 数据密集组件规格（Data-Dense Components）

### 6.1 表格（Table）

| 项 | 规格 |
| --- | --- |
| 表头高 / 行高 | `--table-header-height: 40px` / `--table-row-height: 40px`（compact 均 `36px`） |
| 单元格内边距 | 水平 `--space-2`（8px）；首列左侧 `--space-4`（16px） |
| 表头样式 | 字重 `600`、字号 `13px`、色 `--color-text-secondary`、底色 `--color-surface-sunken`、`border-bottom: 1px solid var(--color-border)` |
| 斑马纹 | `tbody tr:nth-child(even) { background: var(--color-surface-sunken); }`（与 hover 态可区分；开启斑马纹时不再叠加行横线） |
| hover / selected 行 | `--color-surface-hover` / `--color-surface-selected`（选中后悬停用 `--color-surface-selected-hover`） |
| 排序 | 表头文字右侧 `ArrowUpDown` 图标（`14px`），当前排序列着 `--color-primary` |
| 数值列 | `text-align: right; font-family: var(--font-family-mono); font-variant-numeric: tabular-nums;` |
| 长文本列 | `text-overflow: ellipsis; white-space: nowrap;` + Tooltip 展示全文 |
| 空值 | 渲染为 `--`，色 `--color-text-disabled`，不渲染空白单元格 |
| 行操作 | ≤ 2 个用文字按钮；3 个及以上收进"更多"下拉 |
| 固定列 | 首列（编号/名称）可 sticky left，宽 `160px` |

```css
.data-table { --el-table-border-color: var(--color-border-subtle); font-size: var(--font-size-body); }
.data-table .el-table__header th { height: var(--table-header-height); background: var(--color-surface-sunken);
  color: var(--color-text-secondary); font-size: var(--font-size-table-header); font-weight: var(--font-weight-semibold); }
.data-table .el-table__row { height: var(--table-row-height); }
.data-table .el-table__row:hover > td { background: var(--color-surface-hover) !important; }
.data-table .el-table__row.is-selected > td { background: var(--color-surface-selected) !important; }
.data-table .cell.is-numeric { text-align: right; font-variant-numeric: tabular-nums; }
.data-table .col-action { position: sticky; right: 0; background: inherit; border-left: 1px solid var(--color-border); }
```

### 6.2 单元格级告警渲染（Cell-Level Alert）

超限值必须"颜色 + 标记"双编码，禁止仅变色；`▲` 表示高于上限、`▼` 表示低于下限，`sr-only` 文本必须存在（见 §8）。

```html
<td class="cell is-numeric cell--critical">
  <span class="cell__value">128.4</span><span class="cell__marker" aria-hidden="true">▲</span>
  <span class="sr-only">超出上限 120.0</span>
</td>
```

```css
.cell--critical .cell__value { color: var(--color-danger); font-weight: var(--font-weight-semibold); }
.cell--critical .cell__marker { margin-left: var(--space-1); color: var(--color-danger); font-size: var(--font-size-caption-xs); }
.cell--warning .cell__value { color: var(--color-warning); font-weight: var(--font-weight-medium); }
.cell--muted   .cell__value { color: var(--color-text-muted); }
.cell--critical { background: var(--color-danger-subtle); }  /* 仅用于需要抢注意的整格高亮 */
```

### 6.3 状态标签与徽章（Status Tag / Badge）

```css
.status-tag { display: inline-flex; align-items: center; gap: var(--space-1); height: 22px;
  padding: 0 var(--space-2); border-radius: var(--radius-xs); border: 1px solid transparent;
  font-size: var(--font-size-caption-xs); font-weight: var(--font-weight-medium); white-space: nowrap; }
.status-tag__dot { width: 6px; height: 6px; border-radius: var(--radius-full); background: currentColor; }
.status-tag--running     { color: #067647; background: #E7F6EE; border-color: #B7E3CC; }
.status-tag--idle        { color: #5A6472; background: #EEF1F6; border-color: #D3DAE4; }
.status-tag--fault       { color: #B42318; background: #FDECEA; border-color: #F3C3BD; }
.status-tag--maintenance { color: #B45309; background: #FDF3E2; border-color: #F0D6A8; }
.status-tag--offline     { color: #666F7E; background: #F4F6F9; border-color: #DDE2EA; }
```

标签文案必须是中文业务词（运行中 / 待机 / 故障 / 维护中 / 离线），禁止只显示颜色圆点；内部顺序为图标 → 圆点 → 文字，同列左对齐。计数徽章（未处理告警数）：danger 底 `#B42318`、白字、`--radius-full`、最小宽 `16px`。

### 6.4 分页与空态（Pagination / Empty State）

分页：高 `--layout-pagination-height: 56px`，上边框 `1px solid var(--color-border)`，内边距 `0 var(--space-4)`；左侧为"共 N 条 / 已选 M 条"（`--font-size-caption`、`--color-text-muted`），右侧为页码控件；每页条数默认 `20`，可选 `20 / 50 / 100 / 200`，切换后回到第 1 页；页码按钮 `32px × 32px`、`--radius-sm`，当前页 `background: var(--color-primary); color: var(--color-text-inverse)`；服务端分页必须保留排序与筛选状态（同步到 URL query），刷新后不丢失；加载态用表格区 `v-loading` + 骨架行（5 行），禁止整页遮罩。

```css
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-3); padding: var(--space-12) var(--space-6); text-align: center; }
.empty-state__title { font-size: var(--font-size-body); color: var(--color-text-secondary); }
.empty-state__hint  { font-size: var(--font-size-caption); color: var(--color-text-muted); max-width: 360px; }
```
| 空态场景 | 图标 | 标题 | 动作 |
| --- | --- | --- | --- |
| 无数据（首次） | `Inbox`（`48px`，`--color-text-disabled`） | 暂无数据 | 主按钮：新建（有权限时） |
| 筛选无结果 | `SearchX` | 没有符合条件的记录 | 次按钮：清空筛选条件 |
| 无权限 | `Lock` | 你没有查看该内容的权限 | 无按钮，提示联系管理员 |
| 加载失败 | `AlertTriangle`（danger） | 数据加载失败 | 主按钮：重试；附错误码与追踪号 |

禁止插画风格空态；禁止在空态中隐藏筛选器与搜索框（用户需要它来撤销筛选）。

---

## 7. 表单、控件与反馈（Forms / Controls / Feedback）

### 7.1 表单布局（Forms）
- 默认**顶部对齐** label（`label-position="top"`），label 在控件上方，间距 `--space-1`（4px）。
- 仅"筛选工具条"与"设置类表单"允许左对齐 label，`label-width: 112px`，右对齐并加 `padding-right: var(--space-3)`。
- 桌面端 2 列（`span 12`），窄屏 1 列；备注、长文本占整行。字段分组用分隔线 + `section-title`，组间距 `--space-6`；单列表单最大宽 `480px`。只读字段使用描述列表渲染，不用禁用输入框。

必填与内联校验：

```html
<el-form-item prop="workOrderNo">
  <template #label><span class="form-label form-label--required">工单编号</span></template>
  <el-input v-model="form.workOrderNo" placeholder="请输入工单编号" />
</el-form-item>
```

```css
.form-label--required::after { content: "*"; margin-left: 2px; color: var(--color-danger); }
.form-item__help  { font-size: var(--font-size-caption); color: var(--color-text-muted); margin-top: var(--space-1); }
.form-item__error { font-size: var(--font-size-caption); color: var(--color-danger); margin-top: var(--space-1); }
.el-form-item.is-error .el-input__wrapper { border-color: var(--color-danger); box-shadow: 0 0 0 1px var(--color-danger); }
```

1. **内联呈现**：错误文案紧贴字段下方（`12px`、danger 色），不得只用 Toast 报错。
2. **触发时机**：失焦触发首次校验，之后输入即校验；提交时全量校验并聚焦/滚动到第一个错误字段。
3. **文案可读**：说明"哪里错、怎么改"（如"计划开始时间不能晚于计划结束时间"），禁止只写"输入有误"，禁止暴露异常堆栈。
4. **不丢输入**：校验失败保留已填内容，禁止重置表单。
5. **提交中**：主按钮 `loading` + `disabled` 防重复提交；成功后按 §7.3 反馈并关闭弹层。

### 7.2 基础控件规格（Controls）

| 控件 | 高度 | 内边距 | 圆角 | 字号 |
| --- | --- | --- | --- | --- |
| Button (default) | `32px` | `0 16px` | `--radius-sm` | `--font-size-body` |
| Button (small / large) | `24px` / `40px` | `0 12px` / `0 20px` | `--radius-sm` | caption / body-lg |
| Input / Select | `32px` | `0 12px` | `--radius-sm` | `--font-size-body` |
| 图标按钮 | `32px × 32px` | `0` | `--radius-sm` | — |
| Checkbox / Radio | `16px × 16px` | — | `--radius-xs` | `--font-size-body` |
| 卡片（card） | 自适应 | `var(--card-padding)` | `--radius-md` | — |
| 抽屉 / 模态 | — | `--space-6` | `--radius-lg` | — |

按钮层级（每屏最多一个 primary）：`primary` 底 `--color-primary` 白字（hover `#1D4ED8`、active `#1E40AF`）；`secondary` 白底 + `1px solid var(--color-border-strong)` + `--color-text-primary`，hover 底 `--color-surface-hover`；`text` 无边框、`--color-primary` 文字，hover 底 `--color-primary-subtle`；`danger` 底 `--color-danger` 白字，**仅**用于破坏性主操作；`disabled` 底 `--color-surface-disabled`、字 `--color-text-disabled`、`cursor: not-allowed`、`opacity` 保持 `1`。图标统一 `16px`（行内）/ `18px`（控件内），禁止混用多套图标库。

### 7.3 反馈与通知（Feedback）

| 级别 | 底色 / 描边 | 图标色 | 自动关闭 | 场景 |
| --- | --- | --- | --- | --- |
| success | `--color-success-subtle` / `#B7E3CC` | `#067647` | `2s` | 保存、提交、导出成功 |
| info | `--color-info-subtle` / `#B7DCE6` | `#0E7490` | `2s` | 已复制、已加入队列 |
| warning | `--color-warning-subtle` / `#F0D6A8` | `#B45309` | `4s` | 部分数据未生效、需关注 |
| error | `--color-danger-subtle` / `#F3C3BD` | `#B42318` | 手动关闭 | 保存失败、接口错误、校验拒绝 |

```css
.el-message { border-radius: var(--radius-md); box-shadow: var(--shadow-md); font-size: var(--font-size-body); }
.el-message--error { background: var(--color-danger-subtle); border-color: #F3C3BD; }
.el-message--error .el-message__content { color: var(--color-danger-strong); }
```

- 通知统一右上角、距顶 `calc(var(--layout-header-height) + var(--space-4))`，同屏最多 3 条，超出排队。
- 错误通知必须含可操作信息（错误码 + 追踪号 + "重试"），禁止裸文案"操作失败"。
- **破坏性操作**（删除、作废、强制停线、批量重置）必须二次确认：标题说明后果，主按钮用 danger 变体并写出动作动词（"确认作废"），禁止用"确定/取消"。
- 长任务（> 3s）改用内联进度条或任务抽屉，不用 Toast 承载进度。全局网络异常使用顶部横幅（高 `40px`、`--color-danger-subtle`），可关闭，恢复后自动消失。

---

## 8. 无障碍基线（Accessibility Baseline）

1. **对比度**：正文与界面文字对底色 ≥ `4.5:1`；`18px` 以上或 `14px` 加粗文本 ≥ `3:1`；图标、边框、状态圆点等非文本元素 ≥ `3:1`。本文件已登记值满足该基线：text-primary `15.65:1`、text-secondary `7.76:1`、text-muted `5.07:1`、primary `5.17:1`、success `5.69:1`、warning `5.02:1`、danger `6.57:1`、info `5.36:1`（白底）。`--color-text-disabled: #98A1AF` 仅 `2.61:1`，**只允许**用于禁用态。
2. **焦点可见（Focus-Visible）**：所有可聚焦元素必须提供焦点环，禁止无替代地 `outline: none`。

```css
:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; box-shadow: var(--shadow-focus); }
.el-table__row:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
```

3. **不依赖颜色**：状态必须"颜色 + 图标 + 文字"三重编码（见 §1.3 / §6.3）；图表序列除颜色外需有线型或标记差异，并提供数据表视图。
4. **键盘可达**：Tab 顺序符合视觉顺序；表格行支持 `↑`/`↓` 移动、`Enter` 打开详情、`Space` 选中；模态打开后焦点锁定在模态内，`Esc` 关闭并把焦点还给触发元素。
5. **语义化**：表格使用 `<th scope="col">`；告警单元格配 `sr-only` 文本；图标按钮必须有 `aria-label`；表单错误用 `aria-describedby` 关联字段。
6. **触控目标**：可点击元素最小 `32px × 32px`，触屏 ≥ `44px`。
7. **缩放**：`200%` 缩放且 `320px` 宽下不出现内容裁切或整页横向滚动（宽表格允许容器内滚动）。
8. **动态播报**：异步结果用 `aria-live="polite"`（错误用 `assertive`）播报，避免键盘用户漏掉反馈。

---

## 9. 一致性约束与交付自检（Consistency & Checklist）

**Token 优先级**：本文件 token > UI Designer 默认建议值 > UI 框架默认主题，冲突时以本文件为准。
**哈希一致性**：相同 `design.md` 内容哈希必须产生相同视觉输出；跨交付批次界面须可识别为同一系统。
**品牌色锁定**：`--color-primary: #2563EB` 为不可变值，修改属 BREAKING CHANGE。
**补充而非覆写**：未覆盖领域（如第三方图表库主题、打印样式）可补充，但必须标注"设计系统未定义，以下为补充规范"，且视觉语言与已定义部分协调。
**版本标记**：UI 设计文档末尾必须记录所依据的 `design-system-version`。

交付前逐项确认：

- [ ] 所有色值来自 §1 token 清单，`design_system_lint.py` 报告 `p0Count: 0`，无内联 `style` 硬编码。
- [ ] 字号仅取 §2 阶梯值；指标数字使用 mono + tabular-nums。
- [ ] 间距、内边距、间隙仅为 §3.1 的 4px 倍数档位。
- [ ] 圆角、阴影、z-index 取 §4.1 / §4.3 登记值。
- [ ] 布局骨架复用 §5 的 T1–T4 之一，侧边栏 / 顶栏尺寸与 §3.2 一致。
- [ ] 表格行高、斑马纹、hover/选中、状态标签、分页、空态符合 §6。
- [ ] 表单 label 位置、必填标记、内联校验与反馈级别符合 §7。
- [ ] 无障碍基线 §8 全部满足（对比度、焦点环、非颜色编码、键盘可达）。
- [ ] 主题变量覆写集中在单一文件，组件内无全局主题变量覆写。
