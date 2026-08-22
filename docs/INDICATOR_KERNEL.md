# Indicator Kernel

更新时间：2026-08-21

## 定位

`packages/quant-core/guiyi_quant/indicators/` 是指标业务口径的唯一权威模块。当前保留 EMA、
MACD、ATR、HTDY original/strict、主力照妖镜 V2、Registry 与 formal policy。旧策略包、回测、
Signal/Review、generic realtime evaluator 与主力照妖镜 V0/V1 执行实现已退役，仅由 Git
history 追溯。当前 Alert V2 只保留独立、严格限域的 HTDY current-bar consumer，
以及复用现有 resolver 的 SuBing consumer；主力照妖镜不进入 Alert。

| 角色 | 位置 | 当前状态 |
|---|---|---|
| Python Kernel | `packages/quant-core/guiyi_quant/indicators/` | 唯一研究算法与 policy 权威 |
| Market HTTP | `MainForceMirrorV2Service` | 只读分页输出，不复制公式 |
| Web 副图 | `MACD | 主力照妖镜 V2` | 只渲染 API 数值与分类，不重算 V2 |

## 代码位置

```text
packages/quant-core/guiyi_quant/indicators/
├── atr.py
├── ema.py
├── htdy_original.py
├── htdy_strict.py
├── macd.py
├── main_force_mirror_v2.py
├── models.py
├── policy.py
├── realtime_observation_policy.py
└── registry.py
```

## 通用正式边界

- EMA 默认 `seed_policy=sma_window`；无效输入不得补零，恢复输出前必须重新取得完整有效窗口。
- MACD/ATR 支持显式计算 policy，但 `compatibility_validated` 不等于 formal strategy、live
  或 alert 资格。
- Gate C 批准的 `subing_macd_sma_window_scale2_v1` 只允许 `subing_signal` consumer，不提升
  generic MACD。
- HTDY original 只允许明确命名的 `htdy_alert_observation` consumer 在
  `actual_dominant + confirmed 15m + current last bar` 边界执行。
- 所有正式消费者只使用 confirmed bars；未确认 bar 最多用于 Web preview。
- 未知 `indicator_code`、policy 或 consumer 必须 fail-closed。
- 未来若重建策略或回测，必须新任务、新合同并复用 Python Kernel。

当前 Registry 核心状态：

| indicator_code | status | web | backtest | live | alert |
|---|---|---:|---:|---:|---:|
| `ema10` / `ema21` / `ema60` | `validated` | yes | yes | yes | no |
| `macd` | `compatibility_validated` | yes | no | no | no |
| `atr` | `compatibility_validated` | yes | no | no | no |
| `main_force_mirror_v2` | `observation_only` | yes | no | no | no |
| `huotian_dayou_original_v0` | `observation_only` | yes | no | no | yes |
| `huotian_dayou_strict_v1` | `strategy_candidate` | no | yes | no | no |

Kernel capability 不表示当前存在对应应用入口，也不授权 Runtime、通知或交易。

## 主力照妖镜 V2

唯一 active identity 为 `main_force_mirror_v2@futures-member-research-v2`，formal policy 为
`main_force_mirror_observation_v2`。它只支持：

```text
frequency   = 60m
series_kind = contract | actual_dominant
bar         = Historical confirmed
member      = pinned immutable main_force_member_rank_v1 snapshot
status      = observation_only
```

`continuous` 与其他六个正式周期均不支持，也不跨频或跨实现回退。行情仅通过
`MarketDataService`；`contract` 绑定请求中的规范物理合约，`actual_dominant` 只使用
`MainContractMap rank=1` 已解析 segment identity。身份缺失/冲突、时间异常、OI 缺失、无效
OHLCV 或 member snapshot 身份/覆盖异常都必须显式 fail-closed，不猜合约、不补零、不使用
Live 或未钉住数据填缝。

压力计算、EMA5 累积压力、五种状态、追多/追空小心评分、latch/re-arm 及其原因码都由
Python Kernel 一次性产生。Web 仅展示 API 的即时压力柱、累积 EMA5、小心 marker、member
关系与不可用原因，不重算或改写服务端数值。底部 Tab 精确为：

```text
MACD | 主力照妖镜 V2
```

member 对齐仅使用 Bar 交易日 T-1 的已钉住 daily snapshot；不得使用 T 日收盘后才可知的同日
数据，不得为可用率回填。member 数据不可用时，已有价格/OI 压力观察保留，member
关系显式为 unavailable；身份或核心行情不可用时，整个对应观察 fail-closed。

真实 member snapshot 与 retrospective matrix 本次均未执行，仍是需要独立、精确执行意图的
external Gate。本代码、测试和文档不授权真实 RQData/snapshot apply、Canonical/DB 写入、
Live/Alert/notification、Runtime switch、release/tag 或订单；`auto_order=false`。

## SuBing scoped MACD

SuBing V1 Entry Signal 复用 Factor observation 的固定数学等价 tuple：

```text
("sma_window", 2, "fast12_slow26_signal9", True)
```

Signal core 必须核对 exact policy；policy 缺失或不等价时 fail-closed。generic MACD 仍为
`compatibility_validated`，不因该 scoped consumer 获得 backtest/live/alert 资格。
`macd_zero_distance_abs/bps` 继续保留为 Factor/Web/research observation，不属于
intraday V1 executable Signal 条件。

## HTDY 风险边界

- original 使用 XMA 风格居中窗口，具有已知未来依赖和重绘风险；只能作为 Web observation，
  或在 `actual_dominant + 15m + confirmed completed bar` 上只检查当前最后一根的 Alert observation。
- Alert 只使用 Python Kernel 已有 observation，不扫描旧 repaint 区域，不将 original 升级为
  backtest、正式 live strategy 或 `auto_order`。
- original 的 single/double XMA exact future dependency 分别为 12/24 根；Web 使用 27 根保守
  repaint scan zone。
- strict 是独立 causal 计算，只具策略研究候选资格；它不会自动恢复回测、Signal、
  live evaluator 或 alert。
- `RealtimeRepaintingObservationPolicy` 仅保留 frozen policy validator 与历史兼容测试。
- 原始公式外部语义 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；不得宣称 original
  已可正式回测或验证。

## Web 镜像

Web `calculateEMA`、`calculateMACD`、`calculateATR` 与 HTDY observation 只服务浏览器展示；
口径冲突时以 Python Kernel 与已冻结 fixture 为准。主力照妖镜 V2 不在浏览器复制公式，只投影
Market HTTP 返回的服务端数值、分类与不可用诊断。Web 不得自行产生 StrategySignal、写数据库、
发送通知或把 preview 提升为 Canonical。

## 验证

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/research/test_research_cli_mirror_robustness.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
```

验收只证明代码与观察合同在该验证范围内一致，不表示策略有效、盈利、Runtime-ready
或获得交易资格。
