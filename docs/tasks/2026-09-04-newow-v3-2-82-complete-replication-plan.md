# Newow v3.2.82 完整复刻 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将牛哇 v3.2.82 当前公开可证的目标/吸筹通道、参数比较、综合决策、诊股解释和技术选股行为，实现为证据可追溯、公式身份隔离、可复算且只读展示的 Newow Quant Core 能力。

**Architecture:** 外部公开页面和匿名只读 JSON 只进入带 SHA-256 的研究证据包与最小金样本；guiyi_quant.newow 只接收不可变 typed facts，并严格拆开 page-parity、causal-research、repainting 与本项目 clean-room 身份。现有 MarketDataService -> ActualDominantResearchSegmentLoader -> NewowResearchBar 仍是期货唯一输入 seam，现有 /api/v1/market/newow/trend-detail 扩展只读事实，Web 不复算公式。

**Tech Stack:** Python 3.13、frozen dataclass、Decimal、pytest、FastAPI/Pydantic、Vue 3、TypeScript 6、Node test runner、Playwright、Markdown/JSON/SHA-256 evidence。

**Spec:** docs/tasks/2026-09-04-newow-v3-2-82-complete-replication-design.md

## Global Constraints

- 基线为 develop@f96f1c9a40371276f66223e5fdedb2812de72ef3，执行工作区为 .worktrees/newow-v3-2-82-complete-replication，分支为 codex/newow-v3-2-82-complete-replication。
- RQData 是唯一外部行情事实源；正式期货输入只能经过 MarketDataService，禁止 glob、自选 active、自判主力或跨频回退。
- 股票数据只作为牛哇页面 parity 证据；禁止进入 Canonical、Catalog、PostgreSQL、Redis 或长期 Runtime。
- 新 Core module 必须是纯函数或不可变结果，不读取网络、文件、数据库、Redis 或系统时钟。
- page-parity 复刻页面事实但不得进入可信收益、Alert、Runtime 或候选晋升；页面比较器必须返回 trustworthy_for_research=false。
- causal-research 只允许 completed Bar 产生意图、下一根 Open 成交、显式成本/滑点/可成交约束；不跨物理合约段、不在样本末 Close 强平。
- 重绘结果必须带 repainting=true 且 formal_signal_eligible=false；正式信号和研究回测必须拒绝它。
- 页面公式、clean-room 修正版和既有 Newow 公式不得共用 calculation identity 或可互换返回类型。
- 所有价格、仓位、成本、收益和费用使用 Decimal；Web 边界显式、安全地序列化。
- 公开采集只允许匿名 GET/只读 POST，不带 Cookie、Token 或账户数据；发现认证字段立即停止该请求并在 coverage 中标记 `UNKNOWN`。
- auto_order=false；禁止新增订单、账户、持仓管理、Alert、Scope、通知、scheduler、migration、Runtime enable 或生产写入。
- 不修改 PROJECT_SOURCE.md 稳定产品面；不执行 main 合入、tag、release 或 Runtime promotion。
- 每个 Slice 必须完成 RED、GREEN、定向回归、Ruff、Mypy、证据 hash readback、Standards Review、Spec Review 和 P1/P2 清零，才能进入下一 Slice。
- 每个 Slice 独立提交；全 Slice 完成并最终 Review 后才允许普通流程合入 develop。合入 develop 不等于 release 或 Runtime Ready。
- 新公开错误码固定为 NEWOW_PRICE_CHANNEL_INVALID_WINDOW、NEWOW_PRICE_CHANNEL_MIXED_SERIES、NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE、NEWOW_PAGE_OPTIMIZER_UNTRUSTED_RESULT、NEWOW_COMPOSITE_STATE_UNSUPPORTED、NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT、NEWOW_SCREENER_EVIDENCE_INSUFFICIENT、NEWOW_FORMULA_IDENTITY_MISMATCH；测试必须逐项覆盖，调用方不得通过捕获 ValueError 静默降级。

---

## File map

### 外部研究证据，不进入 Git

- /Users/zhangzhao/.codex/visualizations/2026/09/03/01a06734-c185-79d2-86b7-86cca05278ad/newow-strategy-detail-research/v3.2.82-gap-closure/sources/：冻结匿名公开响应和静态资源。
- /Users/zhangzhao/.codex/visualizations/2026/09/03/01a06734-c185-79d2-86b7-86cca05278ad/newow-strategy-detail-research/v3.2.82-gap-closure/screenshots/：功能、指标说明、股票样本和筛选结果截图。
- /Users/zhangzhao/.codex/visualizations/2026/09/03/01a06734-c185-79d2-86b7-86cca05278ad/newow-strategy-detail-research/v3.2.82-gap-closure/analysis/：只读采集与逐值复算脚本、diff 和结果 JSON。
- /Users/zhangzhao/.codex/visualizations/2026/09/03/01a06734-c185-79d2-86b7-86cca05278ad/newow-strategy-detail-research/v3.2.82-gap-closure/evidence-manifest.json：相对路径、来源 URL、版本、采集时间、字节数与 SHA-256。
- /Users/zhangzhao/.codex/visualizations/2026/09/03/01a06734-c185-79d2-86b7-86cca05278ad/newow-strategy-detail-research/v3.2.82-gap-closure/report-source.md：source-separated 研究底稿；完成时状态改为 COMPLETE。

### 仓库新增

- docs/tasks/2026-09-04-newow-v3-2-82-coverage.md：稳定覆盖 canonical，只记录来源、状态、公式身份、实现入口和剩余 Gate。
- services/quant-api/tests/newow/golden/newow_v3_2_82_page_facts.json：从证据包裁剪的最小数值金样本。
- services/quant-api/tests/newow/golden/newow_v3_2_82_screener_observations.json：六类匿名筛选请求/响应的最小行为事实。
- packages/quant-core/guiyi_quant/newow/price_channel.py：HHV/LLV、展示选择、页面五窗口和因果五窗口比较。
- packages/quant-core/guiyi_quant/newow/composite_decision.py：综合决策、第一行动原则、clean-room 决策、确定性与波动率。
- packages/quant-core/guiyi_quant/newow/diagnostic_facts.py：EMA20、通道距离、趋势持续期、主力控盘等事实。
- packages/quant-core/guiyi_quant/newow/diagnostic_rules.py：解释 token 与六组合页面评分，不含 UI 文案。
- packages/quant-core/guiyi_quant/newow/screener_observation.py：旧标签、黑盒观察、证据 Gate 和 clean-room candidate。
- services/quant-api/tests/newow/test_price_channel_page_v1.py
- services/quant-api/tests/newow/test_price_channel_causal_v1.py
- services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
- services/quant-api/tests/newow/test_diagnostic_rules.py
- services/quant-api/tests/newow/test_screener_observation.py

### 仓库修改

- packages/quant-core/guiyi_quant/newow/__init__.py：导出新版本常量、types 和纯函数。
- packages/quant-core/guiyi_quant/newow/research_backtest.py：只增加 channel causal identity/intents，不改变既有三策略语义。
- services/quant-api/app/market_data/newow/trend_detail_service.py：加载 D1/W1/60m，各物理段独立 warm-up，组装 typed facts。
- services/quant-api/app/schemas/market_newow.py：新增封闭 Pydantic schema。
- services/quant-api/app/api/market_newow.py：Core-to-API 显式映射与安全 Decimal 序列化。
- services/quant-api/tests/newow/test_trend_detail_service.py、test_market_newow_api.py：三周期、身份、边界和响应合同。
- apps/quant-web/src/types/newow.ts：新增 exact types 和 formula literals。
- apps/quant-web/src/utils/newowTypes.ts：fail-closed normalization。
- apps/quant-web/src/utils/newowViewModel.ts：typed facts 到 observation-only view model。
- apps/quant-web/src/components/market/detail/TrendDetailWorkspace.vue：目标/吸筹、综合决策、诊断和边界区块。
- apps/quant-web/src/components/market/detail/NewowTrendChartStage.vue、newowTrendChartPrimitives.ts：只绘制 API 通道。
- apps/quant-web/tests/newowTypes.test.ts、newowViewModel.test.ts、NewowTrendChartStage.test.ts、MarketDetailPage.test.ts。
- apps/quant-web/e2e/market-detail.spec.mjs：桌面与移动 bounded E2E。

---

## Slice A：覆盖表与股票逐值证据

### Task 1: 冻结 v3.2.82 公开资源与匿名请求合同

**Files:**
- Create externally: v3.2.82-gap-closure/sources/*
- Create externally: v3.2.82-gap-closure/screenshots/*
- Create externally: v3.2.82-gap-closure/analysis/build_evidence_manifest.py
- Create externally: v3.2.82-gap-closure/evidence-manifest.json
- Modify externally: v3.2.82-gap-closure/report-source.md

**Interfaces:**
- Consumes: 公开 index.html、stock_detail.html、strategy-calc.js?v=3.2.82、screener.html 和浏览器匿名只读网络事件。
- Produces: 每个文件的 relative_path/source_url/product_version/captured_at/byte_count/sha256，以及动态请求的 method/url_path/query/body/response_schema/response_sha256。

- [ ] **Step 1: 记录开始前资源身份并拒绝静默版本漂移**

~~~bash
date '+%F %T %Z'
curl -fsS 'http://118.24.52.32/index.html' -o /private/tmp/newow-index-v3282.html
curl -fsS 'http://118.24.52.32/stock_detail.html' -o /private/tmp/newow-detail-v3282.html
curl -fsS 'http://118.24.52.32/strategy-calc.js?v=3.2.82' -o /private/tmp/newow-strategy-calc-v3282.js
curl -fsS 'http://118.24.52.32/screener.html' -o /private/tmp/newow-screener-v3282.html
shasum -a 256 /private/tmp/newow-index-v3282.html /private/tmp/newow-detail-v3282.html /private/tmp/newow-strategy-calc-v3282.js /private/tmp/newow-screener-v3282.html
wc -c /private/tmp/newow-index-v3282.html /private/tmp/newow-detail-v3282.html /private/tmp/newow-strategy-calc-v3282.js /private/tmp/newow-screener-v3282.html
~~~

Expected: 首页仍自报 v3.2.82。任一 hash 与 2026-09-04 13:15 CST 基线不同，保存新旧 diff 和新身份，不覆盖旧来源文件。

- [ ] **Step 2: 用 Playwright 捕获页面与网络只读事实**

在 Chrome 中依次打开 000001.SH、399001.SZ、399006.SZ、601233.SH、600519.SH、600036.SH、002594.SZ、300750.SZ、000651.SZ。每个标的切换 week/day/60min，保存通道值、日/周信号、趋势/震荡三周期状态、综合决策、确定性分解、波动率和 AI 诊断字段。

AI 诊股证据同时冻结旧模板 A-E 的选择条件和当前 v3.2.49 周×日 16 组合矩阵。旧 A-E 依赖月线的部分只记录 OBSERVED_EXACT，不带入归一正式 1w/1d/60m Core；当前 16 组合拆成输入事实、branch key 和输出 token，不复制原站 HTML 文案。

网络监听默认只保留 host 为 `118.24.52.32` 的 GET/只读 POST。Slice A 运行时发现详情页自身会匿名调用 `www.v8848.cn/api/kline`；经 2026-09-04 只读证据边界复核，允许额外冻结且仅冻结该页面自产生的 `GET /api/kline` 响应，固定标的为本 Step 的 9 个代码、周期为 week/day/60min，不允许扩展到该 host 的其他路径或主动业务请求。两类 host 的请求若 header/body 出现 authorization、cookie、token、password 或用户标识，均丢弃响应并标记 `UNKNOWN`；禁止触发关注、盯盘、订阅、分享或写操作。

- [ ] **Step 3: 冻结六类筛选行为**

~~~text
trend_build
mainrise_build
cup_handle
daily_buy
weekly_buy
oscillation_build
~~~

每类保存完整分页请求参数、所有返回行字段名/排序/代码，不只保存前三行；空结果与缺字段原样保留。当前截面在此保存，第二独立截面在 Task 12 保存。

- [ ] **Step 4: 生成并回读 manifest**

Manifest builder 以 Path(__file__).resolve().parents[1] 为唯一 root，排除 evidence-manifest.json、__pycache__ 和 pyc；按 relative_path 排序，以 1 MiB chunk 读取原始 bytes，写入临时文件后 os.replace 原子发布。--verify 重新计算所有 byte_count/hash，任何缺失、额外文件或不匹配都返回非零。Manifest 结构固定为：

~~~json
{
  "schema_version": "newow-evidence-manifest-v1",
  "captured_at": "2026-09-04T13:15:00+08:00",
  "product_version": "v3.2.82",
  "files": [
    {
      "relative_path": "sources/index-v3.2.82.html",
      "source_url": "http://118.24.52.32/index.html",
      "byte_count": 1242189,
      "sha256": "23e4d02d65828bfacf86867891c121a967a58d9ada7618dbc9a7e4265ad23713"
    }
  ]
}
~~~

Run: python3 analysis/build_evidence_manifest.py && python3 analysis/build_evidence_manifest.py --verify

Expected: 全部 OK；manifest 不含绝对路径、Cookie、Token、账号或原站整站副本。

- [ ] **Step 5: 生成与 2026-09-03 金样本的显式 diff**

对旧 evidence-manifest.json 与新 manifest 比较资源 hash、symbols、periods、字段集合、formula branch keys 和 matched/mismatched counts，写入 analysis/v3.2.82-vs-2026-09-03.json。每个变化固定为 added/removed/changed/unchanged；禁止用新文件覆盖旧样本。

### Task 2: 裁剪股票逐值金样本并建立 coverage canonical

**Files:**
- Create: services/quant-api/tests/newow/golden/newow_v3_2_82_page_facts.json
- Create: services/quant-api/tests/newow/golden/newow_v3_2_82_screener_observations.json
- Create: docs/tasks/2026-09-04-newow-v3-2-82-coverage.md
- Modify: tests/engineering/test_canonical_consistency.py

**Interfaces:**
- Consumes: Task 1 manifest 和原始匿名响应。
- Produces: page-facts-v1、screener-observations-v1 和每个公开功能唯一 evidence status。

- [ ] **Step 1: 写 coverage RED**

~~~python
def test_newow_v3282_coverage_has_one_status_and_no_unknown_active_formula() -> None:
    text = Path("docs/tasks/2026-09-04-newow-v3-2-82-coverage.md").read_text()
    assert "OBSERVED_EXACT" in text
    assert "REPRODUCED_EXACT" in text
    assert "UNKNOWN" in text
    assert "REJECTED" in text
    assert "UNKNOWN | active" not in text
~~~

Run: PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py

Expected: FAIL because coverage file is absent.

- [ ] **Step 2: 创建最小 page facts fixture**

~~~text
schema_version = exact "newow-v3.2.82-page-facts-v1"
evidence_manifest_sha256 = shasum -a 256 evidence-manifest.json 的第一列，且匹配 [0-9a-f]{64}
symbols = non-empty array
display_selection_cases = non-empty array
channel_window_rankings = non-empty array
composite_cases = non-empty array
diagnostic_cases = non-empty array
~~~

symbols 恰好包含 3 指数 + 6 股票和 week/day/60min；每个点只保留 OHLCV、页面输出、来源相对路径和源响应 hash。display_selection_cases 覆盖日周同多、日多周空、日空周多、双空、字段缺失、日线目标突破升级和 previous_close 护栏两端。

- [ ] **Step 3: 创建 screener observation fixture**

六个 strategy ID 每个至少一条观察；字段缺失保持缺失，不写 null 冒充页面返回。顶层只允许 schema_version 和 observations，每条 observation 固定 strategy_id/captured_at/request/response_sha256/ordered_rows。

- [ ] **Step 4: 创建完整 coverage canonical**

表格固定列：

~~~text
Feature | Current source/version | Evidence status | Formula identity | Implementation entry | Stock evidence | Futures evidence | Remaining gate
~~~

覆盖首页、详情、S跑/D1-D6、趋势、震荡、主升浪、杯柄、11周期、三副图、目标/吸筹、参数比较器、综合决策、第一行动原则、AI 六组合、AI 诊股、六类技术选股和边界外基本面/CANSLIM。UNKNOWN 只能指向新选股服务端私有逻辑或明确排除的账户/付费功能，Implementation entry 必须为 none。

- [ ] **Step 5: 验证并提交 Slice A**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
git add docs/tasks/2026-09-04-newow-v3-2-82-coverage.md tests/engineering/test_canonical_consistency.py services/quant-api/tests/newow/golden/newow_v3_2_82_page_facts.json services/quant-api/tests/newow/golden/newow_v3_2_82_screener_observations.json
git commit -m "docs(newow): freeze v3.2.82 coverage evidence"
~~~

Expected: tests PASS，secret scan findings=0。

### Task 3: Slice A 双路独立 Review Gate

**Files:**
- Review: Slice A commit diff and external evidence manifest.
- Modify on findings: only Slice A files and external Task 1 evidence.

**Interfaces:**
- Consumes: Slice A commit、manifest verify output、coverage canonical。
- Produces: Standards Review 和 Spec Review，分别列出 P0/P1/P2/P3。

- [ ] **Step 1: Standards Review**

固定检查 source separation、copyright-minimal fixture、secret/path safety、hash reproducibility、Git scope 和无外部 mutation。

- [ ] **Step 2: Spec Review**

逐条核对 Spec §3、§5、§12、§13，特别检查 3 指数 + 6 股票、3 周期、13 矩阵、六类筛选和 UNKNOWN 不指向 active formula。

- [ ] **Step 3: 清零 P1/P2 并重跑 Task 2 Step 5**

Expected: 两路 Review 都明确 P1=0, P2=0，才进入 Slice B。

---

## Slice B：目标/吸筹通道与双身份参数比较

### Task 4: HHV/LLV 通道与展示价格选择

**Files:**
- Create: packages/quant-core/guiyi_quant/newow/price_channel.py
- Create: services/quant-api/tests/newow/test_price_channel_page_v1.py
- Modify: packages/quant-core/guiyi_quant/newow/__init__.py

**Interfaces:**
- Consumes: Sequence[NewowResearchBar]、MultiPeriodPriceFacts、DisplayPeriod、Decimal current_price、Decimal | None previous_close。
- Produces: calculate_price_channel(bars: Sequence[NewowResearchBar], *, window: int) -> tuple[PriceChannelPoint, ...]；select_display_prices(facts: MultiPeriodPriceFacts, *, view_period: DisplayPeriod, current_price: Decimal, previous_close: Decimal | None) -> DisplayPriceSelection。

- [ ] **Step 1: 写通道 RED**

~~~python
def test_price_channel_requires_full_window_and_includes_current_bar() -> None:
    bars = make_research_bars(11)
    points = calculate_price_channel(bars, window=10)
    assert points[8].available is False
    assert points[9].target == max(bar.high for bar in bars[:10])
    assert points[10].absorb == min(bar.low for bar in bars[1:11])
    assert points[10].formula_version == TARGET_ABSORB_CHANNEL_PAGE_V1
~~~

同时覆盖非法 window、乱序、重复 source identity、混 product/frequency/segment、OHLC 非法和零成交量仍可计算价格通道。

Run: PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_price_channel_page_v1.py

Expected: FAIL with missing price_channel import。

- [ ] **Step 2: 定义不可变类型和公式常量**

~~~python
TARGET_ABSORB_CHANNEL_PAGE_V1 = "newow_target_absorb_hhv_llv10_page_v1"
TARGET_ABSORB_DISPLAY_PAGE_V1 = "newow_target_absorb_display_selection_page_v1"

class DisplayPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    BEST_AVAILABLE = "best_available"

class PageSignalState(StrEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    WAIT = "wait"

@dataclass(frozen=True, slots=True)
class PriceChannelPoint:
    bar_end: datetime
    target: Decimal | None
    absorb: Decimal | None
    window: int
    available: bool
    formula_version: str = TARGET_ABSORB_CHANNEL_PAGE_V1
~~~

MultiPeriodPriceFacts 显式包含 daily/weekly target、daily/weekly absorb、daily/weekly signal、cross_weekly、fallback target/high/cost，不接受自由 dict。

~~~python
@dataclass(frozen=True, slots=True)
class MultiPeriodPriceFacts:
    target_daily: Decimal | None
    target_weekly: Decimal | None
    absorb_daily: Decimal | None
    absorb_weekly: Decimal | None
    signal_daily: PageSignalState
    signal_weekly: PageSignalState
    cross_weekly_buy: bool
    fallback_target: Decimal | None = None
    fallback_high: Decimal | None = None
    fallback_absorb: Decimal | None = None

@dataclass(frozen=True, slots=True)
class DisplayPriceSelection:
    target: Decimal | None
    absorb: Decimal | None
    target_period: DisplayPeriod | None
    absorb_period: DisplayPeriod | None
    target_branch_token: str
    absorb_branch_token: str
    formula_version: str = TARGET_ABSORB_DISPLAY_PAGE_V1
~~~

- [ ] **Step 3: 实现完整窗口 HHV/LLV 与统一护栏**

~~~python
def _guard_price(value: Decimal | None, previous_close: Decimal | None) -> Decimal | None:
    if value is None or not value.is_finite() or value <= 0:
        return None
    guarded = value if previous_close is None else min(max(value, previous_close / 2), previous_close * 2)
    return guarded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
~~~

通道不足 window 根返回 available=False 和 None，禁止 partial fallback。

- [ ] **Step 4: 按共享脚本顺序实现 target/absorb 选择**

严格覆盖 day/week/best_available、buy > hold、cross_weekly=buy、日线目标突破升级、双空和 fallback。返回 selected_target_period、selected_absorb_period、原始值、guard 后值、formula identity 和 branch token；无合法值返回 None，不返回 0 或 --。

- [ ] **Step 5: 金样本逐值验证**

在同一测试文件定义具体 helper：load_page_facts 只读仓库内固定 JSON；facts_from_case 逐字段构造 MultiPeriodPriceFacts 并拒绝额外 key；optional_decimal 只接受 None 或十进制字符串；serialize_selection 将 Decimal 用 format(value, "f") 序列化。make_research_bars(count) 生成同一 rb/RB2701/segment、UTC 严格递增、completed/eligible 的确定性 bars，价格为 Decimal("100") + index 且 high/low 各加减 1。

~~~python
@pytest.mark.parametrize("case", load_page_facts()["display_selection_cases"])
def test_display_selection_matches_v3282_fixture(case: dict[str, object]) -> None:
    result = select_display_prices(
        facts_from_case(case),
        view_period=DisplayPeriod(case["view_period"]),
        current_price=Decimal(case["current_price"]),
        previous_close=optional_decimal(case["previous_close"]),
    )
    assert serialize_selection(result) == case["expected"]
~~~

Run: PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_price_channel_page_v1.py

Expected: PASS。

- [ ] **Step 6: 导出并提交**

~~~bash
git add packages/quant-core/guiyi_quant/newow/price_channel.py packages/quant-core/guiyi_quant/newow/__init__.py services/quant-api/tests/newow/test_price_channel_page_v1.py
git commit -m "feat(newow): add target and absorb page channel"
~~~

### Task 5: 页面五窗口比较器

**Files:**
- Modify: packages/quant-core/guiyi_quant/newow/price_channel.py
- Modify: services/quant-api/tests/newow/test_price_channel_page_v1.py

**Interfaces:**
- Consumes: validated single-series bars and fixed windows (10, 20, 24, 30, 52)。
- Produces: rank_page_channel_windows(bars: Sequence[NewowResearchBar], *, windows: tuple[int, ...] = (10, 20, 24, 30, 52)) -> tuple[PageChannelWindowResult, ...]，score 降序，同分保持候选原顺序。

- [ ] **Step 1: 写页面同 Bar RED**

page_optimizer_fixture 从 page-facts fixture 的 channel_window_rankings[0].bars 逐字段构造单一 physical segment 的 NewowResearchBar tuple；不自行生成期望结果。其 expected 数组恰好包含窗口 10/20/24/30/52 的页面输出。

~~~python
def test_page_optimizer_clears_then_rebuilds_on_same_bar_and_force_closes() -> None:
    ten = next(item for item in rank_page_channel_windows(page_optimizer_fixture()) if item.window == 10)
    assert ten.execution_timing == "same_bar_close"
    assert ten.force_closed_at_end is True
    assert ten.trustworthy_for_research is False
    assert ten.formula_version == CHANNEL_OPTIMIZER_PAGE_V1
~~~

同时覆盖收益简单相加、持仓浮盈参与 MDD、负收益、零回撤、零交易和五窗口稳定排序。

- [ ] **Step 2: 定义页面结果**

~~~python
CHANNEL_OPTIMIZER_PAGE_V1 = "newow_hhv_llv_window_optimizer_page_v1"

@dataclass(frozen=True, slots=True)
class PageChannelWindowResult:
    window: int
    cumulative_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    win_rate_pct: Decimal
    score: Decimal
    force_closed_at_end: Literal[True]
    execution_timing: Literal["same_bar_close"]
    trustworthy_for_research: Literal[False]
    formula_version: str = CHANNEL_OPTIMIZER_PAGE_V1
~~~

- [ ] **Step 3: 逐句复刻页面 bt 与 score**

~~~text
holding and high[t] >= HHV_N[t] -> close at close[t]
flat and low[t] <= LLV_N[t] -> open at close[t]
same bar order -> CLEAR then BUILD
equity -> closed cumulative percentage + current trade percentage
end -> force close at last close
score -> (cum - min(0, maxRet)) / max(1, maxRet - minRet + 1)
         + minDD / max(1, mdd if mdd != 0 else 1)
~~~

所有中间值使用 Decimal；Core 不格式化百分号字符串。

- [ ] **Step 4: 冻结五窗口逐字段 parity 并提交**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_price_channel_page_v1.py
git add packages/quant-core/guiyi_quant/newow/price_channel.py services/quant-api/tests/newow/test_price_channel_page_v1.py
git commit -m "feat(newow): reproduce page channel window ranking"
~~~

Expected: 五个窗口的 cum、mdd、trade_count、win_rate、score 和排序完全一致。

### Task 6: 因果五窗口比较器与现有 executor 集成

**Files:**
- Modify: packages/quant-core/guiyi_quant/newow/price_channel.py
- Modify: packages/quant-core/guiyi_quant/newow/research_backtest.py
- Modify: packages/quant-core/guiyi_quant/newow/__init__.py
- Create: services/quant-api/tests/newow/test_price_channel_causal_v1.py

**Interfaces:**
- Consumes: bars、explicit windows、BacktestCostSnapshot、BacktestExecutionConstraint。
- Produces: rank_causal_channel_windows(bars: Sequence[NewowResearchBar], *, windows: tuple[int, ...], cost_snapshots: tuple[BacktestCostSnapshot, ...], execution_constraints: tuple[BacktestExecutionConstraint, ...], require_execution_facts: bool) -> tuple[CausalChannelWindowResult, ...]，每个结果含现有 ResearchBacktestResult。

- [ ] **Step 1: 写 causality RED**

同一测试文件定义 bars() 为 14 根单段确定性 NewowResearchBar，令第 10 根触达 LLV、第 12 根触达 HHV；costs() 为覆盖全段且带 multiplier/tick/source identity 的 BacktestCostSnapshot；limits() 为每根可能成交 Bar 提供绑定 bar_source_identity 的上下限。所有时间为 UTC 严格递增。

~~~python
def test_causal_optimizer_signals_on_completed_bar_and_fills_next_open() -> None:
    result = rank_causal_channel_windows(
        bars(),
        windows=(10,),
        cost_snapshots=costs(),
        execution_constraints=limits(),
        require_execution_facts=True,
    )
    fill = result[0].backtest.fills[0]
    assert fill.signal_bar_end < fill.fill_bar_end
    assert fill.raw_open == bars()[10].open
    assert result[0].formula_version == CHANNEL_OPTIMIZER_CAUSAL_V1
~~~

同时写 strict-before、future-tail mutation、prefix invariance、rollover pending cancel、rollover incomplete、末样本不强平、手续费、tick 滑点、涨跌停拒绝、零量拒绝和 identity mismatch。

- [ ] **Step 2: 增加独立 causal identity 和策略枚举**

~~~python
CHANNEL_OPTIMIZER_CAUSAL_V1 = "newow_hhv_llv_window_optimizer_causal_v1"

class ResearchStrategy(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    MAIN_RISE = "main_rise"
    PRICE_CHANNEL = "price_channel"
~~~

为 price-channel intents 使用独立 signal formula identity；禁止把页面 optimizer identity 加入 CAUSAL_SIGNAL_FORMULAS。

~~~python
@dataclass(frozen=True, slots=True)
class CausalChannelWindowResult:
    window: int
    backtest: ResearchBacktestResult
    force_closed_at_end: Literal[False]
    trustworthy_for_research: Literal[True]
    formula_version: str = CHANNEL_OPTIMIZER_CAUSAL_V1
~~~

- [ ] **Step 3: 只复用现有 next-open executor**

每个 window 生成 completed-Bar BUILD/CLEAR intents，再调用 run_causal_long_only_backtest。禁止复制 fill、cost resolver、constraint resolver、rollover 或 summary 代码。结果显式 force_closed_at_end=False 和 trustworthy_for_research=True。

- [ ] **Step 4: 证明返回类型不可互换**

~~~python
def test_page_and_causal_results_have_disjoint_identities_and_types() -> None:
    page = rank_page_channel_windows(bars())
    causal = rank_causal_channel_windows(
        bars(),
        windows=(10,),
        cost_snapshots=costs(),
        execution_constraints=limits(),
        require_execution_facts=True,
    )
    assert type(page[0]) is PageChannelWindowResult
    assert type(causal[0]) is CausalChannelWindowResult
    assert page[0].formula_version != causal[0].formula_version
~~~

- [ ] **Step 5: 验证并提交**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_price_channel_page_v1.py services/quant-api/tests/newow/test_price_channel_causal_v1.py services/quant-api/tests/newow/test_research_backtest.py services/quant-api/tests/newow/test_research_walk_forward.py
uv run --project services/quant-api python -m ruff check packages/quant-core/guiyi_quant/newow services/quant-api/tests/newow
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports packages/quant-core/guiyi_quant/newow
git diff --check
git add packages/quant-core/guiyi_quant/newow/price_channel.py packages/quant-core/guiyi_quant/newow/research_backtest.py packages/quant-core/guiyi_quant/newow/__init__.py services/quant-api/tests/newow/test_price_channel_causal_v1.py
git commit -m "feat(newow): add causal channel window research"
~~~

Expected: all PASS。

### Task 7: Slice B 双路独立 Review Gate

**Files:**
- Review: Slice B commits and tests only.
- Modify on findings: Slice B files only.

**Interfaces:**
- Consumes: Slice B base/head refs and fresh validation output。
- Produces: formula/causality Review and standards/scope Review。

- [ ] **Step 1: Formula/causality Review**

检查 HHV/LLV current-bar、完整 warm-up、页面同 Bar 偏差隔离、next-open、成本、limit、换月和末样本。

- [ ] **Step 2: Standards/scope Review**

检查无第二套 executor、无文件/网络读取、价格均为 Decimal、identity 精确、无 Alert/Runtime/API 扩张。

- [ ] **Step 3: 修复所有 P1/P2 并重复 Task 6 Step 5**

Expected: 两路 Review 均 P1=0, P2=0，才进入 Slice C。

---

## Slice C：综合决策、确定性、仓位和波动率

### Task 8: 页面综合决策、13 格矩阵和 clean-room 修正版

**Files:**
- Create: packages/quant-core/guiyi_quant/newow/composite_decision.py
- Create: services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
- Modify: packages/quant-core/guiyi_quant/newow/__init__.py

**Interfaces:**
- Consumes: MultiPeriodTrendState、MultiPeriodOscillationState、daily bars。
- Produces: calculate_composite_decision(*, trend: MultiPeriodTrendState, oscillation: MultiPeriodOscillationState, daily_bars: Sequence[NewowResearchBar]) -> CompositeDecision；calculate_cleanroom_composite_decision(*, trend: MultiPeriodTrendState, oscillation: MultiPeriodOscillationState, daily_bars: Sequence[NewowResearchBar]) -> CleanroomCompositeDecision。

- [ ] **Step 1: 写 13 格与不可达 warning RED**

daily_bars() 固定返回 21 根同一 D1 physical segment 的合法 NewowResearchBar。cartesian_states() 枚举 weekly/daily 为 BUY/HOLD/SELL/WAIT/IDLE、60m 为 HOLD/WAIT/IDLE，oscillation 三周期为 HOLDING/CLEARED/IDLE 的完整笛卡尔积；测试逐个调用，NEWOW_COMPOSITE_STATE_UNSUPPORTED 计入 rejected，其余结果计入 reached，最后同时断言 rejected 非空和 warning keys 不可达。

~~~python
def test_page_matrix_has_thirteen_keys_but_warning_keys_are_unreachable() -> None:
    assert len(PAGE_DECISION_MATRIX) == 13
    assert PAGE_UNREACHABLE_DECISION_KEYS == (
        "warning-bullish",
        "warning-bearish",
        "warning-neutral",
    )
    reached: set[str] = set()
    rejected = 0
    for trend, oscillation in cartesian_states():
        try:
            result = calculate_composite_decision(
                trend=trend,
                oscillation=oscillation,
                daily_bars=daily_bars(),
            )
        except ValueError as exc:
            assert str(exc) == "NEWOW_COMPOSITE_STATE_UNSUPPORTED"
            rejected += 1
            continue
        reached.add(result.decision_key)
    assert rejected > 0
    assert set(PAGE_UNREACHABLE_DECISION_KEYS).isdisjoint(reached)
~~~

逐项断言 13 个 action token 和仓位区间；neutral-neutral 为 PositionRange(None, None)，禁止 --。

- [ ] **Step 2: 定义封闭类型**

~~~python
COMPOSITE_DECISION_PAGE_V3282 = "newow_composite_decision_page_v3_2_82"
COMPOSITE_DECISION_CLEANROOM_V1 = "newow_composite_decision_cleanroom_v1"

class TrendSignal(StrEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    WAIT = "wait"
    IDLE = "idle"

class OscillationStatus(StrEnum):
    HOLDING = "holding"
    CLEARED = "cleared"
    IDLE = "idle"

@dataclass(frozen=True, slots=True)
class PositionRange:
    minimum: Decimal | None
    maximum: Decimal | None

@dataclass(frozen=True, slots=True)
class MultiPeriodTrendState:
    weekly: TrendSignal
    daily: TrendSignal
    sixty_minute: TrendSignal

@dataclass(frozen=True, slots=True)
class MultiPeriodOscillationState:
    weekly: OscillationStatus
    daily: OscillationStatus
    sixty_minute: OscillationStatus

@dataclass(frozen=True, slots=True)
class CertaintyBreakdown:
    trend: int
    oscillation: int
    alignment: int
    direction: int
    total: int
~~~

CompositeDecision 包含 formula identity、trend/oscillation bias、direction token、decision key、action token、position range、certainty breakdown、volatility、risk tokens 和 unreachable_decision_keys。

- [ ] **Step 3: 实现 page-exact 控制流**

顺序必须先 weekly bearish -> bearish，再检查其他分支；保留后置且不可达的 weekly bearish and daily bullish -> warning。未列入 13 格的组合抛 NEWOW_COMPOSITE_STATE_UNSUPPORTED，禁止 fallback neutral-neutral。

- [ ] **Step 4: 实现独立 clean-room 修正版**

clean-room 先判断 weekly bearish and daily bullish -> warning，再判断一般 bearish；返回 page_difference_reason=weekly_bearish_daily_bullish_reclassified。其结果类型不继承 CompositeDecision，调用者显式选择 identity。

- [ ] **Step 5: 实现确定性评分**

~~~text
trend = weekly bull * 12 + daily bull * 12 + 60m holding * 6
oscillation = weekly holding * 10 + daily holding * 12 + 60m holding * 8
alignment = 20 for same bullish/bearish; 10 if either neutral; otherwise 0
direction = 3, 5, 10, or 20 according to the page branch
total = trend + oscillation + alignment + direction
alignment 0 -> cap 60
alignment 10 -> cap 85
~~~

- [ ] **Step 6: 运行矩阵与 6 股票金样本**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
~~~

Expected: 13 个定义、10 个 page 可达 key、3 个不可达 warning key、clean-room warning 可达和至少 6 个真实股票 composite fixture 全部 PASS。

### Task 9: ATR20/Close 与第一行动原则

**Files:**
- Modify: packages/quant-core/guiyi_quant/newow/composite_decision.py
- Modify: services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py

**Interfaces:**
- Consumes: 至少 6 根合法 completed D1 bars；WeeklyDailyTrendState；MultiPeriodOscillationState。
- Produces: CompositeVolatility | None 和 FirstActionPrinciple。

- [ ] **Step 1: 写 gap TR、边界和规则差异 RED**

~~~python
def test_first_action_preserves_rebound_warning_when_page_composite_is_bearish() -> None:
    trend = MultiPeriodTrendState(
        TrendSignal.WAIT,
        TrendSignal.HOLD,
        TrendSignal.IDLE,
    )
    oscillation = MultiPeriodOscillationState(
        OscillationStatus.IDLE,
        OscillationStatus.IDLE,
        OscillationStatus.IDLE,
    )
    composite = calculate_composite_decision(
        trend=trend,
        oscillation=oscillation,
        daily_bars=daily_bars(),
    )
    principle = calculate_first_action_principle(
        trend=WeeklyDailyTrendState(trend.weekly, trend.daily),
        oscillation=oscillation,
    )
    assert composite.trend_bias == TrendBias.BEARISH
    assert principle.level == PrincipleLevel.WARN
    assert principle.rule_token == "weekly_bearish_daily_bullish_rebound_risk"
~~~

波动率覆盖 gap up/down、最少 5 个 TR、20 根上限、1.95/2.0/3.95/4.0 边界和非法 series。

- [ ] **Step 2: 实现页面一致波动率**

~~~text
n = min(20, len(bars) - 1)
TR[t] = max(high-low, abs(high-prev_close), abs(low-prev_close))
require at least 5 valid TR
value_pct = round_half_up(mean(TR) / latest_close * 100, 1)
LOW < 2.0; MID < 4.0; HIGH >= 4.0
~~~

不足时返回 None；需要完整 volatility 的 composite 调用抛 NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT。

- [ ] **Step 3: 实现独立第一行动原则**

~~~python
FIRST_ACTION_PRINCIPLE_PAGE_V3263 = "newow_first_action_principle_page_v3_2_63"

@dataclass(frozen=True, slots=True)
class WeeklyDailyTrendState:
    weekly: TrendSignal
    daily: TrendSignal

@dataclass(frozen=True, slots=True)
class FirstActionPrinciple:
    level: PrincipleLevel
    rule_token: str
    fact_tokens: tuple[str, ...]
    formula_version: str = FIRST_ACTION_PRINCIPLE_PAGE_V3263
~~~

优先级：双空硬空仓、周空日多反弹风险、周多日空等待日线企稳、单侧空且另一侧未知硬空仓、60m 震荡 cleared、日线震荡 cleared、周线震荡 cleared、正常观察。只返回 level/rule_token/fact_tokens，不复制原站建议文案。

- [ ] **Step 4: 验证并提交**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
uv run --project services/quant-api python -m ruff check packages/quant-core/guiyi_quant/newow/composite_decision.py services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports packages/quant-core/guiyi_quant/newow/composite_decision.py
git diff --check
git add packages/quant-core/guiyi_quant/newow/composite_decision.py packages/quant-core/guiyi_quant/newow/__init__.py services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
git commit -m "feat(newow): add composite decision identities"
~~~

Expected: all PASS。

### Task 10: Slice C 双路独立 Review Gate

**Files:**
- Review: Slice C commit.
- Modify on findings: Slice C files only.

**Interfaces:**
- Consumes: exact matrix source excerpt、fixture hash、Slice C diff/tests。
- Produces: page-parity/defect Review and clean-room/type-safety Review。

- [ ] **Step 1: Page-parity/defect Review**

证明不可达 warning-* 是精确保留的页面缺陷，不是遗漏测试；验证 FirstActionPrinciple 未被 composite 覆盖。

- [ ] **Step 2: Clean-room/type-safety Review**

检查 corrected identity、unsupported state fail-closed、Decimal position、ATR rounding 和 token 无交易指令。

- [ ] **Step 3: 清零 P1/P2 并重复 Task 9 Step 4**

Expected: 两路 Review 均 P1=0, P2=0，才进入 Slice D。

---

## Slice D：诊股模板与服务端行为反推

### Task 11: Diagnostic facts、解释 token 与六组合页面评分

**Files:**
- Create: packages/quant-core/guiyi_quant/newow/diagnostic_facts.py
- Create: packages/quant-core/guiyi_quant/newow/diagnostic_rules.py
- Create: services/quant-api/tests/newow/test_diagnostic_rules.py
- Modify: packages/quant-core/guiyi_quant/newow/__init__.py

**Interfaces:**
- Consumes: channel、trend、oscillation、main-force、main-rise、cup-handle typed facts 和 page backtest summaries。
- Produces: build_diagnostic_facts(inputs: DiagnosticInputs) -> DiagnosticFacts；diagnostic_tokens(facts: DiagnosticFacts) -> tuple[DiagnosticToken, ...]；rank_page_ai_combinations(combinations: tuple[PageAiCombination, ...]) -> PageAiRanking。

- [ ] **Step 1: 写 facts/token 分离 RED**

diagnostic_inputs() 构造同一 physical segment 的 25 根 D1 bars、Task 4 DisplayPriceSelection、最后一根 trend frame、最新 non-repainting MainForceControlResult、main-rise holding state 和 READY cup overlay；另一个 fixture 将照妖镜 repainting result 放入 formal input，并断言 constructor 拒绝。

~~~python
def test_diagnostic_copy_cannot_change_quant_facts() -> None:
    facts = build_diagnostic_facts(diagnostic_inputs())
    tokens = diagnostic_tokens(facts)
    assert facts.formula_versions
    assert all(token.code.startswith("NEWOW_DIAG_") for token in tokens)
    assert not hasattr(facts, "advice")
    assert not hasattr(tokens[0], "position")
~~~

同时覆盖缺事实不臆测、EMA20 strict-before、距目标/吸筹百分比 Decimal、趋势持续 bars 在换月归零、repainting 照妖镜被拒绝。

- [ ] **Step 2: 定义 DiagnosticFacts**

~~~python
DIAGNOSTIC_FACTS_CLEANROOM_V1 = "newow_diagnostic_facts_cleanroom_v1"
DIAGNOSTIC_RULES_CLEANROOM_V1 = "newow_diagnostic_rules_cleanroom_v1"
AI_SIX_COMBO_PAGE_V3250 = "newow_ai_six_combo_page_v3_2_50"

@dataclass(frozen=True, slots=True)
class DiagnosticFacts:
    as_of: datetime
    target_price: Decimal | None
    absorb_price: Decimal | None
    target_distance_pct: Decimal | None
    absorb_distance_pct: Decimal | None
    ema20: Decimal | None
    close_vs_ema20: Literal["above", "below", "equal", "unavailable"]
    trend_state: TrendBandState
    trend_duration_bars: int
    main_force_status: MainForceStatus | None
    main_rise_active: bool | None
    cup_state: CupHandleState | None
    repainting_inputs_excluded: tuple[str, ...]
    formula_versions: tuple[str, ...]
~~~

全部事实来自已有 primitive 或合法 bars，不接受页面文案。

- [ ] **Step 3: 冻结解释 token 规则**

模板族固定为趋势阶段、通道位置、操盘线、主力控盘、主升浪、杯柄、风险冲突、数据不足。token 只携带 code/severity/fact keys/formula identities；Web copy adapter 提供归一文案。

旧模板 A-E 只在 evidence/coverage 中保留：A=全蓝下跌，B=月周蓝且日黄刚上穿，C=月周蓝且日黄持有，D=月蓝周黄反转确认，E=月黄强势共振。由于归一正式周期不含月线，不创建 page-exact A-E Core identity。当前 v3.2.49 周×日 16 组合按已冻结 branch key 转换为 diagnostic tokens；这一区分必须有回归测试。

- [ ] **Step 4: 实现六组合页面评分**

~~~text
periods = week, day, 60min
strategies = oscillation, trend
discard trade_count < 3
min-max normalize cumulative return, log1p(max(0, Calmar)), accuracy
raw = 0.40 * return + 0.35 * calmar + 0.25 * accuracy
penalty = 1.0 if trades >= 10 else 0.85
score = browser-number result rounded to 4 decimals
tie break = trade_count descending, then input order
~~~

PageAiRanking 带 trustworthy_for_research=false。可信选择只接受 WalkForwardValidationResult 并返回独立 OosCandidateAssessment，两类不共享 recommendation 类型。

增加回归：把 PageAiRanking 传入 OOS selector 必须抛 NEWOW_PAGE_OPTIMIZER_UNTRUSTED_RESULT；任何 combination formula identity 不匹配必须抛 NEWOW_FORMULA_IDENTITY_MISMATCH。

- [ ] **Step 5: 验证并提交**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_diagnostic_rules.py services/quant-api/tests/newow/test_subplots_page_v1.py services/quant-api/tests/newow/test_research_walk_forward.py
uv run --project services/quant-api python -m ruff check packages/quant-core/guiyi_quant/newow/diagnostic_facts.py packages/quant-core/guiyi_quant/newow/diagnostic_rules.py services/quant-api/tests/newow/test_diagnostic_rules.py
git diff --check
git add packages/quant-core/guiyi_quant/newow/diagnostic_facts.py packages/quant-core/guiyi_quant/newow/diagnostic_rules.py packages/quant-core/guiyi_quant/newow/__init__.py services/quant-api/tests/newow/test_diagnostic_rules.py
git commit -m "feat(newow): add diagnostic facts and page scoring"
~~~

Expected: all PASS。

### Task 12: 技术选股观察、证据 Gate 与 clean-room candidates

**Files:**
- Create: packages/quant-core/guiyi_quant/newow/screener_observation.py
- Create: services/quant-api/tests/newow/test_screener_observation.py
- Modify: packages/quant-core/guiyi_quant/newow/__init__.py
- Modify: docs/tasks/2026-09-04-newow-v3-2-82-coverage.md
- Modify: services/quant-api/tests/newow/golden/newow_v3_2_82_screener_observations.json
- Modify externally: v3.2.82-gap-closure/sources/screener-*.json and evidence-manifest.json

**Interfaces:**
- Consumes: two dated/frozen screener snapshots、legacy homepage facts、trend/main-rise/cup facts。
- Produces: ScreenerProbeObservation、compare_screener_observations、legacy filters 和三类 clean-room candidate。

- [ ] **Step 1: 写证据不足 RED**

one_snapshot() 从 golden observations 读取 trend_build 的首个冻结截面。two_snapshots_with_multiple_matching_rules() 构造两个 captured_at 不同、hash 不同但同时可被“黄色持有”和“最近 BUILD”解释的 observations，用来证明非唯一规则必须拒绝；helper 不修改观察内容或生成伪响应。

~~~python
def test_page_exact_factory_rejects_one_snapshot_or_non_unique_rule() -> None:
    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule((one_snapshot(),))
    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule(two_snapshots_with_multiple_matching_rules())
~~~

同时覆盖非法 hash、naive captured_at、重复 symbol、排序不稳定、缺字段保真、版本 hash 变化和 Jaccard 集合比较。

- [ ] **Step 2: 补第二独立截面**

优先下一交易日；若公开接口支持历史 as_of，则保存不同历史截面。六个 strategy ID 都保存全量分页。无法得到真正独立截面时保持 UNKNOWN，禁止复制响应换时间戳。

- [ ] **Step 3: 定义观察类型**

~~~python
@dataclass(frozen=True, slots=True)
class ScreenerProbeObservation:
    strategy_id: ScreenerStrategyId
    captured_at: datetime
    request_identity: str
    response_sha256: str
    ordered_symbols: tuple[str, ...]
    rows: tuple[ScreenerRowFacts, ...]

@dataclass(frozen=True, slots=True)
class ScreenerObservationComparison:
    intersection: tuple[str, ...]
    only_left: tuple[str, ...]
    only_right: tuple[str, ...]
    jaccard: Decimal
    stable_field_names: tuple[str, ...]
~~~

- [ ] **Step 4: 冻结 legacy filter，不冒充新服务端策略**

observed_legacy_filter_v3_2_82 实现已证的九个首页规则，返回 surface=legacy_homepage。禁止用它构造 /api/screener page-exact identity。

- [ ] **Step 5: 实现三个自有 candidate**

~~~text
newow_trend_build_candidate_v1:
latest trend band is YELLOW and latest BUILD is newer than latest CLEAR in the same segment

newow_mainrise_build_candidate_v1:
latest main-rise band state is holding and latest main-rise BUILD is newer than latest CLEAR in the same segment

newow_cup_handle_candidate_v1:
latest same-segment cup overlay is READY or BREAKOUT and hard_failures is empty
~~~

每个结果带 page_parity=false、formula lineage 和 evidence note；只处理传入 facts，不扫描数据库或全市场。

- [ ] **Step 6: 反算三类服务端集合**

逐 symbol 关联同日详情 primitive，计算 candidate 命中、false positive/negative 和可区分反例。只有两个独立截面都只剩唯一规则才升级 BEHAVIOR_INFERRED；否则保持 UNKNOWN / private server logic，自有 candidate 不宣称 page-exact。

- [ ] **Step 7: 验证并提交**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_screener_observation.py
uv run --project services/quant-api python -m ruff check packages/quant-core/guiyi_quant/newow/screener_observation.py services/quant-api/tests/newow/test_screener_observation.py
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports packages/quant-core/guiyi_quant/newow/screener_observation.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
git add packages/quant-core/guiyi_quant/newow/screener_observation.py packages/quant-core/guiyi_quant/newow/__init__.py services/quant-api/tests/newow/test_screener_observation.py docs/tasks/2026-09-04-newow-v3-2-82-coverage.md services/quant-api/tests/newow/golden/newow_v3_2_82_screener_observations.json
git commit -m "feat(newow): model screener evidence and candidates"
~~~

Expected: tests PASS，manifest verify PASS，secret scan findings=0。

### Task 13: Slice D 双路独立 Review Gate

**Files:**
- Review: Slice D commits、coverage、external screener evidence。
- Modify on findings: Slice D files only.

**Interfaces:**
- Consumes: diagnostic lineage、two screener snapshots、candidate diffs。
- Produces: diagnostic/OOS isolation Review 和 evidence/inference Review。

- [ ] **Step 1: Diagnostic/OOS isolation Review**

检查 token 不含公式、页面六组合不进入可信研究、OOS 类型独立、repainting 输入被拒绝。

- [ ] **Step 2: Evidence/inference Review**

检查没有用名称相似替代公式、没有伪造第二截面、server UNKNOWN 未宣称 page-exact、自有 candidate identity 清楚。

- [ ] **Step 3: 清零 P1/P2 并重复 Task 11/12 验证**

Expected: 两路 Review 均 P1=0, P2=0，才进入 Slice E。

---

## Slice E：只读 API 与详情页集成

### Task 14: 扩展 Newow trend-detail typed facts

**Files:**
- Modify: services/quant-api/app/market_data/newow/trend_detail_service.py
- Modify: services/quant-api/app/schemas/market_newow.py
- Modify: services/quant-api/app/api/market_newow.py
- Modify: services/quant-api/tests/newow/test_trend_detail_service.py
- Modify: services/quant-api/tests/newow/test_market_newow_api.py

**Interfaces:**
- Consumes: NewowTrendDetailQuery 和 ActualDominantResearchSegmentLoader.load(symbol=query.product, frequencies=(BarFrequency.D1, BarFrequency.W1, BarFrequency.H1), since=query.since, through=query.through)。
- Produces: 现有响应加 price_channel、page_window_comparison、composite_page、composite_cleanroom、first_action_principle、diagnostic_facts、diagnostic_tokens、semantic_labels。

- [ ] **Step 1: 写 service/API RED**

service_with_sc2302_weekly_owner_subset() 使用现有 fake MarketDataService：全局 authoritative segments 为 SC2302(2023-01-03..04) + SC2303(2023-01-05..later)，D1/H1 owner subsets 含两段，W1 只含结束于 2023-01-06 的 SC2303 Bar。query() 固定 product=sc、since=2023-01-03、through=2023-01-31。

~~~python
def test_detail_service_loads_each_frequency_and_preserves_owner_subsets() -> None:
    result = service_with_sc2302_weekly_owner_subset().query(query())
    assert result.price_channel.daily.formula_version == TARGET_ABSORB_CHANNEL_PAGE_V1
    assert result.composite_page.formula_version == COMPOSITE_DECISION_PAGE_V3282
    assert result.composite_cleanroom.formula_version == COMPOSITE_DECISION_CLEANROOM_V1
    assert result.semantic_labels.page_parity is True
    assert result.semantic_labels.observation_only is True
~~~

加入 SC2302 反例：D1/60m owner 子集可含 SC2302，W1 可从 SC2303 开始；全局 MainContractMap authoritative segments 仍校验。覆盖缺 W1/60m、混 identity、prefix limit、unsupported state 和 API 409。

- [ ] **Step 2: 三周期读取，不复制 resolver**

一次 loader 请求 D1/W1/H1。每周期使用该周期 owner subset 和全局 authoritative segments；每个物理段创建新 kernel state，段间不延续 channel、trend、oscillation 或 EMA warm-up。可见 D1 仍受 1500/2000 bounded gate。

- [ ] **Step 3: 只由 Core 组装 facts**

Service 将 Canonical bars 适配为 NewowResearchBar 后调用 Core；禁止在 service/API 重算 HHV/LLV、ATR、评分、仓位或诊断。page comparison 显式 trustworthy_for_research=false；causal/OOS 不在在线请求执行。

- [ ] **Step 4: 定义封闭 Pydantic schema**

所有 model 继承 _Out(extra="forbid")。价格/仓位使用 Decimal，枚举和 formula identity 使用精确 Literal。API 不输出内部路径、exception、Cookie、source file 或未过滤 mapping。

- [ ] **Step 5: 扩展 calculation identity**

Identity 包含 Canonical authority、rank1 authority、product、actual_dominant、1d+1w+60m、既有 trend/D123/cup identities、四个 Slice B identities、三个 Slice C identities 和 diagnostic identity。旧 response 不得被新前端误认完整。

- [ ] **Step 6: 验证并提交**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_trend_detail_service.py services/quant-api/tests/newow/test_market_newow_api.py services/quant-api/tests/newow/test_futures_validation.py
uv run --project services/quant-api python -m ruff check services/quant-api/app/market_data/newow services/quant-api/app/schemas/market_newow.py services/quant-api/app/api/market_newow.py services/quant-api/tests/newow
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/market_data/newow services/quant-api/app/schemas/market_newow.py services/quant-api/app/api/market_newow.py packages/quant-core/guiyi_quant/newow
git diff --check
git add services/quant-api/app/market_data/newow/trend_detail_service.py services/quant-api/app/schemas/market_newow.py services/quant-api/app/api/market_newow.py services/quant-api/tests/newow/test_trend_detail_service.py services/quant-api/tests/newow/test_market_newow_api.py
git commit -m "feat(newow): expose strategy detail facts"
~~~

Expected: all PASS。

### Task 15: Web exact normalization 与 observation-only view model

**Files:**
- Modify: apps/quant-web/src/types/newow.ts
- Modify: apps/quant-web/src/utils/newowTypes.ts
- Modify: apps/quant-web/src/utils/newowViewModel.ts
- Modify: apps/quant-web/tests/newowTypes.test.ts
- Modify: apps/quant-web/tests/newowViewModel.test.ts

**Interfaces:**
- Consumes: Task 14 exact API JSON。
- Produces: deeply frozen NewowTrendDetailResponse 和 DetailViewModel sections。

- [ ] **Step 1: 写 normalization RED**

completeNewowPayload() 在 newowTypes.test.ts 中返回深拷贝的完整 JSON literal，包含 21 根 D1 bars、完整新增 facts 和精确 calculation identity；expectedIdentity 固定为 {symbol: 'rb', from: '2026-01-05', through: '2026-01-25'}。测试变量声明为 Record<string, unknown>，以便删除字段后传入 unknown normalizer。

~~~typescript
test('rejects missing semantic labels or a page identity presented as causal', () => {
  const payload = completeNewowPayload()
  delete payload.semantic_labels
  assert.throws(() => normalizeNewowTrendDetailResponse(payload, expectedIdentity))
})
~~~

覆盖 unknown top-level key、非法 Decimal、仓位上下限、13 decision keys、unreachable keys、trustworthy_for_research=false、formula mismatch 和 stale calculation identity。

- [ ] **Step 2: 扩展 exact types**

page-parity、cleanroom、observation-only、repainting、causal-research 定义为互斥 literals。本 endpoint 的 online facts 只允许 page-parity/cleanroom + observation-only，拒绝伪造 causal result。

- [ ] **Step 3: 更新 normalizer**

每个数组检查顺序、唯一性和关联 bar_end；每个 formula description 与 calculation identity 同步验证；返回对象 deepFreeze。

- [ ] **Step 4: 构造 view model，不在 TS 重算公式**

View model 只依据 action/risk/token code 选择归一自有文案；目标、吸筹、分数、仓位和 volatility 原样来自 API。缺失/不一致进入 unavailable，不从 generic bars 推断。

- [ ] **Step 5: 验证并提交**

~~~bash
pnpm -C apps/quant-web exec node --test tests/newowTypes.test.ts tests/newowViewModel.test.ts tests/newowApi.test.ts tests/useNewowTrendDetail.test.ts
git diff --check
git add apps/quant-web/src/types/newow.ts apps/quant-web/src/utils/newowTypes.ts apps/quant-web/src/utils/newowViewModel.ts apps/quant-web/tests/newowTypes.test.ts apps/quant-web/tests/newowViewModel.test.ts
git commit -m "feat(web): normalize newow strategy facts"
~~~

Expected: all PASS。

### Task 16: 详情页通道、综合决策和诊断呈现

**Files:**
- Modify: apps/quant-web/src/components/market/detail/TrendDetailWorkspace.vue
- Modify: apps/quant-web/src/components/market/detail/NewowTrendChartStage.vue
- Modify: apps/quant-web/src/components/market/detail/newowTrendChartPrimitives.ts
- Modify: apps/quant-web/tests/NewowTrendChartStage.test.ts
- Modify: apps/quant-web/tests/MarketDetailPage.test.ts
- Modify: apps/quant-web/e2e/market-detail.spec.mjs

**Interfaces:**
- Consumes: normalized view model 和 chart stage props。
- Produces: D1 target/absorb overlay、参数比较 disclosure、综合决策 card、确定性、波动率、第一行动原则差异和诊断 cards。

- [ ] **Step 1: 写组件 RED**

renderTrendWorkspace 使用仓库既有 Vue SFC 测试 helper 和 fake completed D1 Market response；completeNewowPayload 由测试共享 fixture 导出，其内容与 Task 15 normalizer fixture 相同，不通过组件内部构造策略结果。

~~~typescript
test('shows page-parity and observation-only labels beside composite facts', async () => {
  const html = await renderTrendWorkspace({ response: completeNewowPayload() })
  assert.match(html, /页面一致性复算/)
  assert.match(html, /仅供研究观察/)
  assert.doesNotMatch(html, /交易指令/)
})
~~~

同时覆盖 mobile 顺序、unavailable、page-vs-cleanroom 差异、warning unreachable disclosure、参数比较器不可信标签和 rollover reset notice。

- [ ] **Step 2: 增加纯绘图通道 primitive**

只把 API 的 bar_end/target/absorb/available 映射为 line data；available=false 断线，不用 generic bars 计算 HHV/LLV，不跨 rollover seam 连线。

- [ ] **Step 3: 扩展 TrendDetailWorkspace**

顺序：核心观察结论、目标/吸筹、综合决策、第一行动原则、诊断事实、参数比较、公式/证据 disclosure、主图。仓位写“页面状态映射区间”，禁止表述为实际账户仓位；蓝带仍说明不是建立期货空单。

- [ ] **Step 4: 归一自有 copy adapter**

统一使用“观察”“状态”“风险”“等待确认”，不复制原站建议，不出现“应买入”“必须加仓”“下单”或收益保证。页面 bug 说明为“页面一致性身份保留原控制流；研究修正版另列”。

- [ ] **Step 5: Web unit、build 与 E2E**

~~~bash
pnpm -C apps/quant-web exec node --test tests/NewowTrendChartStage.test.ts tests/MarketDetailPage.test.ts tests/newowTypes.test.ts tests/newowViewModel.test.ts tests/newowApi.test.ts tests/useNewowTrendDetail.test.ts
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-detail.spec.mjs
git diff --check
~~~

Expected: unit PASS、Vue TypeScript build PASS、1920×1080 与 390×844 E2E PASS，无水平溢出和 console error。

- [ ] **Step 6: 提交 Web 集成**

~~~bash
git add apps/quant-web/src/components/market/detail/TrendDetailWorkspace.vue apps/quant-web/src/components/market/detail/NewowTrendChartStage.vue apps/quant-web/src/components/market/detail/newowTrendChartPrimitives.ts apps/quant-web/tests/NewowTrendChartStage.test.ts apps/quant-web/tests/MarketDetailPage.test.ts apps/quant-web/e2e/market-detail.spec.mjs
git commit -m "feat(web): present newow strategy evidence"
~~~

### Task 17: 报告、全量验证、最终双路 Review 与 develop 集成

**Files:**
- Modify externally: v3.2.82-gap-closure/report-source.md
- Create externally: v3.2.82-gap-closure/report.md
- Modify externally: v3.2.82-gap-closure/evidence-manifest.json
- Modify: docs/tasks/2026-09-04-newow-v3-2-82-coverage.md
- Modify: docs/tasks/2026-09-04-newow-v3-2-82-complete-replication-design.md

**Interfaces:**
- Consumes: Slice A-E commits/tests、external evidence、stock parity、futures validation seam。
- Produces: completion audit、P1/P2-cleared reviews、clean branch、ordinary develop merge。

- [ ] **Step 1: 运行 3 指数 + 6 股票逐值复算**

对 week/day/60m 比较 channel、display selection、五窗口排序、composite、certainty、volatility、first-action 和 diagnostic tokens。逐功能给出 compared/matched/mismatched/unavailable counts；任一 mismatch 定位 source hash、symbol、period、bar_end、field。

- [ ] **Step 2: 运行期货迁移验证**

使用现有只读/fixture seam 覆盖 RB/SC/M × 1d/1w/60m、至少两个历史 rollover、SC2302 周线 owner 子集、prefix invariance、成本/limit facts 和 anchored OOS。真实 production read-only 若需要新授权而当前没有，则只跑 fake/fixture 合同并标记 EXTERNAL_GATE_PENDING，禁止伪造结果。

- [ ] **Step 3: 完成报告与 coverage**

report.md 分为 Observed UI facts、Manual claims、Repository facts、Implementation hypotheses、Parity results、Futures migration results、Rejected/Unknown、Risks。公开可访问面须为 REPRODUCED_EXACT、CLEANROOM_IMPLEMENTED 或有证据的 REJECTED；私有服务端可保持 UNKNOWN，但必须解释边界。

- [ ] **Step 4: 完整验证矩阵**

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
uv run --project services/quant-api python -m ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-detail.spec.mjs
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
~~~

Expected: all executable checks PASS，secret scan findings=0。

- [ ] **Step 5: 最终 Standards Review**

独立 reviewer 从 Slice A base 到 HEAD 检查工程标准、唯一数据链、模块深度、Decimal、错误合同、无重复 resolver/公式、API 安全、Web fail-closed、无 Alert/Runtime/订单和测试充分性。

- [ ] **Step 6: 最终 Spec Review**

另一独立 reviewer 对 Spec §1-§13 和本计划 Task 1-17 建 requirement-to-evidence ledger，逐条给出 proved/contradicted/missing；任何 P1/P2 或 missing requirement 都修复并重跑受影响验证。

- [ ] **Step 7: 清零 P1/P2 并做 completion audit**

~~~bash
git status --short --branch
git log --oneline --decorate develop..HEAD
git diff --stat develop...HEAD
git diff --check develop...HEAD
~~~

Expected: task worktree clean；两路最终 Review P1=0, P2=0；coverage 无公开面未解释 UNKNOWN；无 production mutation。

- [ ] **Step 8: 普通流程合入 develop**

~~~bash
git push -u origin codex/newow-v3-2-82-complete-replication
git -C /Volumes/扩展盘/guiyi-quant-workstation merge --no-ff codex/newow-v3-2-82-complete-replication
git -C /Volumes/扩展盘/guiyi-quant-workstation push origin develop
~~~

执行前重查主工作区 develop、dirty state 和远端是否前进；存在用户未提交修改或新冲突则停止 merge，保留已 push task branch。禁止合入 main、创建 tag/release、切换 Runtime 或修改 production Scope。

---

## Completion definition

只有以下证据同时成立才能标记 COMPLETED：

~~~text
Slice A-E commits present
all executable validation green
external manifest verifies
3 indexes + 6 stocks + 3 periods covered
page-parity and causal identities type-separated
13 matrix entries documented and warning defect regression-tested
diagnostic facts/copy separated
screener private logic not overstated
futures migration contract verified; production-only readback labeled external gate when not authorized
two final independent reviews with P1=0 and P2=0
task branch merged to develop and develop pushed
no main/tag/release/Runtime/Alert/notification/order mutation
~~~

若真实期货只读 evidence 因缺少一次性授权未运行，工程状态最多为 CODE_COMPLETE_EXTERNAL_GATE_PENDING；fixture 测试不能表述为真实期货验证完成。
