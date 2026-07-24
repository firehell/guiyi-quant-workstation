# S6-07 JM 收盘自动增量与漏跑补偿

## 当前状态

```text
JM_EOD_AUTOMATION_CODE_COMPLETE
JM_EOD_AUTOMATION_SIMULATION_PASSED
JM_EOD_AUTOMATION_SAFE_SUPERVISOR_SMOKE_PASSED
JM_EOD_AUTOMATION_DEPLOYMENT_PASSED
JM_EOD_INCREMENTAL_AUTOMATION_READY
```

最终 Gate `JM_EOD_INCREMENTAL_AUTOMATION_READY` 已发布。Issue 为 #46。D1=`2026-07-22` 由 scheduler 正常自动归档；`2026-07-23` 的第二次在线归档作为连续性证据保留但不冒充停机补偿；D2=`2026-07-24` 在 eligible 窗口停机后，由重新加载的独立 scheduler 自动发现并补齐。D2 batch=`s607_20260724_19e6ca31`，7 个 primary/passed 资产（含 1w）、7 行 manifest、metadata/quality、8 条 consumer binding、48 个归档前 immutable 文件均通过，watermark 与 required binding end 到 `2026-07-24`，四类禁写 counter 仍为 `3/1/5/5`。

历史恢复记录：合并 1w hotfix 后曾发现 PostgreSQL Alembic revision 漂移为 `20260712_0022` 且 checkpoint 表缺失。系统拒绝普通 seed，改用 `schema_upgrade_with_checkpoint_recovery` 精确绑定 D1 receipt、D2 outage/failed packet/task、DB资产/binding与禁写 counter，升级到 `0025` 后只恢复一个 blocked checkpoint（watermark=`2026-07-23`、current=`2026-07-24`、retry=1）。后续 recovery deployment、service enable 与显式同日 retry 均使用独立精确 hash 批准；没有跳日、重写旧资产或手工调用单日 archive CLI。

## 独立运行契约

- 进程：launchd runner 直接 `exec services/quant-api/.venv/bin/python -m app.after_market_scheduler --run`；不使用会遗留孤儿子进程的 `uv run` 监管外壳。
- 开关：`GUIYI_AFTER_MARKET_AUTOMATION_ENABLED`。
- launchd：`com.guiyi.quant-after-market-scheduler`，日志 `after-market-scheduler.log`。
- Redis singleton：`guiyi:eod:jm:scheduler:singleton`，180 秒 lease，每 60 秒续租。
- Redis heartbeat：`guiyi:eod:jm:scheduler:heartbeat`，TTL 180 秒。
- 扫描：每 300 秒；不向 live 20 秒 scheduler 添加任务。
- checkpoint：migration `20260721_0025` 的 `after_market_scheduler_checkpoints`，每个 product 唯一。
- 专用运行面：`run-after-market-scheduler.sh`、`install-after-market-scheduler.sh` 与独立 plist；共享 API/Web/live/RQ installer 不管理该 label。

Redis 不可用、lease 丢失或审批事实漂移时，不开始新归档并退出实例。launchd 只负责监督该独立进程，不影响 API、Web、live scheduler 或 RQ worker。

## 审批和每日执行

`scripts/jm_eod_automation_gate.py` 分离 deployment packet 与服务级 enable packet。deployment packet schema v2 绑定 Runtime 当前/目标 commit、schema-only backup hash、五张表 row count、checkpoint row count 与仅重启 API 的操作范围，并 fail-closed 区分：

- `schema_upgrade`：只接受 DB=`0022`，精确绑定 `0023 -> 0024 -> 0025` 三个 migration hash并执行 Alembic；
- `schema_upgrade_with_checkpoint_recovery`：在 `schema_upgrade` 之外，只允许从 hash-bound D1/D2/DB证据恢复一个 `blocked` checkpoint；禁止从 foundation重新 seed或跳过失败日；
- `checkpoint_recovery_only`：仅用于 Alembic已到 `0025`、checkpoint仍为空的中断恢复；不再执行 migration，仍要求同一组不可变恢复证据；
- `code_only`：只接受 DB=`0025`，migration chain必须为空，部署前后保持 revision和checkpoint行数，不执行 Alembic。

所有模式都要求 Runtime tracked state为空、执行目录无未跟踪代码；确认部署后先清理 Runtime 源码 bytecode并重建 `.venv`，执行 frozen lock sync，再次验证代码树后才允许 Alembic或 API restart。生产 after-market launchd label在部署前后都必须被只读探针明确确认为未加载；探针错误不能等同于未加载。

固定命令为：

```text
--prepare-deploy-packet
--verify-deploy-packet
--confirm-deploy --approval-packet ... --approval-hash ...
```

enable packet 为 schema v2，要求 clean tracked state，并绑定：

- S6-06 `JM_ARCHIVE_PASSED` receipt 路径、内容 hash、交易日、合约和 packet hash；
- Git commit/tracked-state hash（不绑定 branch，使相同 commit 的 clean main 与 detached Runtime 一致）、`uv.lock` hash；
- 脱敏 DB identity及 `alembic_revision=20260721_0025`；
- Runtime root、output root、设备 identity；
- JM/DCE、120 分钟安全延迟、单轮 5 日、六档重试、provider 两次稳定性检查；
- 独立 launchd label、allowed writes，以及 SignalEvent/notification/strategy/order 禁写范围。

真实启动必须同时提供批准包路径、精确 hash 和显式确认。服务在启动及每轮执行前重新验证全部事实。每日 packet 为 `s607_<YYYYMMDD>_<commit8>`，绑定当日主力、provider-final hash、binding snapshot 和父级批准 hash；单日成功只写 `JM_EOD_ARCHIVE_DAY_PASSED`。

批准后的三个 runtime key 由 `configure-after-market-automation.sh` 原子更新；它不显示或改写其他配置。独立 runner 只读取 runtime `project.env`，并复用共享本地服务的 Redis 密码归一化规则。长运行 singleton lock 关闭 redis-py 的 thread-local token，使主线程取得的 lease 可由 heartbeat 工作线程续租。专用 installer 的 `--bootout` 只停止该 label并保留 enabled flag，`--disable` 只停止该 label并原子关闭 flag。

代码或绑定事实变化后必须使用新的 service approval。既有 checkpoint 仅在 `idle/success`、无 current trading day、无 retry/error 时允许在已验证的新批准下原子轮换 `authorization_hash`，并在 `last_result.authorization_history` 保留旧/新 hash 和轮换时间。blocked 状态通常继续拒绝轮换；唯一例外是已验证新批准包与 `--retry-failed-day <当前失败日> --confirm-retry` 同时出现，此时先保留授权轮换审计，再复用原有同日 reset契约，不能借换包跳日。

## 顺序补偿与失败恢复

TradingCalendar/TradingSession 计算最终收盘，越过 120 分钟后才 eligible。watermark 后的日期严格升序，每轮最多 5 日；首个日期未成功立即停止。provider pending 不推进 watermark且不消耗 retry；provider/DB/manifest 暂时失败使用 `5/15/30/60/120/240` 分钟六档重试，之后再次失败进入 blocked。quality、mount/device、mapping、binding/consumer 或授权错误立即 blocked。

人工恢复只允许：

```bash
python -m app.after_market_scheduler \
  --retry-failed-day <YYYY-MM-DD> \
  --confirm-retry \
  --confirm-after-market-automation \
  --approval-packet <packet.json> \
  --approval-hash <approved-hash>
```

日期必须等于 checkpoint 当前最早失败日。重复任务先验证既有 packet/receipt/资产/checksum/DB/Profile；验证通过只恢复 watermark，不重复归档。

## Runtime health

`/api/runtime/health` 的 `components.after_market_scheduler` 与 live `components.scheduler` 分离，至少包含：

```text
last_successful_trading_day
latest_completed_trading_day
latest_eligible_trading_day
archive_lag_trading_days
current_task
last_error_type
last_error_at
retry_count
scheduler_heartbeat
active_binding_end
active_binding_ends
next_retry_at
authorization_hash
lock_status
```

`archive_lag_trading_days` 只统计越过安全延迟的交易日；`active_binding_end` 先按七个 required JM Profile/period identity 各取结束日最新的 active passed binding，再取七者的共同最小结束日。这样保留 long-horizon profile 的历史分段合约时，不会把历史合约终点误报为当前归档覆盖终点。enabled 状态下 DB/Redis/heartbeat/checkpoint/授权失败 fail-closed，安全延迟内 idle 不报假失败。工程只读探针完整读取最多 1 MiB 的 JSON 响应；不得再以固定 4096 字节截断健康载荷，超限则明确报告 `payload_too_large`。

## 模拟与安全 supervisor smoke

定向和全量验证使用 SQLite/临时目录、fake clock/provider/Redis 及既有 archive-contract-v2 mocks，覆盖多日漏跑、5 日上限、首日失败阻断、provider pending、六档重试、显式恢复、packet/授权漂移、create-only/idempotency、commit 后 receipt recovery、lock conflict/lease lost、heartbeat 和 health。

安全 supervisor smoke 使用一次性 Redis 容器和临时 launchd label，只运行 `--supervised-smoke`：不打开 DB/provider，不写 checkpoint/Parquet/Profile。KeepAlive 在 4 秒内完成 3 次 clean run，heartbeat 为独立 `:smoke` key；临时 label 与容器均已移除。生产 label 未加载。

不可覆盖的模拟摘要位于 `data/reports/jm_eod_incremental_automation_s6_07/simulation_20260721_issue46/simulation_acceptance.json`。

验证结果：

```text
targeted S6-07/T4/runtime health: 72 passed
backend full: 1177 passed, 3 skipped
engineering: 29 passed
full app/tests ruff: passed
shell/plist lint: passed
temporary PostgreSQL migration: 0022 -> 0023 -> 0024 -> 0025 passed；五张表 row count 不变，checkpoint=0
supervised smoke: 3 KeepAlive runs，临时 label/Redis 已清理，生产 label 未加载
```

首次 PostgreSQL migration 验证准确暴露了一个 65 字符索引名超过 PostgreSQL 63 字符上限的问题；失败事务未产生半迁移。修复为显式短索引名并对 ORM/migration 对齐后，同一完整链重新执行通过。SQLite 单测不作为 PostgreSQL migration Gate 的替代。

`2026-07-23` 最终验收分支与当前 main 合并后的最新验证为：

```text
targeted S6-07/T4/runtime health/final verifier: 80 passed
backend full: 1226 passed, 3 skipped
engineering: 42 passed
full app/tests ruff: passed
secret scan: passed, 9174 files
```

`2026-07-24` checkpoint recovery修复验证：

```text
targeted S6-07/archive/deployment/health/final verifier: 121 passed
backend full: 1263 passed, 3 skipped
engineering: 44 passed
full app/tests ruff: passed
secret scan: passed, 9170 files
real PostgreSQL READ ONLY recovery fact collection: mode=schema_upgrade_with_checkpoint_recovery, revision=0022, checkpoint=0, assets=6, active bindings=7, forbidden counters unchanged
```

`2026-07-24` D2 completion 与最终 Gate 验证：

```text
targeted S6-07/archive/deployment/health/final verifier: 123 passed
backend full: 1265 passed, 3 skipped
engineering: 44 passed
full app/tests ruff: passed
shell syntax / all launchd plist lint: passed
secret scan: passed, 9172 files
D2 completion snapshot: sha256=ddbcc21d508df6a9b1392ebc8bf7d4b54b89624b7f71b7f326620b00687d0245
final receipt: sha256=84ea496f1f7140f72657c2f53f2fca675bf38ad466fd94e601cfd1e62772c4e4
```

D2 停机前 create-only 基线位于 Runtime Git-ignored 审批目录：

```text
.run/approvals/s607/00668660/d2_20260724_pre_outage_baseline.json
sha256=3487352e985661a0faaa655aaecaa3a7b90c3949bf3d495957d67a4d917f4a8b
```

该基线绑定 Runtime/enable packet、`2026-07-23` receipt、六个当日资产、48 个旧 active 资产、checkpoint、heartbeat missing 状态及四类禁写 counter；它不是 D2 completion，也不提前发布最终 Gate。

## 真实验收与 Gate

已完成：

1. health response schema、active binding health、独立 scheduler、checkpoint、singleton/heartbeat 和闭市 live idle hotfix 已合入；
2. recovery deployment 将 Runtime 恢复到 `19e6ca313105ad04e409e8a328558c83fdcbdf58`，PostgreSQL=`20260721_0025`，并只恢复最早失败日 checkpoint；
3. service enable packet hash=`6ea4a54138a697f24858401800c37a681bc82d928ae855837e9b69c75c5005ed` 已批准，生产 label只操作 `com.guiyi.quant-after-market-scheduler`；
4. D1=`2026-07-22` 正常自动归档通过，receipt Gate=`JM_EOD_ARCHIVE_DAY_PASSED`；
5. D2=`2026-07-24` outage 证据证明 label unloaded、enabled=true、watermark仍为`2026-07-23`、lag=1、heartbeat missing且 receipt 不存在；
6. scheduler恢复后自动生成 `s607_20260724_19e6ca31`，7 个资产、manifest、checksum、metadata、quality、Profile consumer 与旧资产 immutable 全部通过；
7. checkpoint=`idle`、watermark=`2026-07-24`、lag=0、required `active_binding_end=2026-07-24`、Redis lock/heartbeat 正常，四类禁写 counter 增量均为 0；
8. 最终 verifier 在 clean commit `405d813ddcbdc8be1c3155819c8be5da35938a4e` 上通过并 create-only 发布 receipt。

最终验收器分别绑定 D1 enable packet、outage enable packet和 D2 enable packet。发生已批准 recovery deployment 时，只接受 D1/outage Runtime commit 均为当前 D2 Runtime commit 的 Git 祖先，并要求各 packet hash 有效、历史成功资产保持 immutable；不得把任意跨 commit 证据拼接为通过。

最终 receipt：

```text
data/reports/jm_eod_incremental_automation_s6_07/real_acceptance_20260724_19e6ca31/completion_receipt.json
sha256=84ea496f1f7140f72657c2f53f2fca675bf38ad466fd94e601cfd1e62772c4e4
```

最终 Gate：

```text
JM_EOD_INCREMENTAL_AUTOMATION_READY
```

该 Gate 仍不代表 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
