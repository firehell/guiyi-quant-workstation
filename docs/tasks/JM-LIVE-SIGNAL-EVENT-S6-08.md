# JM Live-confirmed SignalEvent Gate（S6-08）

更新时间：2026-07-23

## 状态

```text
S6_08_CODE_COMPLETE
REAL_T5_NOT_EXECUTED
```

本任务只实现 approval packet、运行时 fail-closed、最终验证器、create-only receipt、只读 health 和测试。
未部署、未修改 Runtime 配置、未执行真实 T5、未发送企业微信，也未授予自动交易或长期运行资格。

## 前置与边界

真实启用的硬前置是内容和 SHA-256 均验证通过的 S6-07 schema-v2 最终收据：

```text
JM_EOD_INCREMENTAL_AUTOMATION_READY
```

`REAL_ACCEPTANCE_IN_PROGRESS`、D1 单独通过、scheduler health 或普通测试均不能替代该收据。
S6-08 不修改策略参数、指标公式、live evaluator、Profile、migration、EOD scheduler、通知发送或交易路径。

SignalEvent 只能来自：

- JM 实际合约；
- 5m / 15m confirmed bar；
- `rqdata / primary / passed`；
- warnings 为空；
- `live_observation_v1` 完整 formal lineage；
- `jm_v1b_daily_direction_fast_entry / v1b.0`；
- approval packet 绑定的单一交易日。

## Approval packet

CLI：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python -m app.live_signal_event_gate --dry-run
```

非 dry-run 的 `--prepare-packet` 必须显式提供 S6-07 final receipt、其精确的 64 位小写
SHA-256、目标交易日、输出根和 create-only 输出路径；缺少或格式不符时必须 fail-closed，且不得打开数据库。
packet 使用 canonical JSON SHA-256，并绑定：

- S6-07 final receipt 路径、SHA-256、schema_version=2、task/gate/status、Runtime commit、DB revision
  和 authorization hash；验证 deployment lineage、D1、D2 outage、D2 及禁写 counter/delta 的完整契约。
  receipt 的 evidence 路径只验证结构和外层绑定 hash，不读取路径内容；`scope_boundaries` 必须使用
  `automatic_trading_ready=false`，不得以旧字段 `auto_trading_ready` 替代。
- Runtime commit、tracked-state hash、`uv.lock` hash、项目根、输出根和设备；
- 脱敏数据库 identity 与 Alembic revision；
- 实际合约与 dominant mapping；
- active Profile binding hash；
- 策略代码、版本和源码 hash；
- 冻结 indicator policy snapshot/hash；
- confirmed/passed/no-warning quality policy；
- feature flags；
- live bars/checkpoints 的逐行全字段 SHA-256 与 scope 元数据；
- StrategySignal / SignalEvent `{count,max_id,row_hashes}`；
- notification、scan、backtest、order/trade、Profile、canonical asset 和 EOD checkpoint
  禁止表的全表内容 SHA-256。

packet 的 `writes_authorized=false` 是待人工批准状态。只有用户明确批准精确 packet hash 后，才能把同一
packet/hash 配入 Runtime。

## Code-only Runtime deployment Gate

状态：

```text
CODE_COMPLETE_EXTERNAL_GATE_PENDING
```

`scripts/jm_live_signal_event_deployment_gate.py` 为 S6-08 增加独立的 code-only Runtime deployment Gate。
本任务只开发、fake-test 和提交 Gate 代码；在取得新鲜事实与用户对精确 packet hash 的明确批准前，
不得执行真实 prepare / confirm，不得修改 Runtime、DB、runtime env 或 launchd。

CLI 三种模式严格互斥：

```bash
PYTHONPATH=services/quant-api uv run --project services/quant-api \
  python scripts/jm_live_signal_event_deployment_gate.py --prepare-deploy-packet ...
PYTHONPATH=services/quant-api uv run --project services/quant-api \
  python scripts/jm_live_signal_event_deployment_gate.py --verify-deploy-packet ...
PYTHONPATH=services/quant-api uv run --project services/quant-api \
  python scripts/jm_live_signal_event_deployment_gate.py --confirm-deploy ...
```

prepare / verify 只采集只读事实。prepare 以 create-only 方式生成 schema-v1 packet：

```text
task_id=JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY
status=approval_required
writes_authorized=false
authorization_mode=exact_packet_hash
```

packet 使用既有 `canonical_packet_hash`，并绑定：

- source commit、tree、tracked clean、目标 commit 和 `services/quant-api/uv.lock` SHA-256；
- source 中仅允许的 S6-07 未跟踪证据清单及每个相对路径/SHA-256 的综合摘要：
  `data/manifests/jm_after_market_archive_s607_*` 和
  `data/reports/jm_eod_incremental_s6_07/**`；任何其他未跟踪路径或未跟踪 executable 都拒绝；
- Runtime root、当前 commit/tree、tracked clean、无非 venv 未跟踪 executable，以及相同的
  `uv.lock` SHA-256；
- source commit 已存在于 Runtime 本地 Git object store，Runtime 当前 commit 精确等于 S6-07
  final receipt 的 `runtime_commit`，且是 source/target commit 的祖先；禁止 fetch/pull；
- S6-07 schema-v2 final receipt 的路径、精确外层 SHA-256 及完整
  `validate_s6_final_receipt` 校验结果；
- PostgreSQL 脱敏 identity hash、`20260721_0025` revision；采集事务执行
  `SET TRANSACTION READ ONLY` 并 rollback；
- runtime env 只解析和绑定三个安全 flag，不输出其他变量值：
  `GUIYI_LIVE_RUNTIME_ENABLED=true`、
  `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false`、
  `GUIYI_WECHAT_AUTOSEND_ENABLED=false`；
- 已加载的精确 label `com.guiyi.quant-runtime-scheduler`、PID、plist 路径/SHA-256、
  ProgramArguments 和 `GUIYI_PROJECT_ROOT` identity。

confirm 前重新采集全部事实，必须与已批准 packet 完全一致。唯一允许操作是：

1. 使用本地 Git object detach Runtime 到已批准 target commit；
2. 只清理 Runtime 内非 `.venv` 的 `__pycache__` / `.pyc` / `.pyo`；
3. 只执行 `launchctl kickstart -k gui/$UID/com.guiyi.quant-runtime-scheduler`；
4. 只读验证新 PID、target commit/tree、tracked clean、DB revision 不变、三个 flag 仍安全以及
   runtime health 为 `ok`；
5. create-only 写 deployment receipt。

明确禁止 migration、DB write、runtime env write、SignalEvent enable、企业微信/notification、
EOD scheduler、API、worker、fetch、push 或其他 launchd label 操作。

任一步失败只回滚本次 Runtime 切换：detach 回 previous commit、kickstart 同一 runtime scheduler，
并只读验证恢复。回滚失败必须 fail-closed。成功 receipt 记录批准 hash、previous/target commit、
scheduler restart、DB unchanged、flags safe 和 `rollback=false`；失败 receipt 只记录 bounded
`error_type` 与 rollback attempted/succeeded，不包含 secret 或路径细节。所有 receipt 均为
create-only，目标已存在时在任何命令前拒绝。

## Runtime 数据流

```text
现有 20 秒 live scheduler
→ Redis singleton lock
→ 写前重验 S6 receipt + packet + 当前事实
→ live ingest / aggregate
→ 5m/15m evaluator
→ StrategySignal / SignalEvent（同一 DB transaction）
→ 写后重验累计 delta、scope、lineage 和 dedupe
→ 唯一 commit
```

`LiveSignalEventService` 不自行 commit。写后校验失败时，live rows、StrategySignal 和 SignalEvent 整轮回滚。
同 bar 同 state 零新增；revision/state hash 变化由既有唯一键最多产生一个 `signal_changed`。

允许推进：

- live minute/aggregate bars 和 checkpoints；
- scheduler lock/heartbeat；
- packet 范围内的 StrategySignal / SignalEvent。

禁止推进：

- SignalNotification / signal scan；
- backtest task/report/trade/order；
- Profile、historical/canonical/manifest；
- EOD scheduler/checkpoint；
- 企业微信和任何订单/交易。

## 单日真实验收协议

1. S6-07 最终收据发布后，为一个明确交易日生成新 packet。
2. 用户批准该 packet 的精确 hash。
3. `configure-live-signal-events.sh --enable` 只写 signal enabled、packet、hash 三个键。
4. 仅重启既有 `com.guiyi.quant-runtime-scheduler`，自然等待合格事件，不强制构造信号。
5. 当日无合格事件时，关闭 flag、清空授权、重启并输出 `PENDING_ELIGIBLE_EVENT`；下一交易日必须新 packet、新批准。
6. 产生事件后先执行 `--disable` 并重启，确认 live-only scheduler health 为 `ok`。
7. final verifier 检查所有允许/禁止 delta、lineage、dedupe、flags 和 Runtime identity；恢复后的
   health 快照及 scheduler heartbeat 必须在 180 秒内，SignalEvent 授权哈希必须为空，并且
   heartbeat 必须晚于或等于本次最新 SignalEvent 的 `created_at`；两端时间写入 final evidence。
8. 只有恢复关闭后，才可带 `--confirm-final-gate` create-only 发布：

```text
JM_LIVE_SIGNAL_EVENT_PASSED
```

该 Gate 仍明确：

```text
notification_ready=false
long_running_ready=false
runtime_ready=false
auto_trading_ready=false
```

回滚只关闭 SignalEvent flag、清空 packet/hash 并重启 live scheduler；已接受的 SignalEvent 证据不删除、不重写。

## 测试

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests -k "live_signal_event or live_signal or signal_event or stage9"

uv run --project services/quant-api ruff check \
  services/quant-api/app \
  services/quant-api/tests

uv run --project services/quant-api pytest -q \
  tests/engineering/test_live_signal_event_service_scripts.py

bash scripts/engineering/check-secrets.sh
git diff --check
```

测试通过只表示代码 Gate 可审查，不表示真实 T5 已执行。
