# 架构决策记录

更新时间：2026-09-16

本文件只记录长期决策；当前版本、部署、Scope、evidence 与 Gate 只看 `STATUS.md`，历史过程从 Git history 追溯。

| 主题 | 长期决策 | 不变量 |
|---|---|---|
| 产品 | 本地、单用户的国内期货研究工作站 | 当前研究观察阶段 `auto_order=false`；不做 SaaS，不跳过人工 Gate 进入无人值守真实下单 |
| 分阶段演进 | 研究观察 → Paper → Shadow → Broker Read-only → 订单草稿 → 人工确认 → 半自动 → 受控自动 | AI 可以自动研究但不能自动晋升；每阶段独立人工 Gate，当前不新增账户或执行能力 |
| 数据事实链 | `RQData -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService` | Historical consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退 |
| 数据维护职责 | 每日增量维护最新数据，每周 operational 全历史只读审计，发现后的修复按明确范围独立处理；语义见 `docs/DATA_CENTER.md` | 日常成功不证明全历史完整；周检不下载、不自动修复、不通知；复用既有锁和权威数据链，不建立第二套缺口事实或后台补数平台 |
| Canonical 月发布 | 每 DatasetKey 每月唯一 active Catalog pointer，指向不可变 `part.<sha256>.parquet` | 完整校验与文件 durability 先于既有事务 register/flush/真实 MDS strict-read；commit 为单 partition 可见点；commit 异常停批并以独立只读事务核实；保留旧文件，无 GC/version table/global snapshot；legacy 固定 URI 只按 Catalog 明确引用兼容 |
| Live/Historical | Redis Live 仅为当日 observation，Canonical 是治理后的 Historical fact | Live 不直接晋升 Canonical；未确认 Bar 不进入正式历史或正式信号 |
| Session 锚点 | RQData 1m 首根标签在 adapter 边界减一分钟，统一为 `SessionWindow(start, end]` 的排他 start | 不在聚合器或 consumer 分散补偿；分钟对齐、跨午夜、无效区间与重叠 fail-closed；Canonical V2 原地替换，不新增 data-version |
| Universe | `active_products.txt` 定义研究能力，`operational_products.txt` 定义持续 Runtime 授权 | 即使文件内容相同也不合并授权边界 |
| 通用 EMA21 斜率 | 只保留 10K primitive | 恰好 10 个 EMA21 值；首尾差 / 9 / 当前 EMA21 × 10000；无周期、方向过滤或策略语义 |
| Range Detector | 仅只读图表展示 | 不进入策略、Alert、Runtime、通知或数据写入 |
| HTDY | operational universe × 七周期 observation；持久 Alert 只记录触发窗口最新 completed Bar 的 forward-only first-seen 事实 | Scope 只认 symbol × frequency；D1/W1 只走 `canonical_updated` seam；历史 repaint 只供 Web 展示 |
| 苏冰预警 | 新 `subing_ths_alert_15m_v1` observation，公式版本 `subing_ths_15m_v3` | v3 数学公式不变，只冻结正确 session Bar/时间；completed actual_dominant 15m；MACD exact CROSS + `EMA(CLOSE, 21)`；同物理合约 warm-up/rollover；无零轴、Range、量能、斜率或多周期隐藏过滤；`exact Event` |
| Alert | 两表、Event 先提交、one-shot transport | 0043 删除旧策略，0044 只加 disabled + empty-scope SuBing，0045 只规范化 RQData session；HTDY `first_seen`、SuBing `exact`；无 retry/replay/backfill/queue/outbox/订单；provider accepted 不等于送达 |
| Alert activation | disabled Rule 的通用 Scope 写入必须拒绝；SuBing 首次启用走专用原子 seam | dry-run 零写入；apply 只在精确 0045 和 disabled + empty scope preflight 后一次 commit/readback；先完成锚点修复与新 G10 compatibility evidence，后 G9 Scope + enable |
| Market Home | 牛哇式有限图标 + update-time derived overview projection + immutable Alert Events | `MarketHomeOverviewService` 是唯一 overview compute authority；projection 位于 Canonical root 的 `.derived`、可删除可重建；任何正式 `data update/refresh --apply` 与自然 after-market 都在 manager 已取得 maintenance lease 后、任何 authority mutation 前失效旧 projection；natural refresh 默认关闭，只有 owner-written activation marker 才在同一 lease 内装配；API hit 只读 projection，miss/corrupt/mismatch 必须回退现有 compute；首页独立消费 overview、Runtime health、批量品种目录、按需历史消息与单个 operational bulk 行情 WebSocket，不发起 per-product 读取；图标/HTDY marker/SuBing `S↑/S↓` 不表达交易语义 |
| Newow 产品 | Newow 是趋势、震荡、主升浪 × `1w/1d/60m` 的只读策略 Workspace；Market 详情用六个扁平分析入口和一个周期入口，旧 `view=trend` 页面链接迁移到统一 Newow 趋势身份，D1 API 仍只作固定兼容入口 | 同品种同周期且时间轴一致才保留缩放；策略切换必须替换互斥图层。主动作只有策略自身 `BUILD/CLEAR`；J、D1–D6、4/7/11 等均为 `quantity_effect=none` Hint；无主动作、缺证据、不适用与重绘回看必须分别表达；HTDY/SuBing/Free 合同不变 |
| Newow 分阶段开放 | 长期九组合允许先日周六组合、后独立 60m；按品种/窗口/面板声明支持范围，数据就绪与产品开放分开验收 | 不删除通用分钟链路，不改其他消费者；未开放周期不得成为已开放同周期面板的隐含依赖；完整跨周期解释缺输入则暂缓，不创造简化评分；主动作与参考交易合同不变 |
| Newow 发布能力 authority | typed current/historical API 与 Web 共用无数据库依赖的 `product-capabilities`；日周版对 60 品种开放 `1d`，仅对版本化首批 41 品种开放 `1w` chart/auxiliary/reference/comparator | 其余 19 品种 `1w`、全部 `60m` 和 explanation 显式 409，不静默改写周期；旧 `/trend-detail` 固定 D1 兼容语义及其他 Market consumer 不受影响；Release 不授权 Runtime promotion 或推定数据缺口已修复 |
| Reference Trading | `ReferenceTrade` 是当前 Canonical 输入和固定版本规则的纯计算投影，不是 Position、Order、Account、Execution、Fill 或 AlertEvent；主升浪完整生命周期中首次无入场 CLEAR 是独立 Action-only 事实 | 趋势参考慢线 B、震荡 BUILD Low/CLEAR High、主升浪 MA45；`INITIAL_CLEAR_NO_ENTRY` 必须有 reader lifecycle evidence，只显示“清仓（无入场）”且不生成交易/收益；Decimal 零成本乐观口径；不推断手数、资金、真实成交、费用或滑点；typed/reference 合同使用 v2，公式身份不变，期货输入适配版本按输入语义独立演进 |
| Reference 生命周期与统计 | BUILD/CLEAR 只在同策略、周期、物理合约、owner 区段和版本内精确配对；统计窗口独立于图表 viewport | 无 CLEAR 保持 OPEN；换月为 `ROLLOVER_INTERRUPTED` 并单列旧合约同周期 completed Close 参考浮动，不伪造退出、不跨频/跨合约补价；仅 CLOSED 进入明确窗口的简单收益率合计，不能称账户收益 |
| 统一参考记录模式 | 历史重建与启用后观察共享纯 reducer、但使用独立 stream identity；公共层不改策略公式、参考价、既有 source ID 或统计 | `historical_replay` 不伪造 observation；`forward_observation` 从 FLAT 开始，后续 CLEAR 只有 `NO_OBSERVED_ENTRY`；HTDY first-seen 具体参考模型仍为 `MODEL_NOT_APPROVED`，不会由公共基础自动接受 |
| Newow 时间、解释与证据 | 多周期解释使用各周期 completed Bar 和显式 `as_of`；解释、比较器与回看图层不得反向改变主动作 | 未来完成周线不回填历史 60m；五窗口比较器期末理论平仓隔离于 ReferenceTrade；照妖镜保持 `repainting=true / formal_signal_eligible=false`；缺精确合同标记 `EVIDENCE_REQUIRED`，不得以“无信号”或 0 分代替 |
| Newow 期货无交易事实 | 权威 `OHLC=0 + volume=0 + turnover=0` 保留为原始行情事实，但不构成策略有效观察 | 不造价、不进入指标窗口、不推进 warming/状态/周期、不生成 Action/Hint/ReferenceTrade；恢复交易 Bar 承接上一有效 Bar；其他非正价格继续 fail-closed；输入政策 `newow_futures_effective_observation_v1`，期货适配 `newow_futures_segment_interrupt_no_trade_v2` |
| 既有策略整体退役 | 删除其代码、配置、API、CLI、Web、Runtime、Scope、Event 和派生 cache 能力 | 旧身份只保留 Git/Alembic lineage 与删除迁移断言；未来策略必须使用新身份、新合同和新版本 |
| Validation | causality、strict-before、future-leak、prefix invariance、golden parity、fail-closed 是长期合同 | Retrospective 不回填 prospective OOS，不自动晋升候选 |
| 开发协作 | AI 自主完成开发维护闭环；owner 决定产品方向、重要架构/业务语义和生产边界 | 讨论/Plan-only 不提前实施；普通开发授权不推导生产 mutation、main/tag/release 或 Runtime promotion，细则见 `AGENTS.md` |
| 外部操作 | 真实数据/DB、Runtime/live、Scope、通知、release/tag 按目标、环境、范围明确的任务或批次授权 | 授权不因会话切换失效；已完成的历史授权、测试、dry-run、配置或 health 不授权重跑；重试和恢复须在批准边界内 |
| 交付收敛 | 精确候选冻结后只接纳该次交付阻断；代码缺陷、数据缺口、证据不足、现场 Gate 与新版需求分开处理 | 已修复先验证不重写；已披露限制不得掩盖共享完整性缺陷；release 与 Runtime promotion 是独立授权项，可在一次批准中明确覆盖，运行证据绑定对应版本，不由 develop 集成自动推导 |
| 文档职责 | `PROJECT_SOURCE.md` 定义稳定产品面；`docs/ARCHITECTURE.md` 定义 active 依赖；deep canonical 定义业务语义 | `STATUS.md` 不承载历史过程，Git history 不构成未来授权 |
