# SuBing Daily Watch Cross-Roll V2 Design

日期：2026-08-26
状态：用户已批准（2026-08-26）
目标分支：`develop`

## 1. 决策摘要

SuBing Daily Watch V2 继续使用 `actual_dominant + 1d + 60m`，但 EMA21 与 5/10 Bar EMA21 回归斜率不再于每次 rank1 主力切换时清空 warm-up。V2 按 `MainContractMap rank=1` 原样拼接截至来源交易日的真实主力合约 Bars，并在该拼接序列上连续计算指标。

换月接缝不做前复权、后复权、比例调整或平移。新旧主力合约的真实价差直接进入 EMA21 与 slope。这一选择保持 `RQData -> Canonical contract Bars -> MainContractMap -> MarketDataService actual_dominant` 为唯一事实链，不新增第二套连续价格算法。

V1 的 segment-local 公式、历史 artifact 和代码可追溯性保持不变。V2 使用新的 projection/formula identity 与独立存储命名空间，不能把 V1 artifact 原地解释为 V2。

## 2. 问题与目标

V1 先 probe 来源交易日的当前 rank1 segment，再只从该 segment 的真实起点加载 D1/60m。EMA21 使用 `sma_window` seed，并要求最近 10 个 EMA21 值 ready，因此每个周期至少需要 30 根当前 segment Bars。

当多个品种集中换月时，大量品种虽有完整 Canonical 历史，仍会被标记为：

```text
D1_HISTORY_INSUFFICIENT
H1_HISTORY_INSUFFICIENT
```

2026-08-25 的自然 Daily Watch 中，active60 有 56 个品种因当前 segment 不足 30 根 D1 而 unavailable；同一时点 Market Radar 对 active60 的 actual-dominant D1 读取为 60/60 current。这不是数据资产缺失，而是 V1 warm-up 边界造成的产品可用性问题。

V2 目标：

1. 换月后继续使用换月前的 rank1 actual-dominant Bars 完成 EMA21/slope warm-up。
2. 保持严格因果：只读取 `trading_day <= source_trading_day` 的 confirmed Canonical Bars。
3. 保持真实主力身份：每根 Bar 必须由该交易日 `MainContractMap rank=1` 指向的物理合约提供。
4. 不把 `continuous/MAIN`、当前合约的非主力历史或 Live preview 混入 Daily Watch。
5. 只在整个 stitched actual-dominant 历史仍不足 30 根时返回 typed unavailable。

## 3. 范围

### 3.1 本次修改

- Daily Watch 的 D1/60m warm-up 读取和 EMA21/slope 计算；
- Daily Watch projection/formula/storage version；
- Daily Watch artifact lineage 字段；
- current API 与 Web 对 V2 contract 的严格解析；
- 对应后端、store、API、Web 单元测试与真实只读 smoke；
- `docs/DATA_CENTER.md`、`PROJECT_SOURCE.md` 和完成后的 `STATUS.md` 事实口径。

### 3.2 明确不修改

- SuBing intraday Factor、Signal、Calibration、FormalPolicy、Lifecycle；
- SuBing Historical replay/overlay；
- SuBing Alert Rule、product Scope、Event identity 与通知；
- HTDY、N、JDJ 或 Candidate/OOS 语义；
- Canonical、八表 Catalog、MainContractMap schema 或数据内容；
- Market Radar 公式；
- Live、Runtime、release、production 配置或真实通知。

Daily Watch V2 不自动授权任何 Alert、Runtime 或发布操作。

## 4. 已选方案与排除方案

### 4.1 已选：raw rank1 stitched actual-dominant

按交易日使用 `MainContractMap rank=1` 选择物理合约 Bar，保持原始 OHLCV 数值，跨 segment 连续输入 EMA21 Kernel。

优点：

- 复用现有 `MarketDataService` actual-dominant resolver；
- 不新增价格调整权威或派生资产；
- 与 Market Radar 已使用的 actual-dominant 历史口径一致；
- source-day cutoff 可由 MarketDataService 的交易日 Session 边界严格执行。

已接受的代价：换月价差会影响 EMA21 与 slope，必须视为 V2 公式事实，不能在实现中暗中平滑。

### 4.2 排除：复权拼接

不采用换月平移、比例复权或收益率链。它们需要新的 adjustment formula、锚点、舍入与历史修订合同，超出本次最小目标。

### 4.3 排除：当前合约上市以来历史

不读取当前物理合约在成为 rank1 之前的 Bars 作为 warm-up。该口径描述的是 current-contract history，不是 actual-dominant history。

## 5. 数据身份与读取合同

### 5.1 新请求合同

在 Market domain 增加只读请求：

```python
@dataclass(frozen=True, slots=True)
class ActualDominantRecentBarsQuery:
    symbol: str
    frequency: BarFrequency
    through: date
    limit: int
```

约束：

- `symbol` 使用现有 product code 校验；
- `frequency` 复用七周期 enum；Daily Watch 只调用 `1d` 与 `60m`；
- `through` 必须是 Catalog 中该品种的交易日；
- `1 <= limit <= 2000`；Daily Watch 固定请求 30；
- 返回严格不晚于 `through` 的最新 `limit` 根 actual-dominant Bars。

### 5.2 MarketDataService 行为

新增：

```python
def query_actual_dominant_recent_bars(
    self,
    request: ActualDominantRecentBarsQuery,
) -> MarketSeriesPageResult:
```

实现必须：

1. 用既有 `_trading_day_window(symbol, through, through)` 解析来源交易日精确 Session end；
2. 以 `before = session_end + 1 microsecond` 调用既有 `query_page(actual_dominant, limit=...)`；
3. 验证结果非空、严格递增、最后一根 `trading_day == through`；
4. 验证所有返回 Bar 的 `trading_day <= through`；
5. 继续复用 `_actual_dominant_page` 对 map 缺口、物理分区、重复 Bar、owner contract 与 coverage 的 fail-closed 校验。

不得让调用方自行猜测自然日、夜盘边界、Parquet 路径或换月 owner。

### 5.3 Daily Watch V2 loader

V1 `ActualDominantResearchSegmentLoader.load()` 的单 segment 语义保留给既有调用者，不放宽、不复用参数开关改变。

新增独立的 recent-history loader，输出：

```python
@dataclass(frozen=True, slots=True)
class ActualDominantStitchedResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesPageResult]
    current_segment: ResolvedContractSegment
```

loader 对 D1 与 60m 分别请求最近 30 根。它只要求：

- 两个周期最后一根均属于 source trading day；
- 两个周期的当前 owner contract 相同；
- 当前 owner 与 `dominant_segment_for_day(symbol, source_day)` 一致；
- 每个结果自身的 map/partition/Bar identity 完整；
- 历史 segments 可以不同，因为 30 根 D1 与 30 根 60m 覆盖的日期跨度不同。

任何 identity、map、coverage 或物理读取异常继续映射为既有 typed unavailable，不允许静默缩短后仍分类为 ready。

## 6. V2 指标合同

### 6.1 公式

公式本身保持：

```text
EMA period = 21
seed_policy = sma_window
slope windows = 5, 10 ready EMA values
price side = close vs latest EMA21
```

最小 ready 数仍为 30 根：第 21 根产生第一个 ready EMA21，第 30 根产生连续 10 个 ready EMA21 值。

变化仅为输入序列：

```text
V1: current rank1 segment bars only
V2: latest 30 raw rank1 stitched actual-dominant bars through source day
```

### 6.2 换月接缝

- 不调整价格；
- 不重置 EMA seed；
- 不重置 slope window；
- 不把换月跳空标记为缺口；
- 不把前一合约继续用于切换日之后；
- 不修改原始 volume、turnover 或 open_interest，尽管 Daily Watch V2 当前只消费 close。

测试必须以明显换月价差证明 Kernel 收到原始 close，而不是平滑后的 close。

### 6.3 纯函数边界

V1 `calculate_subing_ema_trend(..., segment_start_trading_day=...)` 保留，避免改变其他 segment-local SuBing consumer。

新增 V2 纯函数或显式 history-mode 参数时必须满足：

- V1 调用仍拒绝 segment start 之前的 Bars；
- V2 调用允许多 segment stitched Bars；
- 两种公式 identity 不共享含糊默认值；
- V2 snapshot 仍记录当前 contract，但不能把 warm-up 起点误称为当前 segment 起点。

推荐新增独立入口：

```python
calculate_subing_ema_trend_stitched(
    bars,
    *,
    timeframe,
    current_contract,
    current_segment_start_trading_day,
)
```

## 7. Snapshot 与 lineage

V2 trend snapshot 保留当前事实，并新增 warm-up lineage：

```text
contract                         # source day 当前 rank1 contract
current_segment_start_trading_day
warmup_start_trading_day         # 输入序列第一根 trading day
warmup_bar_count                 # ready 时固定为 30
warmup_segment_count             # 输入窗口覆盖的 rank1 segment 数
history_mode = rank1_stitched_raw
```

`segment_start_trading_day` 在 V2 contract 中重命名为 `current_segment_start_trading_day`，避免把跨段 warm-up 起点误读为当前 segment 起点。Web 只需严格校验这些字段，不必在首页默认展开全部 lineage。

当整个 actual-dominant 历史少于 30 根：

- 对应 trend 为 `None`；
- reason 继续使用 `D1_HISTORY_INSUFFICIENT` 或 `H1_HISTORY_INSUFFICIENT`；
- 不用 29 根近似计算；
- 不回退 V1、continuous 或当前合约自身历史。

## 8. Artifact 与版本

V1 identity：

```text
projection_version = subing_daily_watch_v1
formula_version = subing_ema21_trend_v1
namespace = $GUIYI_SUBING_OBSERVATION_ROOT/
```

V2 identity：

```text
schema_version = 2
projection_version = subing_daily_watch_v2
formula_version = subing_ema21_rank1_stitched_raw_v2
namespace = $GUIYI_SUBING_OBSERVATION_ROOT/v2/
```

V2 namespace 内仍使用：

```text
history/<target>.json
current.json
generation-status.json
```

规则：

- 不移动、删除、覆盖或重新序列化 V1 文件；
- active Store/parser 直接升级为严格 V2，不保留第二套 active V1 reader；V1 公式与 parser 只由 Git history 追溯；
- V2 store 只读写 V2 namespace，只接受 V2 projection/formula/schema；
- V2 current API 不回退 V1 current；
- V2 首次自然生成前，current API 返回 typed unavailable；
- 同 target 的 V2 内容冲突仍 fail-closed；
- V2 根继续使用现有 `/Volumes/...` mount/symlink/atomic replace 校验；
- composition 先用现有 resolver 校验配置的 base root，再把严格子目录 `v2/` 交给 Store；root revalidation 必须再次得到同一 `base/v2`；
- 不新增环境变量或生产凭据。

## 9. API 与 Web

Endpoint 保持：

```text
GET /api/v1/market/research/subing-daily-watch/current
```

API 只投影 V2。顶层增加或严格暴露：

```text
projection_version
formula_version
history_mode
```

每个 ready trend 使用第 7 节 V2 lineage 字段。前端 wire normalizer 必须拒绝 V1/mixed-version payload，不能把未知版本显示成 ready。

首页保留既有四类计数与 typed unavailable 展开。可用项不增加交易、评分或推荐语言。不可用文案继续表示实际整个 stitched history 不足；不再把正常换月初期一律解释为不足。

## 10. 错误与降级

| 场景 | V2 结果 |
|---|---|
| 最近 30 根跨一个或多个 rank1 segment 且完整 | ready，原样计算 |
| 整个历史不足 30 根 | 对应周期 `*_HISTORY_INSUFFICIENT` |
| source day Bar 缺失 | `SOURCE_TRADING_DAY_MISSING` |
| map 缺口、owner 冲突、重复 Bar | identity typed unavailable |
| D1/60m 当前 owner 不一致 | `DATA_IDENTITY_MISMATCH` |
| V2 current 不存在 | 顶层 current unavailable |
| 仅存在 V1 current | 不回退，顶层 current unavailable |
| V2 artifact version/schema 不一致 | fail-closed，不返回候选 |
| Web 收到 V1/mixed payload | 拒绝 normalization，显示 unavailable |

## 11. 测试与验收

### 11.1 MarketDataService

- recent query 精确包含 source-day final Bar；
- 排除 source day 之后的夜盘/未来交易日 Bars；
- 30 根跨多个 rank1 segment 原样返回；
- map/partition/owner/coverage 缺口继续失败；
- limit 和 trading-day 输入校验。

### 11.2 Loader 与公式

- D1/60m 当前 owner 一致时接受不同历史 segment spans；
- source-day current segment identity 必须精确；
- 29 根 insufficient，30 根 ready；
- 30 根横跨换月时 EMA21/slope 与 raw close Kernel exact parity；
- 明显换月价差未被平移或复权；
- V1 segment-local 测试保持不变。

### 11.3 Builder、store、API 与 Web

- 跨月 warm-up 的品种从 unavailable 进入 long/short/excluded 正常分类；
- 真正历史不足仍保留 typed reason；
- V2 bytes、idempotency、conflict、current regression、failure status；
- V2 store 不读取或修改 V1 fixture；
- API/Web 拒绝 V1/mixed-version payload；
- 首页计数、展开和候选跳转保持既有行为。

### 11.4 真实只读 smoke

使用 production Catalog/Canonical 的只读 composition，以最近完整来源交易日重算 active60，但不 publish artifact。输出：

```text
universe
long_watch
short_watch
excluded
unavailable
unavailable reason counts
per-frequency warmup bar-count distribution
```

验收不要求强行得到 60/60 ready；若某品种整个 stitched 历史确实不足 30 根，必须保留 unavailable。验收要求原先仅因当前 segment reset 造成的 56 个 D1 shortage 被消除，剩余项均有可解释的真实证据。

### 11.5 回归命令

至少运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py \
  services/quant-api/tests/test_subing_daily_watch_api.py

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation

uv run --project services/quant-api ruff check services/quant-api/app services/quant-api/tests
uv run --project services/quant-api mypy services/quant-api/app

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec vue-tsc --noEmit
pnpm --dir apps/quant-web build
```

根据实际 diff 再扩展后端全量或 Web E2E。

## 12. 发布与迁移边界

代码完成只可声明：

```text
CODE_COMPLETE
TEST_COMPLETE
EXTERNAL_GATE_PENDING
```

本任务不需要 PostgreSQL migration、Canonical 写入或 V1 artifact 迁移。以下仍需独立授权：

- main/tag/release；
- Runtime promotion/switch；
- 首次 V2 production artifact 的自然生成与读回；
- 任何真实通知或 Scope 修改。

首次部署 V2 后，API 在自然盘后生成 V2 current 前保持 unavailable；不能复制、转换或回填 V1 current 冒充 V2。

## 13. 验收结论

V2 完成的定义：

1. Daily Watch EMA21/slope 使用 raw rank1 stitched actual-dominant 最近 30 根 confirmed Bars；
2. 换月不清空 warm-up，也不复权；
3. V1 artifact 不变，V2 identity/namespace 独立且 fail-closed；
4. current source-day、current contract 与完整 map/coverage 仍严格验证；
5. 真实只读 active60 smoke 能解释所有剩余 unavailable；
6. 不改变 SuBing intraday、Alert、其他研究产品或 Runtime 授权。
