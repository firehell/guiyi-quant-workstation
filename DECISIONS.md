# 架构决策记录

更新时间：2026-08-26

本文件只记录长期决策；当前版本、部署、Scope、evidence 与 Gate 只看 `STATUS.md`，历史过程只从 Git history 追溯。

| 主题 | 长期决策 | 不变量 |
|---|---|---|
| 产品 | 本地、单用户的国内期货研究工作站 | 不做自动交易、SaaS 或无人值守下单；`auto_order=false` |
| 数据事实链 | `RQData -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService` | Historical consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退 |
| Live/Historical | Redis Live 仅为当日 observation，Canonical 是治理后的 Historical fact | Live 不直接晋升 Canonical；未确认 Bar 不进入正式历史或正式信号 |
| Universe | `active_products.txt` 定义研究能力，`operational_products.txt` 定义持续 Runtime 授权 | 即使文件内容相同也不合并授权边界 |
| SuBing | 一个产品，Daily Context、Current Signal State、Formal Event 三种事实 | 共享权威公式但不合并为 mega endpoint、表或 DTO；Alert 只认 `scope_products` |
| Historical replay | SuBing 15m Strategy Projection 保持 source-specific | 不创建 UniversalStrategyAdapter、统一 Opportunity 模型、正式回测 worker/queue 或订单域 |
| HTDY | operational universe × 七周期 observation | Scope 只认 symbol × frequency；D1/W1 只走 `canonical_updated` seam |
| Validation | causality、strict-before、future-leak、prefix invariance、golden parity、fail-closed 是长期合同 | Retrospective 不回填 prospective OOS，不自动晋升候选 |
| Alert | 两表、Event 先提交、one-shot transport | 无 retry/replay/backfill/queue/outbox/订单；provider accepted 不等于送达 |
| 外部操作 | 真实数据/DB、Runtime/live、Scope、通知、release/tag 需要范围明确的一次性执行意图 | 测试、dry-run、历史授权、配置存在或 health 不构成 mutation 授权 |
| Retired surface | Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、RQAlpha、Execution Review 退出 active surface | 历史只保留 Git/Alembic lineage，不保留 active route、consumer 或 Runtime seam |
| 文档职责 | `PROJECT_SOURCE.md` 定义稳定产品面；`docs/ARCHITECTURE.md` 定义 active 依赖；deep canonical 定义业务语义 | `STATUS.md` 不承载历史过程，Git history 不构成未来授权 |
