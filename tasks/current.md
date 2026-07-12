# 当前任务：JM-LIVE-T3-T4-LONG-RUN-GATE

生成时间：2026-07-12

状态：`GATE_EXECUTION_BLOCKED_EXTERNAL`

## 本轮完成

| Step | 任务 | 状态 |
|---|---|---|
| Phase 0 | runtime 副本只读 pre-flight | `PASSED` |
| Gate T3-A | 首次真实 `--once` | `BLOCKED_BY_NON_TRADING_TIME` |
| Gate T3-B/C | 幂等复跑 + kill/recovery | `PENDING_TRADING_SESSION` |
| Gate T4-A | 盘后归档 dry-run | `PASSED` |
| Gate T4-B/C | 真实归档 + 幂等复跑 | `BLOCKED_PENDING_T3` |
| Gate T7 | 5 交易日长稳 | `BLOCKED_PENDING_T3_T4`（手册已落档 §15） |

## 关键结论

```text
PHASE0_PREFLIGHT_PASSED
T3_BLOCKED_BY_NON_TRADING_TIME
T3_REAL_PENDING
T4A_DRY_RUN_PASSED
T4_BLOCKED_PENDING_T3
T7_BLOCKED_PENDING_T3_T4
```

不可声明：`T3_REAL_PASSED` / `T4_REAL_PASSED` / `JM_RUNTIME_READY` / `LONG_RUNNING_READY`

## 运行位置

- 开发主仓库：`/Volumes/扩展盘/guiyi-quant-workstation`
- Gate 执行副本：`~/GuiyiRuntime/guiyi-quant-workstation-runtime`（`ops/local-runtime-disk`）

## 运行命令

```bash
# Phase 0 pre-flight（只读）
cd ~/GuiyiRuntime/guiyi-quant-workstation-runtime
./scripts/local-services-status.sh
./scripts/dev-healthcheck.sh --json --no-start
cd services/quant-api && uv run python -m app.runtime_scheduler --dry-run --product jm

# T3-real（需可交易时段 + 用户授权）
cd ~/GuiyiRuntime/guiyi-quant-workstation-runtime/services/quant-api
set -a && source "$HOME/Library/Application Support/GuiyiQuant/project.env" && set +a
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi
GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run python -m app.runtime_scheduler --once --confirm-live-write --product jm

# T4 dry-run
cd ~/GuiyiRuntime/guiyi-quant-workstation-runtime
uv run --project services/quant-api python scripts/after_market_archive.py \
  --product jm --trading-day <YYYY-MM-DD>
```

## 证据路径

- `docs/tasks/TASK-2026-07-12-020-jm-live-t3-t4-long-run-gate.md`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §13–§15

## 硬约束

- 未开启企业微信 autosend
- 未开启 T5 signal event
- 未执行 T4 真实 `--run-write`
- 未加载 `com.guiyi.quant-runtime-scheduler`
- 未自动 commit / push / merge

## 下一步（需人工 Gate）

1. JM 可交易时段 + 用户显式授权 → 执行 T3-A/B/C（§13.1–§13.3）
2. T3 `PASSED` 后 + 收盘日 + 单独授权 → T4-B/C（§14）
3. T3+T4 `PASSED` 后 + 5 交易日授权 → T7 长稳（§15）

## 任务单

- `docs/tasks/TASK-2026-07-12-020-jm-live-t3-t4-long-run-gate.md`
- `docs/tasks/TASK-2026-07-12-017-jm-single-live-gate-plan.md`
- `docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`
