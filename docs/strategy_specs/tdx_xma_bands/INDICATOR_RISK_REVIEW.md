# TDX XMA Bands Indicator Risk Review

生成时间：2026-07-07

## 1. Stage 7 结论

`experiments/rqalpha_tdx_xma_bands` 是通达信 XMA 通道研究 PoC，不是归一量化 V1 正式策略、正式回测或正式信号链路。

核心结论：

- 原始 `XMA` 为居中 / 偏移移动平均，会读取当前 bar 之后的数据，存在未来函数和重绘风险。
- `ZK1 / ZD1 / ZD2`、`VAR23`、`XG`、`XG2` 均直接或间接依赖 `XMA`，不得作为可信回测或正式 signal 条件。
- `tdx_xma_bands_strategy.py` 在回测开始时预计算全序列信号，历史信号可能随回测终点变化，不可进入 PostgreSQL 正式报告链路。
- `XG2 / CURRBARSCOUNT` 在 PoC 中被简化为“当前 bar 视为图表末 bar”，与通达信滚动图表语义仍需单独验证。

## 2. 文件范围

本次历史审查当时覆盖：

- 原 `experiments/rqalpha_tdx_xma_bands/xma_core.py`
- 原 `experiments/rqalpha_tdx_xma_bands/tdx_xma_bands_strategy.py`
- 原 `experiments/rqalpha_tdx_xma_bands/README.md`

这些 PoC 文件当前仅可从 Git history 查阅；active 的原始 XMA 风险边界由
`packages/quant-core/guiyi_quant/indicators/htdy_original.py` 和指标 registry 维护。

本次不覆盖：

- RQAlpha bundle 数据可信度。
- JM v2 active parquet 回放。
- vn.py 正式策略迁移。
- Web Market 展示。
- `signal_events`、企业微信、live evaluator。

## 3. 指标风险分类

| 指标 / 条件 | 分类 | 未来函数 | 重绘 | 主要原因 |
|---|---|---|---|---|
| `XMA` | `forbidden_for_backtest_signal` | 是 | 是 | 居中窗口读取未来 bar。 |
| `ZK1 / ZD1 / ZD2` | `forbidden_for_backtest_signal` | 是 | 是 | 双 XMA 高低通道派生。 |
| `VAR23` | `forbidden_for_backtest_signal` | 是 | 是 | 对涨跌幅和绝对涨跌幅做双 XMA。 |
| `XG` | `observation_only` | 是 | 是 | 依赖 `ZD1` 和 `VAR23`。 |
| `XG2` | `observation_only` | 是 | 是 | 依赖 `ZK1 / ZD1`，且 `CURRBARSCOUNT` 语义为 PoC 简化。 |
| `DDX` | `candidate_after_rewrite` | 否 | 否 | 当前公式只用当前 OHLCV，但仍需 confirmed-bar 审查。 |
| `CURRBARSCOUNT` | `observation_only` | 否 | 否 | PoC 语义和通达信滚动图表语义不完全等价。 |
| `REF` | `candidate_after_rewrite` | 否 | 否 | 当前实现中正偏移只读过去值。 |
| `MA` | `candidate_after_rewrite` | 否 | 否 | 当前实现只读当前和过去窗口。 |
| `EMA` | `candidate_after_rewrite` | 否 | 否 | 当前实现为递推 EMA。 |

分类含义：

- `forbidden_for_backtest_signal`：不得进入可信回测、正式 signal、live evaluator 或企业微信提醒。
- `observation_only`：只能作为图形观察或人工研究说明，不可作为可行动信号。
- `candidate_after_rewrite`：只有在另一个阶段改写为 strictly backward-looking，并通过 confirmed-bar 测试后，才可作为候选。

## 4. 接入边界

本 PoC 结果不得：

- 写入 `StrategySignal`、`SignalNotification`、`SignalScanTask` 或未来 `signal_events`。
- 接入 `SignalScanner`、`LiveSignalEvaluator`、Backtest 或 Web Market 正式信号展示。
- 推送企业微信或读取 `QYWX_WEBHOOK_URL`。
- 作为 JM v2 active parquet 的可信回测结论。
- 作为自动下单、订单草稿或实盘建议。

如后续需要继续研究，应另开 Stage 7.5 或 Stage 8 前置 Plan，将可候选部分重写为 strictly backward-looking 指标，并单独命名策略版本。

## 5. 验证

当前验证：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_indicator_kernel.py
```

测试覆盖：

- 原始 XMA25/XMA6 的对称依赖窗口、双层依赖范围和非有限值处理。
- 修改未来尾部或修订尾部数据会改变既有历史观察，并受 24-bar future horizon 与 27-bar repaint scan zone 约束。
- 指标 registry 将原始 HTDY 标为 `repainting_risk=known`，并把 strict 因果实现保持为独立身份。
- realtime repainting policy 只接受冻结身份，因果 EMA 的未来尾部不改变既有前缀。

## 6. 下一步

下一阶段应进入 Stage 8 `signal_events` 信号事件化；不要把原始 XMA PoC 直接接入 Stage 8。若需要 XMA 类观察指标，先做单独改写和审查。
