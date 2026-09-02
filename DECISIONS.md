# 架构决策记录

更新时间：2026-09-02

本文件只记录长期决策；当前版本、部署、Scope、evidence 与 Gate 只看 `STATUS.md`，历史过程从 Git history 追溯。

| 主题 | 长期决策 | 不变量 |
|---|---|---|
| 产品 | 本地、单用户的国内期货研究工作站 | 不做自动交易、SaaS 或无人值守下单；`auto_order=false` |
| 数据事实链 | `RQData -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService` | Historical consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退 |
| Live/Historical | Redis Live 仅为当日 observation，Canonical 是治理后的 Historical fact | Live 不直接晋升 Canonical；未确认 Bar 不进入正式历史或正式信号 |
| Universe | `active_products.txt` 定义研究能力，`operational_products.txt` 定义持续 Runtime 授权 | 即使文件内容相同也不合并授权边界 |
| 通用 EMA21 斜率 | 只保留 10K primitive | 恰好 10 个 EMA21 值；首尾差 / 9 / 当前 EMA21 × 10000；无周期、方向过滤或策略语义 |
| Range Detector | 仅只读图表展示 | 不进入策略、Alert、Runtime、通知或数据写入 |
| HTDY | operational universe × 七周期 observation；持久 Alert 只记录触发窗口最新 completed Bar 的 forward-only first-seen 事实 | Scope 只认 symbol × frequency；D1/W1 只走 `canonical_updated` seam；历史 repaint 只供 Web 展示 |
| 苏冰预警 | 新 `subing_ths_alert_15m_v1` observation，公式版本 `subing_ths_15m_v2` | completed actual_dominant 15m；MACD exact CROSS + `EMA(CLOSE, 21)`；同物理合约 warm-up/rollover；无零轴、Range、量能、斜率或多周期隐藏过滤；`exact Event` |
| Alert | 两表、Event 先提交、one-shot transport | 0043 删除旧策略，0044 只加 disabled + empty-scope SuBing；HTDY `first_seen`、SuBing `exact`；无 retry/replay/backfill/queue/outbox/订单；provider accepted 不等于送达 |
| Alert activation | disabled Rule 的通用 Scope 写入必须拒绝；SuBing 首次启用走专用原子 seam | dry-run 零写入；apply 只在精确 0044 和 disabled + empty scope preflight 后一次 commit/readback；先 G10 兼容性 evidence，后 G9 Scope + enable |
| Market Home | 牛哇式有限图标 + update-time derived overview projection + current Alert Events | `MarketHomeOverviewService` 是唯一 overview compute authority；projection 位于 Canonical root 的 `.derived`、可删除可重建；任何正式 `data update/refresh --apply` 与自然 after-market 都在 manager 已取得 maintenance lease 后、任何 authority mutation 前失效旧 projection；natural refresh 默认关闭，只有 owner-written activation marker 才在同一 lease 内装配；API hit 只读 projection，miss/corrupt/mismatch 必须回退现有 compute；首页仍只有 overview、Runtime health、current Alert Events 三个 O(1) 读取；图标/HTDY marker/SuBing `S↑/S↓` 不表达交易语义 |
| 既有策略整体退役 | 删除其代码、配置、API、CLI、Web、Runtime、Scope、Event 和派生 cache 能力 | 旧身份只保留 Git/Alembic lineage 与删除迁移断言；未来策略必须使用新身份、新合同和新版本 |
| Validation | causality、strict-before、future-leak、prefix invariance、golden parity、fail-closed 是长期合同 | Retrospective 不回填 prospective OOS，不自动晋升候选 |
| 外部操作 | 真实数据/DB、Runtime/live、Scope、通知、release/tag 需要范围明确的一次性执行意图 | 测试、dry-run、历史授权、配置存在或 health 不构成 mutation 授权 |
| 文档职责 | `PROJECT_SOURCE.md` 定义稳定产品面；`docs/ARCHITECTURE.md` 定义 active 依赖；deep canonical 定义业务语义 | `STATUS.md` 不承载历史过程，Git history 不构成未来授权 |
