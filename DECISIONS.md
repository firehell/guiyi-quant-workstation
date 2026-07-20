# 架构决策记录

更新时间：2026-07-20

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
| 数据最终状态 | `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 已通过；`DATA_LAYER_REAUDIT_REQUIRED` 与其并列 | 前者只关闭 formal Market/Backtest/Signal/Review 的 Profile、lineage 与 Golden Query 准入；后者保留全历史 residual 治理，二者均不可被扩写为 live、OOS、企业微信或自动交易 Ready |
| 指标内核 | EMA validated；MACD/ATR compatibility_validated；HTDY original observation_only / strict strategy_candidate | Registry V1 契约已落地（Cursor 临时态）；XMA/original 不得进入回测、live evaluator、`signal_events` 或提醒链路；正式 `INDICATOR_REGISTRY_V1_READY` 留给 Codex |
| D4-00 HTDY 审计 | 证据落盘完成；最终 Gate `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` | 不重开公式审计；不得宣称 `HTDY_XMA_SEMANTICS_AUDITED`；original 保持 observation-only，strict 仅 formal candidate |
| 本轮工具顺序 | 完整 Cursor Wave → 单次交接 → Codex Wave | 不在 Cursor/Codex 间穿插；正式报告写入、OOS、T3/T4 留给 Codex Wave |
| 回测口径 | vn.py CTA + 自定义 adapter/runner/result converter/trust audit | `next_bar_open`、成本、乘数、tick、lineage 必须可追溯 |
| 信号提醒 | 企业微信只做观察提醒 | 不自动下单，不生成订单草稿 |
| live 数据 | live tables 与 historical active 分层 | live 不自动登记为可信 historical active |
| 运行部署 | 本地 Mac / Docker / launchd；公网只读入口为腾讯云 Nginx + FRP 模板 | 配置通过不等于真实远端验收通过 |
| 工作站协作 | **GitHub + GPT + Codex + 用户**；Issue/PR 为任务生命周期；`STATUS.md` 为项目状态 | 不把 WorkBuddy/CodeBuddy/dispatcher 作为正式架构；工程入口迁向 `scripts/engineering/*` |
| 工作站精简 | `WORKSTATION_SIMPLIFICATION_IN_PROGRESS`；目标 `WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY` | 以 `WORKSTATION_SIMPLIFICATION_INVENTORY.md` 为删除/迁移依据；未发现调用 ≠ 可删；Gate 不得削弱 |
| 工作站支持模式 | `WORKSTATION_NON_BLOCKING_SUPPORT_MODE`（保留） | 精简与历史清理不阻塞业务 Gate；不扩展多项目/自动 merge/代理团队模拟 |

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
- 下一轮按策略可信验证、JM T3/T4 真实 Gate 串行推进；OOS/walk-forward 默认只写文件或隔离数据库，canonical PostgreSQL 写入须单独审批。
- D4-00 以仓库证据为准：任务完成 ≠ XMA 语义已 Audited；后续只消费 `data/reports/indicator_contract_v1/`，不重开源码/XMA 公式审计。
- 所有敏感凭据只允许通过本机环境或受控系统配置，不写入仓库。
- 工作站精简期间保留 `WORKSTATION_NON_BLOCKING_SUPPORT_MODE`；删除旧控制面必须以 inventory + Pilot + grep/CI 证据为准，不得削弱安全 Gate。
- 工作站支持 backlog 不参与业务 P0 排序，也不得成为全历史盘点、Audit V2、Profile 或消费者契约的前置 Gate。

## 已关闭（不再作为开放决策）

- Profile target-aware 选优与 eligible current candidate binding rollout：阶段 B 已完成；规则与证据保留为历史事实，不重新列为未决。
- Market / Backtest / Signal / Review formal consumer contract 与 Golden Query 验收口径：C2-05 已通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- D4-00 是否重开：关闭。审计任务已执行并落盘；残留 XMA(6)/VAR23/provenance 属后续独立证据任务，不在 Cursor Wave 重开。

## 后续需决策

- Audit V2 residual 的 calendar/session 历史有效性、physical partial 与 failed quality 的分批处置口径（非阻塞 P1）。
- `research_only` schema/API 语义是否拆分。
- Web trust audit 专项展示和公共 chunk 拆包优先级。
- GPT Sources 兼容摘要是否逐步归档为 `superseded`，以及何时删除重复摘要文件。
- 工作站精简 Step 5–7：真实 Pilot、legacy 删除范围、最终 freeze 时机（由用户 merge / 验收决定）。
- 阶段 5/6 各 Task 的具体审批包、OOS 硬拒绝阈值与 JM T3/T4 写入窗口（按手册串行冻结，不在本文件预写 Ready）。

## ADR

| ADR | 状态 | 结论 |
|---|---|---|
| `docs/decisions/ADR-WS-001-github-native-control-plane.md` | Accepted | 采用 GitHub Native V3 控制平面五层事实模型，保留 V2 TASK Schema 和 dispatcher |
