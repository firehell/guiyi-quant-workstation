# WEB-V1-04：Live 观察与技术观察文案收口

```text
WEB_MARKET_LIVE_OBSERVATION_READY
WEB_LIVE_INDICATOR_CONTEXT_READY
NO_FRONTEND_SIGNAL_OVERCLAIM
```

## 目标

前端 EMA/侧边栏不再使用「策略状态 / entry_signal / 正式信号」语言；Live 指标不前端猜测 merge；riskDraft 明确为示例计算器。

## 变更摘要

| 区域 | 内容 |
|---|---|
| `chart.vue` strategyStatus | 改为「技术观察 / 前端展示计算 / 非 StrategySignal」；EMA21 上/下方标签 |
| `chart.vue` mainIndicatorStatusText | Live：`Live 指标上下文待服务端只读接口；当前不前端猜测 merge` |
| `chart.vue` riskDraft | 标题「固定参数示例计算器（非正式风控）」 |
| `MarketStrategySidebar.vue` | 标题「技术观察 / Live 技术观察」；指标状态副文案；告警去交易指令化 |
| Live refresh | 20s 轮询 + hidden 停表 + `liveRefreshInFlight` 防重叠（注释加固） |
| Live 不支持 period | 明确原因：仅 1m~60m，日/周线需历史模式 |

## Gate 验收

### WEB_MARKET_LIVE_OBSERVATION_READY

- [ ] Live 模式侧边栏与主图指标区无「待 C3」类占位
- [ ] Live 不支持日/周线时有明确文案与 period disabled
- [ ] 页面 hidden 时停止 20s 轮询，恢复可见时补一次刷新
- [ ] 并发 refresh 不重叠（in-flight 守卫）

### WEB_LIVE_INDICATOR_CONTEXT_READY

- [ ] Live 模式不请求 historical EMA API、不前端 merge 指标序列
- [ ] 展示「待服务端只读接口」说明文案
- [ ] 未接入 `historical_live_context_v1` 时不写 StrategySignal

### NO_FRONTEND_SIGNAL_OVERCLAIM

- [ ] EMA 观察区不含 entry_signal / 多头信号 / 策略状态等正式信号语言
- [ ] riskDraft 标注「固定参数示例计算器，非正式风控」
- [ ] 侧边栏 Alert：「技术观察 · 前端展示计算 · 非交易指令」

## 测试

```bash
cd apps/quant-web && npm test && npm run build
```
