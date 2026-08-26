# 归一量化项目事实源

更新时间：2026-08-26

## 稳定产品边界

归一量化是本地、单用户的国内期货研究工作站：可信行情、Market Web、研究观察与 Alert 构成当前闭环。它不做自动交易、实盘下单、账户/委托/持仓管理、SaaS 或 AI 自动晋升；所有信号和通知均为研究观察，`auto_order=false`。

SuBing 是一个 SuBing 产品，向用户投影三种不能互相替代的内部事实：Daily Context（盘后 immutable artifact，回答“今天看什么”）、Current Signal State（Canonical + completed Live current state，回答“现在是什么状态”）和 Formal Event（immutable `AlertEvent`，回答“是否需要处理”）。Daily Watch V2 的 Daily Context 只使用截至来源交易日的最近 30 根 confirmed raw rank1 stitched `actual_dominant` D1/60m Bar；换月不复权、不平移、不重置 EMA21/slope，固定身份为 `subing_daily_watch_v2 + subing_ema21_rank1_stitched_raw_v2 + rank1_stitched_raw`，artifact 只写校验后 base 根的 `v2/` namespace。base 根中的 V1 字节保持不变且 active API/Store 不回退 V1；只有整个 stitched 历史仍不足 30 根或存在真实来源日、rank1、数据身份、metadata 缺口时才 typed unavailable。三类事实由同一权威 Factor/Signal/Lifecycle 逻辑服务，不合并为 mega endpoint、表或 DTO；SuBing Alert Scope 保持 product-level `scope_products`，所有 Daily Watch 结果仍是 research-only observation，不进入订单路径。

SuBing Strategy V1 Stage 1 是与上述三类当前事实分离的 Historical Strategy Projection：只支持 active 单品种 `actual_dominant + 15m + since/through`，在每个 rank1 物理合约段内从真实段起点复算 Factor/Lifecycle/Strategy。四种 `ENTRY_CONFIRMED` 来源均可按 Daily Watch V2 上一共同交易日 D1/60m 方向建仓；普通动作在下一根同物理合约 15m Bar open 模拟生效，只有 EMA21、上一根 15m 极值、绑定 Pivot 和 MACD 高低位反向交叉四类退出。绑定 Pivot 是 Lifecycle 在唯一 `ENTRY_CONFIRMED` 冻结的同交易日、同物理段、严格早于确认边界的最新 5m `ConfirmedPivot`（多头 LOW、空头 HIGH）；既有多头 HIGH / 空头 LOW Pivot 只保留为突破、回踩和 risk 的 trigger，不得冒充保护性绑定来源。缺少绑定 Pivot 不阻止建仓，只禁用该 Episode 的结构退出。不加减仓、不反手、不做同 Bar 重建仓、不跨物理段；只有请求覆盖到权威段末时才以旧段最后一根 15m close 清仓，普通 `through` 不冒充 terminal。Action/Episode 、“参考变动”与 Web Marker/记录都是历史因果投影和模拟动作，非实际成交；缓存只能位于校验后 observation base 的 `cache/subing-strategy-v1/`，可删除、非权威且失败不得改变结果。该能力不创建账户、订单、保证金、费用/滑点、资金曲线、通用回测平台、Alert Rule 或 Stage 2 completed-Live。

HTDY 是 observation-only/repainting 的全周期产品：operational universe × 七个正式周期 `1m/5m/15m/30m/60m/1d/1w`。稳定 Rule code 保持 `htdy_original_15m`；HTDY 唯一 Scope authority 为 `scope_product_frequencies` 的 symbol × frequency，SuBing 唯一 Scope authority 为 `scope_products`。HTDY storage identity 为 `(rule_id, symbol, frequency, bar_end)`，SuBing 的业务 Event identity 保持 `rule_id + symbol + bar_end`。日内只消费同周期 completed Live Bar；D1/W1 只由 `market:state(reason=canonical_updated)` 触发并读取 Canonical，不增加 scheduler、replay 或 backfill。

Market 主图只保留：`无 | 苏冰 | 日进斗金参考回放 | 火天大有`。N Structure 与 raw JDJ Candidate 只保留在内部研究面；N Structure 仅额外提供可选的 `actual_dominant + 5m` Historical Canonical completed-N range-band 投影：形成区为 N1 pivot 到严格完成点，完成后沿同一 N1-N2 price span 向右观察至既有 N2-origin break、rank1 segment 边界或当前 Canonical 边界。该投影可与四项主图 Overlay 组合显示，但不是第五个 Overlay、独立策略产品、Alert、Live 或 Runtime evaluator。JDJ reference replay 是 active-universe 单品种 `actual_dominant + 1m` 的 deterministic、read-only reference action/fill；SuBing Overlay 在 15m 请求上另显示后端投影的 Strategy Action Marker 和完整相交 Episode 记录，前端不计算策略公式或参考变动。两者都不进入 DB、Redis、Alert、Runtime 或订单。

Market Radar 的 Summary、Scatter、Detail 是唯一全市场研究入口。Attention、Trend Focus、Main Force Mirror、Five-Candidate Dossier/Relationships 都不是 active 产品、API、CLI、Web、protocol 或 report。Generic Robustness relationship metrics 与 pending prospective OOS 保留；Alembic migration history 与 `futures_member_ranks` table identity 作为历史/schema 事实保留，但没有 active rank reader、builder、provider 或 CLI。

RQAlpha 与 Execution Review 已退出 active 产品面、源码和接口；历史 migration 只保留 schema lineage。未来如需回测或人工执行复盘，必须作为新任务重新定义当前 consumer、事实合同和数据边界，不恢复旧模块。

## 稳定数据边界

```text
RQData -> staging + hard validation -> Canonical Parquet
       -> 八表 Catalog + MainContractMap -> MarketDataService
       -> Market Web / indicators / read-only research
```

- RQData 是唯一外部行情事实源；Canonical Parquet 是唯一 active Historical Bar 存储；PostgreSQL 不存 Bar。
- active universe 唯一入口为 `data/universe/active_products.txt`；物理 Dataset 只有 `continuous` 与 `contract`，`actual_dominant` 查询时按 rank1 有效区间拼接。
- `MarketDataService` 是 Historical consumer 的唯一入口；不得 glob、自选 active、自判主力、绕过质量或跨频回退。
- Redis Live 仅为当日 observation，不能提升为 Canonical。
- `alert_rules` / `alert_events` 是独立 Application Domain，不改变八表 Catalog；历史 `trade_*` migration 不构成 active schema 或 consumer。

## 稳定接口与 CLI

Web 只保留 Market：`/market` 与 `/market/chart`。主 HTTP 面为 `/api/v1/market/*`、`/api/alerts/*` 与只读 `/api/runtime/*`。

只读 Research CLI 精确为：

- `guiyi research subing-calibration`
- `guiyi research subing-lifecycle`
- `guiyi research n-structure`
- `guiyi research jdj-1m`
- `guiyi research candidate-validation`
- `guiyi research candidate-robustness`

Candidate Validation/Robustness 保持 source-specific causality、strict-before、embargo 与 prospective OOS 分离；retrospective 不回填 OOS，不生成 rank、winner、promotion、盈利或可交易结论。Historical overlay 只通过现有 confirmed Canonical 接口投影，Web 不复制公式。

## Alert

Alert 只含 `htdy_original_15m` 与 `subing_entry_signal_v1` 两个 Rule code，且仍只有 `alert_rules`、`alert_events` 两张表。Event 先提交，随后最多一次 transport；无逐收件人状态、retry、queue、replay、backfill、fallback 或订单路径。provider accepted 不等于送达。

## 外部操作与文档职责

真实 RQData、Canonical、生产 DB、Runtime/live、通知、release/tag 与 Scope/transport 变更都需要范围明确的一次性执行意图。当前 release、Runtime、Scope、evidence 与 Gate 只看 `STATUS.md`。

| 文件 | 职责 |
|---|---|
| `STATUS.md` | 当前 release、Runtime、evidence 与 pending Gate |
| `DECISIONS.md` | 长期决策与理由 |
| `docs/ARCHITECTURE.md` | active 模块依赖 |
| `docs/DATA_CENTER.md` | Canonical 数据合同 |
| `TESTING.md` | 当前可执行验证命令 |
