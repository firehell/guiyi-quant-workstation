# Market Web 品牌视觉重设计（方向 B 深蓝壳）

> 状态：已与用户逐段确认（2026-08-15）。实现计划另行编写。
> 前置：`docs/superpowers/plans/2026-08-14-decision-compression-web-ui.md` 的 8 项任务已全部落在 `develop`，本设计在其之上做视觉层重构。

## 目标

把现有浅色 Market Web 升级为**深蓝品牌壳 + 浅色工作区**的混合结构，并按"先结论、后细节"重排首页信息层级；只改视觉与布局，不改功能、不改后端。

## 边界（硬性）

- 只修改 `apps/quant-web/` 前端；不改后端逻辑、API、DB、Runtime、WeCom。
- 保留全部既有功能与用户习惯：左侧导航、Market 看板各区能力（需要处理 / Summary / 散点 / 板块 / 明细）、K 线主视觉、双 Rule 独立开关、今日记录、exact-frequency Marker。
- 中国期货方向色不变：买/涨 = 红（`#DC2626`），卖/跌 = 绿（`#16A34A`）；方向必须文字化；HTDY 观察 = 橙（`#F79009`）；蓝色只做中性操作色。
- 不新增路由、不新增 score/confidence 等业务字段、不加 theme 切换、不做可配置仪表盘。
- 信号、通知和 Web 始终是研究观察，不是交易指令；`auto_order=false` 边界表达保留。

## 视觉系统（令牌）

在现有 `--gy-*` 语义体系上扩展，语义变量名保持稳定，只改取值并新增壳层令牌：

| 分组 | 令牌 | 值 | 用途 |
|---|---|---|---|
| 深蓝壳 | `--gy-shell-bg` | `#0B1D3A` | 侧栏 + 顶栏底色 |
| | `--gy-shell-item-hover` | `#16305C` | 导航 hover/选中底 |
| | `--gy-shell-text` | `#8CA8CF` | 壳上次级文字（对壳底对比 ≈6.8:1） |
| | `--gy-shell-text-active` | `#BFDBFE` | 壳上选中文字 |
| | `--gy-shell-accent` | `#60A5FA` | 壳上选中标记条 |
| 工作区 | `--gy-bg-app` | `#F4F7FB` | 内容区底（微蓝，与壳呼应） |
| | `--gy-bg-panel` | `#FFFFFF` | 卡片 |
| | `--gy-border` | `#DBE3EE` | 卡片边（微蓝调） |
| 文字 | `--gy-text-primary` | `#0F1F38` | 主文字（深蓝黑） |
| | `--gy-text-secondary` | `#33507E` | 次级 |
| | `--gy-text-muted` | `#5B718F` | 弱化 |
| 方向/状态 | up / down / warning | `#DC2626` / `#16A34A` / `#F79009` | 不变 |
| 品牌 accent | `--gy-accent` | `#1D4ED8` | 中性操作色（白字对比 ≈6.3:1，过 WCAG AA） |

字级 / 间距 / 圆角沿用现有 scale（11/12/13/14/16/20/26px；4 基数 spacing；6/10/14px 圆角）。图表令牌微调：grid `#EDF1F7`、axis `#98A2B3`。

`theme.ts`（Naive UI overrides）与 `chartTheme.ts` FALLBACK 同步对齐；`MainLayout.vue` 壳层换深蓝。

## 首页（Market 看板）信息层级

自上而下固定四层：

1. **需要处理（决策区）**：页首宽幅白卡。信号卡方向色条（红=买/绿=卖）+ 14px 结论（品种 · 买入/卖出信号）+ 次级信息（Rule 来源 · 周期 · 确认时间 · 合约）+ "查看 →" 直达 `/market/chart`。2 条以内横排，更多换行网格。只显示 backend `kind=formal_signal` 当前交易日 Event；HTDY 不进入此区。
2. **Summary chip 横条**：上涨 / 下跌 / 放量 / 增仓 / 高波动 5 个 pill chip 一行，不再占大卡片。
3. **散点 + 值得关注**：等高白卡并排（约 6:5）。原"板块概览"卡撤除，板块信息并入明细区 Tab 栏。
4. **全品种明细（板块 Tab）**：Tab 直接复用后端 `sector_summary` 板块集合与顺序，每个 Tab 带板块中位涨跌 chip（红涨绿跌）；默认选中第一个板块 Tab；切换 Tab 只在前端过滤既有 `items`，不新增请求、不持久化。表格列保持现有字段。

## K 线页（Product Workspace）

- 结构不动：工具栏 → 身份行 → 左 K 线（含副图）+ 右侧栏（与 K 线列等高、栏内滚动，已实现）→ 底部研究面板。
- 右侧栏顺序保持：SuBing 正式信号卡 → 两个独立 Rule 开关 → 今日记录 → HTDY 观察 → 研究事实。
- 只换肤：方向 B 组件语言；图表网格/坐标令牌微调；Marker 与 exact-frequency 行为不变。

## 组件语言与微交互

- 卡片：白底 + 0.5px `#DBE3EE` 边 + 10px 圆角 + 一级极浅投影；可点卡 hover 上移 1px + 边变深，150ms。
- Chip/Tag：tinted surface + 同色深文字；方向 chip 必须带文字。
- 按钮：主按钮 `#1D4ED8` 实底白字；次按钮白底灰边；危险操作用 error token，不用方向红。
- 微交互只三处：hover 抬升、Tab 下划线滑动、页面切换淡入；全部 `prefers-reduced-motion` 可关。

## 错误与空态

- 需要处理：`ready` 空 = 一行安静文案（"当前交易日暂无正式信号"）；`unavailable` = 警告 chip + 文案，区域占位不消失。
- Radar / 明细加载用骨架行；接口失败保留上次内容 + 顶部错误条。
- K 线页右栏各区块独立空态，互不影响。

## 测试策略

- 扩展 `tests/themeContract.test.ts`：`--gy-shell-*` 令牌断言 + 壳上文字对比度（≥4.5:1）+ accent 白字对比度。
- 明细 Tab 组件测试：默认选中第一个板块、切换过滤正确、Tab 顺序 = `sector_summary` 顺序。
- 现有 e2e 选择器保持稳定；首页结构变化处更新对应断言。
- 验收断点：1440×900 / 1280×720 / 1024×768。

## 非目标

- 不改 Radar 计算、不改任何 API 形状、不加新数据源。
- 不做暗色主题切换、不做移动端 App、不做多用户。
