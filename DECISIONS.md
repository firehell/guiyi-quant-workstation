# 架构决策记录

更新时间：2026-07-17

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
| 历史/live 分层 | live DB 与 historical canonical 分离 | live 数据盘后必须重新获取 provider 最终历史数据并通过完整 Gate |
| 数据最终状态 | 当前为 `DATA_LAYER_REAUDIT_REQUIRED` + `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS`；`DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 尚未通过 | `DATA-PART-TARGET-CLOSURE` 仅是先前数据部分目标收口；manifest 强支持物理数据大规模下载，但 DB/Profile/consumer 尚未封板 |
| 指标内核 | EMA validated；MACD/ATR draft；火天大有 observation-only | XMA/火天大有不得进入回测、live evaluator、`signal_events` 或提醒链路 |
| 回测口径 | vn.py CTA + 自定义 adapter/runner/result converter/trust audit | `next_bar_open`、成本、乘数、tick、lineage 必须可追溯 |
| 信号提醒 | 企业微信只做观察提醒 | 不自动下单，不生成订单草稿 |
| live 数据 | live tables 与 historical active 分层 | live 不自动登记为可信 historical active |
| 运行部署 | 本地 Mac / Docker / launchd；公网只读入口为腾讯云 Nginx + FRP 模板 | 配置通过不等于真实远端验收通过 |
| 工作站协作 | GitHub Native V3 控制平面：main canonical docs / task branch TASK / Issue lifecycle / Draft PR delivery / local `.ai/results` evidence | Issue 不取代 TASK；GPT 不直写 main；Codex 仍是唯一编码执行器；用户保留 Plan、生产写入、merge、deploy 最终批准权 |
| WorkBuddy Unified V3 | WorkBuddy 是上班/远程统一协调入口；只通过 `scripts/ai/workbuddy_task.sh` 白名单 facade 触发受控脚本；CodeBuddy compatibility-only | WorkBuddy 对话和 memory 不是状态源；不自由 shell、不模糊审批、不自动串 stage、不 push/merge/deploy；控制面修复已合并，不再作为业务启动前置阻塞 |
| 工作站支持模式 | `WORKSTATION_NON_BLOCKING_SUPPORT_MODE` | WorkBuddy Demo、旧 Issue / PR 清理和文档迁移可继续但不阻塞 Audit V2；后续只修真实业务 Task 暴露的可复现缺陷，不扩展多项目、复杂模型路由、自动 merge/deploy、Dashboard 或代理团队模拟 |

## 当前重要取舍

- `DATA_LAYER_REAUDIT_REQUIRED` 优先于乐观 ready 叙述；未完成 Gate 必须保留。
- provider earliest 权威证据缺失时，V2 可将 canonical physical minimum 标记为 `start_boundary_supported`，无物理支持则为 `start_boundary_unverified`；两者均不得冒充 provider authoritative exact，也不得据此通过严格 data Gate。
- direct 1d 用于长周期研究/provider reference；derived 1d 只来自 passed 1m；direct 1w 使用 provider 完成周 bar，不要求等于上市日。
- 五层状态 `physical_coverage / registration / quality / reference_metadata / profile_eligibility` 必须独立保存，warning 不得折叠为 passed，partial 不得进入 historical formal consumer。
- `report_id=14` 只能读取和引用，禁止更新、回填、重算覆盖或替换历史 lineage。
- 旧 Phase 3 的 `metadata_gap=1853`、`pre_2020_weekly_missing=34` 和 actual contract 旧固定 gap 只作为历史审计模型快照；当前不基于这些数字直接批量修复。
- `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只说明 manifest 层强支持物理历史数据已大规模下载；不代表 PostgreSQL、quality、Profile binding 和 formal consumer contract 已通过。
- 历史验收文档保持历史数字，不改写成当前状态。
- `docs/gpt/project_sources/` 是 GPT GitHub 读取导航与兼容摘要包，不替代 canonical 文档，也不维护第二份事实结论。
- GPT 默认读取 `docs/gpt/project_sources/00-INDEX.md`、`PROJECT_SOURCE.md`、`STATUS.md`、`DECISIONS.md`、`CODEX_TASKS.md` 和任务相关 deep canonical；截图、外部 PDF、未提交本地文件和 `.ai/results` 原始 evidence 仍需按需提供。
- GitHub Issue 是生命周期和远程入口，不是 dispatcher 执行契约；TASK、V2 Schema 和 `dispatch_task.sh` 必须保留。
- Draft PR 是任务共享容器，用于设计、diff、CI 和 Review；不代表自动 merge。
- `.ai/results/<TASK_ID>/` 保持 local-first，只同步脱敏摘要到 Issue / PR。
- 文档任务中若发现代码/数据不一致，只记录后续任务，不顺手修代码或写数据。
- 所有敏感凭据只允许通过本机环境或受控系统配置，不写入仓库。
- WorkBuddy 控制面修复已合并，不再阻塞 V1 数据重审业务启动；未通过 Demo 和业务 Pilot 前仍不写 `FROZEN`，也不改变主业务 Gate。
- 工作站支持 backlog 不参与业务 P0 排序，也不得成为全历史盘点、Audit V2、Profile 或消费者契约的前置 Gate。

## 后续需决策

- Audit V2 residual 的 calendar/session 历史有效性、physical partial 与 failed quality 的分批处置口径。
- Profile target-aware 选优、binding rollout dry-run/apply/rollback 规则。
- Market / Backtest / Signal / Review formal consumer contract 与 Golden Query 验收口径。
- `research_only` schema/API 语义是否拆分。
- Web trust audit 专项展示和公共 chunk 拆包优先级。
- GPT Sources 兼容摘要是否逐步归档为 `superseded`，以及何时删除重复摘要文件。

## ADR

| ADR | 状态 | 结论 |
|---|---|---|
| `docs/decisions/ADR-WS-001-github-native-control-plane.md` | Accepted | 采用 GitHub Native V3 控制平面五层事实模型，保留 V2 TASK Schema 和 dispatcher |
