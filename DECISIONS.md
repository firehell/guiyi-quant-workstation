# 架构决策记录

更新时间：2026-08-22

本文件只记录长期决策、理由与不可破坏边界。版本、部署、evidence 和 Gate 状态只看 `STATUS.md`；
exact protocol/window/hash/count 只看 policy、report 与测试；历史过程只从 Git history 追溯。

| 主题 | 长期决策 | 理由与不可破坏边界 |
|---|---|---|
| 产品 | 本地、单用户国内期货研究工作站 | 个人研究闭环优先于平台化；不做自动交易、SaaS、多用户或无人值守下单，`auto_order=false` |
| 外部操作 | 真实数据/DB/Runtime/live/通知/release 只接受范围明确的一次性执行意图 | mutation 风险不能由代码、测试、dry-run、历史授权或 health 绿灯推导；Market 与 Alert 的有界持续授权互不继承 |
| 数据源 | RQData 是唯一外部行情事实源 | 避免多源逐行裁决与不可复算漂移；不建 provider 插件 seam |
| 历史存储 | 只长期保存一套 Canonical Parquet，PostgreSQL 不存 Bar | Canonical 是可治理事实，Catalog 只保存轻量身份、coverage、质量与映射 |
| 数据身份 | `DatasetKey=(kind,symbol,series_or_contract,frequency)` | provider/schema 属于来源与校验属性，不进入业务 identity |
| 主力数据 | 物理保存真实合约，`actual_dominant` 查询时按 rank1 有效区间拼接 | 避免重复的主力拼接资产；mapping 缺失或冲突必须 fail-closed |
| 周期 | Provider 基础周期为 `1m/1d`；派生周期只从同源 Canonical 基础周期聚合 | 保持单一可复算口径；禁止消费者跨频回退或重新聚合 |
| 分区与质量 | 每 Dataset 每自然月一个 `part.parquet`，硬校验通过后原子发布 | 失败时保留最后有效月；不建第二套缺口、版本或逐行裁决状态 |
| Market Catalog | Data Foundation 精确保留八表；明确设计的应用事实进入独立 Application Domain | 防止 Catalog 变成重型仓库；Alert/Execution Review 表不得冒充 Market 表 |
| Historical 查询 | `MarketDataService` 是唯一入口 | consumer 不得 glob、自选 active、自判主力或绕过 coverage/quality |
| Live | Redis Live 永远只是 Observation | 未确认或盘中事实不得提升为 Canonical，也不得替代 Historical evidence |
| 研究读模型 | 派生市场事实按需计算，不为可复算事实新增 Catalog 表或第二套 resolver | 保持模块深而少；Research 只能向 Historical gateway 依赖，Runtime/Market/Alert 不反向依赖离线 Research |
| Research 因果性 | segment、contract、trading-day、strict-before 与 event evidence-bar 是硬边界 | 任一身份不完整即 fail-closed；未来 Bar、跨换月 memory 和 same-bar 回标都会污染复算 |
| Candidate/OOS | source-specific retrospective、embargo、prospective OOS 分离 | 不建立伪 common window，不用 retrospective 回填 OOS；evidence 不自动形成 rank、winner、promotion、盈利或可交易结论 |
| Candidate convergence | dossier 只组装冻结事实；comparability 不等于 relationship；dependency/overlap 不外推 | 避免把不同 timeframe、event unit 与 outcome 语义强行统一；exact count/window 留在 protocol/report/tests |
| 主力照妖镜 | active observation 与 sequence forensic 分层；forensic 只使用预定义全局 profile | 不按品种调参、不选 best profile；没有真实 read-only evidence Gate 就不冻结正式 Phase |
| Alert | Event 先提交，通知最多一次；两条 Rule 复用既有 evaluator/read model | 保留故障隔离与因果 cutoff；无 retry/replay/backfill/outbox/queue/逐人状态或订单路径 |
| Execution Review | 只从 eligible immutable Event 记录人工 Decision、Execution、Episode 与 Review | 不恢复旧 Review Center、不连接账户、不自动反手；Historical reconstruction 只经 `MarketDataService` |
| Execution Review roll | roll reconcile 默认关闭；request-scoped composition 每请求读取一次 Gate 后注入 callback | missing/`disabled`/`invalid` 注入 fail-closed callback，只有 `enabled` 注入真实 reconciler；`record_executed` 不重复读取 marker |
| Multiplier | 使用 trusted-partial 官方 evidence，Episode 创建时 snapshot | completeness 不阻断工作流；缺失只令人民币估算 unavailable，reference 扩大不改写历史 |
| Web B1 | 首页只用 D1 Radar 做“优先检查”，详情页按“当前检查栏”验证 | 减少遍历但不建立 Opportunity domain、综合分或推荐；`degraded` fail-closed，正式 Event/研究观察/Research-only 分层 |
| Runtime 入口 | `guiyi` 是用户 CLI，`app.runtime_entry` 只服务受监督进程 | 避免第二套业务入口；手工进程调用不能冒充自然 Runtime evidence |
| 工程验证 | `TESTING.md` 只保留项目原生命令；工程脚本只保留无依赖 secret scan | 不维护自验证治理框架、重复流程文档、active task/plan 目录或可选 CI 双轨 |
| 运维拓扑 | Mac launchd → FRPC → FRPS/Nginx 是唯一 active 链 | 本地/隧道/公网分段只读检查；不保留并行 PID 管理器或远端应用副本 |
