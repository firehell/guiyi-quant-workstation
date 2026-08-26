---
name: quant-frontend
description: Use when 任务涉及归一量化 Vue 3、Vite、TypeScript、Naive UI、Market K线、Lightweight Charts、WebSocket、布局、浏览器错误或前端测试。
---

# 归一量化前端与 K 线工作台

## Current surface

- 路由只保留 `/market`、`/market/chart`。
- 主图 Overlay 精确为 `none | subing | htdy`。
- N 字区间是独立、默认关闭的 `actual_dominant + 5m` Historical 投影，不是第五个 Overlay。
- Market 展示 Canonical 历史、允许范围内的 Redis Live observation、server-side Alert Scope 和
  persistent Event。

已退役 Dashboard、数据中心、策略中心、旧信号/Review Center、RQAlpha、Execution Review 不得恢复。

## 实现边界

- Vue 3/Vite/TypeScript/Naive UI；不引入 Next.js、登录、多用户权限或第二套状态框架。
- 前端不直连数据库、不选 Canonical 文件、不判断主力、不复制后端策略公式。
- 行情 identity、Historical/Live seam、generation、分页和重连由
  `composables/useMarketSeries.ts` 及 `src/types/market.ts` 的 Market contracts 管理；图表渲染由
  `components/kline/KlineChart.vue` 管理。
- WebSocket URL 由 `utils/network.ts` 解析，配置入口是 `VITE_MARKET_WS_URL`；只在证据指向服务端
  握手、close code 或 upstream 后再转 `services/quant-api/app/api/market_live.py` 排查。当前前端
  seam 不持久化 close event 的 code/reason，必须从浏览器 Network/WS 留证，不得从重连现象猜测。
- Alert Scope 只认 server API；persistent Event 与会重绘的 HTDY marker 必须保持独立。
- DataGap、identity mismatch 和旧响应 fail-closed，不伪造 fallback 或 stale facts。

## UI 与故障处理

先在真实浏览器路径复现，记录 viewport、Console、Network/WS 和当前 identity；再判断 owner 是 API、
socket lifecycle、数据 normalization、图表容器/生命周期还是样式。做最小根因修复，不以组件重写
掩盖 seam 问题。桌面与 Drawer 复用同一组件和 props 合同。

页面保持深蓝品牌 Shell、浅色研究区、中国期货红涨绿跌和明确 unavailable 状态。

## 验证

先运行覆盖改动的 unit 或 Playwright 场景；图表、WebSocket 或布局问题需浏览器复现验证。再按风险
扩展完整 Web unit、Playwright 和 build，命令以 `TESTING.md` 为准。
