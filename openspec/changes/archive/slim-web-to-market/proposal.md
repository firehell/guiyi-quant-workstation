## Why

项目需要从「多模块研究工作站」收缩为可快速浏览 69 品种历史行情的精简观察面，以便从干净基线重新搭建策略/信号等能力。当前 Web 仍挂着今日工作台、信号、策略、复盘、数据中心、运行状态等入口，干扰专注看盘。

## What Changes

- **BREAKING**: Web 侧栏与路由只保留 Market 工作台（列表 + K 线）；删除今日工作台、信号监控、策略中心、复盘中心、数据中心、运行状态页面与顶栏相关入口；默认首页改为 `/market`。
- **BREAKING**: 卸掉信号/策略/dashboard/复盘的 HTTP API、`/ws/signals`，以及 signal/notification RQ worker 可执行面。
- Market K 线页去掉右栏信号/复盘/运行、信号层/marker、FuturesResearch 实验面板；保留 EMA10/21/60、火天大有、MACD 与看行情必需控件。
- 保留 `/api/v1/market`、`/api/v1/data`、`/api/runtime` 与 CLI；不 drop DB 表；不删 quant-core 策略研究源码。
- 更新 `STATUS.md` 等模块真相描述。

## Capabilities

### New Capabilities

- `market-only-web`: Web 仅提供 Market 历史行情观察面（69 品种列表 + K 线 + 约定指标），不含策略/信号/复盘等入口。
- `retired-research-surfaces`: 策略/信号/dashboard/复盘 Web 与对应 API/worker/WS 可执行面退役（DB 与策略源码保留）。

### Modified Capabilities

- （无既有 `openspec/specs/` 能力需 delta；本变更为新建能力合同。）

## Impact

- 前端：`apps/quant-web` 路由/布局/页面/API 客户端与相关测试大幅收缩。
- 后端：`services/quant-api` 取消注册 signals/strategies/dashboard/reviews/WS；worker 停挂 signal/notification；market/data/runtime 保留。
- 文档：`STATUS.md` 及仍宣称旧 Web 入口存在的导航表述。
- 不涉及生产 DB 写入、Runtime promotion、通知开启或自动交易。
