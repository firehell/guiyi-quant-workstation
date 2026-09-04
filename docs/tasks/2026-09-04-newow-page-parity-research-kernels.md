# Newow 页面一致性 Primitive 与可信研究回测

日期：2026-09-04
状态：`CODE_COMPLETE / TEST_COMPLETE / FUTURES_VALIDATION_CONTRACT_COMPLETE / REAL_FUTURES_EVIDENCE_PENDING`
基线：`develop@7e9d6c5a9b92a99169a9e6ccc69bb9045b0ceebb`
分支：`feature/newow-trend-page-parity`

## 1. 目标与边界

本任务把当前牛哇详情页中已经能由公开页面源码和可重放浏览器数据确认的算法，实现为版本化 Quant Core primitive，并建立不复活旧 Backtest 应用域的纯研究评估器。

包含：

- 黄蓝趋势带 page v2；
- D1/D2/D3 page v2；
- 4/7/11 神奇数字；
- 主升浪 MA35/45、J 减仓、D4-D6 及组合 Gate；
- 震荡 HHV/LLV10 状态机与可配置通道；
- 主力控盘、主力照妖镜、涨跌动能三个副图 primitive；
- 七周期独立、下一根开盘成交、显式期货成本的研究回测。

不包含：

- 生产 RQData、Canonical、PostgreSQL 或 Redis 写入；
- active Backtest API、任务、表、Web、通知或 Runtime；
- 自动交易、订单或账户；
- 页面 AI 样本内推荐器；
- 把 A 股页面结果表述为期货收益证据；
- release、tag、main 或 Runtime promotion。

## 2. 证据分层

### 2.1 页面事实

浏览器采集覆盖 3 个指数与 6 只不同风格股票：上证指数、深证成指、创业板指、桐昆股份、贵州茅台、招商银行、比亚迪、宁德时代、格力电器。

日线公式横截面：

- 6,216 Bar；
- D1-D3 148 个 Marker；
- 11 周期 516 个 Marker、3,240 个 count-line；
- 主升浪 175 个带信号、415 个 J 减仓、287 个 D1-D6 文本信号；
- 三副图所有连续数组、状态和标记逐字段一致。

震荡横截面因贵州茅台页面返回 600 Bar，共 6,571 Bar、461 个事件。

多周期回测横截面为 3 指数 + 6 股票 × 周/日/60 分，共 27 组、12,482 Bar、81 个策略周期组合。

证据存放于当前 Codex 可视化研究包：

```text
newow-strategy-detail-research/trend-ma7-ma10-parity
```

该目录不是仓库 canonical，不参与 Runtime；它保存采集来源、截图、原始浏览器 JSON、分析脚本、结构化结果和 SHA-256 manifest。

### 2.2 仓库事实

- 旧 `newow_trend_band_cleanroom_v1` / `newow_escape_d123_v1` 保持原义；
- 新页面版本只通过新 profile/formula identity 启用；
- 既有 detail API 由 `newow_trend_d1_page_v2` 计算，但仍固定 completed actual-dominant D1；
- 其他 primitive 与回测仅为 Quant Core 研究能力，没有 active API/Runtime；
- `PROJECT_SOURCE.md` 的稳定产品面不因本任务自动改变。

## 3. 公式身份

```text
newow_trend_d1_page_v2
newow_trend_band_page_v2
newow_escape_d123_page_v2
newow_magic11_page_v1
newow_main_rise_ma35_ma45_page_v1
newow_main_rise_j_reduce_page_v1
newow_buy_d456_page_v1
newow_hhv_llv_channel_page_v1
newow_oscillation_hhv_llv10_page_v1
newow_main_force_control_page_v1
newow_zhaoyao_mirror_repainting_page_v1
newow_up_down_energy_page_v1
newow_causal_next_open_costed_v1
```

`MAIN_RISE_PAGE_V1` 冻结 band、J、escape、D4-D6 与 11 周期五个公式身份。组合 Gate 只接受这一精确集合，防止不同版本静默混用。

## 4. 策略语义

### 4.1 趋势

```text
JJ = (Close + High + Low) / 3
A = partial SMA(JJ, 7)
B = partial SMA(JJ, 10)
YELLOW iff Close >= B
BUILD = BLUE -> YELLOW
CLEAR = YELLOW -> BLUE
Marker price = B
```

MA7 是视觉边界，不参与状态判定。

### 4.2 D1-D3

页面版本使用 RSV10、partial SMA3、partial MA120 与 D3 峰值转折。旧 v1 的 RSV9/SMA_CN/OLS 斜率与页面事件 F1 仅约 0.149，不能复用身份。

### 4.3 主升浪

主升浪带是 partial SMA35(JJ) 与 partial SMA45(JJ)；J 减仓使用完整 RSV9 和 EMA3 K/D。D1-D3、D4-D6 与 11 周期是同一个页面组合的附加事件，杯柄、主力控盘与涨跌动能不是已证明硬 Gate。

### 4.4 震荡

震荡策略固定完整 HHV/LLV10。持有且触达上轨时先 CLEAR；随后空仓且触达下轨时 BUILD，因此一根 Bar 可按固定顺序产生两个事件。事件评分只是解释字段，不改变状态机。

### 4.5 副图

副图命名中的“主力”不代表资金流或持仓事实。照妖镜使用 5% zigzag 事后确认并把峰值回填到历史 Bar，属于 repainting：

```text
repainting = true
formal_signal_eligible = false
```

任何正式 signal、Alert 或回测入口必须拒绝它。

## 5. 多周期合同

研究评估器只接受七个正式周期：

```text
1m / 5m / 15m / 30m / 60m / 1d / 1w
```

每个周期必须由应用层从统一 `MarketDataService` 提供独立 completed actual-dominant 序列。评估器不做跨频聚合、不降级到别的周期、不用高周期状态过滤低周期信号，也不把月线/120 分钟等页面周期带入正式集合。

## 6. 可信研究回测合同

`newow_causal_next_open_costed_v1` 只处理 long-only 研究状态，不产生订单：

1. 输入 Bar 必须 completed、actual_dominant、同产品、同周期、时间严格递增且 source identity 唯一；
2. completed Bar 上产生的意图只能在下一根 Bar 的 Open 成交；
3. 买入滑点向上、卖出滑点向下；支持 Decimal bps/tick 滑点；
4. 支持 Decimal 单边费率、每手固定费用、合约乘数和最小变动价位；
5. physical contract 或 segment 改变时，取消未成交意图，未平仓记为 `DOMINANT_ROLL_EXCLUDED`，不跨月拼接盈亏；
6. 样本末意图取消，未平仓记为 `END_OF_SAMPLE_EXCLUDED`，不使用最后 Close 强平；
7. 只对已平仓交易按净收益复利；回撤字段明确为 closed-trade equity drawdown；
8. 照妖镜不属于可选策略枚举，传入未知/重绘策略 fail-closed；
9. 无 DB、API、任务、通知、Runtime 或真实订单入口。

页面口径只作为反例保存：同根 MA/High/Low 成交、零费用、收益相加、期末强平和事后最高价“理论值”均不得迁移。

## 7. 验证

已执行：

```text
uv run --project services/quant-api ruff check <本任务 Newow 源码与测试>
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/newow
  => 453 passed in 194.89s
PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
  => Success: no issues found in 103 source files
npm --prefix apps/quant-web test
  => 314 passed, 1 skipped
npm --prefix apps/quant-web run build
  => vue-tsc + Vite + bundle topology passed
npm --prefix apps/quant-web run test:e2e -- --grep Trend
  => 4 passed
```

定向新增回测测试覆盖：next-open、bps 费率、合约乘数、每手固定费、tick 滑点、换月取消、未平仓排除、混频/乱序拒绝、60m 独立计算、跨周期无 fallback、重绘策略拒绝。

独立 Review 提出的底层重绘入口、跨合约段批量计算、Web v1/v2 合同断裂和 marker ID 命名空间共四项问题均已修复并增加回归测试。

## 8. 未完成 Gate

- 只读 Canonical actual-dominant 期货金样本；
- 1d/1w/60m session 与 physical-contract rollover 实证；
- 外部带来源、日期与 hash 的 cost / multiplier / tick / limit 研究快照绑定；
- 涨跌停与流动性可成交性；
- OOS、Walk-forward 与参数稳定性；
- release 与 Runtime promotion 人工批准。

在这些 Gate 完成前，只能声明页面公式复算与研究内核测试完成，不能声明收益可信、策略候选晋升、已发布或 Runtime Ready。

## 9. 期货验证合同进展

后续 `codex/newow-futures-validation` 阶段已实现但尚未合入：

- `MarketSeriesResult -> NewowResearchBar` 的严格 actual-dominant 逐周期适配；
- 带来源和生效区间的合约成本、multiplier 与 tick 快照；
- 逐拟成交 Bar 的涨跌停约束与零成交量拒绝；
- 固定公式、空仓进入测试期的 anchored Walk-forward；
- 明确区分 fixture 合同验证与真实期货收益证据。

八表 Catalog 按 canonical 约束没有手续费表，因此不复活已退役的 `FeeMarginRule`。真实成本与涨跌停需要另行提供带日期、来源和 hash 的只读研究快照。完整边界和后续真实 evidence matrix 见 `docs/tasks/2026-09-04-newow-futures-validation.md`。
