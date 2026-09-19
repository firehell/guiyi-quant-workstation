# 牛哇六项视觉与交互完善实施方案

**Goal:** 将现有六项页面能力做成接近牛哇的易读、紧凑、可操作界面，不改变策略或收益语义。

**Architecture:** 延用 NewowProductWorkspace、现有 composable/API、presentation/view-model 和原生 dialog。新增展示组件仅负责渲染已有事实；请求身份、快照一致性、能力 Gate 仍由原入口负责。

**Tech Stack:** Vue 3、TypeScript、现有 CSS tokens、Node tests、Playwright；不增加 UI 或图表依赖。

**Spec:** 本文设计部分及用户本轮“设计六项、视觉对照、terra medium 开始实施”的授权。按 AGENTS.md 连续执行，不重复请求设计批准。

**Execution:** 独立 Codex 项目 worktree，gpt-5.6-terra / medium；使用 executing-plans 按任务落实。基线 develop `94df72d99fb84050a7039ca7a48c3d2d0705d723`，开始时重新核对 HEAD、其他 worktree 与 dirty state。

## 视觉证据和取舍

已实际查看以下 2026-09-18 留存截图；这是有日期的视觉基线，不代表本轮重新访问了最新在线页面。

- [详情页、统计、快捷窗口、参考记录](../../research/newow-v3.2.82/screenshots/20260918/600519-composite.png)
- [AI 分析弹窗、卡片和排序](../../research/newow-v3.2.82/screenshots/20260918/600519-ai-recommendation.png)
- [算法与差异审计](../../research/newow-v3.2.82/CURRENT_AUDIT.md)

牛哇可观察特点：白色内容面、浅灰分组底、细边框和圆角；橙色强调当前策略及重点、蓝色空仓标签、红涨绿跌数值；标题与关键数字优先，说明小且灰；胶囊窗口按钮；弹窗中先结论卡，再指标卡，最后来源/免责声明。

本次将这些特征应用到六项。不得为追求一模一样复制不具备合同的收益曲线、年化、AI 采纳推荐、股票财务字段或新评分。五窗口卡片借鉴六组合弹窗布局，但标题、对象、排序和含义保持“五窗口页面比较器”。杯柄尚无原站私有公式/完整布局证据，只采用相同视觉语言，并始终标明归一 clean-room 候选。

布局建议：卡片圆角 10–12px、细中性色边框、内部 12–16px 留白，保持现有 tokens 优先；局部橙色强调，不给整个页面染色。桌面概览三组信息；窄屏自然堆叠。比较器桌面五卡可换行，手机单列/双列自适应，禁止通过压窄文字保持五列。普通解释保留紧凑弹窗，比较器/杯柄允许宽版（最大约 880px）；窄屏距边至少 16px。颜色只辅助表达，状态必须有文字。

## 全局约束

- 六项只改 Web 展示与交互；不改 quant-core、策略公式、收益计算、数据源、Scope、默认周期或 Runtime。
- 不启用 W1/60m；如果其他任务已合法改变能力，服从当前 capability 响应，不硬编码回退或擅自扩大开放。
- 页面参考始终是零费用/零滑点、非可执行；不冒充因果研究或账户收益。
- 尊重物理合约、segment、formula/profile、as_of、请求 generation 与跨 section 兼容性。
- 不在前端重算收益、评分、建仓状态；使用服务端已有值。交易 decimal 字符串不得转浮点后排序。
- 未识别字段使用中性原名和来源，不编造金融解释。没有事实就展示原因，不造数、不补 0。
- 保留原生 dialog 的 Escape、Tab、焦点恢复、身份切换关闭、滚动锁与背景点击行为。
- 允许隔离开发预览和 fixture 测试；fixture 截图必须注明测试场景，不作为真实行情或策略效果证据。
- 不进行 provider 下载、生产写入、通知、main/tag/release 或 Runtime 切换。

## Review Focus

1. 快速切品种/周期后旧响应到达：不得显示前一身份的杯柄、统计或解释。
2. 月末、闰年、历史快照：快捷窗口以已接受数据截止日为锚，不以电脑日期或未经确认行情为锚。
3. 空结果与失败：无信号、未开放、未请求、加载、数据不足、失败、历史/过期须可区分。
4. 小样本、并列与负值：排序稳定，不将缺失当零，不把展示最高值称为策略推荐。
5. 窄屏和键盘：390px 无页面横向溢出，弹窗可滚动且所有交互可键盘触达。

## 文件职责

- `apps/quant-web/src/components/market/detail/newow/NewowProductWorkspace.vue`：接入六项，继续拥有对话框与选择事件。
- 同目录 `NewowExplanationPanel.vue`：比较器卡片、排序、摘要与来源。
- 同目录 `NewowReferencePanel.vue`：窗口胶囊、服务端统计、覆盖提示。
- 同目录 `NewowDetailDialog.vue`：仅增加宽版展示选项，不重写生命周期。
- 同目录新增 `NewowCupFactsPanel.vue`：杯柄结构与事实卡片。
- `apps/quant-web/src/utils/newowProductViewModel.ts`：已有事实转换；扩展比较器展示字段。
- `apps/quant-web/src/utils/newowDetailPresentation.ts`：中文显示及状态解释；复用既有状态入口，禁止平行 resolver。
- 新增 `apps/quant-web/src/utils/newowReferenceWindows.ts`：纯日期窗口 helper；不接触行情或收益。
- `apps/quant-web/src/types/newowProduct.ts`：仅在确有展示类型需要时补充，不变更 API 合同。

## 任务 1：统一状态呈现和弹窗视觉基础

- [ ] 在 `tests/newowDetailPresentation.test.ts` 增加加载/未请求/未开放/无结果/数据不足/失败/历史状态用例，断言缺失不显示为数值零。先运行观察失败，再实现。
- [ ] 复用现有 presentation 状态，显示中文标题、简短说明、必要的当前合约/快照；原始错误码折叠，失败提供已有 section retry。
- [ ] 修改 Workspace 对话框与 auxiliary 状态区域，避免为同一状态创建第二套请求逻辑；未请求按原 lazy-load 入口触发，未开放不请求。
- [ ] 为 NewowDetailDialog 增加可选宽版样式，保留所有焦点与身份 guard。局部 token 统一卡片/说明/标题样式，不做全站主题重构。
- [ ] 在 `e2e/newow-product.spec.mjs` 补充失败后局部重试、旧响应晚到、Escape/焦点恢复和宽窄弹窗；完成测试后提交这一独立变更。

## 任务 2：策略概览层级

- [ ] 在 `tests/newowDetailPresentation.test.ts` 固定 BUILD/HOLD/REDUCE/CLEAR/FLAT、缺失 latest action、OPEN reference 与无 OPEN 的展示差异。
- [ ] Workspace 概览第一组显示策略名、状态徽标、物理合约和数据截止；第二组显示最近动作、当前页面参考交易及参考浮动；第三组放目标/吸筹与数据说明。
- [ ] 未开放目标/吸筹显示简短原因而非重复空格或虚构进度条。空仓不等于数据加载失败，当前策略状态不等于真实账户持仓。
- [ ] 在 `e2e/newow-product.spec.mjs` 断言概览身份、历史快照标识、空仓与未请求区别；截图桌面 1440×900 和手机 390×844，检查密度/换行，提交。

## 任务 3：指标和信号解释

- [ ] 扩展 `tests/newowDetailPresentation.test.ts`：已知说明、未知 token 原文、安全缺失、日期/价格、无关联 action。
- [ ] Workspace 现有 indicator/hint/action 弹窗改为“当前读数或信号 → 含义 → 边界 → 来源”。仅映射现有已证实解释；未知项显示“暂无经确认的解释”。
- [ ] 默认不展开 IDs、known_at、sequence 和版本；来源折叠中保留可审计信息。时间上区别发生时间/确认时间，不将未来确认当作当时已知。
- [ ] 保留精确 signal/hint 定位和 identity guard，不使用最近日期替代。E2E 验证点信号、来源展开、身份切换关闭与键盘，提交。

## 任务 4：杯柄事实卡片

- [ ] 新增 `tests/newowCupFactsPanel.test.ts`，覆盖完整 witness、空数组、多 witness、相同价格、缺失可选信息及 candidate 标识。
- [ ] NewowCupFactsPanel 接收当前兼容 auxiliary 中的 `NewowCupWitness[]`，不自行请求。每个 witness 展示左杯沿、杯底、右杯沿、柄极值的价格与 pivot/confirmed 时间，再展示 pivot_price、确认时间、score 与 score_breakdown。
- [ ] 可用轻量 SVG 连接已提供的四个拐点，必须标“已确认结构示意，非完整 K 线”；不画未来突破路径。等价价格避免除零，屏幕阅读器有对应文字事实。
- [ ] 多 witness 以确认时间展示列表或显式选择，保留当前物理合约/segment 来源，禁止跨段拼杯；无 witness 不宣称策略看空。
- [ ] 标明“归一杯柄候选 / 非牛哇私有原公式”，原始事实继续折叠。Workspace 用它替代裸 JSON 首屏，非可用周期沿用能力提示。
- [ ] `e2e/newow-product.spec.mjs` 补充完整/空/切身份场景；完成定向测试和桌面手机截图，提交。

## 任务 5：五窗口比较器

- [ ] `tests/newowViewModel.test.ts`、`tests/newowExplanationPanel.test.ts` 固定默认窗口顺序、并列稳定、负收益、缺失、零交易和 decimal 排序；确认测试确实覆盖当前 product VM，不误测旧 detail VM。
- [ ] VM 从既有结果投影窗口、page_display 收益/回撤/胜率、trade_count、已有 score 和 synthetic terminal 标识；不计算新评分。零交易时胜率按既有合同显示不可用，不擅改 API 数值。
- [ ] ExplanationPanel 用五窗口指标卡 + 紧凑对照表，卡内显示统计口径和样本次数。默认维持 candidate_windows 顺序。
- [ ] 增加显示排序：默认、收益从高到低、回撤从小到大（先核对 API 回撤正负定义）、胜率从高到低。缺失始终末尾，同值按原顺序；复用现有精确 decimal 比较，否则实现并测试字符串精确比较，不引入浮点收益计算。
- [ ] 只高亮“当前排序首位”，不写“推荐买入/采纳策略”，不自动应用 N；卡片标题始终明确五窗口，不出现六组合 AI 的冒充入口。
- [ ] E2E 测排序不触发行情请求/策略参数切换，宽版弹窗窄屏可读，terminal 理论清仓与实际 reference exit 不混用；提交。

## 任务 6：参考统计快捷窗口

- [ ] 新增 `tests/newowReferenceWindows.test.ts`，锚点 2026-09-18 时近三月起点 2026-06-18、近一年 2025-09-18、今年 2026-01-01；2024-02-29 减一年 clamp 至 2023-02-28，2026-05-31 减三月 clamp 至 2026-02-28。日期按已接受交易日字符串运算，不经本机时区漂移。
- [ ] helper 输入 `anchor: YYYY-MM-DD, preset: three_months | one_year | ytd`，输出 `{performanceSince, performanceThrough}`；缺失/非法锚点明确失败并禁用快捷项。完整窗口继续复用 completeWindowAction。
- [ ] ReferencePanel 日期输入前添加“近3月/近1年/今年/完整窗口”胶囊；选择只 emit 原 reload 事件，依赖服务端统计。保留自定义日期，选中状态来自已接受响应而非尚未完成的点击。
- [ ] 不静默将请求日期 clamp 到可用数据然后仍称近一年。区分请求区间、服务端接受区间及 coverage；超出覆盖时显示不足/实际覆盖，遵守已有 API 错误合同。
- [ ] `tests/newowReferencePanel.test.ts` 与 E2E 覆盖快速双击窗口、请求失败、历史快照、零笔交易、数据中断；保留分页和定位，不改变清仓配对。提交。

## 合并前验证和交付

- [ ] 先运行每任务相关 Node tests；新增测试必须进入最终命令。再跑现有 Web 全测试和 build：

```sh
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
env -u NO_COLOR -u FORCE_COLOR pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs
git diff --check
```

- [ ] 浏览器测试使用当前 worktree 的隔离服务，不能复用其他 worktree 服务或修改正式服务。fixture-only 测试不冒充真实后端验收。
- [ ] 人工查看渲染截图，逐项比对原站：信息顺序、重点色、数字层级、间距、卡片、按钮、弹窗、窄屏。将代表性截图及一页“原站/本实现/有意差异”记录放 `docs/research/newow-v3.2.82/implementation-ui/20260919/`，避免提交大批重复截图。
- [ ] 自审全部 diff；对日期窗口、精确排序和异步身份风险做独立 Review（可使用独立 reviewer）；修正确认问题后再集成。Review 分类按 AGENTS.md，不以 finding 数量为目标。
- [ ] 更新现有 CURRENT_AUDIT.md 和 REPLICATION_MANUAL.md 的六项状态与截图链接；仅在实现/验证真实完成后标完成，不扩张“原算法完全复刻”声明。
- [ ] 精确暂存、commit/push；核对 develop 新变更及并行 `newow-w1-formal-open` 对 Workspace 等文件的冲突，必要时更新基线并重测受影响测试，满足 Gate 后集成 develop。
- [ ] 交付六项完成表、实际测试结果、视觉截图入口、commit 和未完成 Gate。代码合入不等于正式发布或 Runtime 生效。
