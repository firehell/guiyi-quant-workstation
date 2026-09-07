# 架构决策记录

更新时间：2026-09-05

本文件只记录长期决策；当前版本、部署、Scope、evidence 与 Gate 只看 `STATUS.md`，历史过程从 Git history 追溯。

| 主题 | 长期决策 | 不变量 |
|---|---|---|
| 产品 | 本地、单用户的国内期货研究工作站 | 不做自动交易、SaaS 或无人值守下单；`auto_order=false` |
| 数据事实链 | `RQData -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService` | Historical consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退 |
| Live/Historical | Redis Live 仅为当日 observation，Canonical 是治理后的 Historical fact | Live 不直接晋升 Canonical；未确认 Bar 不进入正式历史或正式信号 |
| Session 锚点 | RQData 1m 首根标签在 adapter 边界减一分钟，统一为 `SessionWindow(start, end]` 的排他 start | 不在聚合器或 consumer 分散补偿；分钟对齐、跨午夜、无效区间与重叠 fail-closed；Canonical V2 原地替换，不新增 data-version |
| Universe | `active_products.txt` 定义研究能力，`operational_products.txt` 定义持续 Runtime 授权 | 即使文件内容相同也不合并授权边界 |
| 通用 EMA21 斜率 | 只保留 10K primitive | 恰好 10 个 EMA21 值；首尾差 / 9 / 当前 EMA21 × 10000；无周期、方向过滤或策略语义 |
| Range Detector | 仅只读图表展示 | 不进入策略、Alert、Runtime、通知或数据写入 |
| HTDY | operational universe × 七周期 observation；持久 Alert 只记录触发窗口最新 completed Bar 的 forward-only first-seen 事实 | Scope 只认 symbol × frequency；D1/W1 只走 `canonical_updated` seam；历史 repaint 只供 Web 展示 |
| 苏冰预警 | 新 `subing_ths_alert_15m_v1` observation，公式版本 `subing_ths_15m_v3` | v3 数学公式不变，只冻结正确 session Bar/时间；completed actual_dominant 15m；MACD exact CROSS + `EMA(CLOSE, 21)`；同物理合约 warm-up/rollover；无零轴、Range、量能、斜率或多周期隐藏过滤；`exact Event` |
| Alert | 两表、Event 先提交、one-shot transport | 0043 删除旧策略，0044 只加 disabled + empty-scope SuBing，0045 只规范化 RQData session；HTDY `first_seen`、SuBing `exact`；无 retry/replay/backfill/queue/outbox/订单；provider accepted 不等于送达 |
| Alert activation | disabled Rule 的通用 Scope 写入必须拒绝；SuBing 首次启用走专用原子 seam | dry-run 零写入；apply 只在精确 0045 和 disabled + empty scope preflight 后一次 commit/readback；先完成锚点修复与新 G10 compatibility evidence，后 G9 Scope + enable |
| Market Home | 牛哇式有限图标 + update-time derived overview projection + current Alert Events | `MarketHomeOverviewService` 是唯一 overview compute authority；projection 位于 Canonical root 的 `.derived`、可删除可重建；任何正式 `data update/refresh --apply` 与自然 after-market 都在 manager 已取得 maintenance lease 后、任何 authority mutation 前失效旧 projection；natural refresh 默认关闭，只有 owner-written activation marker 才在同一 lease 内装配；API hit 只读 projection，miss/corrupt/mismatch 必须回退现有 compute；首页仍只有 overview、Runtime health、current Alert Events 三个 O(1) 读取；图标/HTDY marker/SuBing `S↑/S↓` 不表达交易语义 |
| Newow 产品 | Newow 是趋势、震荡、主升浪 × `1w/1d/60m` 的只读策略 Workspace；旧 `view=trend` 与 D1 API 只作固定 `actual_dominant + 1d` 兼容入口 | 主动作只有策略自身 `BUILD/CLEAR`；J、D1–D6、4/7/11 等均为 `quantity_effect=none` Hint；无主动作、缺证据、不适用与重绘回看必须分别表达；HTDY/SuBing/Free 合同不变 |
| Reference Trading | `ReferenceTrade` 是当前 Canonical 输入和固定版本规则的纯计算投影，不是 Position、Order、Account、Execution、Fill 或 AlertEvent | 趋势参考慢线 B、震荡 BUILD Low/CLEAR High、主升浪 MA45；Decimal 零成本乐观口径；不推断手数、资金、真实成交、费用或滑点；只读产品能力不恢复已退役账户或策略事件域 |
| Reference 生命周期与统计 | BUILD/CLEAR 只在同策略、周期、物理合约、owner 区段和版本内精确配对；统计窗口独立于图表 viewport | 无 CLEAR 保持 OPEN；换月为 `ROLLOVER_INTERRUPTED` 并单列旧合约同周期 completed Close 参考浮动，不伪造退出、不跨频/跨合约补价；仅 CLOSED 进入明确窗口的简单收益率合计，不能称账户收益 |
| Newow 时间、解释与证据 | 多周期解释使用各周期 completed Bar 和显式 `as_of`；解释、比较器与回看图层不得反向改变主动作 | 未来完成周线不回填历史 60m；五窗口比较器期末理论平仓隔离于 ReferenceTrade；照妖镜保持 `repainting=true / formal_signal_eligible=false`；缺精确合同标记 `EVIDENCE_REQUIRED`，不得以“无信号”或 0 分代替 |
| 既有策略整体退役 | 删除其代码、配置、API、CLI、Web、Runtime、Scope、Event 和派生 cache 能力 | 旧身份只保留 Git/Alembic lineage 与删除迁移断言；未来策略必须使用新身份、新合同和新版本 |
| Validation | causality、strict-before、future-leak、prefix invariance、golden parity、fail-closed 是长期合同 | Retrospective 不回填 prospective OOS，不自动晋升候选 |
| 外部操作 | 真实数据/DB、Runtime/live、Scope、通知、release/tag 需要范围明确的一次性执行意图 | 测试、dry-run、历史授权、配置存在或 health 不构成 mutation 授权 |
| 文档职责 | `PROJECT_SOURCE.md` 定义稳定产品面；`docs/ARCHITECTURE.md` 定义 active 依赖；deep canonical 定义业务语义 | `STATUS.md` 不承载历史过程，Git history 不构成未来授权 |
