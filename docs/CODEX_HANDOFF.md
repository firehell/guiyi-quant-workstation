# CODEX_HANDOFF.md

更新时间：2026-07-11

## 1. 接手结论

当前分支：`codex/jm-live-runtime-gate`。Worktree：`/Volumes/扩展盘/guiyi-parallel/jm-live-gate`。基于 `main` @ f29de0dd，已 merge `codex/v1-live-runtime-closure`。

接手时先运行：

```bash
git rev-parse --show-toplevel
git status --short --branch
sed -n '1,240p' tasks/current.md
```

不要覆盖用户未提交文件；`.env`、`.run`、用户 LaunchAgents 和真实凭据不入库。

## 2. 当前可信事实

### Stage 13-G

- `report_id=14`
- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- 155 trades 全部 mapped
- 239 orders 全部 mapped
- trust audit 10/10 passed
- total return 约 -19.29%

审计通过只代表可追溯和内部一致，不代表策略有效。下一步只允许样本外验证设计，不调参改善收益。

### JM 最新主连数据

- version window：`20230103_20260710_v2`
- 1m：290490 rows / passed / RQData direct
- 5m：58098 rows / passed / aggregated from 1m
- 15m：19366 rows / passed / aggregated from 1m
- 30m：10108 rows / passed / aggregated from 1m
- 60m：5904 rows / passed / aggregated from 1m
- 1d：851 rows / passed / grouped by trading_day from 1m
- `jm_main_six_period_latest`：6/6 active passed

### 全品种 Stage 8.6

- products：82 active passed / 8 active partial
- assets：176 active passed / 8 audit pending
- pending：5 个主连 quality warning，3 个 actual-contract 缺 DB 登记
- Stage 9 readiness：90 blocked；本报告不授权企业微信发送

### Live Runtime（代码已 merge，真实 Gate 未通过）

- 状态：`T1_OPS_PASSED / T3_CLOCK_IDLE_NON_TRADING / T3_REAL_PENDING / CODE_COMPLETE_EXTERNAL_GATES_PENDING`
- D0 已建立 `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`，只记录基线、T1 手册、后续 Gate 顺序和 block 条件。
- T1 render-only 已执行：`.run/launchd` 生成 7 个 plist，lint 通过；runtime/log-rotate 脚本已同步到 `~/Library/Application Support/GuiyiQuant/`。
- T1 confirm-load 已执行：API/Web/backtests worker/signals worker/log-rotate 均 loaded，`dev-healthcheck.sh --json --no-start` passed。
- scheduler 和 notification worker 未加载。
- T1 kill/recovery 已执行：API/Web/backtests worker/signals worker 均通过 launchd 自动恢复；最终 `dev-healthcheck.sh --json --no-start` passed。
- T3 已获单次授权并执行两次受控 `--once` smoke；因当前为非交易时段，均返回 `idle / phase=closed / outside_trading_sessions`，未写入 live 表。
- T4-real 未执行。
- 四 feature flag 默认 `false`
- 当前基础 5 个 LaunchAgent loaded；scheduler 和 notification worker missing；未长期开启 live/archive/event/autosend，未写真实 live DB，未发送企业微信。

## 3. active 数据硬约束

```text
provider in (rqdata, local_parquet)
data_role = primary
quality_status != failed
```

严格研究使用 passed。禁止 validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据进入默认 Market、Backtest、Signal。

## 4. 运行与安全

- Compose PostgreSQL / Redis 只绑定 `127.0.0.1`。
- 公网与 macOS launchd 外接卷权限：见 `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`。

## 5. 禁止事项

- 不自动下单，不接实盘账户。
- 不一次性全开 live / archive / autosend flag。
- 不打印或提交 webhook/token/password/license。

## 6. 下一步

1. T3-real：等待下一个 JM/DCE 合法交易时段，再执行真实 1m + 聚合 + 重启续跑（仅 `GUIYI_LIVE_RUNTIME_ENABLED=true`）。
2. T4-real：T3 真实写入通过后，再单独授权盘后归档。

详见 `docs/tasks/JM-LIVE-GATE-EVIDENCE.md` 与 `docs/tasks/TASK-2026-07-11-004-jm-live-runtime-gate.md`。注意：`scripts/rqdata_realtime_poc.py` 中的 `JM2609` 仅是旧只读 PoC 示例，不是 T3 runtime scheduler 入口。

## 7. 必读文件

- `AGENTS.md`
- `tasks/current.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- `docs/gpt/NEXT_STEPS.md`

## 8. 最小验证

```bash
uv run --project services/quant-api pytest services/quant-api/tests/ -q
bash -n scripts/run-local-service.sh scripts/dev-healthcheck.sh
git diff --check
```
