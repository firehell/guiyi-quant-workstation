# JM Live-confirmed SignalEvent Gate（S6-08）

更新时间：2026-07-26

## 2026-07-26 合同冻结

本文件下方的 JM V1-B schema-v2 实现说明保留为 superseded 历史。active 目标已改为：

```text
strategy_code=htdy_original_realtime_first_seen
strategy_version=v1.0
indicator_code=huotian_dayou_original_v0
indicator_version=original-v0
source_mode=live_realtime_repainting
signal_policy=htdy_original_xma_15m_first_seen_v1
product=jm
contract=当日 MainContractMap.rank=1 实际主力
period=15m
partial_allowed=true
confirmed_allowed=true
live_confirmed_required=false
future_looking=true
repainting_accepted=true
first_seen_no_retraction=true
historical_backtest_allowed=false
auto_order=false
```

新合同要求 schema-v3 service packet、最多五个明确 DCE 交易日的 bounded parent authorization、
每日 exact child packet、`signal_review_lineage_v2`、`signal_created` only 和 first-seen
no-retraction。旧 JM V1-B schema-v2 packet/hash 继续保留为历史文件，但已从 Runtime 配置解除引用；
旧 receipt 不能通过新 verifier。

当前冻结状态：

```text
HTDY_REALTIME_EXCEPTION_CONTRACT_FROZEN
OLD_S6_08_AUTHORIZATION_REVOKED
S6_08_HTDY_SCHEMA_V3_GATE_READY
REAL_T5_NOT_EXECUTED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
```

Step 0～3 的 contract、kernel/policy、snapshot/evaluator、first-seen writer/lineage v2 已形成
checkpoint。Step 4 已完成 schema-v3 parent/child/final verifier、active Runtime handler、首次自然
事件后一次同 key 幂等探测、create-only 消费状态，以及 deployment/S6-07 rebind/service parent
三包生成与重载验证代码。尚未发布真实三个 packet/hash，未请求 Approval A，未部署、启用 Runtime
flag 或执行真实 T5。

固定父窗口仅为：

```text
2026-07-27
2026-07-28
2026-07-29
2026-07-30
2026-07-31
```

生成器仅在 `2026-07-27` 前且 DCE calendar 五日完整时工作；窗口开始或 facts 漂移必须停止，
不得静默换日。active scheduler 只接受 schema-v3 service parent，schema-v2/旧 JM packet 在
构造 Gate 时即拒绝。当前仍为：

```text
CODE_COMPLETE_EXTERNAL_GATE_PENDING
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
```

---

## Superseded JM V1-B schema-v2 implementation record

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
services/quant-api/.venv/bin/python -m app.live_signal_event_gate --dry-run

PYTHONPATH=services/quant-api:packages/quant-core \
services/quant-api/.venv/bin/python -m app.live_signal_event_gate \
  --check-strategy-eligibility \
  --eligibility-out <create-only-path>
```

策略资格检查不打开数据库、Redis 或 RQData。唯一允许结果为冻结的
`jm_v1b_daily_direction_fast_entry / v1b.0`、`live_observation_v1` 和
`jm_v1b_report14_frozen_v1`；输出同时绑定策略源码 hash 与冻结 policy hash，
并固定 `observation_only=true`、`notification_ready=false`、`trading_ready=false`。
HTDY rejected/original/strict 或任何其他策略身份返回
`LIVE_SIGNAL_EVENT_BLOCKED_NO_ELIGIBLE_STRATEGY`，不得调参或翻转阶段 5 结论。

非 dry-run 的 `--prepare-packet` 必须显式提供 S6-07 final receipt、其精确的 64 位小写
SHA-256、目标交易日、已部署 Runtime 根、输出根和 create-only 输出路径；缺少或格式不符时必须
fail-closed，且不得打开数据库。`--verify-packet`、`--verify-final` 和 `--publish-final`
也必须显式传入同一 `--runtime-root`。packet 的 Runtime identity 必须从该部署根采集，
不得绑定生成 packet 的开发 checkout 路径。
service packet 使用 schema v2 canonical JSON SHA-256，并绑定：

- S6-07 final receipt 路径、SHA-256、schema_version=2、task/gate/status、Runtime commit、DB revision
  和 authorization hash；验证 deployment lineage、D1、D2 outage、D2 及禁写 counter/delta 的完整契约。
  receipt 的 evidence 路径只验证结构和外层绑定 hash，不读取路径内容；`scope_boundaries` 必须使用
  `automatic_trading_ready=false`，不得以旧字段 `auto_trading_ready` 替代。
- Runtime commit、tracked-state hash、`uv.lock` hash、项目根、输出根和设备；
- 脱敏数据库 identity 与 Alembic revision；
- 实际合约与 dominant mapping；
- active Profile binding hash；
- 策略代码、版本和源码 hash；
- 冻结 indicator policy snapshot/hash 及独立策略资格结论；
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
PYTHONPATH=services/quant-api \
services/quant-api/.venv/bin/python \
  scripts/jm_live_signal_event_deployment_gate.py --prepare-deploy-packet ...
PYTHONPATH=services/quant-api \
services/quant-api/.venv/bin/python \
  scripts/jm_live_signal_event_deployment_gate.py --verify-deploy-packet ...
PYTHONPATH=services/quant-api \
services/quant-api/.venv/bin/python \
  scripts/jm_live_signal_event_deployment_gate.py --confirm-deploy ...
```

prepare / verify 只采集只读事实。所有模式都必须显式传入 `--runtime-root`、
`--s6-final-receipt`、精确的 `--s6-final-receipt-sha256`、`--runtime-env` 和
`--output-root`。prepare 还必须同时提供 `--packet-out` 和
`--deployment-receipt-out`；后两条路径会与已存在的 output root、设备号和
各自父目录 inode 一起绑定进 packet。建议在主仓库和 Runtime 之外使用独立的批准目录，例如：

```text
/Volumes/扩展盘/GuiyiApprovals/s608/<packet-id>/
```

output root 必须预先存在，不得与 source、Runtime、runtime env、launchd plist、
固定 runner、Git dir 或 Git common dir 重叠；packet、receipt 及其父目录不得通过
symlink 绕过范围验证。packet 与 receipt 都是 create-only，confirm 的 receipt
路径必须精确等于 packet 中已批准的路径。写文件时重新以已验证父目录的 dirfd 打开，
使用 `O_NOFOLLOW|O_EXCL`，不创建父目录；失败清理前必须确认目标仍是本次创建的 inode，
不得删除并发替换的文件。

prepare 以 create-only 方式生成 schema-v1 packet：

```text
task_id=JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY
status=approval_required
writes_authorized=false
authorization_mode=exact_packet_hash
```

packet 使用既有 `canonical_packet_hash`，并绑定：

- source 必须位于 `main`，且 `HEAD == refs/heads/main`；记录 `origin/main` 和本地
  main 相对 origin 的 ahead 数量。允许本地 main 是 origin/main 的后代，禁止分叉，
  Gate 不执行 fetch、pull 或 push；
- source commit、tree、tracked clean、目标 commit、Git dir/common dir、
  `services/quant-api/uv.lock` SHA-256，以及目标 commit 内
  `scripts/run-local-service.sh` blob 与工作树文件的相同 SHA-256；
- source 中仅允许精确命名的 S6-07 未跟踪证据。日期必须在 D1..D2 范围，文件名
  commit 后缀必须属于 foundation deployment lineage；manifest 必须是
  `data/manifests/jm_after_market_archive_s607_YYYYMMDD_<commit8>.csv`。
  report 只能位于精确 batch
  `data/reports/jm_eod_incremental_s6_07/s607_YYYYMMDD_<commit8>/`，且成功 D2
  batch 必须完整包含并只包含
  `completion_receipt.json`、`execution_packet.json`、`final_audit.json`、
  `quality_gate.json`。其他部分成功/失败 batch 也必须满足同一日期、lineage 和
  文件名白名单；`.py`、其他路径和未跟踪 executable 一律拒绝；
- Runtime root、当前 commit/tree、tracked clean、无非 venv 未跟踪 executable，以及相同的
  `uv.lock` SHA-256；
- source commit 已存在于 Runtime 本地 Git object store，Runtime 当前 commit 精确等于 S6-07
  final receipt 的 `runtime_commit`，且是 source/target commit 的祖先；禁止 fetch/pull；
- S6-07 schema-v2 final receipt 的路径、精确外层 SHA-256 及完整
  `validate_s6_final_receipt` 校验结果；
- 已加载的精确 label `com.guiyi.quant-runtime-scheduler` 的 path、program、
  arguments、environment、working directory 和 PID，并逐项等于磁盘 plist。
  program/arguments 必须是固定的
  `/bin/bash ~/Library/Application Support/GuiyiQuant/run-local-service.sh scheduler`；
  EnvironmentVariables 只允许 `PATH`、`GUIYI_PROJECT_ROOT` 及未来可选的
  `GUIYI_RUNTIME_DIR`/`GUIYI_RUNTIME_ENV`，拒绝 `BASH_ENV` 等额外键。绑定 plist
  SHA-256 和已安装 runner SHA-256，且 runner 必须等于目标 commit 中的脚本；
- runtime env 路径只能由已加载 launchd environment 或固定
  `~/Library/Application Support/GuiyiQuant/project.env` 唯一推导，CLI
  `--runtime-env` 必须精确匹配且不得是 symlink。解析器只接受 blank、comment 和
  无重复的纯 `KEY=VALUE`；允许安全引号，不进行变量、命令、反斜杠或 shell 展开，
  并绑定整个 env 文件 SHA-256、device、inode 和 size。解析内容与 SHA-256 必须来自
  同一个 `O_NOFOLLOW` 文件描述符和同一份 bytes；`fstat` 必须确认它是 regular file，
  禁止通过路径二次读取；
- 数据库连接只使用上述 env 文件中严格解析出的 `DATABASE_URL`，不得回退到进程环境或
  默认数据库。PostgreSQL 采集事务执行 `SET TRANSACTION READ ONLY` 后查询脱敏
  identity hash 和精确 `20260721_0025` revision，并始终 rollback；packet、stdout
  和 receipt 不记录 URL 或 secret；
- runtime env 绑定三个安全 flag：
  `GUIYI_LIVE_RUNTIME_ENABLED=true`、
  `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false`、
  `GUIYI_WECHAT_AUTOSEND_ENABLED=false`；
- prepare 时的 Runtime health、scheduler PID 和 heartbeat；health 必须为 `ok`，
  scheduler lock/status 必须为 `ok`，last cycle 只能是 idle/running/success，
  SignalEvent 必须保持关闭且授权 hash 为空；
- Runtime 全局 deployment lock identity：由 canonical Runtime root 与固定 launchd
  label 唯一生成，存放在已安装 runner 的受控 Application Support 父目录，不写入
  Runtime tracked tree，也不依赖 output root。相同 Runtime 即使使用两个不同批准目录
  也必须竞争同一个锁。

confirm 在读取任何事实或执行命令前先检查 receipt 不存在并验证 packet/hash/path。
随后用已绑定父目录 device/inode 和 `O_NOFOLLOW` 打开 Runtime 全局锁并执行
`flock(LOCK_EX|LOCK_NB)`；锁文件持久存在且不 unlink，symlink 或父目录漂移立即
fail-closed。在锁内只重新采集一次完整事实并与已批准 packet 精确比较，之后立即切换。
唯一允许操作是：

1. 使用本地 Git object detach Runtime 到已批准 target commit；
2. 只清理 Runtime 内非 `.venv` 的 `__pycache__` / `.pyc` / `.pyo`；
3. 只执行 `launchctl kickstart -k gui/$UID/com.guiyi.quant-runtime-scheduler`；
4. 轮询只读验证新 PID、target commit/tree、tracked clean、DB revision 不变、三个
   flag 仍安全以及 runtime/scheduler health 为 `ok`；post heartbeat 必须严格晚于
   packet 绑定的 pre heartbeat，SignalEvent 必须关闭、授权 hash 必须为空；post
   launchd 的 program、arguments、environment、working directory、runner path/hash、
   plist path/hash、project root 和 label 必须全部与 pre identity 一致；
5. create-only 写 deployment receipt。

明确禁止 migration、DB write、runtime env write、SignalEvent enable、企业微信/notification、
EOD scheduler、API、worker、fetch、push 或其他 launchd label 操作。

`git switch` 返回后立即重新探测 Runtime HEAD：仍为 previous 表示本次未取得所有权，
不得 rollback 或 kickstart；已经是 target 才表示本次 Gate 拥有切换，后续失败才允许
detach 回 previous，且仅当本次已 restart 时才 kickstart 同一 scheduler；出现第三个
commit 表示并发漂移，禁止覆盖。health 成功后仍要再次探测 Runtime HEAD，避免轮询期间漂移。
rollback restart 前必须记录当时 PID 与 heartbeat；rollback 验收要求 PID 改变且 heartbeat
严格晚于该 rollback 起点，再重验 previous Runtime、完整 launchd identity、同 inode/env
SHA、safe flags 和相同只读 DB identity。旧 PID 或旧 heartbeat 均视为 rollback 失败。
回滚失败必须 fail-closed。成功 receipt 记录批准 hash、previous/target commit、PID/heartbeat、
DB unchanged、flags safe 和 `rollback=false`；失败 receipt 只记录 bounded `error_type`
与 rollback attempted/succeeded；发生 rollback restart 时还记录前后 PID/heartbeat，
但不包含 secret 或路径细节。receipt 已存在或 lock busy 时不写失败 receipt。

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
同 bar 同 state 零新增；state key 显式包含 `live_bar_id/live_bar_revision`，revision/state hash
变化由既有唯一键最多产生一个 `signal_changed`。真实验收不篡改生产 bar，revision 分支由
Runtime commit 绑定的集成测试证明。

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
7. 关闭前保存一次 authorized execution health：真实事件后的同 bar 周期必须
   `unchanged>0` 且 `created=changed=0`，authorization hash 和交易日必须仍与 packet 一致。
8. final verifier 同时读取 `--execution-health-json` 与恢复关闭后的 `--runtime-health-json`，
   检查所有允许/禁止 delta、lineage、dedupe、flags 和 Runtime identity；恢复后的
   health 快照及 scheduler heartbeat 必须在 180 秒内，SignalEvent 授权哈希必须为空，并且
   heartbeat 必须晚于或等于本次最新 SignalEvent 的 `created_at`；两端 health hash 和时间写入 final evidence。
   verifier 还必须只读调用 `resolve_review_source_lineage(signal_event)`，绑定每个 event 的
   `review_source_lineage_v1` 及 `/review?source_type=signal_event...` 深链；不得创建 `ReviewNote`。
9. 只有恢复关闭后，才可带 `--confirm-final-gate` create-only 发布 schema-v2 receipt：

```text
LIVE_SIGNAL_EVENT_GATE_PASSED
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
services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests -k "live_signal_event or live_signal or signal_event or stage9"

services/quant-api/.venv/bin/ruff check \
  services/quant-api/app \
  services/quant-api/tests

services/quant-api/.venv/bin/python -m pytest -q \
  tests/engineering/test_live_signal_event_service_scripts.py

services/quant-api/.venv/bin/python -m pytest -q \
  tests/engineering/test_jm_live_signal_event_deployment_gate.py

bash scripts/engineering/check-secrets.sh
git diff --check
```

测试通过只表示代码 Gate 可审查，不表示真实 T5 已执行。
