# 归一量化稳定产品面

更新时间：2026-09-03

归一量化是本地、单用户的国内期货研究工作站。稳定闭环是可信行情、Market Web、通用指标、HTDY/苏冰研究观察、Alert 与人工判断；不做自动交易、实盘下单、账户/委托/持仓管理、SaaS、多用户权限或 AI 自动晋升。所有图表和通知都是研究观察，`auto_order=false`。

## Market Web

- 唯一 Web 产品为 Market，route 仅 `/market` 与 `/market/chart`。
- Market 首页以三个 O(1) bulk、只读资源展示 Runtime health、active completed D1/W1 generic overview 与当前 immutable Alert Events；浏览器不按品种请求、不重算指标或策略。人工点击品种或 Event 后进入 `/market/chart` 复核。
- 首页的红/橙/绿/蓝/灰图标仅表达冻结的 completed-period/数据状态，不表达策略、持仓、买卖建议、订单或交易结果。
- 主图 Overlay 仅 `none | htdy`；SuBing 只显示 Event-backed `S↑/S↓` marker，不新增 overlay。图表设置保留通用 EMA、MACD、Range Detector 与合约控制。
- Web 不显示策略建仓、清仓、持仓、全历史策略效果或已退役策略事件。

## 指标

- EMA、MACD、ATR 与 Range Detector 是通用指标，不拥有策略、下单或 Alert 语义。
- EMA21 斜率只保留 10K primitive：输入恰好 10 个 EMA21 值，以首尾差除以 9 个 bar interval，再除以当前 EMA21，输出 bps/bar。
- 不保留 Daily Watch 大方向过滤，也不保留 5m/15m 正式因子。
- Range Detector 只允许 `range_detector_readonly_display`，不能作为正式策略、Alert 或 Runtime 输入。

## HTDY 与 Alert

HTDY 是 observation-only/repainting 产品，能力覆盖七个正式周期 `1m/5m/15m/30m/60m/1d/1w`。稳定 Rule code 为 `htdy_original_15m`，唯一 Scope authority 是 `scope_product_frequencies` 的 symbol × frequency。

持久 HTDY `AlertEvent` 是 forward-only first-seen 事实，只接受触发窗口的最新 completed Bar。repaint zone 中的历史 Bar 只供 Web retrospective 研究展示，不创建 Event 或通知。Event 创建后不可变，不因后续重绘消失、重现或方向变化而改写或重发。

苏冰预警是新的 observation-only 产品，身份固定为 `subing_ths_alert_15m_v1`，公式身份固定为 `subing_ths_15m_v3`。它只消费 operational Scope 内的 completed actual_dominant 15m，并按 MACD(12,26,9) exact CROSS 与 `EMA(CLOSE, 21)` 判定多头/空头预警；EMA 使用 `sma_window` seed。v3 不改变数学公式，只冻结 RQData 首分钟 session 锚点修正后的正式 Bar、时间与 Candidate。warm-up 与递归状态只在同一物理主力合约内延续，换月重新构建。零轴、Range、量能/OI、ATR、EMA 斜率与多周期共振都不是 V1 Gate。

苏冰持久 Event 使用 `exact` identity：同一 Rule、symbol、frequency、bar_end 的事实完全一致才幂等，冲突 fail-closed。Web 和通知只消费 Event，不复制公式；Event-backed `S↑/S↓` 不拥有 Overlay 或订单语义。

Alert 是独立 Application Domain。0043 删除旧策略 Rule/Event 与专用列，0044 只增加 disabled + empty-scope 的新 SuBing Rule，0045 只规范化 RQData session 排他起点。HTDY 使用 `first_seen`，SuBing 使用 `exact`；两者均先提交 Event，随后最多一次 transport，无 retry、queue、replay、backfill、fallback 或订单路径。provider accepted 不等于送达。通用 Scope 写入拒绝 disabled Rule；首次 SuBing Scope/enable 只走专用原子 seam，且要求精确 0045，真实 apply 仍是外部 Gate。

## 数据与稳定入口

```text
RQData -> staging + hard validation -> Canonical Parquet
       -> 八表 Catalog + MainContractMap -> MarketDataService
       -> Market Web / indicators / HTDY + SuBing observation
```

- RQData 是唯一外部行情事实源，Canonical Parquet 是唯一 active Historical Bar 存储，PostgreSQL 不存 Bar。
- RQData `1m` session 首根时间是首根 `bar_end`；adapter 必须先减一分钟，将其规范化为统一 `(start, end]` 的排他 start。Canonical 仍只有一个 V2 当前事实，不并行创建 data-version。
- `active_products.txt` 定义研究能力；`operational_products.txt` 定义持续 Runtime 授权。即使内容相同也不合并。
- 物理 Dataset 只有 `continuous` 与 `contract`；`actual_dominant` 只通过 `MainContractMap rank=1` 有效区间拼接。
- `MarketDataService` 是 Historical consumer 的唯一入口；Redis Live 只承载当日 observation，不能提升为 Canonical。
- 同物理 contract 的上市有效期内真实 warm-up Bar 可与 rank1 required Bar 共存；它不改变 actual-dominant owner，且任何越界/非 session Bar 都 fail-closed。唯一维护入口是 hash-locked `data contract-warmup`：dry-run 只读，真实 RQData/Canonical apply 仍需 exact plan hash 的单次授权。

稳定 HTTP 面为 `/api/v1/market/*`、`/api/alerts/*` 与只读 `/api/runtime/*`。统一 CLI 为 `uv run --project services/quant-api guiyi`，active domain 仅 `data` 与 `runtime`。

## Retired surface

全部既有策略域（包括 `subing_strategy_v1` 及其 Daily Watch、5m/15m 因子、Historical Projection、Current State、Formal Event、Runtime、Scope、CLI、API、Web 和派生 cache）均退出 active 产品面。新 SuBing Alert 是新身份、新合同和新版本，不恢复或复用旧策略实现。旧身份只允许存在于不可变 Git/Alembic lineage、0043 删除迁移的断言和 `STATUS.md` 的真实未迁移生产事实中。

Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、N Structure、Multi-Candidate Robustness、RQAlpha 与 Execution Review 同样不属于 active 产品、API、CLI、Web 或 Runtime。
