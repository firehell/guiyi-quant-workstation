# SuBing EMA10/21 Ribbon

Date: 2026-08-29  
Status: approved for implementation  
Scope: Market chart (`apps/quant-web`) only

## Goal

选择苏冰 overlay 且能力成立时，主图默认显示 EMA10（快）与 EMA21（慢）之间的蓝黄线带：快线在上为浅黄/橙，快线在下为浅蓝，交叉处立即换色。原独立单色 EMA21 线收入图表设置，默认关闭。

## Non-goals

- 不改后端 EMA、策略公式或苏冰退出语义（策略仍认 EMA21）。
- 不实现参考图中的 SuperTrend/SAR 虚线。
- 不给线带单独开关，不引入第二套图表库或 npm 插件。
- 不把线带做成 `MainIndicatorId`。
- 不改 OpenSpec、Alert、Runtime 或 Canonical。

## Current state

- 苏冰 overlay 通过 `visibleMainIndicatorsForOverlay` 强制插入 `ema_21`。
- 图表设置可选 EMA 只有 EMA10 / EMA60。
- `KlineChart` 用 `LineSeries` 画可选 EMA；无两线之间填色能力。

## Approved decisions

1. 线带由苏冰 overlay 拥有，无设置开关。
2. 渲染用 Lightweight Charts `ISeriesPrimitive`（canvas 填色 + 边界线）。
3. 独立 EMA21 进入可选 EMA，默认关；不 bump preferences v7。

## Display contract

```text
选苏冰 + actual_dominant + 5m/15m
  -> 始终画 EMA ribbon（与可选 EMA 开关无关）
图表设置 EMA：EMA10 / EMA21 / EMA60，默认全关
  -> 只控制原有单色 LineSeries
选火天大有 / 无
  -> 不画 ribbon；可选 EMA 偏好跨 overlay 保留（「无」仍隐藏全部 overlay）
```

- 多头带（EMA10 > EMA21）：填充 `rgba(245, 197, 66, 0.30)`，边线 `#E8B923`
- 空头带（EMA10 < EMA21）：填充 `rgba(125, 211, 252, 0.32)`，边线 `#38BDF8`
- 可选 EMA21 仍用 `--gy-chart-ema`（`#f59e0b`），线宽 2
- 相邻两根真实 bar 各画一块梯形；相邻块共用竖边，缩放不断开
- 相邻两点 `(ema10-ema21)` 变号时，在屏幕坐标按 `splitT` 切开左右填色，**不写入假时间点**
- EMA21 暖身未就绪的 bar 不画带
- 交叉光标图例在线带开启时并入 EMA10、EMA21 读数（按 id 去重）

## Architecture

```text
selectedOverlay=subing && capability.supported
  -> showSubingEmaRibbon
  -> buildSubingEmaRibbon(bars) -> bands
  -> SubingEmaRibbonPrimitive on candle series

optionalEmaIndicators (ema_10 | ema_21 | ema_60)
  -> visibleMainIndicatorsForOverlay
  -> existing LineSeries
```

### Units

| Unit | Responsibility |
|------|----------------|
| `utils/subingEmaRibbon.ts` | 纯函数：对齐 EMA10/21、逐相邻真 bar 出 band、交叉 `splitT` |
| `components/kline/subingEmaRibbonPrimitive.ts` | LC primitive：真实 bar 投影、逐块梯形填色、交叉共用竖边 |
| `utils/mainIndicators.ts` | 苏冰不再强制 ema_21；可选 EMA 含 ema_21 |
| `klineViewModel.ts` | ribbon 开启时派生 ema10/ema21；hover 去重并入 |
| `KlineChart.vue` | `showSubingEmaRibbon` prop；attach/detach primitive |
| `ProductWorkspaceToolbar.vue` | 图表设置增加 EMA21 按钮 |
| `chart.vue` | 传 ribbon prop；`data-subing-ema-ribbon` |

## Error / edge handling

- overlay 不支持或非苏冰：primitive 空数据，不报错。
- 不足 21 根：bands 为空。
- 用户同时打开可选 EMA10/21：单色线叠在线带边上，可接受。

## Testing

- Unit：逐 bar band、交叉 splitT 无假时间、暖身为空。
- Unit：苏冰默认可见指标 `[]`；可选含 ema_21。
- Unit：ribbon 开启时 hover 含 EMA10/21。
- E2E：默认 ribbon=true 且无强制 ema_21；设置含默认关闭的 EMA21。
