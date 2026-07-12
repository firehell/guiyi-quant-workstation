# TASK-2026-07-12-020：JM Live T3/T4/长稳 Gate 执行

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-020-jm-live-t3-t4-long-run-gate |
| 日期 | 2026-07-12 |
| 分支 | `main`（文档）；runtime 副本 `ops/local-runtime-disk` |
| Base | TASK-2026-07-12-017、TASK-2026-07-12-019 |
| 状态 | `DELIVERY_READY_GATE_EXECUTION_BLOCKED_EXTERNAL` |
| 类型 | live runtime gate execution |

## 目标

按 `JM-LIVE-T3-T4-LONG-RUN-GATE` 计划，在 runtime 副本完成三个独立人工 Gate：

1. **T3**：JM 单次真实 1m live 写入 + 幂等复跑 + kill/recovery
2. **T4**：单交易日盘后归档 + `already_archived` 幂等复跑
3. **T7**：5 交易日 supervised 长稳 + 夜盘/断线/故障注入

## 当前结论（2026-07-12 21:47 CST）

```text
PHASE0_PREFLIGHT_PASSED
T3_BLOCKED_BY_NON_TRADING_TIME
T3_REAL_PENDING
T4_BLOCKED_PENDING_T3
T7_BLOCKED_PENDING_T3_T4
```

不可声明：`T3_REAL_PASSED` / `T4_REAL_PASSED` / `JM_RUNTIME_READY` / `LONG_RUNNING_READY`

## 运行位置

| 项 | 路径 |
|---|---|
| 开发/文档主仓库 | `/Volumes/扩展盘/guiyi-quant-workstation` |
| Gate 执行副本 | `~/GuiyiRuntime/guiyi-quant-workstation-runtime` |
| launchd env | `~/Library/Application Support/GuiyiQuant/project.env` |

## 四 flag 互斥规则

| Flag | T3 | T4 | T7 |
|---|---|---|---|
| `GUIYI_LIVE_RUNTIME_ENABLED` | 临时 true | false | 长期 true（仅 T7 窗口） |
| `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED` | false | false | false |
| `GUIYI_AFTER_MARKET_ARCHIVE_ENABLED` | false | 临时 true | false |
| `GUIYI_WECHAT_AUTOSEND_ENABLED` | false | false | false |

## Phase 0：Pre-flight（已完成）

```bash
cd ~/GuiyiRuntime/guiyi-quant-workstation-runtime
git status --short --branch
./scripts/local-services-status.sh
./scripts/dev-healthcheck.sh --json --no-start
cd services/quant-api && uv run python -m app.runtime_scheduler --dry-run --product jm
```

结果：

- `supervised_runtime_root` = runtime 副本（一致）
- `dev-healthcheck`: `status=passed`
- dry-run: 四 `would_write_*=false`，`auto_order=false`
- 基础 5 LaunchAgent loaded；scheduler / notification missing
- live 四表 count=0

证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §13.0

## Gate T3：单次真实 live

### 授权模板（人工确认后执行）

```text
允许本次 JM T3 真实 RQData 读取，并允许写入 live 四表和 checkpoint；
仅临时开启 GUIYI_LIVE_RUNTIME_ENABLED=true，其余三 flag 保持 false。
不包含 signal event、archive、企业微信或交易执行。
```

### T3-A：首次 `--once`

```bash
cd ~/GuiyiRuntime/guiyi-quant-workstation-runtime/services/quant-api
# 加载 project.env（同 run-local-service.sh）
set -a && source "$HOME/Library/Application Support/GuiyiQuant/project.env" && set +a
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi

GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run python -m app.runtime_scheduler \
  --once --confirm-live-write --product jm
```

通过标准：`status=success`；`upserted >= 1`；多周期聚合可解释；`writes_historical_active=false`。

### T3-B：幂等复跑（同 Gate，间隔 ≥1 poll 周期）

重复 T3-A 命令两次；第 2 次 `unchanged_count` 上升或 `upserted=0`；checkpoint 不倒退。

### T3-C：kill/recovery（同 Gate）

记录 checkpoint → kill 进程 → 再次 `--once` → 无漏 bar、无唯一键冲突。

### 本轮执行结果

2026-07-12 21:47 CST（周日非交易时段）两次 `--once` 均返回 `idle` / `outside_trading_sessions`；live 四表仍为 0。T3-B/C 待 T3-A 真实 bar 写入后执行。

证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §13

## Gate T4：单交易日盘后归档

### 授权模板

```text
允许本次 JM T4 真实 RQData 盘后读取，并允许 historical Parquet + metadata 归档写入；
仅临时开启 GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=true，其余三 flag 保持 false。
```

### T4-A：dry-run

```bash
cd ~/GuiyiRuntime/guiyi-quant-workstation-runtime
uv run --project services/quant-api python scripts/after_market_archive.py \
  --product jm --trading-day <YYYY-MM-DD>
```

### T4-B：真实归档

```bash
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=true \
GUIYI_LIVE_RUNTIME_ENABLED=false \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run --project services/quant-api python scripts/after_market_archive.py \
  --product jm --trading-day <YYYY-MM-DD> \
  --run-write --confirm-after-market-archive
```

### T4-C：幂等复跑

重复 T4-B；第二次应返回 `status=already_archived`。

### 本轮执行结果

T4-A dry-run（`trading_day=2026-07-11`）passed；T4-B/C 阻塞于 `T3_REAL_PENDING`。

证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §14

## Gate T7：5 交易日长稳

### 授权模板

```text
允许 5 个真实交易日 supervised live runtime 观察与故障注入；
仅临时开启 GUIYI_LIVE_RUNTIME_ENABLED=true 并加载 scheduler LaunchAgent；
T5/T6 flag 保持 false；企业微信 autosend 保持关闭。
```

### 运行模式

```bash
# project.env 设 GUIYI_LIVE_RUNTIME_ENABLED=true
./scripts/install-local-services.sh --confirm-load  # 加载 scheduler
```

### 日程

| 日次 | 重点 |
|---|---|
| D1 | 日盘 ingest + 聚合 + health |
| D2 | 夜盘跨自然日 trading_day |
| D3 | 重复 bar 幂等 |
| D4 | kill scheduler → launchd 恢复 |
| D5 | 日终 T4 mini-Gate + `already_archived` |

### 故障注入

kill scheduler / API / worker；Redis/PostgreSQL 短暂不可用；可选 Mac 重启；断网/RQData 超时。

### 本轮执行结果

阻塞于 `T3_REAL_PENDING` + `T4_REAL_PENDING`；§15 已记录执行手册与验收清单。

证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §15

## 必须暂停的 Gate

- 非 JM 可交易时段（`idle` ≠ T3 通过）
- `actual_contract` 无法动态解析
- health 非 ok
- 非本 Gate 授权 flag 为 true
- T4 目标日未收盘
- 两个 runtime 副本同时 loaded scheduler

## Codex 后续 Prompt

**Phase 1 — T3-real**（需用户授权 + 可交易时段）

> 于 runtime 副本执行 T3-A/B/C；审计 live 四表；更新 JM-LIVE-GATE-EVIDENCE §13.1–§13.3。

**Phase 2 — T4-real**（需用户单独授权 + 收盘日）

> T4-A dry-run → T4-B → T4-C；更新 §14。

**Phase 3 — T7**（需用户单独授权 + 5 交易日）

> 临时加载 scheduler；D1–D5 观察 + 故障注入；bootout scheduler；更新 §15。

## 相关文档

- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
- `docs/tasks/TASK-2026-07-12-017-jm-single-live-gate-plan.md`
- `docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
