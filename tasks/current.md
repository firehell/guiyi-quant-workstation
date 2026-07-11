# 当前任务：JM-LIVE-RUNTIME-GATE（并行 Codex 会话 D）

更新时间：2026-07-11

任务单：`docs/tasks/TASK-2026-07-11-004-jm-live-runtime-gate.md`

分支：`codex/jm-live-runtime-gate`

Worktree：`/Volumes/扩展盘/guiyi-parallel/jm-live-gate`

当前状态：`T1_OPS_PASSED / T3_CLOCK_IDLE_NON_TRADING / T3_REAL_PENDING / CODE_COMPLETE_EXTERNAL_GATES_PENDING`（merge 完成，D0 证据账本已建立；T1 render-only、基础服务加载、strict health 和 kill/recovery 已通过；T3 已获单次授权并在非交易时段返回 idle，尚未完成真实 1m 写入）

## 目标

把 once 级 live 代码收敛为默认关闭、可监督、可恢复、可审计的 JM actual-contract 运行闭环，严格按 Gate 推进 T1-ops → T3-real。

## 本轮完成的开发范围（merge 自 v1-live-runtime-closure）

- [x] T0–T7-code：scheduler、交易时钟、1m→多周期、盘后归档、live event、notification worker、launchd 模板
- [x] merge `codex/v1-live-runtime-closure` 到本分支
- [x] D0：建立 `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`，冻结真实 Gate 证据格式、T1 手册和后续 Gate 顺序
- [x] T1 render-only：生成 `.run/launchd` 7 个 plist，lint 通过；同步 runtime/log-rotate 脚本；未执行 `--confirm-load`
- [x] T1 confirm-load：基础 5 个 launchd label 已加载；scheduler/notification 未加载；`dev-healthcheck.sh --json --no-start` passed
- [x] T1 kill/recovery：API/Web/backtests worker/signals worker 受控 kill 后 launchd 自动拉起；最终 healthcheck passed
- [x] T1-ops：基础服务监督 Gate passed
- [x] T3 授权确认与 dry-run：仅授权真实 RQData 读取和 live 表/checkpoint 写入；dry-run confirmed no DB/Redis/RQData/live writes
- [x] T3 非交易时段 smoke：两次 `--once --confirm-live-write --product jm` 均返回 `idle / phase=closed / outside_trading_sessions`；live 表与 checkpoint 表仍为 0 行
- [ ] T3-real：JM 单次真实 1m、全周期聚合和重启恢复 smoke
- [ ] T4-real：至少一个 JM 交易日真实盘后归档 smoke（后置）

## Feature flags（全部默认 false）

```text
GUIYI_LIVE_RUNTIME_ENABLED
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED
GUIYI_WECHAT_AUTOSEND_ENABLED
```

## 硬边界

- 不修改 `apps/quant-web/`
- 不 CTP / 自动下单
- 每步只开一个 flag
- D0 不加载 LaunchAgent、不写真实 DB、不发送企业微信
- `scripts/rqdata_realtime_poc.py` 是旧只读 PoC，不作为 T3 runtime Gate 入口

## 验收

见 `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md` 与 `docs/tasks/TASK-2026-07-11-004-jm-live-runtime-gate.md`。
