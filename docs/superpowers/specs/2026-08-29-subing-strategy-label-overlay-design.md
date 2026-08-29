# SuBing Strategy HTML Label Overlay

Date: 2026-08-29  
Status: draft for review  
Scope: Market chart (`apps/quant-web`) only

## Goal

苏冰策略历史动作标记改为参考图风格的浅底描边小标签（HTML 浮层），文案仍为「建多 / 建空 / 清多 / 清空」。拖动与缩放时按可见区动态避让重叠；下方放不下时翻到上方。

## Non-goals

- 不改策略语义、不改参考价/参考变动计算、标签不展示价格或百分比。
- 不改火天大有观察/Alert marker；HTDY 仍用内置 `createSeriesMarkers`。
- 不引入第二套图表库或服务端渲染。
- 不恢复已退役产品面。

## Current state

- `subingStrategyActionToMarker` 产出 `KlineMarker`（label + position + shape + tone）。
- `KlineChart` 把 `researchMarkers` 与 HTDY/Alert markers 合并后交给 `createSeriesMarkers`。
- 内置 marker 仅支持 circle/square/arrowUp/arrowDown + 纯文字，无法实现浅底描边框与引线。

## Approved decisions

1. 文案：方案 A（只改外观，保留「建多 / 建空 / 清多 / 清空」；去掉 ▲▼× 符号）。
2. 渲染：方案 1（HTML 浮层 + 坐标同步）。
3. 布局：重叠则同侧上下错开；默认侧空间不足（尤其下方）则翻到对侧；随拖动/缩放重算。

## Architecture

```text
researchMarkers (SuBing only ids: historical:*)
  -> layoutSubingStrategyLabels(bars, markers, viewport)
  -> HTML overlay in KlineChart (.kline-strategy-labels)
HTDY derived + alert markers
  -> createSeriesMarkers (unchanged path, SuBing excluded)
```

### Components

| Unit | Responsibility |
|------|----------------|
| `utils/subingStrategyLabels.ts`（新） | 纯函数：过滤苏冰标记、量测框尺寸、默认侧、碰撞避让、翻侧、输出像素布局 |
| `KlineChart.vue` | 订阅可见范围/resize/数据变更；坐标换算；渲染 HTML 标签层；series markers 不再画苏冰 |
| `historicalResearchMarkers.ts` | 仅调整 label 文案去掉符号；tooltip/tone/position 语义不变 |

### Data flow

1. `chart.vue` 继续传入完整 `researchMarkers`（苏冰）。
2. `KlineChart` 在 `mergedDisplayMarkers()` 中排除 `id` 以 `historical:` 开头（或显式 `tone`/`source` 合同）的苏冰策略标记，只把剩余交给 `createSeriesMarkers`。
3. 对苏冰标记：用 `timeScale.timeToCoordinate` + candle `high`/`low` 的 `priceToCoordinate` 得锚点；默认侧沿用现有 position（开多 below、开空 above、清多 above、清空 below）。
4. `layoutSubingStrategyLabels` 输出 `{ id, left, top, side, label, leaderY }`；模板用绝对定位渲染标签与短引线。
5. Overlay：`pointer-events: none`；既有 crosshair / hover legend 仍读 marker tooltip 事实，不依赖 HTML 命中。

## Layout algorithm

输入：可见逻辑范围内的苏冰标记、每个标签的固定估算宽高（或一次性 offscreen 量测）、主图 pane 像素矩形。

1. **默认锚点**：`x = timeToCoordinate(barTime)`；`yAnchor = above ? highY : lowY`；标签中心水平对齐 `x`。
2. **初始放置**：标签底边（above）或顶边（below）距影线端点固定 gap；画竖直短引线。
3. **同侧碰撞**：按 `x` 聚类（像素距离小于标签半宽之和视为同列/邻近）；组内按时间序竖直堆叠，间距固定（约 2–4px）。
4. **翻侧**：若堆叠后任一边超出主图 pane（或与底部 pane 交界）则整组或越界个体翻到对侧并重新堆叠；优先保证可读，不画到 volume/MACD pane。
5. **不可见**：`timeToCoordinate` / `priceToCoordinate` 为 `null` 或完全在主图外则不渲染该标签。
6. **重算触发**：`visibleLogicalRangeChange`、`ResizeObserver`、`bars` / `researchMarkers` / overlay 相关 props 更新；拖动缩放跟手（订阅回调内同步重算，可对极高频 pointer move 做 rAF 合并）。

## Visual contract

- 背景：浅奶油/近白不透明或极浅半透明。
- 边框：约 1px 深灰。
- 文字：小字、深色、无图标前缀。
- 引线：1px 深灰，连接影线端点与标签近侧边中点。
- 涨跌色不用于标签底/边（避免与参考图冲突）；方向信息保留在 tooltip / 现有 tone 合同供图例使用。

## Error / edge handling

- 无苏冰标记或坐标不可用：overlay 为空，不报错。
- 极密集标记：允许堆叠增高；仍越界则翻侧；双侧重度拥挤时裁切不可见部分，不扩展价格轴仅为标签让位（避免改动行情比例）。
- identity / overlay 切换：清空旧 DOM 节点后再布局。

## Testing

- Unit：`layoutSubingStrategyLabels` — 无重叠保持默认侧；重叠上下错开；下方越界翻上；不可见坐标丢弃。
- Unit/contract：`mergedDisplayMarkers` / chart 路径 — 苏冰不进入 `createSeriesMarkers`；HTDY/Alert 仍进入。
- Unit：label 文案为「建多」等，无 ▲▼×。
- 手工：Vite dev 下焦煤 15m 苏冰，拖动/缩放确认跟手避让；切换火天大有确认 HTML 层为空且内置观察 marker 正常。

## Out of scope follow-ups

- 标签展示参考价/参考变动%。
- 把 HTDY 也改成同款 HTML 标签。
