# 架构决策记录

更新时间：2026-08-25

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
| Runtime 观察 | 复用现有 Redis heartbeat/status 与盘后状态文件，由唯一只读 health DTO 对外投影 | 不建第二套 monitor/scheduler/DB；只有 Alert persistent status missing 是 `unobserved`，Live heartbeat missing 按启用状态为 degraded/disabled，盘后 missing 按其 pending/missed 合同；无效状态 fail-closed，health 不发送通知或改变 Runtime，精确语义见对应 deep contract |
| 研究读模型 | 派生市场事实按需计算，不为可复算事实新增 Catalog 表或第二套 resolver | 保持模块深而少；Research 只能向 Historical gateway 依赖，Runtime/Market/Alert 不反向依赖离线 Research |
| Research 因果性 | segment、contract、trading-day、strict-before 与 event evidence-bar 是硬边界 | 任一身份不完整即 fail-closed；未来 Bar、跨换月 memory 和 same-bar 回标都会污染复算 |
| Candidate/OOS | source-specific retrospective、embargo、prospective OOS 分离 | 不建立伪 common window，不用 retrospective 回填 OOS；evidence 不自动形成 rank、winner、promotion、盈利或可交易结论 |
| Candidate convergence | dossier 只组装冻结事实；comparability 不等于 relationship；dependency/overlap 不外推 | 避免把不同 timeframe、event unit 与 outcome 语义强行统一；exact count/window 留在 protocol/report/tests |
| 主力照妖镜 | active observation 与 sequence forensic 分层；forensic 只使用预定义全局 profile | 不按品种调参、不选 best profile；没有真实 read-only evidence Gate 就不冻结正式 Phase |
| RQAlpha 研究工作台 | 只作为 loopback local app + 外部 Bundle/artifact 的 research-only 工具，不挂载主 API、不进入正式事实链 | 可用 Web 解决本机 RQAlpha 配置/执行/观察，同时避免暴露远程进程启动面；不恢复旧 backtest worker/DB，不替代未来 Canonical/MarketDataService + Candidate/OOS 正式验证体系；仓库验证不授权 sidecar 加载、真实 smoke、release 或 Runtime |
| Alert Scope 与 Event identity | HTDY 保留单一稳定 Rule `htdy_original_15m`，以 `scope_product_frequencies` 管理 exact `symbol + frequency`；SuBing 继续只认 `scope_products` | 两种 Scope authority 混用即 fail-closed；通用存储键包含 frequency，HTDY 业务 identity 也包含 frequency，SuBing 仍由 Service 保持 bar-level identity |
| Alert 触发 | HTDY 日内五周期复用同周期 completed Live Bar，D1/W1 只响应 `canonical_updated` 并读取正式 Canonical | 不从 Live 聚合 D1/W1，不新增第二套 scheduler 或 Scope 表；保持 current-event cutoff、no-backfill、Event 先提交、通知最多一次及无 retry/replay/outbox/queue/订单路径 |
| Alert Runtime observation | 无 TTL Redis schema v1 只记录 processing/notification observation | 保留故障隔离；missing 不得冒充成功，状态写失败即进程 fail-closed，不保存 provider reference，provider accepted 不等于送达 |
| 盘后可观察性 | 状态文件使用 schema v2 并兼容读 v1，自然运行开始即原子写 `current_run`；health 依 operational exchanges 的 `TradingCalendar` 判断预期日与超时 | 18:20 预期边界和 2h stuck 边界必须可检查；日历/跨交易所事实不可用时 fail-closed，不增独立 monitor |
| 盘后运维通知 | 只对受监督自然盘后 execution failure 向 owner 发起最多一次 PushPlus 请求 | 与 Alert Rule/Application Domain 分离，不用 Topic/Event/DB/retry/fallback；provider accepted 不等于送达，missed/stuck 只是 health |
| Execution Review | 只从 eligible immutable Event 记录人工 Decision、Execution、Episode 与 Review | 不恢复旧 Review Center、不连接账户、不自动反手；Historical reconstruction 只经 `MarketDataService` |
| Execution Review roll | roll reconcile 默认关闭；request-scoped composition 每请求读取一次 Gate 后注入 callback | missing/`disabled`/`invalid` 注入 fail-closed callback，只有 `enabled` 注入真实 reconciler；`record_executed` 不重复读取 marker |
| Multiplier | 使用 trusted-partial 官方 evidence，Episode 创建时 snapshot | completeness 不阻断工作流；缺失只令人民币估算 unavailable，reference 扩大不改写历史 |
| Web B1 | SuBing Daily Watch 是首页“优先检查”的 priority context；每周期均要求 price-vs-EMA21 与 slope_5/slope_10 同向，再以 D1 + 60m 同向纳入多空 | active60 ledger 在已配置扩展盘根不可变保存；不排名、不回退 stale candidate，也不耦合 Alert Scope；正式 Event、研究观察与 Research-only 事实继续分层 |
| Audit 进度 | `data audit --progress` 只向 stderr 输出 per-product compact NDJSON，默认 stdout 合同不变 | audit 仍是 provider-free 只读；进度输出首次失败后只禁用 observer，不改变审计结果或异常 |
| Runtime 入口 | `guiyi` 是用户 CLI，`app.runtime_entry` 只服务受监督进程 | 避免第二套业务入口；手工进程调用不能冒充自然 Runtime evidence |
| 工程验证 | `TESTING.md` 只保留项目原生命令；工程脚本只保留无依赖 secret scan；用户明确批准且绑定具体 Spec 的正式 design / implementation plan 可保存在 `docs/superpowers/specs/` 与 `docs/superpowers/plans/` | 不维护自验证治理框架、重复流程文档、active task/plan 目录或可选 CI 双轨；该狭窄例外只提供可审阅的设计合同，不构成 workflow、当前状态或外部操作授权 |
| 运维拓扑 | Mac launchd → FRPC → FRPS/Nginx 是唯一 active 链 | 本地/隧道/公网分段只读检查；不保留并行 PID 管理器或远端应用副本 |
