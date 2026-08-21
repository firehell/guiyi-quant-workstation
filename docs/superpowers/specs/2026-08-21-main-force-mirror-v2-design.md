# 主力照妖镜 V2 设计

状态：DESIGN_APPROVED / IMPLEMENTATION_PENDING

日期：2026-08-21

设计冻结：2026-08-21T14:00:36+08:00

阶段属性：historical-only / observation-only / no promotion

## 1. 目标

主力照妖镜 V2 将现有 60m 期货观察副图收敛为一个服务端唯一计算、可因果复算的双层主力压力观察器：

```text
Canonical 60m 的价格、成交量、持仓量
→ 即时压力 + 累计压力

RQData 精确物理合约 T-1 Top20 席位排名
→ 席位方向、强度与同向/背离解释

原“ 小心 ”警戒
→ 保留原公式、阈值、冲突与 latch 语义
```

V2 不试图把全部输入压成一个万能资金分数，也不把价格、持仓量或席位排名描述为可验证的真实资金净流入金额。它只帮助用户观察：

1. 当前 60m Bar 的多空持仓方向压力；
2. 压力是否连续累积、衰减或反转；
3. T-1 Top20 席位变化是否与当前压力或“ 小心 ”拥挤方向同向；
4. 数据不可用、换月或预热不足时为什么不能解释。

完成后只允许声明 V2 已形成只读观察面；不得声明策略有效、盈利、可交易、可通知或可晋升。

## 2. 已批准决策

以下决策已由用户在 2026-08-21 逐项批准：

1. 首版为端到端只读观察版：席位快照、Python Kernel、只读 API 与 Web 副图；不含自动盘后更新、Live、Alert 或通知。
2. 使用双层证据，不把席位数据融合进即时压力或“ 小心 ”触发分数。
3. 席位历史数据保存为独立、不可变的 Parquet 研究快照；不恢复 PostgreSQL `futures_member_ranks`，不修改八表 Market Catalog。
4. 算法框架覆盖 active 60；席位层按品种准入，首批只承认已经真实探测的 `jm/ag/cu/m`，其他品种 fail-closed 为 unavailable。
5. T 日所有 60m Bar 只使用 `physical_contract(T)` 对应的 T-1 已公布席位数据；换月日不继承旧合约。
6. 服务端 Python Kernel 是唯一公式事实源，Web 只请求与绘图；不再维护 Python/TypeScript 双公式。
7. 最终副图只保留 `MACD` 与 `主力照妖镜 V2`。
8. V0 与 V1 的当前源码、Registry/Policy、CLI、fixtures、测试、Web 接线和 active canonical 引用全部退役；历史只从 Git history 追溯。
9. “ 小心 ”内容必须在 V2 中保留，不因 V0/V1 代码退役而改变。

## 3. 项目边界

### 3.1 支持范围

```text
market        = domestic_futures
frequency     = 60m
series_kind   = actual_dominant | contract
bar_source    = confirmed Canonical Historical only
indicator     = main_force_mirror_v2
status        = observation_only
```

### 3.2 明确不支持

```text
continuous
1m / 5m / 15m / 30m / 1d / 1w
Redis Live Overlay
未确认 Bar
自动席位同步
通用回测引擎
Signal / Alert / notification
Execution Review
订单 / 撮合 / 仓位管理
真实资金流金额或比例
main / tag / release
Runtime promotion / switch
```

`auto_order=false` 始终成立。

## 4. 总体架构

```text
Canonical 60m + MainContractMap rank=1
                 │
                 ▼
          MarketDataService
                 │
                 ├──────────────────────┐
                 │                      │
                 │             exact physical_contract
                 │                      │
                 │                      ▼
                 │       MemberRankSnapshotRepository
                 │          pinned immutable dataset_id
                 │                      │
                 └──────────┬───────────┘
                            ▼
                MainForceMirrorV2Service
                            │
                            ▼
                MainForceMirror V2 Kernel
                            │
                            ▼
 GET /api/v1/market/research/main-force-mirror
                            │
                            ▼
          KlineChart existing bottom pane renderer
```

查询面不得注入 RQData provider、凭据或写入能力。RQData 只存在于独立的快照构建写侧；Web/API 只读取已经完整发布且钉住身份的快照。

## 5. 席位快照数据合同

### 5.1 数据定位

数据集 schema identity：

```text
main_force_member_rank_v1
```

来源唯一为 RQData `get_member_rank`。请求单位必须是 `MainContractMap rank=1` 解析出的精确物理合约，不允许使用产品汇总排名替代合约排名。

该数据集：

- 不属于 Canonical K 线；
- 不进入八表 Market Catalog；
- 不恢复已退役的 PostgreSQL 席位表；
- 不提交到 Git；
- 不允许 API 请求时联网补齐。

### 5.2 物理布局

研究数据根由 Git 外的明确配置 `GUIYI_RESEARCH_DATA_ROOT` 提供；查询面再由 `GUIYI_MAIN_FORCE_MEMBER_RANK_DATASET_ID` 钉住唯一快照。

```text
<research-data-root>/
  main_force_member_rank_v1/
    <dataset_id>/
      snapshot.json
      contract=<physical_contract>/
        year=<yyyy>/
          member_rank.parquet
```

服务不得 glob “最新目录”，也不维护自动移动的 active 指针。

### 5.3 `snapshot.json`

一个快照只保留一个必要 descriptor，字段固定为：

```text
schema_version
dataset_id
provider = rqdata
provider_client_version
created_at
requested_since
requested_through
requested_products
admitted_products
physical_contracts
partitions[]:
  relative_uri
  row_count
  coverage_start
  coverage_end
  quality_status
```

descriptor 是读取分区的唯一索引，不再建设第二套 Catalog、active manifest 或逐行 lineage 表。

### 5.4 标准化行

```text
physical_contract
trade_date
rank_by              volume | long | short
rank                  1..20
member_name
value                 成交量或持仓量
change                相对上一公布日变化
provider              rqdata
dataset_id
```

原始层不保存“流入、流出、看多、看空”等解释性结果。原始数量保持整数或 Decimal；只有进入指标层后的无量纲标准化值使用文档化 binary64 计算与统一舍入。

### 5.5 严格质量 Gate

每个 `physical_contract × trade_date` 必须同时满足：

1. `volume/long/short` 三类全部存在；
2. 每类恰好 20 行；
3. 排名连续且唯一为 `1..20`；
4. 主键无重复；
5. `member_name` 非空；
6. `value` 非空且非负；
7. `change` 为有限有符号数；
8. 日期属于正式 TradingCalendar；
9. 合约在 Catalog 证明的上市有效期内；
10. Parquet 可读，schema、行数与 descriptor 完全一致。

任一条件失败，整个合约日席位层 unavailable；不得局部拼接、补零、沿用前日或退回产品汇总数据。

### 5.6 因果对齐

```text
T 日 confirmed 60m Bar
→ 读取 Bar 的 physical_contract(T)
→ 通过 TradingCalendar 求 previous_trading_day(T)
→ 读取 physical_contract(T) × previous_trading_day(T) 的完整 Top20
```

换月日使用新合约的 T-1 数据。新合约 T-1 不存在时返回 unavailable，不继承旧主力合约。

### 5.7 构建与发布

统一 CLI 入口预留为：

```text
guiyi data member-rank snapshot
```

默认只输出 plan/dry-run；只有显式 `--apply` 才允许一次真实构建。写侧执行：

```text
exact MainContractMap segments
→ exact-contract RQData requests
→ sibling staging directory
→ schema/identity/coverage/physical readback
→ atomic rename to immutable dataset_id
```

失败不覆盖既有快照、不改变 API pinned dataset、不自动 retry。真实 RQData 请求与数据写入必须取得届时范围明确的单次授权。

## 6. V2 指标身份与参数

### 6.1 Exact identities

```text
indicator_code      = main_force_mirror_v2
indicator_version   = futures-member-research-v2
formal_policy_id    = main_force_mirror_observation_v2
research_protocol   = main_force_mirror_v2_retrospective_v1
member_schema       = main_force_member_rank_v1
```

Registry capability：

```text
web_capable          = true
backtest_capable     = false
live_capable         = false
alert_capable        = false
notification_capable = false
auto_order           = false
future_looking       = false
closed_bar_only      = true
```

## 7. 即时压力层

### 7.1 输入与 calculation block

必需输入：

```text
bar_end
trading_day
physical_contract
open / high / low / close
volume
open_interest
```

时间戳必须严格递增；OHLCV、OI 或物理合约身份异常时逐点 fail-closed。连续有效且物理合约相同的 Bar 构成一个 calculation block。

以下事件结束 block 并清空 ATR、SMA、EMA、压力、累计线和 latch：

- 合法换月；
- invalid Bar；
- 合约身份缺失或冲突；
- 时间戳倒序或重复。

### 7.2 即时公式

```text
price_impulse = clip(
  (close[t] - close[t-1]) / ATR14,
  -3,
  3
)

clv = clip(
  (2 * close - high - low) / (high - low),
  -1,
  1
)

direction = 0.7 * price_impulse + 0.3 * clv

volume_ratio = clip(volume / SMA20(volume), 0, 3)
participation = sqrt(volume_ratio)

oi_impulse = clip(
  delta_open_interest / EMA20(abs(delta_open_interest)),
  -3,
  3
)

strength = clip(
  abs(direction) * abs(oi_impulse) * participation * 25,
  0,
  100
)
```

ATR14 使用 Wilder 语义；OI EMA20 使用 SMA seed。`high == low` 时 `clv=0`。

### 7.3 五状态

先应用：

```text
abs(direction) < 0.15 or abs(oi_impulse) < 0.25
→ turnover
```

否则：

```text
direction > 0 and oi_impulse > 0 → long_build
direction < 0 and oi_impulse > 0 → short_build
direction > 0 and oi_impulse < 0 → short_cover
direction < 0 and oi_impulse < 0 → long_liquidation
```

显示值：

```text
long_build / short_cover       → +strength
short_build / long_liquidation → -strength
turnover                       → sign(direction) * min(strength, 15)
```

其解释固定为 `directional_position_pressure_proxy_not_measured_fund_flow`。

## 8. 累计压力层

```text
accumulated_pressure = EMA5(instant_pressure)
```

规则：

- 只消费同一 calculation block 内的 state-ready 即时压力；
- 使用前 5 个 ready 值的 SMA seed；
- block 切换立即重置；
- 不跨换月拼接；
- 不修改即时柱状态；
- 不参与“ 小心 ”触发；
- 不生成策略或交易方向。

累计压力仅帮助识别即时压力的连续累积、衰减与方向反转。

## 9. 席位解释层

### 9.1 日级原始聚合

对 T-1 精确合约 Top20：

```text
long_total         = sum(long.value)
short_total        = sum(short.value)
long_change_total  = sum(long.change)
short_change_total = sum(short.change)

change_bias =
  (long_change_total - short_change_total)
  / (long_total + short_total)
```

同时计算但不进入方向判断：

```text
position_skew = (long_total - short_total) / (long_total + short_total)
top5_volume_share = sum(volume rank 1..5) / sum(volume rank 1..20)
```

分母非正、字段不完整或数值非有限时该日 unavailable。

### 9.2 因果标准化

```text
baseline = median(
  abs(change_bias) over previous up to 60 available trading days
)
```

要求至少 20 个先前有效交易日，且不包含当前 member trade date。`baseline <= 0` 时为 warm-up/unavailable。

baseline 只用于无量纲强度标准化，不用于填充当前方向：

- `actual_dominant` 按同品种的 causal rank1 日序列计算，允许历史窗口包含此前的 rank1 物理合约；
- `contract` 只使用同一物理合约的历史席位日；
- 当前合约日缺失时仍直接 unavailable，不得用 baseline 中的旧合约方向代替。

```text
member_strength = abs(change_bias) / baseline
```

初始固定分层：

```text
member_strength < 0.5       → neutral
0.5 <= strength < 2.0       → directional
member_strength >= 2.0      → strong_directional
```

参数敏感性只允许比较 `0.5/1.0/1.5/2.0/2.5`，不得按单品种搜索最优阈值。任何未来阈值变化必须产生新参数 hash 或新版本。

### 9.3 两种关系

普通 Bar 返回：

```text
relation_to_accumulated
```

其方向锚定累计压力的正负号；任一侧 neutral/unready 时为 neutral，符号一致为 aligned，符号相反为 divergent。

“ 小心 ”Bar 另返回：

```text
relation_to_caution
```

其中：

```text
long_chase_caution  → 拥挤方向为 long
short_chase_caution → 拥挤方向为 short
```

席位变化与拥挤方向一致时为 aligned；且 `member_strength >= 2.0` 时为 strong_aligned。该状态只描述席位结构同向，不表示提高胜率或确认未来反转。

## 10. “ 小心 ”冻结语义

V2 必须保留现有期货警戒的数学语义：

### 10.1 多头追涨警戒

```text
upper extreme                            +30
short-cover dominated                    +30
10-bar long-open-pressure divergence     +25
high-volume upper rejection/exhaustion   +15
```

### 10.2 空头追空警戒

```text
lower extreme                            +30
long-liquidation dominated               +30
10-bar short-open-pressure divergence    +25
high-volume lower absorption             +15
```

原始未舍入分数达到 70 才成为 candidate。多空同时 candidate 时输出 conflict，不触发方向事件、不消耗 latch、暂停 re-arm counter。

两侧 latch 独立；事件触发后，低分连续 3 根并满足位置回归，或连续 2 根相应 build 状态后才 re-arm。换月和 block 结束全部重置。

席位层不得创建、取消、延迟或重复“ 小心 ”：

```text
小心｜席位强同向
小心｜席位同向
小心｜席位背离
小心｜席位中性
小心｜席位不可用
```

页面使用“强同向”，不使用“强确认”，避免把描述性关系包装成预测结论。

## 11. 只读服务与 API

### 11.1 Service

`MainForceMirrorV2Service` 组合：

```text
MarketDataService
MemberRankSnapshotRepository
MainForceMirror V2 Kernel
```

不得直接读取 Canonical 文件、glob 数据目录、自行解析主力合约或调用 RQData。

### 11.2 分页计算

API 查询合同与 `/bars/page` 对齐：

```text
symbol
series_kind
contract?
frequency
before?
limit <= 2000
```

由于“ 小心 ”latch 可能跨越普通 warm-up 长度，服务不能只查询页面前固定 31 根 Bar。对页面覆盖的每个物理合约 segment，必须从该 segment calculation block 起点计算到请求页末端，再切出当前页 points。

`contract` 查询从 Catalog 证明的有效合约区间起点计算；`actual_dominant` 查询从 MainContractMap 解析的各 rank1 segment 起点计算。首版不增加持久缓存或状态 checkpoint。

### 11.3 Endpoint

```text
GET /api/v1/market/research/main-force-mirror
```

响应：

```text
request
indicator:
  indicator_code
  indicator_version
  formal_policy_id
  parameters_hash
  interpretation
  observation_only
  historical_only
  auto_order

member_dataset:
  status
  dataset_id?
  schema_version?
  admitted_product
  coverage?

points[]:
  bar_end
  trading_day
  physical_contract
  pressure_ready
  pressure_state
  instant_pressure
  accumulated_ready
  accumulated_pressure
  caution_ready
  caution
  long_caution_score
  short_caution_score
  caution_reason_codes
  member_status
  member_trade_date
  member_direction
  member_change_bias
  member_strength
  position_skew
  top5_volume_share
  relation_to_accumulated
  relation_to_caution
  unavailable_reason

page
resolved_contract_segments
```

所有公开数值统一 6 位小数、`half_away_from_zero_binary64`，并把 `-0` 规范化为 `0`。

### 11.4 错误边界

HTTP 422：

```text
MFM_V2_UNSUPPORTED_FREQUENCY
MFM_V2_UNSUPPORTED_SERIES_KIND
MFM_V2_CONTRACT_INVALID
MFM_V2_REQUEST_INVALID
```

HTTP 409：

```text
MFM_V2_MARKET_IDENTITY_CONFLICT
MFM_V2_PHYSICAL_CONTRACT_MISSING
MFM_V2_MEMBER_DATASET_INVALID
MFM_V2_MEMBER_DATASET_IDENTITY_CONFLICT
```

HTTP 200 的 point-level unavailable：

```text
MFM_V2_MEMBER_PRODUCT_NOT_ADMITTED
MFM_V2_MEMBER_PREVIOUS_TRADING_DAY_MISSING
MFM_V2_MEMBER_CONTRACT_DAY_INCOMPLETE
MFM_V2_MEMBER_WARMUP
```

未配置快照时核心压力仍可返回，`member_dataset.status=unavailable`；一旦配置了 dataset id，但 descriptor、分区或身份损坏，则整个请求 409，不得静默降级。

错误响应不得暴露数据根目录、内部路径、SQL、stack trace 或 RQData 凭据。

## 12. Web 副图

### 12.1 最终 Tab

```text
MACD | 主力照妖镜 V2
```

默认仍为 MACD。旧本地偏好迁移规则：

```text
old futures mirror selection → main_force_mirror_v2
old prototype V0 selection   → macd
unknown selection            → macd
```

### 12.2 信息层级

```text
┌ 主力照妖镜 V2｜只读观察 ─────────────────────┐
│ 多头增仓  即时 +36.2  累计 +18.7             │
│ 席位强同向 · 数据日 2026-08-20 · JM2609      │
│                                               │
│        ╭── 累计压力 EMA5                      │
│   ▇ ▇ ╱                                       │
│ ─────────────────────────────────── 0          │
│        ▂ ▃        小心                         │
└───────────────────────────────────────────────┘
```

- 柱体：即时压力；
- 金色细线：累计压力 EMA5；
- 零轴：多空方向边界；
- long build / short build / cover / liquidation 使用稳定、可区分配色；
- turnover 使用灰色；
- “ 小心 ”直接锚定对应 Bar；
- 席位状态始终同时展示 `member_trade_date`；
- Tooltip 展示物理合约、T-1、偏斜、强度和成交集中度；
- 不展示人民币金额、净流入比例或预测概率。

### 12.3 加载与不可用

- 只在 V2 Tab 激活时请求 V2 API；
- 请求身份由 `symbol + series_kind + contract + frequency + before + limit` 唯一确定；
- 身份变化必须取消或丢弃旧响应，不允许旧品种结果覆盖新页面；
- 不建立第二套全局状态管理；
- 使用现有 Kline/Lightweight Charts pane；
- 其他周期或 `continuous` 下保留 Tab，但显示明确 unavailable，不静默切回 MACD；
- Live Bar 不补算，副图右侧保持空白并显示“历史确认截至 ……”；
- API 错误时清除旧 V2 points，不显示 stale 结果。

Web 不包含任何指标公式，只包含 API schema、状态标签与绘图映射。

## 13. 历史研究协议

### 13.1 已有探索结论

2026-08-21 的已授权小样本探测证明：

- `jm/ag/cu/m` 精确 rank1 合约的 Top20 三类数据在探测窗口内完整；`sc` 返回空数据，不能准入；
- 当前压力分数没有稳定的全品种延续预测能力；
- 强席位同向的“ 小心 ”组在 pooled 结果中改善，但 `jm/m` 与 `ag/cu` 存在明显异质；
- 因此席位数据不得成为统一硬过滤器或复合方向分数。

这些结果只决定 V2 的解释性架构，不构成正式策略或 OOS 证据。

### 13.2 CLI

新建：

```text
guiyi research main-force-mirror-v2
```

它只从 `MarketDataService + pinned MemberRankSnapshotRepository` 读取并向 stdout 输出 JSON，不保存报告、不写 DB、不恢复通用 backtest API/Web/worker/queue。

### 13.3 比较组

```text
instant pressure
accumulated pressure
member aligned
member strong-aligned
member divergent
member neutral
member unavailable
all caution events
caution events by member relation
```

### 13.4 指标

未来 horizon 固定为 `1/3/5/10` 根 60m Bar，且不得跨物理合约：

```text
directional forward return
top-bottom group spread
median reversal return
hit rate
warning MFE / MAE
sample count
events per 1000 caution-ready bars
member coverage
parameter sensitivity
```

按产品、年份、状态分别输出；pooled 结果只作次要摘要。

### 13.5 研究纪律

- 2023-01-03 至 2026-08-20 已参与探索，只能称 retrospective / walk-forward diagnostic；
- 不得把该窗口重新包装为 untouched OOS；
- V2 参数冻结后的下一未观察交易日才开始 prospective OOS；
- 不因 pooled 改善掩盖单品种反向；
- 若关系继续异质，只保留描述性“同向/背离”，不得升级为预测确认；
- 首版不输出 Sharpe、收益曲线或盈利结论；
- 未来若把观察标签转换为交易信号，必须新建策略版本并另行定义成交时序、成本、滑点、仓位和 OOS Gate。

## 14. V0/V1 退役

### 14.1 删除范围

V2 通过替代测试后，删除：

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror.py
packages/quant-core/guiyi_quant/indicators/main_force_mirror.pyi
packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py
services/quant-api/app/market_data/main_force_mirror_futures_research_service.py
apps/quant-web/src/utils/mainForceMirror.ts
apps/quant-web/src/utils/mainForceMirrorFutures.ts
tests/fixtures/main_force_mirror_futures_v1_golden.json
```

并删除/替换：

- V0/V1 unit tests；
- V0/V1 Web tests 与 E2E；
- V1 research CLI parser/command/composition 接线；
- Registry/Policy 中 V0/V1 definitions；
- KlineChart 的原型 V0 与 V1 分支；
- README、TESTING、STATUS、PROJECT_SOURCE、INDICATOR_KERNEL 中的 active V0/V1 描述；
- 其他 active import、route、fixture 和文案引用。

`CHANGELOG.md` 中已经发生的历史记录保留，不改写历史。恢复只依赖 Git history，不创建备份目录、rollback copy 或兼容入口。

### 14.2 “ 小心 ”迁移验证

删除 V1 前，必须在同一工作树同时运行旧 V1 与新 V2，对现有 golden 样本逐点比较：

```text
caution_ready
long_caution_score
short_caution_score
caution
caution_reason_codes
conflict
latch re-arm timing
contract-switch reset
```

完全相等后，将期望值冻结为新的 V2 golden fixture，再删除旧实现与旧 fixture。无需保留额外 migration report。

## 15. 实施顺序

1. 先写失败测试和 V2 exact contracts；
2. 实现 snapshot descriptor、reader、quality validator 与 fake provider；
3. 实现 dry-run/staging/atomic publish 写侧，但不执行真实下载；
4. 实现 V2 Kernel 的即时、累计、席位和“ 小心 ”层；
5. 运行 V1→V2 “ 小心 ”迁移等价验证；
6. 实现 V2 historical research service 与 CLI；
7. 实现独立只读 API；
8. 实现 Web pane；
9. 删除 V0/V1 及所有 active references；
10. 综合修复后一次性运行完整相关验证。

实现不得顺手修改 MarketDataService、MainContractMap、Canonical schema、Alert、Execution Review 或 Runtime。

## 16. 验收标准

### 16.1 数据

- 快照身份固定且不可变；
- reader 不 glob、不联网、不读 PostgreSQL 席位表；
- admitted coverage 内每个合约日严格 3×20 rows；
- T-1 使用 TradingCalendar，不使用自然日；
- 换月日精确切换新合约；
- 缺失、损坏和身份冲突均按合同 fail-closed；
- 无真实数据或 provider fixture 被提交到 Git。

### 16.2 Kernel

- Python 是唯一公式实现；
- 60m + contract/actual_dominant 之外拒绝；
- 所有 rolling 状态限定在 calculation block；
- EMA5 不跨 block；
- 席位状态不改变即时柱或“ 小心 ”；
- “ 小心 ”逐点迁移等价；
- metadata、参数 hash、舍入和 `-0` 规范化稳定。

### 16.3 API

- 只读，无 provider、DB、Redis 或文件写入依赖；
- 任意分页位置的 latch 结果与从 segment 起点完整计算一致；
- 422/409/point unavailable 边界稳定；
- 不泄露内部路径、SQL、stack trace 或凭据；
- dataset id 与物理合约身份可读回。

### 16.4 Web

- 副图只有 MACD 与 V2；
- 无 V0/V1 计算或入口；
- 柱、线、“ 小心 ”与席位标签对齐同一 `bar_end`；
- unsupported、member unavailable、Live cutoff 与 stale request 均显式；
- Web 不含指标公式；
- build、unit 与 E2E 通过。

### 16.5 退役完整性

- V0/V1 active code、tests、fixtures、CLI、Registry/Policy 和 Web references 为零；
- 历史只存在于 Git history 与 CHANGELOG；
- 不保留兼容 wrapper、隐藏 Tab、旧路由或第二套实现。

## 17. 验证范围

实现完成时至少运行：

```text
targeted Python unit tests
snapshot repository and quality tests
V2 Kernel golden and property tests
research service / CLI tests
Market API tests
indicator Registry/Policy tests
apps/quant-web unit tests
apps/quant-web build
main-force-mirror V2 browser E2E
engineering active-reference scan
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

真实席位快照构建、真实历史矩阵、develop Runtime 重载和正式 Runtime switch 不属于代码验证；它们分别是后续外部 Gate。

## 18. 完成状态边界

```text
DESIGN_APPROVED
→ 本文获批

CODE_COMPLETE
→ 代码、fixture 与本地测试完成，未执行真实席位下载

CODE_COMPLETE_EXTERNAL_GATE_PENDING
→ 需要用户授权构建真实席位快照和运行真实历史矩阵

OBSERVATION_READY
→ 真实快照质量通过、retrospective 结果只读复核、Web 本地观察通过

RELEASED / RUNTIME_READY
→ 不由本设计或上述任一状态自动授予
```

AI 可以自动研究，但不能自动晋升。任何历史统计都不能把 V2 变成策略、通知或交易能力。
