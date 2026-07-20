# NEXT_STEPS.md

更新时间：2026-07-20

## 总原则

- 数据可信度、可追溯和可复算优先于收益和功能扩展。
- 当前不做自动交易、实盘账户、SaaS、多用户或大型重构。
- live、scheduler、数据写入、schema 和公网部署必须分阶段 Gate。
- 文档和 GPT Sources 必须来自仓库事实源，不靠聊天复述。

## 当前状态

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
STAGE4_COMPLETED
STAGE5_COMPLETED
STAGE6_CANONICAL_SYNCED
JM_HISTORICAL_CATCHUP_READY
JM_REFERENCE_METADATA_FRESH
JM_LIVE_TARGET_FRESHNESS_READY
JM_LIVE_CONTEXT_READY
```

当前 manifest 强支持物理历史数据已大规模下载；formal consumer contract 已通过并进入 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。旧 Phase 3 的 `1853 / 34 / 45` 数字只作为历史审计模型快照保留，暂停直接批量修复。阶段 4/5 已关闭，当前阶段为 Stage 6。

## P0 后续任务

1. **S6-05：T3**
   - 输入：`JM_LIVE_CONTEXT_READY`、`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` 和当前 runtime preflight。
   - 目标：按独立审批包执行 JM live 表/checkpoint 真实 Gate，不扩展其他品种。
   - 不得自动进入 SignalEvent、通知、T4 archive 或长稳。

2. **S6-03/S6-04 已关闭**
   - target=`2026-07-17`、actual=`JM2609`；14 canonical assets、18 Profile bindings 和三个 Gate 已通过。
   - historical/live context 使用 previous DCE trading day freshness、historical-first exact dedupe、OHLCV conflict fail-closed 和双来源 lineage。
   - 证据：`data/reports/jm_historical_catchup_s6_03/s6_03_20260717_0bfd88fc/`、`docs/tasks/JM-LIVE-CONTEXT-S6-04.md`。

3. **S6-06 至 S6-07：T4/EOD Automation**
   - 输入：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
   - 条件：前置 Gate 通过 + 用户逐次显式确认。
   - T3 只允许 live 表/checkpoint；T4 只允许 JM provider final historical archive；EOD Automation 需独立 scheduler/lock/heartbeat/health。

4. **S6-08 至 S6-10：SignalEvent、单条通知和五交易日长稳**
   - 前置：T3/T4/EOD/live context 已通过，且存在合法 live observation / signal event 策略资格。
   - 无 eligible strategy 时可形成合法阻断，不得为了全绿修改被拒绝策略。

## P1 后续任务

1. Audit V2 residual 维护治理。
2. Web trust audit 专项展示。
3. 公共 chunk 拆包。
4. `research_only` schema/API 语义拆分。
5. 真实公网安全 smoke。

## GPT GitHub 读取建议

最小集合：

- `docs/gpt/project_sources/00-INDEX.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `DECISIONS.md`
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`
- `docs/gpt/GITHUB_READ_ORDER.md`

完整集合：

- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`

兼容摘要：

- `docs/gpt/project_sources/01-*.md` 到 `13-*.md` 只作为旧上传流程兼容包；事实冲突时以 canonical 文件为准。

专题补充集合：

- 数据：`docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md`
- 回测：`docs/STAGE13_BACKTEST_TRUST_AUDIT.md`、`docs/BACKTEST_ENGINE.md`
- 信号：`docs/SIGNAL_EVENTS.md`、`docs/STAGE9_WECHAT_DELIVERY.md`
- live：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- 工作站：`docs/workstation/`、`docs/workflows/`
