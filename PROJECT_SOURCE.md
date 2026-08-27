# 归一量化稳定产品面

更新时间：2026-08-27

归一量化是本地、单用户的国内期货研究工作站。稳定闭环是可信行情、Market Web、研究观察、Alert 与人工判断；不做自动交易、实盘下单、账户/委托/持仓管理、SaaS、多用户权限或 AI 自动晋升。所有信号、图表和通知都是研究观察，`auto_order=false`。

## Market Web

- 唯一 Web 产品为 Market，route 仅 `/market` 与 `/market/chart`。
- Market Radar 的 Summary、Scatter、Detail 是唯一全市场研究入口。
- 主图 Overlay 仅 `none | subing | htdy`。

## SuBing

SuBing 是一个产品，保留三种不可互相替代的事实：

- Daily Context：盘后 immutable artifact，回答“今天看什么”；
- Current Signal State：Canonical 与 completed Live 的当前状态，回答“现在是什么状态”；
- Formal Event：immutable `AlertEvent`，回答“是否需要处理”。

三类事实共享权威 Factor、Signal、Calibration、Lifecycle 与 policy，但不合并成 mega endpoint、表或 DTO。SuBing Alert 的唯一授权面是 product-level `scope_products`。

SuBing Strategy V1 的 Stage 1 Historical Projection 与 Stage 2 completed-Live evaluator 共享唯一增量状态机。公开身份始终为 active universe 中单品种 `actual_dominant + 15m`；1m/5m 仅为内部权威输入。Historical 从每个 rank1 物理段起点确定性复算 Daily Context、Factor、Lifecycle、Strategy Action 与 Episode；普通动作只在下一实际同物理合约 15m 区间第一根 completed 1m 的 open 生效。退出仅来自 EMA21、上一根 15m 极值、绑定 Pivot 与 MACD 高低位反向交叉。不加减仓、不反手、不跨物理段、不在同 Bar 重建仓；只有覆盖权威段末时才以旧段最后一根 15m close 清仓。

Stage 2 代码为 active60 在内存恢复和维护相互隔离的策略状态，计算范围独立于 Alert Scope；`scope_products` 只控制 immutable Strategy Action Event 与 owner one-shot PushPlus。启动恢复/catch-up 不补 Event、不补通知；Current Strategy 从 Canonical + completed Live 只读重建，不以 AlertEvent 作为仓位权威。该代码已随 `v1.8.7` release，尚未 Runtime promotion，不改变当前 production Runtime。

## 保留研究能力

- SuBing Candidate Validation 保留 source-specific causality、strict-before、embargo、prefix invariance、golden parity 与 prospective OOS 分离；retrospective 不生成自动 rank、winner、promotion、盈利或可交易结论。

## HTDY 与 Alert

HTDY 是 observation-only/repainting 产品，能力覆盖七个正式周期 `1m/5m/15m/30m/60m/1d/1w`。稳定 Rule code 为 `htdy_original_15m`，唯一 Scope authority 是 `scope_product_frequencies` 的 symbol × frequency；新 SuBing 代码唯一 Rule code 为 `subing_strategy_v1`，唯一 Scope authority 是 `scope_products`。Migration `20260826_0042` 以 forward-only 原子步骤删除旧 SuBing Event、保留旧 Rule row 的 `id/enabled/scope_products` 并将 `subing_entry_signal_v1` 直接替换为 `subing_strategy_v1`；不保留 archive、双 Rule、兼容 reader、replay 或 downgrade。0042 尚未在 production 执行，因此当前 production Rule 身份仍以 `STATUS.md` 为准。两种 Scope 不混用、不合并。

Alert 是独立 Application Domain，只含 `alert_rules` 与 `alert_events` 两张表。Event 先提交，随后最多一次 transport；无逐收件人状态、retry、queue、replay、backfill、fallback 或订单路径。provider accepted 不等于送达。

## 数据与稳定入口

```text
RQData -> staging + hard validation -> Canonical Parquet
       -> 八表 Catalog + MainContractMap -> MarketDataService
       -> Market Web / indicators / read-only research
```

- RQData 是唯一外部行情事实源，Canonical Parquet 是唯一 active Historical Bar 存储，PostgreSQL 不存 Bar。
- active research universe 由 `data/universe/active_products.txt` 定义；持续 Runtime 授权由 `data/universe/operational_products.txt` 定义。即使内容相同，两者也不合并。
- 物理 Dataset 只有 `continuous` 与 `contract`；`actual_dominant` 是按 `MainContractMap rank=1` 有效区间拼接的查询模式。
- `MarketDataService` 是 Historical consumer 的唯一入口；Redis Live 只承载当日 observation，不能提升为 Canonical。

稳定 HTTP 面为 `/api/v1/market/*`、`/api/alerts/*` 与只读 `/api/runtime/*`。统一 CLI 为 `uv run --project services/quant-api guiyi`；research 子命令仅保留 `subing-calibration`、`subing-lifecycle`。

## Retired surface

Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、N Structure、专用于 SuBing↔N 的 Multi-Candidate Robustness、RQAlpha 与 Execution Review 均不属于 active 产品、API、CLI、Web 或 Runtime。Alembic history 与 Git history 只保留 lineage；恢复任何退役能力必须由新任务重新定义 consumer、formula、value、evidence、事实合同与数据边界，不能直接恢复旧模块。
