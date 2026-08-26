# 架构决策记录

更新时间：2026-08-26

版本、部署、evidence 与 Gate 状态只看 `STATUS.md`；历史过程只从 Git history 追溯。

| 主题 | 长期决策 | 边界 |
|---|---|---|
| 产品 | 本地单用户期货研究工作站 | 不做自动交易、SaaS 或无人值守下单；`auto_order=false` |
| 外部操作 | 真实数据/DB/Runtime/live/通知/release 需要一次性明确意图 | 测试、dry-run、历史授权或 health 不构成 mutation 授权 |
| 数据 | RQData -> Canonical Parquet -> 八表 Catalog -> MarketDataService | 只有一条 Historical 事实链；Live 只是 observation |
| Historical 查询 | `MarketDataService` 唯一入口 | 禁止 consumer glob、自选 active、自判主力或跨频回退 |
| SuBing | 一个产品、三种内部投影 | Daily Context、Current Signal State、Formal Event 不合并；Alert 仅 `scope_products` |
| HTDY | operational universe × 七周期观察 | Scope 仅 symbol × frequency；D1/W1 只走 `canonical_updated` seam，不新增第二套 scheduler 或 Scope 表 |
| 研究 | N/raw JDJ 内部化，JDJ 保留参考回放 | 不建立 StrategyAdapter、Scope DSL 或正式回测平台 |
| Retained research | Candidate Validation/Robustness 与 prospective OOS 保留 | 关系指标保持 generic；不从 retrospective 自动晋升结论 |
| Retired surface | Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、RQAlpha 与 Execution Review 退出 active surface | 历史仅 Git/Alembic lineage；不保留 active route、consumer、roll seam 或外部 runs artifacts |
| Alert | 两表、one-shot | 无 retry/replay/backfill/queue/outbox/订单 |
