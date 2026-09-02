# 归一量化稳定产品面

更新时间：2026-09-02

归一量化是本地、单用户的国内期货研究工作站。稳定闭环是可信行情、Market Web、通用指标、HTDY 研究观察、Alert 与人工判断；不做自动交易、实盘下单、账户/委托/持仓管理、SaaS、多用户权限或 AI 自动晋升。所有图表和通知都是研究观察，`auto_order=false`。

## Market Web

- 唯一 Web 产品为 Market，route 仅 `/market` 与 `/market/chart`。
- Market 首页以三个 O(1) bulk、只读资源展示 Runtime health、active completed D1/W1 generic overview 与当前 immutable HTDY Event；浏览器不按品种请求、不重算指标或策略。人工点击品种或 Event 后进入 `/market/chart` 复核。
- 首页的红/橙/绿/蓝/灰图标仅表达冻结的 completed-period/数据状态，不表达策略、持仓、买卖建议、订单或交易结果。
- 主图 Overlay 仅 `none | htdy`；图表设置保留通用 EMA、MACD、Range Detector 与合约控制。
- Web 不显示策略建仓、清仓、持仓、全历史策略效果或已退役策略事件。

## 指标

- EMA、MACD、ATR 与 Range Detector 是通用指标，不拥有策略、下单或 Alert 语义。
- EMA21 斜率只保留 10K primitive：输入恰好 10 个 EMA21 值，以首尾差除以 9 个 bar interval，再除以当前 EMA21，输出 bps/bar。
- 不保留 Daily Watch 大方向过滤，也不保留 5m/15m 正式因子。
- Range Detector 只允许 `range_detector_readonly_display`，不能作为正式策略、Alert 或 Runtime 输入。

## HTDY 与 Alert

HTDY 是 observation-only/repainting 产品，能力覆盖七个正式周期 `1m/5m/15m/30m/60m/1d/1w`。稳定 Rule code 为 `htdy_original_15m`，唯一 Scope authority 是 `scope_product_frequencies` 的 symbol × frequency。

持久 HTDY `AlertEvent` 是 forward-only first-seen 事实，只接受触发窗口的最新 completed Bar。repaint zone 中的历史 Bar 只供 Web retrospective 研究展示，不创建 Event 或通知。Event 创建后不可变，不因后续重绘消失、重现或方向变化而改写或重发。

Alert 是独立 Application Domain。0043 之后 schema 只保留 HTDY 所需 Rule/Event 字段；Event 先提交，随后最多一次 transport，无 retry、queue、replay、backfill、fallback 或订单路径。provider accepted 不等于送达。

## 数据与稳定入口

```text
RQData -> staging + hard validation -> Canonical Parquet
       -> 八表 Catalog + MainContractMap -> MarketDataService
       -> Market Web / indicators / HTDY observation
```

- RQData 是唯一外部行情事实源，Canonical Parquet 是唯一 active Historical Bar 存储，PostgreSQL 不存 Bar。
- `active_products.txt` 定义研究能力；`operational_products.txt` 定义持续 Runtime 授权。即使内容相同也不合并。
- 物理 Dataset 只有 `continuous` 与 `contract`；`actual_dominant` 只通过 `MainContractMap rank=1` 有效区间拼接。
- `MarketDataService` 是 Historical consumer 的唯一入口；Redis Live 只承载当日 observation，不能提升为 Canonical。

稳定 HTTP 面为 `/api/v1/market/*`、`/api/alerts/*` 与只读 `/api/runtime/*`。统一 CLI 为 `uv run --project services/quant-api guiyi`，active domain 仅 `data` 与 `runtime`。

## Retired surface

全部既有策略域（包括其 Daily Watch、5m/15m 因子、Historical Projection、Current State、Formal Event、Runtime、Scope、CLI、API、Web 和派生 cache）均退出 active 产品面。旧身份只允许存在于不可变 Git/Alembic lineage 和 0043 删除迁移的断言中。未来策略必须定义新身份、新合同与新版本，不能直接恢复旧模块或旧数据。

Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、N Structure、Multi-Candidate Robustness、RQAlpha 与 Execution Review 同样不属于 active 产品、API、CLI、Web 或 Runtime。
