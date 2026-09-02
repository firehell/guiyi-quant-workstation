# Market 首页牛哇式图标与全景盯盘 Implementation Plan

状态：`IMPLEMENTATION_PLAN_APPROVED / SOURCE_IMPLEMENTATION_NOT_STARTED`

日期：2026-09-02

Issue：`#302`

事实基线：`develop@8f39539d07ccea6577d1bcc2244dce0ad715f37e`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 active canonical 下，把 `/market` 从 Runtime-only 页面实现为牛哇式全景盯盘首页：以高保真圆形图标展示 completed D1/W1 通用趋势和周期同向状态，以单一 bulk read model 展示 active universe，以独立 HTDY current Event 读投影显示需要复核的正式观察，并保持所有交易决定由用户完成。

**Architecture:** 后端新增只读 `MarketHomeOverviewService`，只通过 `MarketDataService`、active taxonomy、MainContractMap 和现有 `ResearchMetrics` 生成统一 completed D1/W1 快照；Alert Domain 仅增加 HTDY current Event 全局 read endpoint。Web 只用三个常数级请求读取 overview、Runtime health 和 HTDY Event，在纯 ViewModel 层按 symbol join，并用 inline SVG 实现已冻结的牛哇式图标。不得恢复退役策略、不得在 Web 重算指标、不得新增写路径。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLAlchemy、Vue 3、TypeScript 6、Naive UI、inline SVG、Node test runner、Playwright。

**Spec:** `docs/tasks/2026-09-01-market-home-niuwah-reference-redesign-spec.md`

## Global Constraints

- 开始实现前重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`、`TESTING.md`、本 Spec 和 Issue #302。
- 当前 `/market` 是 Runtime-only；`/market/chart` 是唯一品种复核入口。
- active 通用能力只有 EMA/MACD/ATR/Range Detector；active Alert 产品只有 HTDY。
- SuBing、Daily Watch、Strategy Action、Episode、Performance 及旧策略 Runtime/API/Web/cache 已退役，不得从 Git history 恢复。
- 首页价格必须明确为 completed D1 close，不得冒充实时行情。
- 图标语义只允许“上行 / 周期同向 / 下行 / 中性 / 数据不足”；不得写成买入、持股、卖出、空仓。
- 浏览器首页请求数量必须 O(1)，不得按品种发 HTTP。
- 不修改 HTDY kernel/evaluator/Event writer、Rule、Scope、audience、transport。
- 不修改 quant-core 公式、Alembic、production PostgreSQL/Redis、Canonical、RQData、main/tag/Release/Runtime。
- `STATUS.md` 不因本 Web/read-only 功能提前改成 release 或 Runtime ready。

---

# Slice A — 只读数据合同

## Codex 调度

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从执行时最新 `develop` 创建 `feature/market-home-overview-read-model` task worktree
- 人工 Gate：exact-head 独立 Review + 用户“允许集成 develop”

Slice A 完成并进入 `develop` 后，才允许创建 Slice B。

### Task A1: 冻结 Market Home domain contract

**Files:**
- Create: `services/quant-api/app/market_data/market_home_overview.py`
- Create: `services/quant-api/tests/data_foundation/test_market_home_overview.py`

**Interfaces:**
- Consumes: `MarketDataService.query_page()`, `list_latest_dominants()`, `load_active_products()`, `load_product_taxonomy()`, `calculate_research_metrics()`
- Produces: `MarketHomeOverviewService.snapshot() -> MarketHomeOverviewSnapshot`

- [ ] 写失败测试：统一 `data_as_of`、null 保持 null、缺 D1 → unavailable、W1 warm-up → weekly unavailable、dominants 只读取一次、每品种恰好一次 D1 + 一次 W1。
- [ ] 运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py
```

预期红灯：module/import missing。

- [ ] 实现 immutable contracts：`MarketHomeItem`、`MarketHomeSummary`、`MarketHomeSectorSummary`、`MarketHomeOverviewSnapshot`、`MarketHomeOverviewError`。
- [ ] `MarketHomeOverviewService.__init__` 只校验 products/taxonomy，不执行 I/O；products 必须非空、normalized、唯一，taxonomy keys 必须精确匹配。
- [ ] 再跑定向测试，contract import 通过。
- [ ] Commit：`test(market): freeze market home overview contract`。

### Task A2: 实现统一 completed D1/W1 快照

**Files:** same as A1.

- [ ] 增加失败测试：duplicate products、taxonomy mismatch、dominant missing/duplicate、D1 stale、summary 对账、sector median、59/60/61、不把 weekly 不足判成整行 unavailable。
- [ ] 实现固定顺序：

```text
validate universe/taxonomy
→ target_as_of
→ one dominant-list read
→ per product D1 + W1 read
→ clip to target_as_of
→ require D1 latest == target_as_of
→ calculate generic ResearchMetrics
→ item
→ summary
→ sector summary
→ freshness
```

- [ ] `reason_codes` 只允许透明 generic facts，例如 `price_up/down`、`volume_expansion`、`oi_increase/decrease`、`daily_up/down/neutral`、`weekly_up/down/neutral`、`periods_aligned_up/down`；禁止 buy/sell/entry/exit/opportunity/strategy。
- [ ] D1 缺失或未到统一时点时进入 stale/unavailable，不伪造 item；W1 不足时 item 仍存在且 weekly trend unavailable。
- [ ] 运行 domain + existing market research tests；全绿后 Commit：`feat(market): add read-only home overview snapshot`。

### Task A3: 暴露 bulk Market Home HTTP

**Files:**
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/test_market_home_api.py`

**Produces:** `GET /api/v1/market/research/home-overview`

- [ ] 先写失败 API 测试：bulk response、Decimal wire、typed 409、无 provider/Redis dependency。
- [ ] 新增 `MarketHomeSummaryOut`、`MarketHomeItemOut`、`MarketHomeSectorOut`、`MarketHomeOverviewResponse`，使用 `extra="forbid"`。
- [ ] 新增 `build_market_home_overview_service(session)`：只组合 MarketDataService、active products、taxonomy、coverage latest complete day。
- [ ] Endpoint 只调用 service snapshot + pure projection；不在 API 层重算 metrics。
- [ ] 运行 domain/API 测试、Mypy、Ruff。
- [ ] Commit：`feat(api): expose market home overview`。

### Task A4: 增加 HTDY global current Event read endpoint

**Files:**
- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/app/schemas/alerts.py`
- Modify: `services/quant-api/app/api/alerts.py`
- Modify: `services/quant-api/tests/test_alert_service.py`
- Create: `services/quant-api/tests/test_alert_current_events_api.py`

**Produces:** `GET /api/alerts/current-events?limit=30`

- [ ] 先写失败测试：只返回 current trading day active HTDY Rule Event；排序 `detected_at DESC, bar_end DESC, id DESC`；limit 1..100；legacy/non-registry Rule 排除；current day unavailable 返回 typed unavailable。
- [ ] 实现 `AlertService.list_current_events(trading_day, limit)`，仅 SELECT，无 commit、无 Scope/transport mutation。
- [ ] 新增 `CurrentHtdyEventsResponse`。
- [ ] API 继续复用现有 current trading day resolver；endpoint failure 不吞成空 ready。
- [ ] 跑 Alert service/API 相关回归。
- [ ] Commit：`feat(alerts): add current HTDY event read endpoint`。

### Task A5: OpenSpec、完整验证与独立 Review

**Files:**
- Create: `openspec/specs/market-home-overview/spec.md`

- [ ] OpenSpec 冻结 bulk overview 与 current HTDY Event read-only 合同、统一时点、null、degraded、no N+1、无写边。
- [ ] 后端完整非隔离验证：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] 本地只读 benchmark：warm `<1.5s`、cold `<3s` 为目标；不得为性能引入 cache writer、线程池或并发 Parquet 读取。
- [ ] 新开独立 Sol/high Review，检查 authority、Alert read/write separation、retired surface、测试与性能。
- [ ] 修复所有 Critical/Important，重跑受影响验证。
- [ ] 创建 Draft PR → `develop`，Refs #302；未经用户“允许集成 develop”不得合入。
- [ ] 用户批准后 merge，readback develop，清理 task worktree/branch。

---

# Slice B — 牛哇式 Web 首页

## Codex 调度

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从 Slice A 已合入后的最新 `develop` 创建 `feature/market-home-niuwah-web`
- 人工 Gate：独立 Review + 用户视觉 Review + 用户“允许集成 develop”

### Task B1: 冻结 Web wire types 与 normalizer

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/api/alerts.ts`
- Create: `apps/quant-web/tests/marketHomeTypes.test.ts`

- [ ] 先写失败测试：Decimal string→finite number；null 保持 null；invalid enum/date/count/duplicate symbol fail-closed；Event ready/unavailable 分离。
- [ ] 新增严格 `MarketHomeOverviewResponse` / `CurrentHtdyEventsResponse` wire normalizer。
- [ ] `getMarketHomeOverview()` 与 `getCurrentHtdyEvents()` 各自只请求一次 endpoint。
- [ ] Run：`pnpm -C apps/quant-web exec node --test tests/marketHomeTypes.test.ts`。
- [ ] Commit：`feat(web): add market home wire contracts`。

### Task B2: 冻结图标 token 与几何

**Files:**
- Create: `apps/quant-web/src/utils/marketHomeIcons.ts`
- Create: `apps/quant-web/src/components/market/MarketStateIcon.vue`
- Modify: `apps/quant-web/src/styles/tokens.css`
- Create: `apps/quant-web/tests/marketHomeIcons.test.ts`

- [ ] 测试精确常量：红 `#E63935`、橙 `#FF9601`、绿 `#35C759`、蓝 `#017AFF`、灰 `#98A2B3`；尺寸 40/28/24px。
- [ ] 实现 Spec 固定的 inline SVG path；不使用 Naive UI icon，不引用牛哇资产。
- [ ] 所有状态有中文 aria-label/sr-only 文本。
- [ ] 视觉语义只允许上行/同向/下行/中性/数据不足。
- [ ] Commit：`feat(web): add Niuwah-style market state icons`。

### Task B3: 实现纯 ViewModel join

**Files:**
- Create: `apps/quant-web/src/utils/marketHomeViewModel.ts`
- Create: `apps/quant-web/tests/marketHomeViewModel.test.ts`

- [ ] 测试 exact symbol join、duplicate fail-closed、D1/W1 alignment、stale/unavailable priority、latest Event、empty vs unavailable、59/60/61、null formatting。
- [ ] `buildMarketHomeViewModel` 不计算 EMA/MACD/HTDY，不从 Event 推断 D1/W1，不从 Scope 推断 Event，不从无 Event 推断 normal silence。
- [ ] Alignment：up+up→aligned-up；down+down→aligned-down；neutral+neutral→neutral；任一 unavailable→unavailable；其他→mixed。
- [ ] Commit：`feat(web): build market home view model`。

### Task B4: 实现资源生命周期与 O(1) 刷新

**Files:**
- Create: `apps/quant-web/src/composables/useMarketHome.ts`
- Add tests to relevant Market Home test file.

- [ ] 页面首次只并行三个资源：overview、Runtime health、current HTDY events。
- [ ] Overview 手动刷新/页面重新可见刷新；Runtime + Event 页面可见时 60s timer；页面隐藏停止 timer。
- [ ] 同资源不得并发重复请求；失败保留上次成功快照并分别标 stale。
- [ ] 不新增首页 WebSocket，不做 per-row polling。
- [ ] Unit test 断言请求数与 universe size 无关。
- [ ] Commit：`feat(web): add market home resource lifecycle`。

### Task B5: 页面骨架、ticker、legend、trust strip、summary

**Files:**
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Create: `MarketHomeSectorTicker.vue`
- Create: `MarketHomeLegend.vue`
- Create: `MarketHomeTrustStrip.vue`
- Create: `MarketHomeSummary.vue`
- Create: `MarketHomeSkeleton.vue`

- [ ] 首屏顺序严格为标题/刷新 → sector ticker → 图标 legend → trust strip → summary → 主工作区。
- [ ] Legend 固定文案：`周期状态 · 简单看图标`；副文案按 Spec。
- [ ] Trust strip 必须明确 `非实时行情 · 最近完整交易日收盘快照截至 ...`、participant/active、Runtime degraded、Event unavailable、cached stale。
- [ ] 首次加载分区 skeleton，不全屏 spinner。
- [ ] Summary 点击只改变本地筛选，不触发写入或 Scope 改变。
- [ ] Commit：`feat(web): add market home overview shell`。

### Task B6: 牛哇式主表、筛选与本地偏好

**Files:**
- Create: `MarketHomeToolbar.vue`
- Create: `MarketHomeTable.vue`
- Create: `apps/quant-web/src/utils/marketHomePreferences.ts`
- Create: `apps/quant-web/tests/marketHomePreferences.test.ts`

- [ ] 桌面默认列：`品种 | 板块 | 收盘 | 1D | 5D | 量比 | OI | 日 | 周 | 同向 | HTDY | 数据`。
- [ ] 收盘列绝不能称实时价；null 显示 `—`；异常行保留。
- [ ] 日/周/同向图标固定 28px、稳定对齐；未同向不得使用实心橙勾。
- [ ] 搜索 symbol/中文名；筛选 sector、D1、W1、alignment、HTDY、数据异常；排序 default/1D/量比/OI/Event，全部本地完成。
- [ ] localStorage key：`guiyi.market-home.preferences.v1`；解析失败回默认，不写 DB。
- [ ] Table header sticky，品种列在需要时 sticky，无分页/加载更多。
- [ ] Commit：`feat(web): add compact market home table`。

### Task B7: HTDY Focus Rail 与 deep link

**Files:**
- Create: `MarketHomeFocusRail.vue`
- Create: `apps/quant-web/tests/marketHomeRoute.test.ts`
- Modify chart route intent only if required.

- [ ] Focus Rail 显示 current persisted HTDY Event，buy→“买观察”、sell→“卖观察”、双向→“双向观察”；不得写建仓/清仓/已送达。
- [ ] Event empty：`当前交易日暂无 HTDY 正式观察 Event`；unavailable：`HTDY 当前 Event 暂不可用；不能据此判断本时段无观察。`
- [ ] 品种点击进入 `/market/chart?series_kind=actual_dominant`。
- [ ] Event 点击带 symbol/frequency/overlay=htdy；若增加 `entry=alert-event`，只做 route intent/read-only 定位，不改 HTDY 公式/Event。
- [ ] Commit：`feat(web): add market home HTDY focus rail`。

### Task B8: Responsive 与 mobile dedicated list

**Files:**
- Create: `MarketHomeMobileList.vue`
- Modify page/components styles.

- [ ] 1440+：主表 + 288–320px rail。
- [ ] 1200–1439：可隐藏 5D/ATR 等非核心列，但日/周/同向/HTDY 不隐藏。
- [ ] 768–1199：rail 上移，table 自身横向滚动，首列 sticky。
- [ ] <768：trust → Event → filter → mobile rows；每行保留价格、1D、D/W/alignment/HTDY；图标仍 28px。
- [ ] 禁止整页横向 overflow。
- [ ] Commit：`feat(web): make market home responsive`。

### Task B9: E2E、视觉并列 Review 与无障碍

**Files:**
- Create: `apps/quant-web/e2e/market-home.spec.mjs`
- Create: `apps/quant-web/e2e/market-home.helpers.mjs`

- [ ] E2E 场景：all ready、overview degraded、Runtime degraded、Event empty、Event unavailable、cached stale、60 品种筛选、HTDY deep link、keyboard、mobile order、no page overflow、request count constant。
- [ ] 视口：1920×1080、1440×900、1280×800、390×844。
- [ ] Bounding box 断言 40/28/24px；颜色与 glyph path snapshot 稳定。
- [ ] 在可访问牛哇参考页环境做并列截图；重点审查图标颜色/几何、D/W/同向节奏、ticker、status strip、行密度和移动端。
- [ ] 颜色之外必须有文字/aria；键盘 Enter 可打开详情；focus 可见。
- [ ] Commit：`test(web): verify market home visual parity`。

### Task B10: 同步 active canonical

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `openspec/specs/market-home-overview/spec.md`
- Modify: `TESTING.md`

- [ ] 只在源码/测试完成后更新：Market 首页展示 Runtime health、active completed D1/W1 generic overview 与 HTDY current Event；图标无策略/持仓/下单语义；详情仍是复核入口。
- [ ] `DECISIONS.md` 记录：Market Home = 牛哇式有限图标 + bulk read-only overview + HTDY Event；浏览器 O(1)，无 target/position/order。
- [ ] `docs/ARCHITECTURE.md` 加只读依赖边：`/market → MarketHomeOverviewService → MarketDataService`，`/market → current HTDY read → AlertEvent`。
- [ ] `TESTING.md` 增加 targeted Web unit 与 Playwright 命令。
- [ ] 不修改 `STATUS.md`。
- [ ] Commit：`docs: activate market home overview contract`。

### Task B11: 完整验证、独立 Review、PR、用户视觉 Gate

- [ ] Web 完整验证：

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] 重新跑 Slice A targeted 后端 tests、canonical consistency、OpenSpec strict、secret scan、`git diff --check`。
- [ ] 禁止词/退役引用扫描：Market Home 不得引用 SuBing/Daily Watch/Strategy Action/Episode/Performance；业务标签不得无来源出现“买入/持股/卖出/空仓/建仓/清仓/目标价/止损价”。HTDY formatter 的“买观察/卖观察”允许。
- [ ] 新开 Sol/high exact-head Review，轴：product/canonical、data authority、Alert read/write separation、N+1、icon visual parity、semantic overreach、responsive/a11y、tests、retired surface。
- [ ] Critical/Important 全部修复后重跑受影响验证和截图。
- [ ] 创建 Draft PR 到 `develop`，body 包含 exact base/head、icon token table、API contracts、测试输出、截图矩阵、独立 Review、与牛哇的有意差异、no production mutation。
- [ ] 用户重点审查四主图标、D/W/同向节奏、ticker、status strip、行密度、1440/390 截图；只有用户明确“允许集成 develop”才能合入。
- [ ] merge readback 后清理 task worktree/branch；不得触碰 main/tag/Runtime。

---

## Acceptance Matrix

| ID | 验收 | 证据 |
|---|---|---|
| A-01 | bulk overview 单 HTTP | API test + E2E counter |
| A-02 | unified data_as_of | domain test |
| A-03 | null 不填 0 | domain + Web test |
| A-04 | 59/60/61 | domain + Web test |
| A-05 | D1/W1 generic only | code review |
| A-06 | HTDY current Event only | Alert API test |
| A-07 | no Event ≠ normal silence | copy test |
| A-08 | no retired strategy | rg + canonical test |
| V-01 | red `#E63935` | unit + screenshot |
| V-02 | orange `#FF9601` | unit + screenshot |
| V-03 | green `#35C759` | unit + screenshot |
| V-04 | blue `#017AFF` | unit + screenshot |
| V-05 | 40/28/24px | E2E bounding box |
| V-06 | glyph paths stable | component review + screenshot |
| V-07 | D/W/alignment order | E2E |
| W-01 | no pagination | E2E |
| W-02 | one click chart | E2E |
| W-03 | filters local | unit + E2E |
| W-04 | responsive 4 viewports | screenshot |
| W-05 | keyboard/a11y | E2E |
| C-01 | PROJECT_SOURCE after code | diff |
| C-02 | STATUS unchanged | diff |
| C-03 | OpenSpec strict | command |
| S-01 | no secrets | secret scan |
| S-02 | no production mutation | execution log |

## Completion States

Slice A 只有以下全部成立才可称完成：

```text
CODE_COMPLETE
TEST_COMPLETE
INDEPENDENT_REVIEW_COMPLETE
```

Slice B 只有以下全部成立才可称完成：

```text
CODE_COMPLETE
TEST_COMPLETE
VISUAL_REVIEW_COMPLETE
INDEPENDENT_REVIEW_COMPLETE
CANONICAL_UPDATED
```

任何 Slice 合入 `develop` 都不自动产生：`RELEASED`、`RUNTIME_READY`、production evidence 或真实通知授权。

## Codex 起始 Prompt

```text
请先阅读：
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
TESTING.md
docs/tasks/2026-09-01-market-home-niuwah-reference-redesign-spec.md
docs/tasks/2026-09-02-market-home-niuwah-reference-implementation-plan.md
Issue #302

本任务只执行 Slice A，不得越过到 Slice B。
任务车道：Lane 2。
模型：Sol。
推理强度：高。
模式：Plan-then-execute。

从执行时最新 develop 创建 feature/market-home-overview-read-model 独立 task branch/worktree。
先检查 branch、worktree、dirty state、最近提交和 active canonical；若最新事实与 Plan 冲突，fail-closed 并报告。

严格按 Task A1-A5 TDD。
不得恢复 SuBing、Daily Watch、Strategy Action、Episode、Performance 或旧 Radar Web。
不得修改 HTDY 公式、Event writer、Rule、Scope、transport、Runtime。
不得连接生产 PostgreSQL/Redis，不写 Canonical，不发送通知，不修改 main/tag/Release/Runtime。

完成后运行 Slice A 全部验证，开独立 Sol/high Review，修复 Critical/Important 后创建 Draft PR 到 develop。
未经用户“允许集成 develop”，停止在 Draft PR。
输出 exact base/head、改动、测试、Review、风险和未完成 Gate。
```

## 当前 Gate

用户已批准本 Spec 与 Plan，因此现在允许启动：

```text
Slice A：只读数据合同
```

仍不允许直接跳到 Slice B，不允许自动合入 `develop`，不允许 main/tag/Release/Runtime 或任何真实写入。
