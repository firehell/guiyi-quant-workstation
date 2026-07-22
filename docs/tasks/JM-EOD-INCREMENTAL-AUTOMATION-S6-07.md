# S6-07 JM 收盘自动增量与漏跑补偿

## 当前状态

```text
JM_EOD_AUTOMATION_CODE_COMPLETE
JM_EOD_AUTOMATION_SIMULATION_PASSED
JM_EOD_AUTOMATION_SAFE_SUPERVISOR_SMOKE_PASSED
JM_EOD_AUTOMATION_DEPLOYMENT_PASSED
REAL_ACCEPTANCE_IN_PROGRESS
```

最终 Gate `JM_EOD_INCREMENTAL_AUTOMATION_READY` **尚未发布**。Issue 为 #46。Runtime 已同步至 `f2219e44`，PostgreSQL 已顺序完成 `0022 -> 0025` additive migration；API response schema、active binding health 与闭市 live idle 语义的 hotfix 已合入并部署。用户已精确批准 enable packet `e63cff7b...e215`，生产 `com.guiyi.quant-after-market-scheduler` 已运行，真实 Runtime health 为 `overall=ok`、heartbeat `ok`、lock `held`、archive lag 0。当前仍需完成一个正常自动归档日与一次停机漏跑补偿验收，因此状态保持 `REAL_ACCEPTANCE_IN_PROGRESS`，不得提前发布最终 Gate。

## 独立运行契约

- 进程：`python -m app.after_market_scheduler --run`。
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
- `code_only`：只接受 DB=`0025`，migration chain必须为空，部署前后保持 revision和checkpoint行数，不执行 Alembic。

两种模式都要求 Runtime tracked state为空、执行目录无未跟踪代码；确认部署后先清理 Runtime 源码 bytecode并重建 `.venv`，执行 frozen lock sync，再次验证代码树后才允许 Alembic或 API restart。生产 after-market launchd label在部署前后都必须被只读探针明确确认为未加载；探针错误不能等同于未加载。

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

代码或绑定事实变化后必须使用新的 service approval。既有 checkpoint 仅在 `idle/success`、无 current trading day、无 retry/error 时允许在已验证的新批准下原子轮换 `authorization_hash`，并在 `last_result.authorization_history` 保留旧/新 hash 和轮换时间；running、waiting、retry 或 blocked 状态继续 fail-closed，禁止借换包跳过失败日。

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

`archive_lag_trading_days` 只统计越过安全延迟的交易日；`active_binding_end` 先按七个 required JM Profile/period identity 各取结束日最新的 active passed binding，再取七者的共同最小结束日。这样保留 long-horizon profile 的历史分段合约时，不会把历史合约终点误报为当前归档覆盖终点。enabled 状态下 DB/Redis/heartbeat/checkpoint/授权失败 fail-closed，安全延迟内 idle 不报假失败。

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

## 真实验收与 Gate

已完成：

1. health response schema、active binding health 与闭市 live idle hotfix 已合入；
2. Runtime=`f2219e44`、PostgreSQL=`0025`，API/Web/live/after-market 服务已部署；
3. commit/runtime/DB/output/mount/revision 绑定的 enable packet已取得精确 hash 批准；
4. 配置已原子启用，独立生产 label运行，真实 `/api/runtime/health` 为 `overall=ok`。

真实验收尚需：

1. 验收一个正常自动归档日；
2. 人工停掉 scheduler，越过下一 eligible time 后启动并验收漏跑补偿；
3. 两次均验证旧资产 immutable、quality/manifest/checksum/metadata/Profile/consumer、receipt recovery 和 SignalEvent/notification/scan/strategy 零增量。

任一步失败保持 `REAL_ACCEPTANCE_IN_PROGRESS` 或 `BLOCKED`。两日全部通过后，才可生成最终 receipt 并发布：

```text
JM_EOD_INCREMENTAL_AUTOMATION_READY
```

该 Gate 仍不代表 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
