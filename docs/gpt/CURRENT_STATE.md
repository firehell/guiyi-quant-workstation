# 当前项目状态

更新时间：2026-07-18

用途：浏览器 GPT 当前事实速览。代码、数据库和审计产物优先于历史聊天；历史验收文档保留历史数字，不自动代表当前状态。

## 总体结论

当前数据层最终状态：

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT
CONSUMER_CONTRACT_GAPS_IDENTIFIED
BACKTEST_PROFILE_CONTRACT_READY
SIGNAL_REVIEW_PROFILE_LINEAGE_IMPLEMENTED  # external binding Gate pending
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

`DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT` 仅表示 `DATA-ASSET-PROFILE-ACCEPTANCE-009` 的资产与 Profile hard Gate 已通过。C2-01 已冻结 consumer gaps；Backtest contract 已完成服务端 binding、stable error code、immutable snapshot、隔离 PostgreSQL roundtrip 和 canonical `20260718_0024` 应用，状态为 `BACKTEST_PROFILE_CONTRACT_READY`。Signal / Review formal lineage 代码和回归已收口，但 canonical JM actual-contract 5m/15m eligible binding 为 0，状态保持 `CODE_COMPLETE_EXTERNAL_GATE_PENDING / SIGNAL_REVIEW_PROFILE_LINEAGE_IMPLEMENTED`。Market indicator consumer 尚未收口。

## 当前事实源

| 文件 | 职责 |
|---|---|
| `PROJECT_SOURCE.md` | 长期目标和边界 |
| `STATUS.md` | 当前状态和未完成 Gate |
| `CODEX_TASKS.md` | 当前任务池和后续顺序 |
| `docs/DATA_CENTER.md` | 数据层 deep canonical |
| `docs/ARCHITECTURE.md` | 系统架构 deep canonical |
| `docs/BACKTEST_ENGINE.md` | 回测 deep canonical |
| `docs/SIGNAL_EVENTS.md` | 信号/企业微信 deep canonical |
| `docs/CODEX_HANDOFF.md` | Codex 接手事实 |
| `docs/gpt/project_sources/00-INDEX.md` | GPT GitHub 读取导航 |
| `docs/gpt/GITHUB_READ_ORDER.md` | GPT 默认读取顺序 |

## 旧 Phase 3 历史快照

以下数字来自 `data/reports/data_layer_final_audit_phase3_20260712/`，现在仅作为旧审计模型历史快照保留，不再作为当前确定下载缺口或批量修复清单：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |
| duplicate_active_rows | 0 |
| duplicate_or_conflicting_assets | 0 |

基于旧 `1853 / 34 / 45` 数字的批量修复继续暂停；全历史物理事实盘点、Audit V2、必要 residual 修复及 Profile acceptance 已由 B2-01 至 B2-09 完成。当前下一步是阶段 C formal consumer contract 审计与逐消费者收口。

历史数据阶段收口包：

- `data/reports/data_stage_closure/data_stage_closure_summary.md`
- `data/reports/data_stage_closure/document_inventory.csv`
- `docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`

本轮 final audit 复跑因 PostgreSQL 缺密码且 API snapshot 502 降级为 `db_snapshot_source=manifest_only`，用于记录环境 Gate，不作为数据完成度唯一口径。

## 当前已完成能力

- JM 最新主连六周期已登记为 `primary / passed`，5m/15m/30m/60m/1d 从 passed 1m 本地聚合。
- `report_id=14` trust audit passed，trade/order/equity/drawdown/cost/lineage 可追溯。
- Backtest formal API、fixed JM、inline、batch 和 runner 已统一 Profile binding、passed-only 与 immutable task/report snapshot；legacy path mode 被隔离为显式 `research_only`。
- Formal historical Signal 与 live-confirmed event 已强制 actual mapping、passed-only、confirmed bar 和 immutable Profile/file snapshot；Review 只能从冻结 snapshot 回到 exact bar window。旧记录不回填。
- Web 当前有 Dashboard、Data、Market、Strategy、Backtest、Signal、Runtime、Review、Settings 路由。
- 指标内核中 EMA 为 validated；MACD/ATR 为 draft；火天大有为 observation-only。
- Stage 9-A preview、Stage 9-B1 受控发送记录/重试框架、Stage 9-B2 historical replay single-send smoke 已具备。
- Runtime health、launchd/frp/nginx 模板和工作站 V1.5 控制面已具备。
- WorkBuddy 控制面修复已合并到 `main`，不再作为业务启动前置阻塞；Demo/Pilot 仍不等于 FROZEN。

## 当前不可宣称

- 不能宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- 不能把 `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 写成全历史数据层验收完成。
- 不能把旧 Phase 3 的 `1853 / 34 / 45` 写成当前确定下载缺口。
- 不能把 105 条 `quality_warning` 升级为 passed。
- 不能把 Stage 9-B2 historical replay single-send smoke 写成 live-confirmed 或长期发送验收。
- 不能声明 `SIGNAL_REVIEW_LINEAGE_READY`；canonical JM actual-contract 5m/15m Profile binding Gate 尚未通过。
- 不能宣称 `T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY`。
- 不能把 `report_id=14` trust audit passed 写成策略盈利、稳定或实盘准入。

## 下一步 P0

1. 独立、授权的 Profile binding rollout 任务补齐 JM actual-contract 5m/15m binding，然后只读复验 `SIGNAL_REVIEW_LINEAGE_READY`。
2. 收口 Market indicator consumer lineage。
3. JM T3-real 单次 live 写入 Gate。
