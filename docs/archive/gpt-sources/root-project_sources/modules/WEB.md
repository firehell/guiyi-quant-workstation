# Web

更新时间：2026-07-14

事实来源：`docs/ARCHITECTURE.md`、`apps/quant-web/src/app/router.ts`

当前状态：current，部分 UI/性能后置 Gate 未完成。

## 当前路由

- Dashboard
- Data
- Market
- Market Chart
- Strategy
- Backtest
- Backtest Batch
- Signal
- Runtime
- Review
- Settings

## 当前功能

- K 线工作台读取 active primary 数据。
- Market 支持周期切换、主图指标、标记和 linked report/signal/review 入口。
- Backtest 展示报告、曲线、trade/order、marker。
- Signal 展示信号与事件。
- Runtime 展示只读健康状态。
- Review 支持复盘 note 与附件入口。

## 边界

Web 页面是研究和观察界面，不是交易终端。页面展示 passed / warning / blocked 状态不等于授权交易、发送或 runtime ready。

