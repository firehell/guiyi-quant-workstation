# Market Trend Focus V1 实现 Task

更新时间：2026-08-23

> **Spec:** `docs/tasks/2026-08-23-market-trend-focus-v1-spec.md`
>
> 本文件只定义实现与验收，不改写 spec。遇到冲突时以 spec、当前 `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`docs/DEVELOPMENT.md`、`docs/ARCHITECTURE.md` 和 `TESTING.md` 为准；不得从本 task 推导 production mutation、release、Runtime、Alert 或订单授权。

## 1. 任务目标

把现有 Market Web B1「优先检查」从前端 D1 `selectMarketFocus()` 投影升级为后端只读 `market_trend_focus_v1`：

```text
active 60
→ Radar Hot 2/3
→ D1 SMA21
→ 60m SMA21
→ 15m causal Range lifecycle
→ 5m causal + 2x Volume
→ long/short opportunities
→ running/weakening trends
→ 现有 MarketFocusList 展示
```

不建立新平台，不接 Alert，不写数据库/Redis，不新增 Runtime，不修改已有 SuBing/N/JDJ/MFM 公式。

## 2. Codex 调度建议

### Phase A：公式与 read model

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话；完成后新开独立 Review 会话
- Plan：Plan-only，人工批准后再实现
- 工作区：从 `develop` 创建 `feature/market-trend-focus-v1` 独立 task worktree
- 人工 Gate：Plan 批准 + 独立 Review

Worktree 规则：

- base：执行时最新 clean `develop`；
- branch：`feature/market-trend-focus-v1`；
- Phase A 与 Phase B 使用同一 task branch/worktree，但 Phase B 新开 Codex 会话；
- Phase A 公式 Review 未通过前不得做 Web 接入；
- 完成后允许经人工 Review 合入 `develop`；
- 不触及 `main`、tag、release、Runtime worktree；
- 合入 `develop` 并确认后再清理临时 worktree/branch。

### Phase B：API + B1 Web 接入

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Terra；若接入发现跨模块根因不明则升级 Sol
- 推理强度：中
- 会话：新开会话，继续同一 task branch/worktree
- Plan：Plan-then-execute
- 人工 Gate：Phase A 独立 Review 已通过；完成后整体 Review

## 3. 全局硬约束

1. `market_trend_focus_v1` 始终 `auto_order=false`，输出只是人工观察。
2. 不新增 PostgreSQL 表、Alembic migration、Redis lifecycle state、worker、scheduler、launchd label。
3. 不新增 Alert Rule、PushPlus、retry/replay/backfill/outbox/queue。
4. Historical 只经 `MarketDataService`，盘中 observation 只经 `MarketReadService`；不得直接读 Parquet/Redis/RQData/MainContractMap。
5. 60m/15m/5m 必须绑定当前 rank1 exact physical contract；禁止跨 physical contract 继承 Pivot/Range/lifecycle。
6. 所有正式 transition 只消费 completed Bars。
7. 不导入 `app.research` reducer；不修改 N Structure/SuBing/JDJ/MFM 公式或 Candidate contract。
8. 不建立 `TrendFocusService/Repository/Manager/Runtime/Store` 等新抽象；优先一个 `market_trend_focus.py` 模块。
9. 不实现盘中热点 override、自动轮询、历史全量 Overlay、独立 CLI、Candidate Validation/OOS framework。
10. 不做综合 score；排序必须按 spec 的 deterministic 字典序。
11. 不读取、显示、提交或记录凭据。
12. 不修改 `STATUS.md` 提前宣布 Ready；只有实际状态变化才按其职责更新。

## 4. 预期文件范围

### 新建

```text
services/quant-api/app/market_data/market_trend_focus.py
services/quant-api/tests/data_foundation/test_market_trend_focus.py
```

### 修改

```text
services/quant-api/app/schemas/market.py
services/quant-api/app/api/market.py
services/quant-api/app/market_data/composition.py      # 仅现有 builder 复用确有需要时
services/quant-api/tests/data_foundation/test_market_api.py

apps/quant-web/src/types/market.ts
apps/quant-web/src/api/market.ts
apps/quant-web/src/components/market/MarketFocusList.vue
apps/quant-web/src/pages/market/index.vue
apps/quant-web/tests/marketFocus.test.ts
apps/quant-web/e2e/market-research.spec.mjs
```

### 删除/退役

新后端 Focus 接管后删除：

```text
apps/quant-web/src/utils/marketFocus.ts
```

并重写/收敛对应 `apps/quant-web/tests/marketFocus.test.ts`，不得保留旧 EMA21/OI/20d-position 前端选品语义。

### 文档收口（实现通过后）

按 Review 决定最小更新：

```text
PROJECT_SOURCE.md
DECISIONS.md              # 仅有新的长期决策理由需要记录时
/docs/ARCHITECTURE.md
```

不要创建重复的 Trend Focus README/ADR/Guide。任务全部完成并长期 canonical 已收敛后，删除本 spec 与 task 文件，由 Git history 保留。

## 5. Phase A — 核心公式与 reducer

### A1. 先写 exact domain contract

在 `market_trend_focus.py` 内定义最少量 enum/dataclass，名称可以按仓库风格微调，但语义必须一一对应：

```python
TrendDirection = Literal["long", "short"]
DailyTrendState = Literal["long", "short", "neutral"]
HourlyTrendState = Literal["continuation", "pullback", "reversal_block"]
TrendFocusStage = Literal[
    "setup",
    "breakout",
    "retest",
    "ready",
    "running",
    "weakening",
]
SwingKind = Literal["high", "low"]
```

核心内部对象至少表达：

```text
SwingPivot(kind, pivot_time, confirmed_at, price, physical_contract, epoch)
TrendRange(upper, lower, created_at)
TrendFocusState(direction, stage, ...spec required fields...)
TrendFocusItem(...HTTP需要投影的稳定事实...)
TrendFocusSnapshot(status, observed_at, lists, unavailable)
```

不要为每个对象另建文件。

### A2. TDD：SMA21 与 Hot exact 边界

先在 `test_market_trend_focus.py` 写失败测试，至少包括：

```text
- 23 completed Bars 才能得到 latest/t-1/t-2 SMA21；
- Close > SMA21 且三根 SMA 连续上升 = long；
- Close < SMA21 且三根 SMA 连续下降 = short；
- 其余 = neutral；
- abs(change) == 0.02 命中；
- volume_ratio20 == 1.50 命中；
- atr percentile == 0.80 命中；
- 任一 Hot metric=None → 新机会 admission unavailable；
- 3 条中恰好 2 条命中 → current_hot=true。
```

运行：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
services/quant-api/tests/data_foundation/test_market_trend_focus.py
```

确认先 FAIL，再实现最小代码直到 PASS。

### A3. TDD：causal Swing reducer

必须先覆盖：

```text
- 15m HIGH pivot 只在后续反向 Bar 的 bar_end 才 confirmed；
- LOW 镜像；
- pivot_time < confirmed_at；
- inside/equal Bar 不错误确认方向；
- outside Bar：epoch+1、leg reset、running extreme reset；
- outside reset 前 Pivot 不参与 reset 后新 Range；
- input 非严格升序/跨 contract/非目标 timeframe fail-closed；
- 5m 与15m 使用同一私有 reducer 语义。
```

实现时可以参考现有 N Structure 的因果思想，但不得 import `app.research.n_structure`。

### A4. TDD：四 Pivot SETUP

构造 LONG/SHORT 镜像 fixtures：

```text
H1 → L1 → H2 → L2
H2 <= H1
L2 >= L1
```

及镜像起始序列。

必须断言：

```text
range_upper=max(H1,H2)
range_lower=min(L1,L2)
stage=SETUP
```

并覆盖：

```text
- H2>H1 不成立；
- L2<L1 不成立；
- Range 一旦 active 不随区间内后续 Pivot 移动；
- LONG Close<range_lower / SHORT Close>range_upper 失效；
- 失效 boundary 前 Pivot 不得立即复用建立同一 Range。
```

### A5. TDD：BREAKOUT + 3 Bar confirm

LONG exact fixtures：

```text
Close > range_upper → BREAKOUT, confirmation_count=0
后续第1根 Close>upper → 1
第2根 → 2
第3根 → RETEST, confirmation_count=3
```

必须覆盖：

```text
- 首次 breakout Bar 不计数；
- High>upper 但 Close<=upper 不突破；
- confirmation 中 Close==upper 失败；
- 任意 confirmation Bar Close<=upper → lifecycle reset；
- SHORT 全镜像。
```

### A6. TDD：RETEST + second confirmation

LONG fixture 必须 causal 地形成：

```text
breakout confirmed
→ confirmed HIGH
→ confirmed LOW
→ 所有正式 Close 始终 > range_upper
→ retest_held=true
→ rebreak_reference=preceding HIGH.price
→ later Close > rebreak_reference
→ READY
```

必须覆盖：

```text
- retest LOW 仅影线触碰 range 允许；
- completed Close<=range_upper 失败；
- READY trigger 必须 strict-after retest LOW.confirmed_at；
- READY ready_invalidation=retest pivot price；
- READY long Close<ready_invalidation 失败；
- current15m volume == previous15m volume*2 → volume_confirmed=true；
- 小于2x → READY仍成立但 volume_confirmed=false；
- SHORT 镜像。
```

### A7. TDD：5m entry window

LONG：

```text
READY at T
→ 只允许 pivot_time>T 且 confirmed_at>T 的 confirmed 5m HIGH
→ later 5m Close > HIGH.price
→ current volume >= previous volume * 2
→ five_minute_confirmed=true
```

必须覆盖：

```text
- ready_at 之前的5m Pivot不能复用；
- same-boundary trigger不能算；
- volume exactly2x成功；
- SHORT 使用 LOW 镜像；
- 首个 post-ready 15m 趋势方向 Pivot：LONG=HIGH / SHORT=LOW；
- 5m confirmation 先发生 → RUNNING at entry_confirmed_at；
- 15m trend-direction Pivot 先发生 → RUNNING 且 five_minute_confirmed=false；
- 一旦 entry window 关闭，后来的5m rebreak不能回写成当时已确认。
```

### A8. TDD：RUNNING / WEAKENING

必须覆盖：

```text
LONG RUNNING：Close < latest confirmed 15m LOW → WEAKENING
SHORT 镜像；
影线破位但 Close 未破 → 不变；
WEAKENING 后 confirmed LOW → confirmed HIGH → later Close>HIGH → RUNNING；
SHORT 镜像；
恢复 breakout 必须 strict-after HIGH/LOW.confirmed_at。
```

### A9. causal properties

加入 property/fixture tests：

```text
- full replay 与逐 Bar incremental reducer 最终 state 相同；
- 对任意 cutoff 记录的 transition，追加未来 Bars 后过去 transition_at/reason 不变化；
- physical contract A 的 Range/Pivot 不可进入 contract B；
- LONG fixture 做价格轴镜像后得到对应 SHORT 语义。
```

不需要为此引入 Hypothesis 等新依赖；现有 pytest fixtures 足够。

## 6. Phase A — current snapshot 组装

### A10. 复用现有 Market readers，不建 Service 类

在 `market_trend_focus.py` 使用最小 Protocol/函数接收现有 reader；API/composition 注入：

```text
MarketRadarService snapshot
MarketDataService
MarketReadService
latest dominants/current physical contract
now
```

禁止直接实例化数据库/Redis/provider。

建议一个模块级入口，名称可按仓库风格调整：

```python
def build_market_trend_focus_snapshot(
    *,
    radar_snapshot: MarketRadarSnapshot,
    market_data: MarketPageReader,
    market_read: MarketReadFacade,
    dominants: Mapping[str, DominantContractSummary],
    now: datetime,
) -> TrendFocusSnapshot:
    ...
```

不要新增 `MarketTrendFocusService` 类，除非 Plan/Review 证明函数式注入无法保持清晰。

### A11. 输入窗口

只定义少量常量，不开放 runtime 参数：

```text
D1：至少满足23 Bar + Radar既有metric需要
60m：至少23 completed Bars
15m：固定有限 warm-up window
5m：固定有限 warm-up window
```

15m/5m exact query limit 在 Plan 中根据现有 `SeriesPageQuery` 与真实历史样本确定一个固定常量；不得变成用户可调参数，也不得按品种调参。

### A12. Historical + Live merge

每个 current physical contract：

```text
MarketDataService contract history
+
MarketReadService completed current snapshot
→ same contract
→ dedupe bar_end
→ strict ascending
```

盘中 trading/break：Live identity/contract 不可用 → symbol unavailable。

闭市：允许 Historical-only；有 post-close observation 时合并。

### A13. opportunity/running admission

新机会：

```text
current_hot
AND D1 explicit long/short
AND 60m != reversal_block
AND stage in setup/breakout/retest/ready
```

分别 deterministic sort 后最多 10。

趋势跟踪：

```text
stage=running → running_trends
stage=weakening → weakening_trends
```

不要求 current_hot。

Radar 全局 degraded → 整个 snapshot degraded + 四个空列表；单 symbol error → `unavailable`。

### A14. 一次性 Historical read-only 检查

在不新增 CLI/script/report 的前提下，用现有 Python/pytest seam 对当前 active60 做只读抽查。

只检查：

```text
- stage 数量是否存在明显爆炸/全空；
- lifecycle reset 是否死循环；
- READY/RUNNING 是否只集中单一产品；
- full replay / prefix 语义；
- 典型 LONG/SHORT 手工抽样图是否和 reducer transition 对得上。
```

不得输出 PnL/Sharpe/winner/可交易结论，不写正式 evidence artifact。

### Phase A Gate

完成上述后停止，输出：

```text
修改摘要
exact test 结果
真实只读抽查摘要
任何 unavailable/边界问题
是否存在 spec 歧义
```

然后新开独立 Sol Review 会话，重点审：

```text
future leakage
same-boundary
physical-contract continuity
outside-bar ambiguity
full replay/prefix invariance
LONG/SHORT mirror
是否私自新增参数/抽象
```

Review 未明确“允许继续接入”前，不进入 Phase B。

## 7. Phase B — HTTP contract

### B1. Pydantic response

在 `services/quant-api/app/schemas/market.py` 增加最小 Trend Focus DTO。

顶层 exact 字段：

```text
status
observed_at
long_opportunities
short_opportunities
running_trends
weakening_trends
unavailable
```

item 至少覆盖 spec 第 16 节字段。

后端 Decimal 保持 Decimal；不要在 domain 内 float 化。

### B2. API endpoint

只新增：

```text
GET /api/v1/market/research/trend-focus
```

在 `app/api/market.py` 复用现有 builders，组装当前 `radar + market_data + market_read + dominants`，调用 Phase A module-level snapshot 函数，再映射 Pydantic response。

错误语义：

```text
全局 Radar degraded → HTTP 200 + status=degraded + 空列表
单 symbol unavailable → HTTP 200 + unavailable item
请求本身无用户参数，因此不新增可调阈值/频率/query option
```

不要新增 `/trend-focus/{symbol}`。

### B3. API tests

在 `test_market_api.py` 只增加少量 contract tests：

```text
1. ready snapshot 映射字段与 Decimal JSON；
2. degraded snapshot 仍200、四列表为空；
3. unavailable symbol 显式存在；
4. endpoint 无 query 参数，不暴露 threshold/score。
```

不要在 API 层重复 Phase A 全部公式 fixture。

## 8. Phase B — Web B1

### B4. Type/API normalization

修改：

```text
apps/quant-web/src/types/market.ts
apps/quant-web/src/api/market.ts
```

新增 Trend Focus response types 与 `getMarketTrendFocus()`。

只在 HTTP boundary 把 Decimal string normalize 为 number；stage/direction/booleans 原样保留。

### B5. 首页数据流

`apps/quant-web/src/pages/market/index.vue`：

- 保留 Formal Signals、Radar、全市场研究；
- 页面加载时同时取 Trend Focus；
- 用户点击现有“刷新 Radar”时同步刷新 Trend Focus，按钮可以继续是一个统一市场刷新动作；
- V1 不加 `setInterval`/后台 polling；
- Trend Focus 刷新失败时保留上一份成功快照只可明确标注“上一份”，不得伪装当前；首次失败显示 unavailable，不影响全市场研究。

### B6. 改造 MarketFocusList

`MarketFocusList.vue` 改为接收后端 Trend Focus response，不再接收 Radar 后自行 `selectMarketFocus()`。

页面结构：

```text
优先检查

新的机会
  多头 N    默认前3，可展开到后端最多10
  空头 N    默认前3，可展开到后端最多10

趋势跟踪
  运行 N    默认前3，可展开
  转弱 N    默认前3，可展开
```

卡片只显示：

```text
symbol/name
方向
stage 中文名
60m 状态
热点标签
15m volume confirmed
5m confirmed
next_level
invalidation_level
```

不得出现：

```text
综合分
BUY/SELL/推荐交易
Open Interest
MACD/BOLL Trend Focus硬证据
SuBing/N/JDJ/MFM票数
内部pivot id/epoch
```

点击继续进入现有 Product Workspace；不新建详情页。

### B7. 删除旧前端算法

删除：

```text
apps/quant-web/src/utils/marketFocus.ts
```

确保不存在第二套：

```text
ema21_up + oi_increase + near_20d_high/low
```

旧逻辑不得留作 fallback。

### B8. Web tests

重写 `apps/quant-web/tests/marketFocus.test.ts`，只测试 B1 projection：

```text
- 四组 count；
- 默认前三个；
- 查看更多展开；
- stage/60m/volume/5m 文案；
- degraded/首次失败状态；
- 卡片点击走现有 chart route；
- DOM 不出现 score、推荐买卖、OI。
```

更新 `apps/quant-web/e2e/market-research.spec.mjs` 一条关键路径：

```text
mock/fixture Trend Focus API
→ 首页优先检查展示后端结果
→ 点击品种进入现有 Product Workspace
```

不复制全部 reducer fixture 到 browser。

## 9. 文档收口

功能代码与 Review 通过后，再做最小 canonical 更新：

1. `PROJECT_SOURCE.md`：增加 Trend Focus 是 Market Web 只读人工观察 read model；无 Alert/订单/persistence。
2. `docs/ARCHITECTURE.md`：把 B1 `MarketFocusList` 的来源从 D1 client projection 更新为 backend Trend Focus read model；依赖方向仍 Market → Web，不 import offline Research。
3. `DECISIONS.md`：只有“Trend Focus 使用 SMA21 + causal Swing/Range 且不接 Strategy Framework”确实需要长期记录理由时才加一行；否则不重复 spec。
4. 不更新 `STATUS.md` 为 production-ready；是否部署另走 release/Runtime Gate。

任务最终完成并长期 canonical 已承接稳定语义后，删除：

```text
docs/tasks/2026-08-23-market-trend-focus-v1-spec.md
docs/tasks/2026-08-23-market-trend-focus-v1-implementation.md
```

Git history 保留过程，不建 archive。

## 10. 验证命令

### Phase A 定向

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
services/quant-api/tests/data_foundation/test_market_trend_focus.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
services/quant-api/app/market_data/market_trend_focus.py \
services/quant-api/tests/data_foundation/test_market_trend_focus.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
--explicit-package-bases --ignore-missing-imports \
services/quant-api/app/market_data/market_trend_focus.py
```

### Phase B 定向

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
services/quant-api/tests/data_foundation/test_market_trend_focus.py \
services/quant-api/tests/data_foundation/test_market_api.py

pnpm --dir apps/quant-web test -- marketFocus.test.ts
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

### 完整受影响验证

按 `TESTING.md` 当前命令执行：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" \
services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
--explicit-package-bases --ignore-missing-imports \
services/quant-api/app/market_data services/quant-api/app/research \
services/quant-api/app/guiyi_cli services/quant-api/app/alerts \
services/quant-api/app/execution_review services/quant-api/app/runtime_entry.py \
services/quant-api/app/services/runtime_health.py \
services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

若 active OpenSpec/canonical 被修改，再运行：

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
```

任一必要检查失败，不得声明完成。

## 11. 验收标准

必须全部满足：

### 公式

- [ ] D1 Hot exact 2/3 与 None fail-closed 符合 spec。
- [ ] D1/60m SMA21 使用 Simple Moving Average，不误用现有 Radar EMA21。
- [ ] 15m/5m Swing causal，`pivot_time < confirmed_at`。
- [ ] outside bar reset 不猜 bar 内顺序。
- [ ] Range 四 Pivot、Breakout、3-Bar、Retest、Rebreak exact 语义通过。
- [ ] 15m/5m 2x Volume 等号边界通过。
- [ ] 5m strict-after READY，无 same-boundary leakage。
- [ ] RUNNING/WEAKENING 与恢复通过。
- [ ] LONG/SHORT 镜像通过。
- [ ] physical contract 切换不继承 lifecycle。
- [ ] incremental/full replay 与 prefix invariance 通过。

### 工程

- [ ] 不新增 DB/Redis/Runtime/Alert/CLI/persistent evidence。
- [ ] 不 import offline `app.research` 到 Market/Runtime。
- [ ] 不新增 Strategy/Opportunity framework。
- [ ] 后端只有一个 Trend Focus endpoint。
- [ ] 旧前端 `selectMarketFocus()` 语义删除，无 fallback 双轨。
- [ ] Web 保留 B1 结构，默认只展示少量重点项。
- [ ] 不出现 score、交易推荐、OI、MACD/BOLL 投票。

### 测试/Review

- [ ] Phase A 独立 Sol Review 明确通过。
- [ ] 定向 backend tests / Ruff / Mypy 通过。
- [ ] Web unit / B1 Playwright / build 通过。
- [ ] 受影响 backend baseline 与 secret scan / diff check 通过。
- [ ] 一次性 active60 read-only 检查未发现结构性异常或 silent unavailable。

## 12. 完成流转

只有在公式 Review、接入 Review、测试和自审全部通过后，才允许：

```text
task branch
→ develop
```

确认提交已进入 `develop` 后清理 task worktree / 已合并 branch。

本 task **不得**：

```text
发布 main
创建 tag
Runtime promotion/switch
生产 migration
Canonical/DB/Redis mutation
Alert Scope 修改
真实通知
订单能力
```

这些全部是独立人工 Gate。

## 13. 完成后 Codex 输出

必须给出：

```text
1. 修改摘要
2. exact 公式/causal 边界说明
3. 测试结果
4. active60 只读抽查结果
5. 独立 Review 结论与修正项
6. PR/集成 develop 结果
7. task worktree/branch 清理结果
8. 未完成项与后续明确不在本任务内的事项
```

最终结论只能明确写成以下之一：

```text
允许继续实现
要求修正后再集成
允许集成 develop
阻塞
```

不得把 `develop` 集成扩写为 release、Runtime-ready、盈利有效或可交易结论。