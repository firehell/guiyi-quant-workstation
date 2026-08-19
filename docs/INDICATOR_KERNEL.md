# Indicator Kernel

更新时间：2026-08-19

## 定位

`packages/quant-core/guiyi_quant/indicators/` 是指标业务口径的唯一权威模块。当前保留 EMA、MACD、ATR、
HTDY original/strict、主力照妖镜 observation、Registry 与 formal policy；旧策略包、回测、Signal/Review、
generic realtime evaluator、旧通知和报告 Gate 都已退役。当前 Alert V2 只保留独立、严格限域的 HTDY
current-bar consumer，以及复用现有 resolver 的 SuBing consumer；主力照妖镜不进入 Alert。

| 角色 | 位置 | 当前状态 |
|---|---|---|
| Python Kernel | `packages/quant-core/guiyi_quant/indicators/` | 唯一研究算法与 policy 权威 |
| Web 观察镜像 | `apps/quant-web/src/utils/indicators.ts`、`mainIndicators.ts`、`mainForceMirror.ts` | 仅浏览器展示计算；不得成为策略事实源 |
| Market indicators HTTP | 无 | 当前未挂载；未来如需提供，必须从 Kernel 输出 |

当前 Product Workspace 已挂载 `Kline + EMA / Volume / MACD`，并允许在既有最底部副图 Pane 内通过
`MACD / 主力照妖镜` Tab 二选一观察；默认仍为 MACD。Web 指标镜像仍只服务浏览器展示，不得成为
Factor、Signal 或 Runtime 的事实源。

## 代码位置

```text
packages/quant-core/guiyi_quant/indicators/
├── atr.py
├── ema.py
├── htdy_original.py
├── htdy_strict.py
├── macd.py
├── main_force_mirror.py
├── models.py
├── policy.py
├── realtime_observation_policy.py
└── registry.py
```

## 正式边界

- EMA 默认 `seed_policy=sma_window`，`first_ready_index=period-1`；无效输入不得补零，恢复输出前必须重新
  取得完整有效窗口。
- MACD/ATR 支持显式计算 policy，但 `compatibility_validated` 不等于 formal strategy、live 或 alert 资格。
- `web_macd_legacy_v1` 只额外允许明确命名的 `subing_factor_observation` consumer 计算只读 Factor；
  generic `macd` 仍为 `compatibility_validated`，`backtest/live/alert` capability 均为 false。
- `main_force_mirror_v0` 是 causal、`observation_only` 的 Web 副图。六色柱是基于 OHLCV 的设计代理，
  不是主力账户识别、Level-2 资金流或可验证的资金流出比例；`backtest/live/alert/notification` 全部禁止。
- Gate C 已人工批准 `subing_macd_sma_window_scale2_v1`，且只允许 `subing_signal` consumer；它不提升
  generic MACD，也不批准 Backtest、Alert V2、notification、generic live 或 Runtime。
- HTDY original 只允许明确命名的 `htdy_alert_observation` consumer 在
  `actual_dominant + confirmed 15m + current last bar` 边界执行；generic `alert/live/notification`
  consumer 仍然 fail-closed。
- 所有正式消费者只能使用 confirmed bars；未确认 bar 最多用于 Web preview。
- 未知 `indicator_code`、policy 或 consumer 必须 fail-closed。
- 未来若重建策略或回测，必须新任务、新合同并复用 Python Kernel；不得恢复旧策略包或复制算法。

当前 Registry 核心状态：

| indicator_code | status | web | backtest | live | alert |
|---|---|---:|---:|---:|---:|
| `ema10` / `ema21` / `ema60` | `validated` | yes | yes | yes | no |
| `macd` | `compatibility_validated` | yes | no | no | no |
| `atr` | `compatibility_validated` | yes | no | no | no |
| `main_force_mirror_v0` | `observation_only` | yes | no | no | no |
| `huotian_dayou_original_v0` | `observation_only` | yes | no | no | yes |
| `huotian_dayou_strict_v1` | `strategy_candidate` | no | yes | no | no |

这里的 `backtest/live/alert` 表示 Kernel policy 能力，不表示仓库当前存在对应应用入口，也不授权 Runtime、通知
或交易。

## 主力照妖镜 observation V0

`main_force_mirror_v0` 是用户指定“主力照妖镜”视觉语义下的**设计版观察指标**，不是未知原始六色柱
公式的源码复刻。Python Kernel 与 `apps/quant-web/src/utils/mainForceMirror.ts` 使用同一数学口径并由
相同 golden 样本约束：

```text
CLV = (2 * close - high - low) / (high - low)
relative_volume = volume / SMA(volume, 20)，截断到 [0, 3]
raw_flow = CLV * relative_volume
flow = EMA(raw_flow, 5)
range_position = (close - LLV(low, 20)) / (HHV(high, 20) - LLV(low, 20))
```

六色柱只把上述价格位置、量能代理及其变化映射为：

```text
entry / wash / pull_up / distribute / exit / lure
进场  / 洗盘 / 拉高    / 出货       / 退场 / 诱多
```

它们是研究观察标签，不表示识别到了某个“主力”账户，也不得生成 `outflow_ratio`、资金净流出百分比或
交易指令。

### “小心”冻结公式

“小心”是该副图的核心事件，严格采用用户提供的通达信片段：

```text
VAR38 := BARSLAST(HIGH = HHV(HIGH, 5)) < 10;
VAR58 := IF(VAR38=1,2,0);
顶 := IF(VAR58=2,2,0);
顶A := IF(顶>REF(顶,1),50,0);
DRAWTEXT(顶A=50,45,'小 心');
```

Kernel/Web 的等价表达为：

```text
short_high_event = HIGH == HHV(HIGH, 5)
recent_short_high = BARSLAST(short_high_event) < 10
caution = rising_edge(recent_short_high)
caution_level = 50
```

因此它只在该状态从 0→1 时出现一次；连续处于状态内不会重复触发。该事件是短期高位结构重新激活的
警戒观察，不是顶部确认，不直接表示“一日内 70% 主力资金流出”。若未来要验证真实资金流，需要独立的
数据源、合同、统计定义和新任务，不得从本指标推导。

## SuBing scoped MACD

SuBing V1 Entry Signal 复用 Factor observation 的固定数学等价 tuple：

```text
("sma_window", 2, "fast12_slow26_signal9", True)
```

四项依次是 `seed_policy`、`histogram_scale`、`lookback`、`confirmed_only`。Signal core 必须同时读取
`web_macd_legacy_v1` 与 `subing_macd_sma_window_scale2_v1` 并核对该 exact tuple；policy 缺失或不等价时
fail closed，不能产生 `MATCHED`。`macd_zero_distance_abs/bps` 继续保留为 Factor/Web/research observation，
不属于 intraday V1 executable Signal 条件。未来 Alert V2 仍需独立设计、证据与人工 Gate。

## HTDY 风险边界

- original 使用 XMA 风格居中窗口，具有已知未来依赖和重绘风险；只能作为 Web observation，或在
  `actual_dominant + 15m + confirmed completed bar` 上只检查当前最后一根的 Alert observation。
- Alert 只使用 Python Kernel 已有的 `buy_observation` / `sell_observation`；不扫描旧 repaint 区域，不将
  original 升级为 backtest、正式 live strategy 或 `auto_order`。
- original 的 single/double XMA exact future dependency 分别为12/24根；Web 使用27根保守 repaint scan zone。
- strict 是独立 causal 计算，只具策略研究候选资格；它不会自动恢复回测、Signal、live evaluator 或 alert。
- `RealtimeRepaintingObservationPolicy` 仅保留 frozen policy validator 与历史兼容测试。旧
  `HtDyRealtimeCandidateEvaluator` 和相关 Runtime/事件/通知链已经退役，不是当前实现。
- 原始公式外部语义 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；不得宣称 original 已可正式
  回测或验证。

## Web 镜像

Web `calculateEMA`、`calculateMACD`、`calculateATR`、HTDY observation 与 `calculateMainForceMirror`
只服务浏览器展示。口径冲突时以 Python Kernel 和 golden fixture 为准，再修正 Web 镜像。Web 不得自行产生
StrategySignal、写数据库、发送通知或把 preview 提升为 Canonical。

Python 与 Web 当前各保留一份相同 golden 内容供不同测试运行时读取；若后续测试工具可以稳定读取同一
仓库根 fixture，再收口为单文件。在此之前不得手工修改其中一份而不更新另一份。

## 验证

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_htdy_strict_kernel.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_main_force_mirror.py

pnpm --dir apps/quant-web test
git diff --check
```

验收只证明 Kernel 与 Web observation 合同仍一致，不表示策略有效、盈利、Runtime-ready 或获得交易资格。
