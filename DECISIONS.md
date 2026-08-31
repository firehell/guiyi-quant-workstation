# 架构决策记录

更新时间：2026-08-31

本文件只记录长期决策；当前版本、部署、Scope、evidence 与 Gate 只看 `STATUS.md`，历史过程只从 Git history 追溯。

| 主题 | 长期决策 | 不变量 |
|---|---|---|
| 产品 | 本地、单用户的国内期货研究工作站 | 不做自动交易、SaaS 或无人值守下单；`auto_order=false` |
| 数据事实链 | `RQData -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService` | Historical consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退 |
| Live/Historical | Redis Live 仅为当日 observation，Canonical 是治理后的 Historical fact | Live 不直接晋升 Canonical；未确认 Bar 不进入正式历史或正式信号 |
| Universe | `active_products.txt` 定义研究能力，`operational_products.txt` 定义持续 Runtime 授权 | 即使文件内容相同也不合并授权边界 |
| SuBing | 一个产品，Daily Context、Current Signal State、Formal Event 三种事实 | 共享权威公式但不合并为 mega endpoint、表或 DTO；Alert 只认 `scope_products` |
| Historical replay | SuBing 15m Strategy Projection 保持 source-specific | 不创建 UniversalStrategyAdapter、统一 Opportunity 模型、正式回测 worker/queue 或订单域 |
| SuBing Strategy engine | Historical 与 completed-Live 只使用同一个增量状态机；公开身份保持 `actual_dominant + 15m` | 1m/5m 只作内部输入；普通 Action 只认下一实际同合约 15m 区间第一根 1m open；状态不跨 rank1 物理段 |
| SuBing 全历史效果 | 以完整 Episode 的 reference change 统计为唯一效果口径，并复用 Historical Projection | 产品快照必须绑定策略政策、校准、Lifecycle、Daily Context、源 Bar 与主力段 identity 并原子发布后读回；open Episode 不进入完成统计，不建设账户、资金曲线、复利收益、正式 backtest worker 或结果表 |
| SuBing 效果快照 | 不可变 schema-v3 快照加每产品一份 current manifest；盘后只按物理段尾决策 | 决策仅 `UNCHANGED` / `REPLAY_FROM_SEGMENT` / `FULL_REBUILD_REQUIRED`；HTTP 只读校验当前快照；identity 或不可变前缀漂移 fail-closed，不自动全量回退 |
| SuBing Runtime/Scope | active60 计算状态与 `scope_products` 通知授权分离；当前状态从市场事实重建 | restore/catch-up 不补 Event 或通知；Scope 不创建、删除、重置状态；AlertEvent 不是仓位权威 |
| SuBing Rule replacement | `20260826_0042` forward-only 直接将 `subing_entry_signal_v1` 替换为 `subing_strategy_v1` | 删除旧 SuBing Event，保留 Rule `id/enabled/scope_products`；无 archive、双 Rule、兼容 reader、replay 或 downgrade；production 执行另需 Gate |
| HTDY | operational universe × 七周期 observation；持久 Alert 只记录 forward-only first-seen 事实 | Scope 只认 symbol × frequency；D1/W1 只走 `canonical_updated` seam；`bar_end` 是观察 Bar 时间，`detected_at` 是首次识别时间；同一 Event identity 后续重绘一律 immutable no-op |
| Validation | causality、strict-before、future-leak、prefix invariance、golden parity、fail-closed 是长期合同 | Retrospective 不回填 prospective OOS，不自动晋升候选 |
| Candidate Validation authority | Candidate manifest 保持 Candidate/source identity authority，Validation Protocol 保持 schedule/OOS authority；未来加载以一个原子 authority seam 同时交付两份 typed value | JSON 是业务字段唯一 authority；代码只保留 schema/关系校验、raw-byte digest pin、稳定错误码与 source identity 交叉校验；same-ID byte drift fail-closed。实现须另开任务并以 TDD 证明字段、错误、window、OOS 与 consumer parity；不改 JSON、策略、threshold、embargo、cohort、Canonical、Alert 或 Runtime |
| Alert | 两表、Event 先提交、one-shot transport | HTDY Event identity 为 Rule × symbol × frequency × `bar_end`；无 retry/replay/backfill/queue/outbox/订单；provider accepted 不等于送达 |
| 外部操作 | 真实数据/DB、Runtime/live、Scope、通知、release/tag 需要范围明确的一次性执行意图 | 测试、dry-run、历史授权、配置存在或 health 不构成 mutation 授权 |
| Retired surface | JDJ、Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、N Structure、专用于 SuBing↔N 的 Multi-Candidate Robustness、RQAlpha、Execution Review 退出 active surface | 历史只保留 Git/Alembic lineage，不保留 active route、consumer 或 Runtime seam；恢复必须由新任务定义 consumer、formula、value 与 evidence；`subing_structure.py` 是保留的 SuBing 基础设施，不属于本次退役 |
| 文档职责 | `PROJECT_SOURCE.md` 定义稳定产品面；`docs/ARCHITECTURE.md` 定义 active 依赖；deep canonical 定义业务语义 | `STATUS.md` 不承载历史过程，Git history 不构成未来授权 |
