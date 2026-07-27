# JM Live Gate Evidence

更新时间：2026-07-11

> Historical Snapshot / Superseded：本文件保留 T1/T3 早期真实 Gate 证据账本，顶部“当前结论”是当时快照。当前项目状态以 `STATUS.md`、`docs/tasks/JM-LIVE-T3-S6-05.md` 和 `docs/tasks/JM-AFTER-MARKET-ARCHIVE-S6-06.md` 为准：S6-05 已达成 `T3_REAL_PASSED`，下一入口为 S6-06 T4（`REAL_ARCHIVE_APPROVAL_PENDING` / `JM_ARCHIVE_PENDING`）。

## 1. 当前结论

当前状态：

```text
T1_OPS_PASSED
T3_CLOCK_IDLE_NON_TRADING
T3_REAL_PENDING
CODE_COMPLETE_EXTERNAL_GATES_PENDING
```

本文件是 `TASK-2026-07-11-004-jm-live-runtime-gate` 的真实 Gate 证据账本。当前已完成 D0 基线核对、T1 render-only、T1 基础服务加载、strict health 检查和 T1 kill/recovery。T3 已获单次授权并执行非交易时段 smoke，因交易时钟返回 `idle`，T3-real 尚未通过。

当前边界：

- 未加载 `com.guiyi.quant-runtime-scheduler` 或 `com.guiyi.quant-worker-notifications`；未卸载基础 5 个 LaunchAgent。
- 未长期开启 `GUIYI_LIVE_RUNTIME_ENABLED`；T3 smoke 只在单次命令进程中临时设为 `true`。
- 未开启 `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED`。
- 未开启 `GUIYI_AFTER_MARKET_ARCHIVE_ENABLED`。
- 未开启 `GUIYI_WECHAT_AUTOSEND_ENABLED`。
- 未写入真实 `live_minute_bars`、live 聚合表或 checkpoint。
- 未执行企业微信发送。
- 未声明 `JM_RUNTIME_READY`、`LONG_RUNNING_READY` 或 `FULL_UNIVERSE_READY`。

验收编号沿用现有文档：`T1`、`T3`、`T4`、`T5`、`T6`、`T7`。当前验收定义中没有 `T2`，本任务不新增 T2。

## 2. D0 基线

| 字段 | 证据 |
|---|---|
| Worktree | `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` |
| Branch | `codex/jm-live-runtime-gate` |
| HEAD | `3d27fe9a7e1f0a8a7401d3a3dc5d27bf06bb46a6` |
| 前置 merge | `a7df3aac` 已是当前 HEAD 祖先 |
| 当前任务状态 | `T1_OPS_PASSED / T3_CLOCK_IDLE_NON_TRADING / T3_REAL_PENDING / CODE_COMPLETE_EXTERNAL_GATES_PENDING` |
| T1/T3 小步状态 | `T1_OPS_PASSED / T3_AUTH_CONFIRMED / T3_DRY_RUN_PASSED / T3_CLOCK_IDLE_NON_TRADING / T3_REAL_PENDING` |
| 禁止范围 | 不改 `apps/quant-web/`、`.env`、真实数据目录、CTP、账户、订单、自动交易接口 |

D0 只读核对结论：

- `.env.example` 中四个真实开关默认均为 `false`。
- `runtime_scheduler` 只允许 `--product jm`。
- `runtime_scheduler --once/--run` 必须同时满足 `--confirm-live-write` 与 `GUIYI_LIVE_RUNTIME_ENABLED=true`。
- `install-local-services.sh` 默认只加载基础服务：API、Web、backtests worker、signals worker、log rotate。
- `com.guiyi.quant-runtime-scheduler` 仅在 `GUIYI_LIVE_RUNTIME_ENABLED=true` 时加载。
- `com.guiyi.quant-worker-notifications` 仅在 `GUIYI_WECHAT_AUTOSEND_ENABLED=true` 时加载。
- `runtime_health` 对 worker missing、scheduler heartbeat missing/stale、live checkpoint missing/stale 会返回 degraded 或 failed，不应假绿。
- `scripts/rqdata_realtime_poc.py` 中的 `CONTRACT = "JM2609"` 是旧只读 PoC 示例，不是 T3 runtime scheduler 入口；T3 禁止使用该脚本作为真实 Gate 命令。

## 3. 开关清单

| Flag | D0 默认 | T1 | T3 | T4 | T5 | T6 |
|---|---|---|---|---|---|---|
| `GUIYI_LIVE_RUNTIME_ENABLED` | `false` | `false` | 临时 `true` | `false` | 按独立授权 | 按独立授权 |
| `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED` | `false` | `false` | `false` | `false` | 临时 `true` | 按独立授权 |
| `GUIYI_AFTER_MARKET_ARCHIVE_ENABLED` | `false` | `false` | `false` | 临时 `true` | `false` | `false` |
| `GUIYI_WECHAT_AUTOSEND_ENABLED` | `false` | `false` | `false` | `false` | `false` | 临时 `true` |

硬规则：每个 Gate 只允许打开本 Gate 需要的一个开关。任何环境残留 true 都必须先停止并记录，不得继续。

## 4. 服务清单

### T1 基础服务

T1 只允许加载：

| Label | 入口 | 作用 |
|---|---|---|
| `com.guiyi.quant-api` | `scripts/run-local-service.sh api` | FastAPI |
| `com.guiyi.quant-web` | `scripts/run-local-service.sh web` | 静态 Web preview |
| `com.guiyi.quant-worker-backtests` | `scripts/run-local-service.sh worker-backtests` | backtests queue |
| `com.guiyi.quant-worker-signals` | `scripts/run-local-service.sh worker-signals` | signals queue |
| `com.guiyi.quant-log-rotate` | `scripts/rotate-local-service-logs.sh` | 日志轮转 |

T1 禁止加载：

| Label | 原因 |
|---|---|
| `com.guiyi.quant-runtime-scheduler` | 会进入 live runtime 外部 Gate |
| `com.guiyi.quant-worker-notifications` | 属于企业微信 autosend 后置 Gate |

日志目录：`~/Library/Logs/GuiyiQuant`。

运行环境文件：`~/Library/Application Support/GuiyiQuant/project.env`。该路径包含空格，后续执行命令和文档必须保持正确引用，不得打印凭据内容。

## 5. Gate 记录模板

每个 Gate 必须保留以下字段：

| 字段 | 内容 |
|---|---|
| Gate | T1/T3/T4/T5/T6/T7 |
| 时间窗口 | 开始、结束、时区 |
| Git commit | 执行时 HEAD |
| 配置摘要 | 四 flag 状态，凭据只记录 present/missing |
| actual contract | product、continuous contract、rank、actual contract、mapping date、resolver source |
| 运行服务 | launchd label、PID、queue coverage |
| checkpoint | 执行前后值 |
| 数据结果 | 新增、更新、重复、缺失、warning |
| health | 中断、恢复、stale、failed、ok |
| 测试结果 | 命令、exit code、摘要 |
| 外部证据 | RQData、企业微信、HTTPS/WS，只记录脱敏摘要 |
| 结论 | `PASSED` / `FAILED` / `BLOCKED_BY_EXTERNAL_CONDITION` |
| 回滚结果 | 开关是否关闭，服务是否恢复 |

## 6. T1 执行手册

T1 目标：恢复基础受监督服务并验证 strict health，不开放 JM live 写入。

执行前检查：

```bash
git status --short --branch
grep -E 'GUIYI_(LIVE_RUNTIME|LIVE_SIGNAL_EVENTS|AFTER_MARKET_ARCHIVE|WECHAT_AUTOSEND)_ENABLED=' .env.example
scripts/install-local-services.sh --render-only
scripts/local-services-status.sh
```

外接卷 Gate：

- 当前 worktree 在 `/Volumes/` 下。
- 若未人工授予后台进程外接卷访问权限，`scripts/install-local-services.sh --confirm-load` 应被视为 blocked。
- 未显式确认 `GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1` 时，不得绕过保护。
- block 记录使用：

```text
T1_OPS_BLOCKED_EXTERNAL_VOLUME_PERMISSION
```

人工确认后才允许基础服务加载：

```bash
scripts/install-local-services.sh --confirm-load
scripts/dev-healthcheck.sh --json --no-start
```

T1 验收：

- API、Web、backtests worker、signals worker、log rotate 均被 launchd 监督。
- runtime scheduler 未加载。
- notification worker 未加载。
- `/healthz`、`/api/health` 和 `/api/runtime/health` 正常。
- backtests/signals queue 均有 worker coverage。
- kill API/Web/backtests worker/signals worker 后 launchd 能自动拉起。
- 恢复后 strict runtime health 为 `ok`。
- 日志不包含 password、token、webhook、license、cookie、secret。

D0 未执行上述加载和 kill/recovery，本节只是后续 T1 手册。

## 7. 后续 Gate 命令顺序

### T3: JM 单次真实 1m

T3 必须在 T1 passed 后另行授权。授权必须明确允许 RQData 读取和写入 live tables/checkpoint，不包含 signal event、archive、企业微信或交易执行。

只读 dry-run：

```bash
uv run --project services/quant-api python -m app.runtime_scheduler \
  --dry-run --product jm
```

真实单次写入命令：

```bash
GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run --project services/quant-api python -m app.runtime_scheduler \
  --once --confirm-live-write --product jm
```

T3 通过至少需要：

- 动态解析 `MainContractMap.rank=1` actual contract。
- 至少一根真实 confirmed 1m 进入 live 表。
- 多周期聚合返回合法状态。
- checkpoint 重启或重复运行幂等验证通过。
- `writes_historical_active=false`。
- `writes_signal_event=false`。
- `sends_notification=false`。

如果返回 `idle`，只能说明交易时钟 Gate 生效，不能作为 T3 写入通过。

### T4: 单交易日盘后归档

T4 后置，单独授权后才允许：

```bash
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=true \
uv run --project services/quant-api python scripts/after_market_archive.py \
  --product jm --trading-day <YYYY-MM-DD> \
  --run-write --confirm-after-market-archive
```

T4 必须证明 RQData 盘后最终数据是归档事实源，live rows 只作 reference，重复执行不产生第二份 active 资产。

### T5: live signal event

T5 后置，只开启 live event flag，autosend 保持 false。必须证明 same bar 幂等、revision changed event 和 historical/live 边界。

### T6: 单条真实通知

T6 后置，最后才允许开启 autosend。只选择一条 live-confirmed eligible event，验证发送幂等、3 次重试上限和日志脱敏。

### T7: 五交易日长稳

T7 后置，必须覆盖至少五个真实交易日、至少一个夜盘、worker/scheduler kill、Mac 重启、依赖故障注入、真实日线确认和周线合法确认条件。

## 8. Block 条件

任一条件触发时必须停止当前 Gate：

- worktree 位于外接卷且未完成 LaunchAgent 后台访问授权。
- 基础服务无法加载或无法自动恢复。
- runtime health 返回 `degraded` 或 `failed` 且无法解释。
- queue worker coverage 缺失。
- 四个真实开关存在非本 Gate 授权的 true。
- 命令、日志、文档或 DB 输出可能泄露 password、token、webhook、license、cookie、secret。
- T3 执行时无法动态解析 actual contract。
- T3 执行时处于非交易时段且只得到 `idle`。
- live 数据出现进入 historical active 的路径。
- 企业微信 autosend 在 T6 之前被打开。

## 9. D0 检查命令记录

本次 D0 文档落地已运行：

| 命令 | 结果 |
|---|---|
| `git diff --check` | passed |
| `bash -n scripts/run-local-service.sh scripts/dev-healthcheck.sh scripts/install-local-services.sh scripts/local-services-status.sh` | passed |
| `for f in deploy/launchd/*.plist.template; do plutil -lint "$f"; done` | passed，7 个模板均 OK |

本轮只修改文档和任务状态，未触碰 `services/quant-api/app/**`、`scripts/**` 或 `deploy/launchd/**`，因此未运行全量后端 pytest/ruff。若后续触碰这些范围，必须追加：

```bash
uv run --project services/quant-api pytest services/quant-api/tests/ -q
uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
```

## 10. T1 render-only 与 confirm-load 记录

执行时间：2026-07-11。

### 10.1 render-only

执行命令：

```bash
GUIYI_LIVE_RUNTIME_ENABLED=false \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
scripts/install-local-services.sh --render-only
```

结果：

| 项目 | 结果 |
|---|---|
| render-only exit code | `0` |
| rendered path | `/Volumes/扩展盘/guiyi-parallel/jm-live-gate/.run/launchd` |
| 生成 plist 数量 | 7 |
| `.run/launchd/*.plist` lint | passed，7 个模板均 OK |
| runtime script sync | `~/Library/Application Support/GuiyiQuant/run-local-service.sh` present，mode `700` |
| log rotate script sync | `~/Library/Application Support/GuiyiQuant/rotate-local-service-logs.sh` present，mode `700` |
| first `GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD` check | `unset` |

### 10.2 confirm-load 执行过程

前置问题：

- `apps/quant-web/dist/index.html` 缺失。已运行 `pnpm --dir apps/quant-web build` 生成 gitignored dist；build 通过，仅保留既有 chunk size warning。
- 首次 `--confirm-load` 返回 `Bootstrap failed: 5: Input/output error`。
- 诊断发现旧 worktree `/Volumes/扩展盘/guiyi-quant-workstation` 残留 API 进程占用 `127.0.0.1:8000`，且 `/healthz`、`/api/health` 超时。
- 已停止旧 API 残留进程，释放 `8000`。
- 第二次批量 `--confirm-load` 仍在 Web bootstrap 处返回 `Input/output error`，但 API、backtests worker、signals worker 已加载成功。
- 手动验证 Web 入口可启动后，单独 bootstrap `com.guiyi.quant-web` 成功。
- 单独 bootstrap `com.guiyi.quant-log-rotate` 成功。

实际加载命令：

```bash
GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1 \
GUIYI_LIVE_RUNTIME_ENABLED=false \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
scripts/install-local-services.sh --confirm-load
```

最终 `scripts/local-services-status.sh` 输出：

```text
com.guiyi.quant-api                        loaded
com.guiyi.quant-worker-backtests           loaded
com.guiyi.quant-worker-signals             loaded
com.guiyi.quant-web                        loaded
com.guiyi.quant-log-rotate                 loaded
```

后置检查：

```text
com.guiyi.quant-runtime-scheduler missing
com.guiyi.quant-worker-notifications missing
```

`scripts/dev-healthcheck.sh --json --no-start`：

```text
status=passed
api_healthz=http_200
api_health=http_200
runtime_health=http_200_business_ok
web_home=http_200
postgres=ok
redis=ok
```

runtime health 摘要：

```text
status=ok
db=ok
redis=ok
rq=ok
scheduler=disabled
live_checkpoints=disabled
archive=disabled
notification_retry=disabled
worker_count=2
queue:guiyi-backtests:ok:worker_present=True
queue:guiyi-signals:ok:worker_present=True
```

日志敏感词扫描：

```text
api.log=sensitive_terms:none
web.log=sensitive_terms:none
worker-backtests.log=sensitive_terms:none
worker-signals.log=sensitive_terms:none
log-rotate.log=missing
```

判定：

```text
T1_CONFIRM_LOAD_HEALTH_OK
T1_KILL_RECOVERY_PENDING
```

说明：基础 5 个 launchd label 已加载，且 API/Web/runtime health/Redis/PostgreSQL/RQ worker coverage 均通过；scheduler 与 notification worker 未加载。T1 完整验收仍需执行 kill/recovery，因此尚不能写 `T1_OPS_PASSED`。

### 10.3 kill/recovery

执行时间：2026-07-11。

基线：

```text
com.guiyi.quant-api                        loaded
com.guiyi.quant-worker-backtests           loaded
com.guiyi.quant-worker-signals             loaded
com.guiyi.quant-web                        loaded
com.guiyi.quant-log-rotate                 loaded
com.guiyi.quant-runtime-scheduler          missing
com.guiyi.quant-worker-notifications       missing
dev-healthcheck                            passed
```

受控 kill/recovery 顺序与结果：

| Label | Before | After | 恢复方式 | 健康结果 | 结论 |
|---|---|---|---|---|---|
| `com.guiyi.quant-api` | pid `95666`, runs `2` | pid `15879`, runs `3` | auto, 1s | 首次即时 curl 太早失败；复测见下一行 | needs readiness wait |
| `com.guiyi.quant-api` recheck | pid `15879`, runs `3` | pid `18617`, runs `4` | auto, 2s | `/healthz`、`/api/health`、`/api/runtime/health` passed | passed |
| `com.guiyi.quant-web` | pid `99742`, runs `2` | pid `15904`, runs `3` | auto, 1s | Web `/` HTTP 200 | passed |
| `com.guiyi.quant-worker-backtests` | pid `95947`, runs `2` | pid `16027`, runs `3` | auto, 1s | `guiyi-backtests worker_present=True` | passed |
| `com.guiyi.quant-worker-signals` | pid `96383`, runs `2` | pid `16186`, runs `3` | auto, 1s | `guiyi-signals worker_present=True` | passed |

未使用 manual kickstart 作为通过证据。

最终 `scripts/local-services-status.sh`：

```text
com.guiyi.quant-api                        loaded
com.guiyi.quant-worker-backtests           loaded
com.guiyi.quant-worker-signals             loaded
com.guiyi.quant-web                        loaded
com.guiyi.quant-log-rotate                 loaded
```

最终 optional label 检查：

```text
com.guiyi.quant-runtime-scheduler          missing
com.guiyi.quant-worker-notifications       missing
```

最终 `scripts/dev-healthcheck.sh --json --no-start`：

```text
status=passed
api_healthz=http_200
api_health=http_200
runtime_health=http_200_business_ok
web_home=http_200
postgres=ok
redis=ok
```

最终 runtime health 摘要：

```text
status=ok
scheduler=disabled
live_checkpoints=disabled
archive=disabled
notification_retry=disabled
worker_count=2
queue:guiyi-backtests:ok:worker_present=True
queue:guiyi-signals:ok:worker_present=True
```

日志敏感词扫描：

```text
api.log=sensitive_terms:none
web.log=sensitive_terms:none
worker-backtests.log=sensitive_terms:none
worker-signals.log=sensitive_terms:none
log-rotate.log=missing
```

判定：

```text
T1_OPS_PASSED
T3_REAL_PENDING
```

说明：T1 只验证基础服务监督和 strict health；未开启 live runtime、live signal event、after-market archive 或 WeChat autosend。下一步进入 T3-real 前仍需单独授权真实 RQData 读取和 live 表写入。

## 11. T3 授权确认与非交易时段 smoke

执行时间：2026-07-11 22:30-22:36 CST。

授权口径：

```text
允许本次 JM T3 真实 RQData 读取，并允许写入 live 表和 checkpoint；仅临时开启 GUIYI_LIVE_RUNTIME_ENABLED=true，其余三个 flag 保持 false。
```

授权不包含：

- 不创建 signal event。
- 不执行 after-market archive。
- 不发送企业微信。
- 不接 CTP、账户、订单或自动交易接口。
- 不修改 `.env`，不打印或提交 RQData license、Redis/PostgreSQL 密码、webhook 或 token。

执行前环境摘要：

```text
RQDATA_LICENSE_KEY=present
DATABASE_URL=present
REDIS_URL=present
GUIYI_LIVE_RUNTIME_ENABLED=unset
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=unset
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=unset
GUIYI_WECHAT_AUTOSEND_ENABLED=unset
```

T1 仍健康：

```text
scripts/local-services-status.sh:
com.guiyi.quant-api                        loaded
com.guiyi.quant-worker-backtests           loaded
com.guiyi.quant-worker-signals             loaded
com.guiyi.quant-web                        loaded
com.guiyi.quant-log-rotate                 loaded

optional labels:
com.guiyi.quant-runtime-scheduler          missing
com.guiyi.quant-worker-notifications       missing

scripts/dev-healthcheck.sh --json --no-start:
status=passed
api_healthz=http_200
api_health=http_200
runtime_health=http_200_business_ok
web_home=http_200
postgres=ok
redis=ok
```

dry-run：

```bash
uv run python -m app.runtime_scheduler --dry-run --product jm
```

dry-run 结论：

```text
would_open_database=false
would_connect_redis=false
would_construct_rqdata_client=false
would_write_live_tables=false
would_write_historical_active=false
would_write_signal_event=false
would_send_notification=false
auto_order=false
```

真实单次 smoke 命令：

```bash
GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run python -m app.runtime_scheduler --once --confirm-live-write --product jm
```

说明：交互 shell 直接运行 Python 模块时需要先加载 `~/Library/Application Support/GuiyiQuant/project.env`，并复用 `scripts/run-local-service.sh` 的 Redis URL 归一化规则；该过程未打印凭据。

两次 smoke 结果一致：

```text
status=idle
enabled=true
product=jm
actual_contract=JM2609
trading_day=null
phase=closed
reason=outside_trading_sessions
ingest=null
aggregation=null
signal_events=null
writes_signal_event=false
sends_notification=false
writes_historical_active=false
```

live 表执行前后计数：

```text
live_minute_bars:count=0;max=None
live_aggregated_bars:count=0;max=None
live_ingest_checkpoints:count=0;max=None
live_aggregation_checkpoints:count=0;max=None
```

判定：

```text
T3_AUTH_CONFIRMED
T3_DRY_RUN_PASSED
T3_CLOCK_IDLE_NON_TRADING
T3_REAL_PENDING
```

说明：本次只证明 T3 授权边界、dry-run 安全性、actual contract 动态解析和交易时钟关闭态生效。由于当前是非交易时段且没有任何 confirmed 1m 进入 live 表，本次不能判定 `T3_REAL_PASSED`，也不能声明 `JM_RUNTIME_READY`。

## 11. POST-DATA-CLOSURE Phase 1 readiness（2026-07-12 Cursor）

执行位置：主仓库 `/Volumes/扩展盘/guiyi-quant-workstation`（只读 readiness，无 live 写入）。

### 前置检查

```text
git: main...origin/main（工作区有 docs 未提交）
local-services-status:
  inspector_repo=/Volumes/扩展盘/guiyi-quant-workstation
  supervised_runtime_root=/Volumes/扩展盘/guiyi-parallel/jm-live-gate
  基础 5 LaunchAgent loaded
dev-healthcheck: status=passed（api/runtime_health/postgres/redis 均 passed）
```

### 环境变量 present/missing（不记录值）

```text
RQDATA_LICENSE_KEY=present
DATABASE_URL=present
REDIS_URL=present
GUIYI_LIVE_RUNTIME_ENABLED=missing（默认 false）
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=missing（默认 false）
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=missing（默认 false）
GUIYI_WECHAT_AUTOSEND_ENABLED=missing（默认 false）
```

### dry-run

```bash
cd services/quant-api && uv run python -m app.runtime_scheduler --dry-run --product jm
```

```json
{
  "mode": "dry-run",
  "enabled": false,
  "would_write_live_tables": false,
  "would_write_historical_active": false,
  "would_write_signal_event": false,
  "would_send_notification": false,
  "auto_order": false
}
```

### 只读 contract + trading clock（DB 读，无写入）

```text
actual_contract_status=resolved
actual_contract=JM2609（经 MainContractMap 动态解析，非 PoC 硬编码入口）
trading_clock.phase=closed
trading_clock.reason=outside_trading_sessions
gate_note=BLOCKED_BY_NON_TRADING_TIME
```

### Phase 1 判定

```text
POST_DATA_CLOSURE_PHASE1_DRY_RUN_PASSED
T3_CLOCK_IDLE_NON_TRADING
T3_REAL_PENDING
SCHEME_B_MIGRATION_PENDING
```

说明：方案 B 本机磁盘 runtime 副本迁移见 `TASK-2026-07-12-019`；T3-real 须在迁移完成且 JM 可交易时段另行 Gate。

## 12. 方案 B 迁移 + T3 runtime smoke（2026-07-12 Cursor）

### 方案 B 迁移结果

```text
runtime_path=~/GuiyiRuntime/guiyi-quant-workstation-runtime
branch=ops/local-runtime-disk
supervised_runtime_root=~/GuiyiRuntime/guiyi-quant-workstation-runtime（与 inspector_repo 一致）
dev-healthcheck=passed
post-reboot-verify=passed
api_kill_recovery=kickstart 后 healthz ok
```

旧 parallel 绑定 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` 已 bootout；launchd 现绑定本机磁盘副本。

### T3 `--once` smoke（runtime 副本，非交易时段）

```bash
# 经 project.env + Redis URL 归一化（同 run-local-service.sh）
GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run python -m app.runtime_scheduler --once --confirm-live-write --product jm
```

结果：

```text
status=idle
actual_contract=JM2609
phase=closed
reason=outside_trading_sessions
writes_signal_event=false
sends_notification=false
writes_historical_active=false
```

live 表计数（执行后）：

```text
live_minute_bars:count=0
live_aggregated_bars:count=0
live_ingest_checkpoints:count=0
live_aggregation_checkpoints:count=0
```

### 判定

```text
SCHEME_B_MIGRATION_PASSED
T3_RUNTIME_COPY_SMOKE_IDLE_NON_TRADING
T3_REAL_PENDING（需 JM 可交易时段 + 用户显式确认 Phase 2 真实写入）
```

不可声明：`T3_REAL_PASSED` / `JM_RUNTIME_READY` / `LONG_RUNNING_READY`
