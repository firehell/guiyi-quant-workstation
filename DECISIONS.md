# 架构决策记录

更新时间：2026-07-26

## 当前有效决策

| 决策 | 当前结论 | 影响 |
|---|---|---|
| 产品边界 | 本地、单用户、国内期货研究工作站 | 不做 SaaS、多用户、自动交易 |
| 数据主链路 | RQData / local standard parquet -> DuckDB -> PostgreSQL -> Web/回测/信号 | active 入口只允许 `rqdata` / `local_parquet` + `primary` + `quality_status != failed` |
| 严格研究入口 | 默认 `quality_status=passed` | warning 必须显式 opt-in 或阻断 |
| 派生周期 | 5m/15m/30m/60m/1d 默认从 passed 1m 本地聚合 | 不把 RQData direct 多分钟作为新正式主链路 |
| V1 全历史契约 | `V1_DATA_CONTRACT_FROZEN`，audit end=`2026-07-10`，timezone=`Asia/Shanghai` | expected start 按上市语义与权威 provider first-valid evidence 动态解析，不使用统一 2020/2023 起点 |
| Audit V2 | `FULL_HISTORY_AUDIT_V2_READY`，data Gate 保持 `DATA_LAYER_REAUDIT_REQUIRED` | expected years 按 product+period 动态生成；physical support 不冒充 provider authoritative exact |
| actual dominant | 只要求 `MainContractMap.rank=1` 有效区间内的 1m/1d | 不把所有挂牌合约全量分钟数据纳入 V1 完成标准 |
| Stage 6 JM historical continuity | S6-03 使用 provider-final trading day、create-only version、exact passed quality 和 Profile CAS；target=`2026-07-17`、actual=`JM2609` | `JM_HISTORICAL_CATCHUP_READY / JM_REFERENCE_METADATA_FRESH / JM_LIVE_TARGET_FRESHNESS_READY` 已通过；不自动进入 T3/T4 |
| Stage 6 JM live / archive | S6-04 使用 current actual-contract passed historical warm-up + latest live trading day confirmed/passed bars；S6-05 已以真实 receipt 通过 `T3_REAL_PASSED`；S6-06 已以独立 v2 packet 完成真实归档和幂等复跑并通过 `JM_ARCHIVE_PASSED` | 下一入口为独立 EOD Automation Gate；不自动写 SignalEvent/notification，不修改策略，也不扩写为 Runtime 长稳或自动交易 Ready |
| Stage 6 JM EOD automation | 使用独立 `app.after_market_scheduler`、独立 Redis singleton/heartbeat、PostgreSQL watermark、专用 runner/installer 和独立 launchd label；每轮按 TradingCalendar 最早优先、最多 5 日，六档有限重试，前日失败不跳日 | D1=`2026-07-22` 正常自动归档与 D2=`2026-07-24` 停机漏跑自动补偿均通过，已发布 `JM_EOD_INCREMENTAL_AUTOMATION_READY`。deployment/enable/recovery 均绑定精确 hash；最终 verifier 分别绑定 D1、outage、D2 的批准身份并要求恢复 commit 为 Git 祖先。该 Gate 不扩写为 Runtime 长稳、SignalEvent、通知或自动交易 Ready |
| JM provider finality | 使用 RQData `is_data_ready` 分别判断 `future_minbar` / `future_daybar`；S6-03 两者均 ready，T4 仅以 provider-final actual 1m 为硬 Gate | 15:00 后不得用日线缺失推断分钟未完成；market readiness 后仍逐 JM 合约验证行数、交易日与 hash |
| 历史/live 分层 | live DB 与 historical canonical 分离 | live 数据盘后必须重新获取 provider 最终历史数据并通过完整 Gate |
| 数据最终状态 | `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 已通过；`DATA_LAYER_REAUDIT_REQUIRED` 与其并列 | 前者只关闭 formal Market/Backtest/Signal/Review 的 Profile、lineage 与 Golden Query 准入；后者保留全历史 residual 治理，二者均不可被扩写为 live、OOS、企业微信或自动交易 Ready |
| 指标内核 | EMA validated；MACD/ATR compatibility_validated；HTDY original observation_only / strict strategy_candidate | `INDICATOR_REGISTRY_V1_READY` 已落地；original 的普通 backtest/live/alert capability 继续关闭，只有精确 HTDY realtime repainting observation policy 可单独放行 |
| D4-00 HTDY 审计 | 证据落盘完成；最终 Gate `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` | 不重开公式审计；不得宣称 `HTDY_XMA_SEMANTICS_AUDITED`；original 保持 observation-only，strict 仅 formal candidate |
| HTDY 原版 XMA 实时例外 | 仅 `jm + 当日 rank=1 实际主力 + 15m + htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting + htdy_original_xma_15m_first_seen_v1` | 允许 partial 15m 与首次检测冻结；禁止历史回测/OOS/收益声明、`signal_changed`/撤回、订单和自动交易；Stage 5 rejection 不变 |
| S6-10 收盘观察窄化合同 | schema-v6 仅允许 `v1.1 + confirmed_15m_close + partial_allowed=false`，从签名 C2 后 activation receipt 的下一根完整桶开始 | 不补评 activation 前桶；最多 23 条受限企微；autosend=false；最终只验收剩余交易日窗口，不宣称完整一日或灾备 Ready |
| 回测口径 | vn.py CTA + 自定义 adapter/runner/result converter/trust audit | `next_bar_open`、成本、乘数、tick、lineage 必须可追溯 |
| 信号提醒 | 企业微信只做观察提醒 | 不自动下单，不生成订单草稿 |
| live 数据 | live tables 与 historical active 分层 | live 不自动登记为可信 historical active |
| 运行部署 | 本地 Mac / Docker / launchd；公网只读入口为腾讯云 Nginx + FRP 模板 | 配置通过不等于真实远端验收通过 |
| 工作站协作 | **GitHub + GPT + Codex + 用户**；Issue/PR 为任务生命周期；`STATUS.md` 为项目状态 | 正式入口 `scripts/engineering/*`；旧控制面已删除，不恢复 |
| 工作站模式 | `WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY` + `ENGINEERING_GATES_HARDENED` + `WORKSTATION_REPOSITORY_CLEANED` | 仅维护工程入口与安全 Gate；不重建旧多入口控制面 |
| 工作站支持模式 | 已收口为 maintenance-only | 历史清理建议人工处理；不阻塞业务 Gate |
| worktree 生命周期 | ADR-WS-003 提供 main/develop/task/Runtime 的本地受控拓扑；ADR-WS-004 提供 Lane 1/2 的五层受控 PR | 未完成 bootstrap 和双 Pilot 前保持默认 dry-run；main/Runtime/Lane 3 永不自动，所有 PR merge 均由用户执行 |
| 高风险真实写入 | 业务专用 hash-bound / scope-bound approval packet / Gate | 无专用 Gate 则禁止真实写入；Issue 批准不能替代代码层 hash 校验 |

## 当前重要取舍

- `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是 strict formal consumer Gate；`DATA_LAYER_REAUDIT_REQUIRED` 是独立全历史维护 backlog。两者必须并列陈述，不能互相否定或替代。
- provider earliest 权威证据缺失时，V2 可将 canonical physical minimum 标记为 `start_boundary_supported`，无物理支持则为 `start_boundary_unverified`；两者均不得冒充 provider authoritative exact，也不得据此通过严格 data Gate。
- direct 1d 用于长周期研究/provider reference；derived 1d 只来自 passed 1m；direct 1w 使用 provider 完成周 bar，不要求等于上市日。
- 五层状态 `physical_coverage / registration / quality / reference_metadata / profile_eligibility` 必须独立保存，warning 不得折叠为 passed，partial 不得进入 historical formal consumer。
- `report_id=14` 只能读取和引用，禁止更新、回填、重算覆盖或替换历史 lineage。
- 旧 Phase 3 的 `metadata_gap=1853`、`pre_2020_weekly_missing=34` 和 actual contract 旧固定 gap 只作为历史审计模型快照；当前不基于这些数字直接批量修复。
- `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只说明 manifest 层强支持物理历史数据已大规模下载；不代表全历史 residual 已清零、live runtime Ready 或外部 Gate 已通过。
- 历史验收文档保持历史数字，不改写成当前状态。
- 开发流程唯一入口：`docs/DEVELOPMENT.md`；状态源为 `STATUS.md` + GitHub Issue/PR + `DECISIONS.md`。
- GPT 默认读取 `STATUS.md`、`PROJECT_SOURCE.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`DECISIONS.md` 和任务相关 deep canonical。
- Draft PR / PR 是交付容器，不代表自动 merge。
- 文档任务中若发现代码/数据不一致，只记录后续任务，不顺手修代码或写数据。
- Stage 6 S6-03 historical/reference/live-target freshness、S6-04 historical/live context、S6-05 T3 单次真实 live Gate、S6-06 T4 单交易日归档与 S6-07 EOD automation Gate 均已通过。OOS/walk-forward 默认只写文件或隔离数据库；后续 SignalEvent、通知、五交易日长稳、canonical PostgreSQL 或其他真实写入仍须各自审批，不得继承 S6-07 授权。
- D4-00 以仓库证据为准：任务完成 ≠ XMA 语义已 Audited；后续只消费 `data/reports/indicator_contract_v1/`，不重开源码/XMA 公式审计。
- HTDY original 的 exact realtime policy 是独立观察例外，不把 Registry 项普通提升为
  `live_capable` 或 `alert_capable`。同一 15m 观察桶第一次检测到的方向、检测时间和快照永久冻结；
  后续重绘、消失、翻转或 source revision 不撤回、不更正、不产生第二条事件。
- 旧 JM V1-B S6-08 schema-v2 packet 已从 Runtime 配置解除引用并标记 superseded；旧 packet
  文件保留为历史证据。新 HTDY S6-08 schema-v3 deployment/rebind/service packets 生成并取得
  Approval A 前，`NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE`。
- 所有敏感凭据只允许通过本机环境或受控系统配置，不写入仓库。
- 工作站精简已冻结；删除以 inventory + Pilot + grep/CI 证据为准，安全 Gate 未削弱。Step 6 Pilot（Issue #43 / PR #44）已合入并标记 `POST_FREEZE_REAL_PILOT_PASSED` / `WORKSTATION_FINAL_CLEANUP_COMPLETE`。
- 工作站支持 backlog 不参与业务 P0 排序，也不得成为全历史盘点、Audit V2、Profile 或消费者契约的前置 Gate。
- ADR-WS-003 只补充 worktree lifecycle；ADR-WS-004 仅在其显式启用前置满足后允许普通 Lane 1/2 使用受控入口创建 draft PR。ADR-WS-002 的精简控制面、不恢复 dispatcher、所有分支的 merge、main/Runtime/Lane 3 不自动 merge/deploy 继续有效。

## 已关闭（不再作为开放决策）

- Profile target-aware 选优与 eligible current candidate binding rollout：阶段 B 已完成；规则与证据保留为历史事实，不重新列为未决。
- Market / Backtest / Signal / Review formal consumer contract 与 Golden Query 验收口径：C2-05 已通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- D4-00 是否重开：关闭。审计任务已执行并落盘；残留 XMA(6)/VAR23/provenance 属后续独立证据任务，不重开公式审计。
- 完整 Cursor→Codex 分波工具顺序：关闭。当前正式模型为 GitHub Issue/PR + GPT + Codex + 用户；不再把分波交接写成现行流程。
- Indicator Registry 是否仍为临时态：关闭。`INDICATOR_REGISTRY_V1_READY` 已是正式状态。
- 旧多状态源摘要是否归档：关闭。相关目录已从 active tree 删除；事实以根目录 canonical + GitHub Issue/PR 为准。
- 旧多入口控制面是否恢复：关闭。一律不恢复（详见 ADR-WS-002 Deleted components）。

## 后续需决策

- Audit V2 residual 的 calendar/session 历史有效性、physical partial 与 failed quality 的分批处置口径（非阻塞 P1）。
- `research_only` schema/API 语义是否拆分。
- Web trust audit 专项展示和公共 chunk 拆包优先级。
- HTDY S6-08 schema-v3 deployment/rebind/service Gate、S6-09 指定事件单条企业微信、S6-10 schema-v6 剩余交易日窗口和 S6-11 最终验收仍按各自 task 契约串行执行；本次合同冻结不预写任何 Ready。

## ADR

| ADR | 状态 | 结论 |
|---|---|---|
| `docs/decisions/ADR-WS-001-github-native-control-plane.md` | Superseded | 历史：GitHub Native V3 五层事实模型；已被 ADR-WS-002 取代 |
| `docs/decisions/ADR-WS-002-simplified-github-codex-workstation.md` | Accepted | GitHub Issue/PR + GPT + Codex + 用户；`STATUS.md` 为当前状态；业务专用 hash-bound Gate；不恢复旧控制面 |
