# HTDY 五交易日长稳与故障恢复 Gate（S6-10）

更新时间：2026-07-27

## 状态

```text
CONTRACT_IMPLEMENTED
CODE_COMPLETE_EXTERNAL_GATE_PENDING
BACKUP_RESTORE_PREREQUISITE_BLOCKED
FAULT_INJECTION_NOT_AUTHORIZED
LONG_RUNNING_READY=false
```

## 硬前置

- S6-07 Ready、HTDY S6-08 Passed、S6-09 single-send Passed；
- full backup 和 isolated restore smoke Passed；
- autosend=false；
- SignalEvent 长稳策略只产生 observation event，不自动通知。

当前机器未挂载精确独立备份盘 `/Volumes/GuiyiBackup`，因此本分支只能完成
packet/ledger/observer/Runtime routing/CLI 代码与 fake tests。禁止创建同名普通目录冒充挂载，
禁止用历史 W7/W8 测试代替本次真实 full backup 与 isolated restore receipt。

## 已实现公共接口

- `app.services.htdy_s6_10_stability`
  - `HtDyS610ParentPacket` / `HtDyS610DailyChild`
  - `HtDyS610Observer.sample()`
  - `HtDyS610Ledger`
  - schema-v4 parent/daily child、canonical hash、create-only sample/daily seal
- `app.services.htdy_s6_10_runtime_gate`
  - 多日 Runtime Gate；旧 S6-08 schema-v3 Gate 保留
- `app.services.htdy_s6_10_runtime_support`
  - DB/Profile/calendar/Runtime/source/receipt/flag 的 fresh collectors
- `scripts/jm_htdy_s6_10_stability_gate.py`
  - `prepare / verify / calendar-apply / start / sample / seal-day /
    inject-fault / finalize / stop`
- `scripts/run-htdy-s610-observer.sh`
  - 每 60 秒调用只读 sample；不含 WeCom、订单或交易调用
- `deploy/launchd/com.guiyi.quant-htdy-s610-observer.plist.template`

Runtime scheduler 只在 packet 为
`schema_version=4 + packet_type=htdy_s6_10_five_day_parent` 时路由 S6-10；
设置 `GUIYI_HTDY_S610_REQUIRED=true` 后，schema-v3/S6-08/S6-09 packet
不能冒充 S6-10。

## 五日合同

- 至少五个真实 DCE 交易日，包含夜盘和每日 EOD 自动增量；
- 持续采集 Runtime commit、flags、actual mapping、scheduler heartbeat、EOD watermark、
  15m snapshot hash、HTDY candidate/created/unchanged/blocked、事件与通知计数及错误恢复；
- HTDY 同桶不重复、不产生 `signal_changed`，不自动通知；
- live 不进入 historical active；失败记录不得删除或改写；
- 任何代码、policy、schema、strategy 或 Runtime deployment 变化重置五日窗口；
- JM session geometry 固定为 23 个 15m 桶/交易日；首轮 27-bar repaint zone
  加五日 115 桶的理论 observation bar 上限为 142，parent event 安全上限为 160；
- notification 基线固定为 2；长稳窗口不得新增 `SignalNotification`；
- sample/daily seal 均 create-only，sample 以 `previous_sample_sha256` 串联，
  新交易日首条 sample 绑定前一日 `seal_hash`；每次 append/seal 都重验此前整条链；
  passed seal 还必须覆盖夜盘及三段日盘，采样最大间隔 150 秒，并且只能在 15:00 后生成。
  `finalize` 必须精确匹配 parent 的五个日期和五个 passed seal。

## Approval C

故障注入必须在执行前一次性冻结并批准完整矩阵和时间窗口：live scheduler、未加载或关闭状态的
notification worker 边界、API/Web、Redis、PostgreSQL、网络/RQData 和 Mac 重启恢复。
未取得 Approval C 前只允许工具、Ledger、fake tests 和只读观察。

Approval C 必须精确绑定：

1. S6-10 code-only Runtime deployment；
2. S6-07 code-only rebind 与 automation enable；
3. 五日 DCE/RQData calendar/window operations；
4. schema-v4 parent hash；
5. observer launchd identity；
6. D1–D4 及 D4→D5 reboot 的具体 fault slot/target/watchdog。

所有高风险命令同时要求 parent hash、Approval C bundle hash 和独立 detached-signature
批准 receipt。prepare 只生成带随机 challenge 的 approval request；批准 receipt 必须声明
`approved=true` 等价状态及五项精确授权，并通过 parent 预绑定的 `approved_signers` 公钥以
`guiyi-htdy-s610` namespace 验签。Gate 还把 signer fingerprint 固定为本机既有用户
SSH 公钥的 canonical trust root；prepare 参数只能提供该公钥的 allowed-signers 表达，
不能换成调用者临时生成的 key。每次执行均重新校验
deployment/rebind/enable packet、observer plist 和 fault schedule 的路径、文件 hash 与内部
packet hash；Runtime 每轮也重新验证 bundle 和 parent fresh bindings，禁止用 parent
self-hash 自签授权。

Approval C receipt 的冻结结构为：

```json
{
  "schema_version": 1,
  "status": "approved",
  "task_id": "JM-LIVE-STABILITY-S6-10",
  "bundle_hash": "<approved bundle hash>",
  "parent_packet_hash": "<parent hash>",
  "approval_challenge": "<bundle random challenge>",
  "approved_at": "<timezone-aware ISO-8601 before window_start>",
  "authorizations": {
    "deployment": true,
    "s6_07_rebind_and_enable": true,
    "calendar_window": true,
    "five_day_runtime": true,
    "fault_matrix": true
  }
}
```

用户批准时以既有 `id_rsa` 对该文件原始字节执行
`ssh-keygen -Y sign -n guiyi-htdy-s610`；Gate 使用 principal `guiyi-owner`
和 pinned fingerprint 验证 detached signature。私钥、签名内容和任何凭据不得进入仓库。

`inject-fault` 在 Approval C 前不得执行。平台执行器要求 detached watchdog 先写 create-only
armed marker 才允许停止依赖或装载 PF anchor；watchdog 清理后另写 create-only receipt。
恢复证据重新采集 notification worker load state、notification 总数、WeCom attempt 总数、
launchd PID/heartbeat 或 HTTP health，以及真实 RQData calendar probe，不能用常量或 fake
harness 代替。

备份前置不相信手写 JSON：Gate 会调用仓库 `verify_backup_artifact()` 重新验证独立盘
manifest sidecar、inventory、全部文件、Profile binding 与 database dump；isolated restore
receipt 必须位于 `/private/tmp/guiyi-restore-s610-*`，绑定 postgres:16、隔离数据库、
container/volume cleanup 与五个精确 GET consumer。prepare 随后还会使用该 verified artifact
再执行一次新的 disposable postgres:16 independent restore audit，并把新的 audit receipt
绑定进 parent；仅手写原 receipt 和 sidecar不能通过。

五日 window 的每一行还冻结真实 RQData 前一交易日作为 `night_session_date`，因此周一和
节假日后的夜盘不会被错误地按“自然日减一”计算。生产 sample 时间来自本轮 collector 的
UTC `observed_at`，CLI 不提供历史时间回填参数。

只有五日 Ledger 与故障恢复全部通过后，才可发布本地个人工作站范围内的
`LONG_RUNNING_READY / JM_RUNTIME_READY`；不包含公网、SaaS、多用户或自动交易。

## 当前验收状态

```text
S6_08_S6_09_MERGED_TO_LOCAL_MAIN=true
ORIGIN_MAIN_PUSHED=false
RUNTIME_COMMIT=844b3f9b...
DATABASE_REVISION=20260721_0025
SIGNAL_EVENTS_ENABLED=false
WECHAT_AUTOSEND_ENABLED=false
S6_10_CODE_TESTED=true
S6_10_REAL_BACKUP_RESTORE=false
APPROVAL_C_ISSUED=false
FIVE_DAY_WINDOW_STARTED=false
```
