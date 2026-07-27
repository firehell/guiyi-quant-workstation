# WEB-MARKET-UX-001：十字光标与当前 K 数据联动

生成时间：2026-07-14

状态：`GATE_PASSED`

## 目标

修复品种行情详情页 K 线图基础交互：

- 主图十字光标自由移动，不被程序固定到收盘价。
- 顶部 hover 数据按当前图表时间键更新 OHLCV、持仓量和已启用 C2 主图指标。
- 鼠标离开图表工作区后清空 hover 快照，避免保留旧 K。
- 未来空白区域不继续冒充上一根 K。
- 主图、MACD、ATR 同步垂直时间线，不把非活动图的水平线固定到某个价格。
- 主图指标使用 C2 统一 EMA ID 与后端指标响应，不恢复旧本地 `ema10/ema21/huo_tian_da_you` 图层状态。

## 允许范围

- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/utils/barTime.ts`
- `apps/quant-web/tests/barTime.test.ts`
- `docs/tasks/web-market-ux/WEB-MARKET-UX-001.md`
- `.ai/results/WEB-MARKET-UX-001/result.md`
- `tasks/current.md`

## 禁止范围

- 不修改 API、数据库、Parquet、RQData 下载、策略、指标公式、SignalEvent、Stage 9 Gate、企业微信通知和实盘相关逻辑。
- 不用前端静默去重掩盖 1d 重复 K；该问题留给 `WEB-MARKET-UX-002` 只读诊断。

## 本次修改

- `MainIndicatorId` 收口为 C2 ID：`ema_10 | ema_21 | ema_60 | htdy`。
- `HoverKlineContext.mainIndicators` 收口为 `MainIndicatorValue[]`，保留 `cursorPrice?: number | null`。
- 恢复 C2 `mainIndicators.ts` registry、偏好 helper、请求参数构造、响应 normalize 和 latest value helper。
- `KlineChart.vue` 改为由 `props.mainIndicators + props.mainIndicatorSeries` 驱动主图 EMA overlay。
- 移除组件内部旧 localStorage 主图指标状态，不恢复火天大有本地公式；`htdy` 保持 disabled / observation-only 后置。
- hover lookup 改用 Lightweight Charts 实际 `Time` 键；intraday 用 chart timestamp，daily/weekly 用交易日 key。
- 主图和副图均使用 `CrosshairMode.Normal`；跨图同步只保留自定义竖线。
- 未来空白区域清空 hover，不回落最近 K。
- `mouseleave` 和 chart 内部 `!time && !point` 分支均清空 hover。
- MACD/ATR 副图在缺少 `param.time` 时使用对应 chart 的 `coordinateToTime()` 反查时间，再联动主图 hover。
- `market/chart.vue` 补齐 C2 helper imports，十字线快照改读 `HoverKlineContext.mainIndicators[]`，并接回主图偏好保存 watcher。
- `quality` prop 接受 historical/live 两种只读 shape。

## 测试与验证

通过：

```bash
node --test apps/quant-web/tests/mainIndicators.test.ts
node --test apps/quant-web/tests/barTime.test.ts
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
```

通过：

```bash
API_BASE_URL=http://127.0.0.1:8010 WEB_BASE_URL=http://127.0.0.1:5174 ./scripts/dev-healthcheck.sh --no-start --allow-degraded
```

说明：本机 `8000/5173` 被 `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` 常驻 runtime 占用并自动重启，当前 worktree smoke 使用等价替代端口：

- API：`http://127.0.0.1:8010`
- Web：`http://127.0.0.1:5174`

Playwright smoke 页面：

```text
http://127.0.0.1:5174/market/chart?symbol=jm&contract=JM2609&period=15m
```

覆盖结果：

- `15m` 首屏：`rqdata / primary / passed`，EMA21、MACD、ATR 均显示。
- 主图 hover：hover strip 与右侧十字线快照按当前 K 更新，含持仓、EMA21、MACD、ATR。
- 未来空白区：清空为提示文案，不显示旧 K。
- 鼠标离开：清空 hover strip 与右侧十字线快照。
- MACD 区域移动：联动到对应 K，右侧十字线快照更新 EMA21/MACD/ATR。
- 缩放、平移：无 console warning/error，hover 可继续更新。
- 周期切换：`1m / 15m / 1d / 1w` 均返回 200，页面显示质量 `passed`。

截图目录：

```text
output/playwright/web-market-ux/WEB-MARKET-UX-001/
```

关键截图：

- `current-15m-initial.png`
- `current-15m-hover-main.png`
- `current-15m-hover-future-blank.png`
- `current-15m-mouse-leave.png`
- `current-15m-main-to-macd-hover-loaded.png`
- `current-15m-after-zoom.png`
- `current-15m-after-pan.png`
- `current-period-1m.png`
- `current-period-15m.png`
- `current-period-1d.png`
- `current-period-1w.png`

## Gate 结论

```text
WEB-MARKET-UX-001 GATE_PASSED
```

A01 build、测试、healthcheck、Playwright 交互 smoke 均已通过。可以进入 `WEB-MARKET-UX-002` 的 `1d` 重复 K 只读诊断。
