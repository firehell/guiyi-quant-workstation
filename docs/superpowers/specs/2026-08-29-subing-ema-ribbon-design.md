# SuBing EMA10/21 Ribbon V2 — Per-Bar Columns

Date: 2026-08-29  
Updated: 2026-08-30  
Status: approved for implementation  
Scope: Market chart (`apps/quant-web`) only

## Goal

选择苏冰 overlay 且能力成立时，主图继续默认显示 EMA10（快）与 EMA21（慢）的黄蓝趋势带，但将当前“相邻 Bar 连续梯形填充”改成参考图一致的“每根 K 线一根独立柱”：

- EMA10 > EMA21：该 Bar 的柱填充浅黄。
- EMA10 < EMA21：该 Bar 的柱填充浅蓝。
- EMA10 边界线始终为黄色；EMA21 边界线始终为蓝色。
- 柱中心与对应 K 线中心一致，柱宽随图表缩放变化，并与 K 线实体保持同一视觉宽度等级。
- 相邻柱之间必须保留可见间隙，不形成连续 Area Fill。

本 V2 只替换 V1 的 Ribbon 几何与配色合同；苏冰 overlay 所有其余产品行为保持不变。

## Problem with V1

当前实现将相邻两根 EMA-ready Bar 组成一个四边形：

```text
left.ema10 -> right.ema10 -> right.ema21 -> left.ema21
```

相邻四边形共边，并在 EMA10/EMA21 变号时使用 `splitT` 拆分左右颜色，因此视觉结果是连续色带。参考图的目标结构不是连续面，而是以每根 K 线为单位的独立柱。

V2 必须删除这一 interval-based geometry，不保留 legacy/compatibility 双路径。

## Non-goals

- 不改后端 EMA、苏冰 Factor / Signal / Calibration / Lifecycle 或策略公式。
- 不改 SuBing Strategy V1 的 EMA21 exit、建仓、平仓、Historical Projection 或 Episode 语义。
- 不实现参考图中的 SuperTrend/SAR 虚线或其他未纳入现有产品面的指标。
- 不给 Ribbon 增加单独开关。
- 不引入第二套图表库、HistogramSeries/AreaSeries workaround 或新 npm dependency。
- 不把 Ribbon 做成 `MainIndicatorId`。
- 不改 API、OpenSpec、Alert、Runtime、Canonical、DB 或 Redis。
- 不触及 `main`、tag、release 或 Runtime promotion。

## Existing product contract retained

```text
选苏冰 + actual_dominant + 5m/15m
  -> 始终画 EMA ribbon（与可选 EMA 开关无关）

图表设置 EMA：EMA10 / EMA21 / EMA60，默认全关
  -> 只控制已有单色 LineSeries

选火天大有 / 无
  -> 不画 ribbon；可选 EMA 偏好跨 overlay 保留
```

- EMA21 暖身未就绪的 Bar 不画 Ribbon。
- 交叉光标图例在线带开启时继续包含 EMA10、EMA21 读数，并按 id 去重。
- 用户同时打开可选 EMA10/21 时，已有 LineSeries 可叠加在 Ribbon 边界线上；无需增加去重渲染分支。

## Approved V2 decisions

1. Ribbon 仍由苏冰 overlay 拥有，继续使用 Lightweight Charts `ISeriesPrimitive`，挂在 candle series 上并保持 `zOrder=bottom`。
2. 数据模型从“相邻 Bar 的 band”改为“单 Bar 的 point”；一个 point 对应一根柱。
3. 柱填充颜色表达 bull/bear 状态；两条边界线颜色表达 EMA 身份，两者不得共用 tone 决定 stroke。
4. EMA 交叉只表现为两条边界线交叉以及相邻 Bar 柱 tone 切换；不再绘制半黄半蓝柱。
5. 不再需要 `splitT`、`crossingSplitT()`、`splitRibbonCoordinates()` 或假时间点。
6. `EMA10 == EMA21` 时只继承此前最近一个有效 tone；若此前没有有效 tone，则该 Bar 暂不画柱，不向未来 Bar 查找颜色。
7. 柱宽由当前屏幕坐标中的 Bar 间距动态计算，不使用固定像素宽度；目标宽度约为有效间距的 `0.8`，并至少留出约 `1px` 间隙。

## Data contract

```ts
export type SubingEmaRibbonTone = 'bull' | 'bear'

export interface SubingEmaRibbonPoint {
  time: string
  ema10: number
  ema21: number
  tone: SubingEmaRibbonTone
}

export interface SubingEmaRibbon {
  ema10: EmaPoint[]
  ema21: EmaPoint[]
  points: SubingEmaRibbonPoint[]
}
```

`buildSubingEmaRibbon(bars)` 仍以现有 `calculateEMA(bars, 10|21)` 为唯一浏览器侧 EMA 输入，不引入第二套计算。

生成 `points` 的规则：

```text
EMA21 not ready
  -> no point

EMA10 > EMA21
  -> tone=bull

EMA10 < EMA21
  -> tone=bear

EMA10 == EMA21 and previous tone exists
  -> inherit previous tone

EMA10 == EMA21 and no previous tone exists
  -> no point
```

删除旧模型：

- `SubingEmaRibbonBand`
- `left` / `right`
- `leftTone` / `rightTone`
- `splitT`
- `crossingSplitT()`
- `splitRibbonCoordinates()`

## Display contract

### Fill

```text
bull column fill = #FFE2A0
bear column fill = #AFCBFF
```

### Boundary lines

```text
EMA10 line = #E8B923
EMA21 line = #38BDF8
```

颜色归属是硬合同：

```text
column fill -> bull / bear
EMA10 line  -> EMA10 identity
EMA21 line  -> EMA21 identity
```

因此空头阶段也不能把 EMA10 线改成蓝色，多头阶段也不能把 EMA21 线改成黄色。

### Per-Bar geometry

对每个 `SubingEmaRibbonPoint`：

```text
x = timeScale.timeToCoordinate(time)

y10 = candleSeries.priceToCoordinate(ema10)
y21 = candleSeries.priceToCoordinate(ema21)

top    = min(y10, y21)
bottom = max(y10, y21)

column centered at x
```

一个真实 Bar 最多对应一根独立柱。柱与柱之间不得通过 polygon 连接。

### Dynamic width

Primitive 应从已投影的有效相邻 x 坐标估算当前 Bar spacing。对每个 point：

- 优先使用与前后有效 point 的较小正间距；
- 仅一侧存在时使用该侧间距；
- 没有可用邻点时不猜测固定大宽度，使用最小安全宽度。
- `columnWidth ~= spacing * 0.8`。
- `columnWidth <= spacing - 1px`。
- 可绘制最小宽度为 1px。

缩放、滚动、prepend/live update 后均由 primitive 重新投影，柱宽随当前视觉 spacing 更新。

### Render order

```text
1. draw all per-Bar columns
2. draw continuous EMA10 polyline
3. draw continuous EMA21 polyline
```

EMA polyline 只连接相邻的已投影 EMA-ready point，不制造额外业务时间点。

## Architecture

```text
selectedOverlay=subing && capability.supported
  -> showSubingEmaRibbon
  -> buildSubingEmaRibbon(bars)
       -> ema10[]
       -> ema21[]
       -> points[]
  -> SubingEmaRibbonPrimitive on candle series
       -> project points
       -> derive dynamic width
       -> draw independent columns
       -> draw EMA10/EMA21 lines

optionalEmaIndicators (ema_10 | ema_21 | ema_60)
  -> existing LineSeries
```

### Units

| Unit | Responsibility |
|---|---|
| `utils/subingEmaRibbon.ts` | 纯函数：对齐 EMA10/21，并为每个 EMA-ready Bar 生成单点 Ribbon model 与 causal tone |
| `components/kline/subingEmaRibbonPrimitive.ts` | LC primitive：屏幕投影、动态柱宽、逐 Bar 独立填充、两条固定身份边界线 |
| `klineViewModel.ts` | 保持现状：Ribbon 开启时复用同一次 EMA10/21 结果给 hover |
| `KlineChart.vue` | 保持 primitive 生命周期，只把 `.bands` 数据入口改为 `.points` |
| `tests/subingEmaRibbon.test.ts` | V2 数据合同、warm-up、tone、无 split/band 回归 |
| `e2e/market-research.spec.mjs` | 仅在现有 E2E 需要最小适配时修改，不新增生产 hook |

## Error / edge handling

- overlay 不支持或非苏冰：primitive 接收空 points，不报错。
- 不足 21 根 Bar：`points=[]`。
- `timeToCoordinate` / `priceToCoordinate` 返回 null 的 point 跳过，不影响其他 point。
- 相邻 point 的屏幕 x 无有效正间距时，使用最小安全宽度，不连接成面。
- 恰好相等的 EMA 不向未来取 tone，避免仅为视觉颜色引入 look-ahead。
- 交叉 Bar 只按该 Bar 的 EMA 相对关系着色，不绘制 `splitT` 半柱。

## Testing

### Unit

必须覆盖：

- EMA21 未 ready 时 `points=[]`。
- N 个 EMA21-ready Bar 对应 N 个可着色 points（不再是 N-1 个相邻 band）。
- EMA10 > EMA21 -> `bull`。
- EMA10 < EMA21 -> `bear`。
- EMA10 == EMA21 -> 只继承之前 tone；无之前 tone 时跳过。
- 源码中不再存在 `splitT`、`crossingSplitT`、`splitRibbonCoordinates`、`fillRibbonQuad`。
- Ribbon 开启时 hover 继续包含 EMA10/21。

### Web regression

按 `TESTING.md` 运行：

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
git diff --check
```

## Visual acceptance gate

在合入 `develop` 前必须由人工检查真实浏览器渲染，至少覆盖：

1. 连续上涨黄柱区；
2. 连续下跌蓝柱区；
3. EMA10/EMA21 黄蓝交叉区；
4. 正常、放大、缩小三种 zoom level。

全部满足：

- 一根真实 K 对应至多一根独立 Ribbon 柱；
- 柱中心与 K 线中心一致；
- 相邻柱之间存在可见间隙；
- 不存在连续 Area Fill；
- 不存在相邻 Bar 梯形连接；
- 不存在半黄半蓝柱；
- EMA10 始终黄色；
- EMA21 始终蓝色；
- 缩放后仍保持独立柱结构。

测试通过不能替代该视觉 Gate。

## Delivery boundary

本任务完成代码与测试后只允许创建 `task branch -> develop` PR，并提交视觉证据等待人工 Review。

人工视觉批准前：

- 不自动 merge `develop`；
- 不修改 `main`；
- 不创建 tag/release；
- 不做 Runtime promotion；
- 不进行真实数据、DB、Redis、Scope 或通知写入。
