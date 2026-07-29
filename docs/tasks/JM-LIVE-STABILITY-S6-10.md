# HTDY 15m 收盘观察与长期晋级 Gate（S6-10）

更新时间：2026-07-29

## 状态

```text
SCHEMA_V7_DECISION_CLOSE_CODE_COMPLETE_EXTERNAL_GATE_PENDING
SCHEMA_V5_FAILED_DEPLOYMENTS_PRESERVED
R12_DECISION_CLOSE_DEFECT_EVIDENCE_PRESERVED
FRESH_EXACT_C2_PENDING
COMPLETE_DAY_23_CLOSE_ACCEPTANCE_PENDING
APPROVAL_D_NO_CODE_PROMOTION_PENDING
LONG_RUNNING_RUNTIME_CONSUMER_CODE_COMPLETE_EXTERNAL_GATE_PENDING
LONG_RUNNING_READY=false
DISASTER_RECOVERY_READY=false
```

schema-v4 五日合同及其 packet、receipt、snapshot、restore 和 observer 证据均为
create-only 历史证据，状态为 `superseded`；不得覆盖、删除或复用其 Approval C。
schema-v5、schema-v6 及 r12 材料同样保持 create-only 历史证据。当前 active 工程合同是
schema-v7：从成功 activation 后的下一根完整 15m 桶开始，每次 confirmed close 扫描冻结
27-bar 窗口；旧 K 线 observation 若在本次收线首次显现，按当前 `decision_bucket_end`
进入 Gate，同时保留原始 `bar_end`。它不补发历史事件、不把缺失时段算作通过，也不再把
backup/restore 作为硬前置。
通用备份能力和旧产物保留，但本 Gate 明确
`backup_required=false / disaster_recovery_ready=false`。

## schema-v7 active 合同

- `strategy_version=v1.1`
- `signal_policy=htdy_original_xma_15m_close_first_seen_v1`
- `decision_trigger=confirmed_15m_close`
- `partial_allowed=false`
- parent 固定目标交易日、最晚 activation 时间、EOD 与
  `next_full_15m_bucket` 规则；
- activation receipt 冻结首个允许收盘点及不超过 23 个的剩余桶 allowlist；
- 正在形成的 partial 桶与 activation 前已收盘桶均不进入 evaluator；
- 1m 只负责 confirmed 聚合；第 15 根确认后判断一次；
- 同桶 polling/revision 不重复判断；重启重算依靠事件和通知唯一键保持幂等；
- 每次收盘仍扫描冻结 27-bar XMA 重绘窗口，首次 observation 不撤回且不产生
  `signal_changed`；
- `bar_end` 表示原始 observation K 线，lineage 的 `decision_bucket_end` 表示本次确认
  收线；evaluator、Ledger、dispatcher 必须统一按后者，缺失时 fail-closed；
- 全局 `GUIYI_WECHAT_AUTOSEND_ENABLED=false`；专用 dispatcher 仅接受当前 parent
  内 JM actual、15m、v1.1 的 `signal_created`；
- 每事件一条通知、最多 3 次尝试、全日最多 23 条，窗口结束失效；
- 消息固定声明“仅供观察、不是交易指令、不自动下单”。
- 剩余窗口最终结论只能是 `REMAINING_TRADING_DAY_STABILITY_PASSED...`；完整日父包必须
  覆盖 23 次收线并 EOD passed，之后仍需独立 Approval D 才能同代码晋级长期 daily child。

### r12 事实与根因

r12 在 2026-07-29 14:15 confirmed close 首次创建 event 5/6；其原始 `bar_end` 分别来自
更早的 XMA observation K 线。旧 evaluator 没有冻结独立 decision close，dispatcher 与
Ledger 又用原始 `bar_end` 对 activation allowlist 过滤，因此事件写入但通知和 Ledger
事件数均为 0。该行为不是无信号，也不是应当追发的历史通知；r12 只作为缺口证据保留，
不得验收、修改事件或复用其 C2。

schema-v7 还将 DB 不可变哈希与获准的 exact SignalEvent/SignalNotification 增量分离，
避免合法通知行反过来触发 `parent_bindings_drift`；部署配置改为
`--arm → activation receipt → --activate`，并要求 Runtime health 验证 exact parent、
最近 decision close 与 observer/dispatcher 心跳。

完整日 16:00 后不再评估或发送；observer 转为最长 3 小时的只读 finalizer，使用盘中生成并
双写 Redis/evidence 的 create-only terminal seal，等待 S6-07 在 120 分钟安全延迟后把目标日
checkpoint 推进，再生成唯一 `final_acceptance.json`。EOD heartbeat 即使被周期任务刷新为
`running/idle`，只要 fresh、非 failed 且 durable checkpoint 精确落在目标日，仍可确定验收。
不可变表全内容摘要用 PostgreSQL `xmin` 变更标记缓存；真实库只读基准为首次约 1.093 秒、
同进程无变化复核约 0.024 秒。

### Approval D 长期晋级

完整交易日 23-close acceptance sample 必须证明 partial=0、signal_changed=0、通知无失败/
重复/超限、四项 health 为 true 且 S6-07 EOD passed。Approval D request 绑定该 sample、
parent 与同一 commit/tree；receipt 还必须通过固定 signer trust root、SSH signature、
namespace/principal 与批准时间验证。批准后每日 child 仍绑定当日 rank=1 主力、session geometry、
source facts 和前一交易日 EOD。前日 EOD 非 passed 时下一日 fail-closed。长期路径复用 S6-07，
不新增 EOD scheduler，global autosend 与 auto_order 始终为 false。

当前仓库已补齐 Approval D request/签名校验、权威 daily facts、create-only daily child、
Runtime/scheduler 路由、observer/dispatcher/health 消费和同日恢复/跨日轮换。每日 child 的
authorization hash 是 Runtime、Ledger/heartbeat 与 bounded dispatcher 的唯一当日授权；
静态 Approval D hash 只是根授权，不能直接替代 daily child。该状态仍只是
`CODE_COMPLETE_EXTERNAL_GATE_PENDING`：没有 fresh 完整日 C2、Approval D 签名和真实部署
证据时，不是 `LONG_RUNNING_READY`，也不得用手工 child 文件绕过 Gate。

长期链还在下一夜盘前四小时执行独立 mapping preflight。它只在相邻前一交易日 S6-07
checkpoint 的 authorization hash 精确通过时调用
`rqdatac.futures.get_dominant(jm, exact_day, rank=1)`；事务内使用 canonical strict resolver
创建或验证一条逻辑 `MainContractMap`，允许同合约不同 data version 的合法 supersession，
但不同合约、同 version 重复、非 actual contract 或 RQData/DB 漂移均 fail-closed。盘前
mapping 事务先 commit，随后 create-only 发布 `mapping_receipt.json`；至少下一次 scheduler
cycle 才能只读验证 receipt、预先发布或恢复 daily child，然后构建 handler 并进入信号事务。
active session receipt 缺失和日内休市均禁止补建 mapping，避免事件先于授权证据提交。
observer、dispatcher、health 的 metadata 路径只读验证既有文件，禁止自行调用 RQData、
写 DB 或创建证据。receipt identity 不绑定数据库 sequence id，绑定 Approval D hash、
交易日、raw/normalized contract、provider/rule/rank/data version 与 RQData response hash。

首个 schema-v7 完整日与上述 Approval D 日切使用同一 canonical mapping resolver，但授权源
不同。首日必须先验签 exact Approval C2 parent，再在 full deployment preflight 前执行一次
C2-bound mapping transaction；否则 preflight 会要求尚不存在的目标日 mapping，而该 mapping
又会等待部署后的 Approval D，形成无法启动的循环依赖。该首日路径仍先验证 source/deployment、
旧 Runtime、global autosend=false、signal/dispatcher=false 与 deadline，任何漂移都在
RQData 和 DB 之前 fail-closed。mapping DB commit 后才 create-only 发布 receipt；receipt
已存在时重启只读 rebind DB，禁止再次调用 RQData。activation receipt 只在 activate 后的
allowlist 校验中必需，不能作为 pre-activation、activation-ready 或 Runtime switch 的前置输入。

Approval D request 不信任 acceptance 中的 `complete_trading_day_passed` 布尔值本身：
必须重算 schema-v7 sample type、partial/rejection、DCE 权威 23 个 aware close 与 evaluated
逐项相等。daily source facts 精确镜像 evaluator 的 `live_observation_v1` 合同，绑定 active
profile、actual-contract 1m/15m、RQData、bars、primary、passed、版本/checksum 及文件实哈希；
任一漂移在 child 发布前 fail-closed。

实现入口：

- `app.services.htdy_s6_10_one_day`
- `app.services.htdy_s6_10_one_day_runtime_gate`
- `app.services.htdy_s6_10_one_day_notifications`
- `app.services.htdy_s6_10_one_day_ledger`
- `app.services.htdy_s6_10_remaining_window`
- `app.services.htdy_s6_10_remaining_window_runtime_gate`
- `app.services.htdy_s6_10_remaining_deployment`
- `app.services.htdy_s6_10_service_heartbeat`
- `app.services.htdy_s6_10_long_running`
- `app.services.htdy_s6_10_long_running_runtime_gate`
- `scripts/jm_htdy_s6_10_remaining_window_gate.py`
- `scripts/jm_htdy_s6_10_remaining_deploy.py`
- `scripts/jm_htdy_s6_10_one_day_gate.py`
- `scripts/jm_htdy_s6_10_one_day_dispatch.py`
- `scripts/configure-htdy-s610-one-day-runtime.sh`
- `scripts/configure-htdy-s610-long-running-runtime.sh`
- `scripts/install-htdy-s610-one-day-services.sh`
- `scripts/run-htdy-s610-one-day-observer.sh`
- `scripts/run-htdy-s610-one-day-dispatcher.sh`
- `deploy/launchd/com.guiyi.quant-htdy-s610-one-day-observer.plist.template`
- `deploy/launchd/com.guiyi.quant-htdy-s610-one-day-dispatcher.plist.template`

同一 Runtime 进程内只共享最后一个 confirmed 15m `bucket_end` checkpoint，不共享数据库
session；因此约 20 秒 polling 不会重复进入 evaluator。进程重启后 checkpoint 重置并允许
安全重算，事件与通知仍由数据库唯一键防重。observer 只从
`htdy_close_evaluation_summary` 结构化日志统计唯一收盘桶。

绑定 `71172a5a…0b2e` 的 Approval C2 已在首次部署尝试中消费。Runtime 切换后，
observer/dispatcher 因未继承本机 Redis 密码而认证失败；S6-07 after-market scheduler
也因 enable packet 仍绑定旧 commit 而报告 `automation_bound_fact_drift`。Gate
fail-closed 后已卸载两项新服务、关闭 schema-v5 signal/dispatcher 授权，并把 Runtime
恢复到 `3ef58f5f`。失败 receipt 明确记录没有新 SignalEvent、SignalNotification 或
WeCom request。

替代合同要求 observer/dispatcher 使用与既有 Runtime runner 相同的 authenticated
Redis URL 规则；新 parent 还必须哈希绑定 S6-07 code rebind packet、新 enable packet
及 schema-v5 deployment packet。deployment receipt 绑定最终 C2 parent，执行 rebind
时重新验证 parent → rebind/deployment 文件哈希 → target commit 的完整链，避免循环依赖。
已消费的 `71172a5a…0b2e` 不得复用。

2026-07-29 对 `8119dbba…8d64` 的 schema-v7 首次完整日部署尝试，在任何 Runtime 切换、
mapping/SignalEvent/SignalNotification/企微或订单写入前，以
`mapping_duplicate_or_missing` fail-closed。审计确认初始 mapping 与 activation receipt
均存在前后置循环依赖；该 C2 与 artifacts 保留为失败证据，不重试、不手工补 mapping，
修复后必须冻结新 commit/tree 并生成新的目标日 parent/C2。

第二份 parent `36559086…1465f` 已完成 code-only Runtime switch 和 S6-07 rebind，
但在装载 schema-v5 observer/dispatcher 前被 fresh Runtime Gate 拒绝：
`runtime_tree/source_tree` 错把 40 位 Git tree OID 当作合同值，而 collector 使用
`sha256(tree OID)`；initial bindings 还遗漏了绝对 `parent_packet_path`。Gate 未被绕过，
随后恢复旧 Runtime/EOD packet，数据库仍为 4 个 SignalEvent、2 个
SignalNotification，企微请求为 0。该 C2 同样已消费，不得修改 parent 或复用。

后续生成器必须从目标 commit 本身重新解析 tree OID 并哈希，禁止相信调用方手填 tree；
parent build 必须拒绝 40 位 raw tree、缺失 parent path、非 clean Runtime binding。
新 C2 生成前必须用与 Runtime collector 相同的 tree identity 算法重算目标 commit，
并对 staged parent 的绝对路径、artifact hash 和 Git binding 做预检。

第三份 parent `1fce29b7…62403` 已通过上述 tree/path 预检并启用 schema-v5 服务，但
observer 在 267 个启动前样本后发现 `parent_bindings_drift`：packet 中的
`profile_sha256`、`baseline_hashes` 是从早期目录复制的旧 DB snapshot，而非在本次
parent 生成前重新采集。它没有造成新 SignalEvent、SignalNotification 或 WeCom request；
服务和授权已再次 fail-closed，且失败 receipt 保存在
`/Volumes/扩展盘/GuiyiApprovals/s610/8d278d0e-20260729-one-day-c2/`
`runtime_drift_fail_closed_receipt.json`。该 C2 已消费，不得复用。

修复后的 `refresh-bindings` 子命令以 read-only transaction 从当前 PostgreSQL 收集
`database_revision`、profile hash、受控表 counts/hashes、max-id baseline 和指标/policy
hash，然后才允许 `prepare-deployment` / `prepare` 生成新的 create-only artifacts。它保留
operator scaffold 中的目标 code、artifact path 和 fail-closed flag 合同，但绝不继承旧
packet 的 DB lineage；`backup/restore` 字段仍被剔除。任何新 parent 仍须经过新的精确 C2。

单一 deploy/orchestrator 固定执行“停专用服务 → 暂停 after-market → Runtime 切换 →
S6-07 rebind → 恢复并核验 after-market → 配置 pending activation → 创建 activation
receipt → 检查首桶启动余量 → 启动专用服务与 signal Runtime”。
任一步失败均卸载 observer/dispatcher、关闭专用授权、恢复旧 Runtime 与 after-market，
其中回滚 Runtime 使用部署前 S6-07 enable packet 所绑定的已知可恢复 commit/tree，
回滚 after-market 使用该 parent 另行绑定的部署前 packet/hash，而不是新 Runtime packet。
回滚不完整时 receipt 必须明确 `rollback_incomplete`，不得伪装 fail-closed 成功；所有
create-only 失败 receipt 和既有审计记录均保留。

schema-v6 r1～r3 分别绑定 `1240364f…a1e`、`7b35f4bc…e0a`、
`003d5bb2…7d5`，均在 `restore_after_market` 失败并已消费。最终根因不是
S6-07 未恢复，而是恢复验证器依赖目标或回滚 Runtime 的 `/api/runtime/health`
heartbeat PID 字段；部署前 Runtime `8d278d0e` 的旧 health schema 不含该字段，所以
回滚服务即使随后正常持有 Redis lease 也会被永久判定失败。r4 修复要求：

- bootout 后只等待 `guiyi:eod:jm:scheduler:singleton` lease 自然释放，禁止删除或覆盖；
- 在一个 300 秒 monotonic 总截止时间内完成等待、配置、启动和验证；
- 直接读取 Redis heartbeat owner，要求 fresh `generated_at`、`lock_status=held`、
  heartbeat PID 与 launchd PID 一致；
- Runtime health 仍验证 enabled/status/authorization hash，但不得再把 API 是否暴露
  heartbeat PID 作为恢复成功的必要条件；
- forward 与 rollback 使用同一恢复函数，因此必须兼容旧 Runtime health schema。

schema-v6 r4 绑定 `a83f5cb6…af42` 与 source `3c4dd56c…`。它完成 code-only
Runtime switch 和 S6-07 rebind，前向 scheduler 也在数据库留下了从旧 enable hash
轮换到 r4 enable hash 的审计历史，但组合恢复验证仍在截止时间内未通过。回滚随后完整
成功：Runtime 回到 `8d278d0e…`，S6-07 恢复旧 packet 且健康，observer/dispatcher
未加载，signal/bounded WeCom/global autosend 均为 false；SignalEvent=4、
SignalNotification=2、orders=4225、trades=4361，均与 pre-activation baseline 一致。
r4 failure receipt 保持 `failed_closed`，该 C2 不得复用。

后续恢复验证必须在回滚覆盖日志前发布 create-only 脱敏 observation，逐项记录：
runtime env packet/hash/enable 匹配、launchd PID/running、API enabled/status/auth 匹配、
Redis heartbeat timestamp/status/PID/lock owner 匹配及最终组合结论。诊断只记录哈希、
PID、状态与时间，不得记录 Redis/DB/企微凭据；failure receipt 必须绑定诊断文件 sha256。

schema-v6 r5 绑定 `58c2557b…96b8` 与 source `3e1cfbe3…`。首次调用在 Docker
未运行时止于无写入 preflight；依赖恢复后的正式调用进入 `restore_after_market`，并由
新 diagnostic 精确确认 env packet/hash/enable、launchd PID 与 Redis heartbeat owner
全部匹配，但 API 仍报告 `enabled=false/status=disabled`。根因是 configure 更新
`project.env` 后只启动 after-market scheduler，API 进程未重启，因而 Runtime health
继续持有旧环境。r5 随后完整 fail-closed：Runtime 回到 `8d278d0e…`，旧 S6-07 健康，
observer/dispatcher 未加载，signal/bounded WeCom 授权关闭。r5 C2 不得复用。

forward 与 rollback 的 S6-07 restore 必须在 configure 后、scheduler install 前，于同一
bounded deadline 内 kickstart API；API 重载新 packet/hash/enable 后再组合验证 launchd、
API 与 Redis owner。该顺序不得通过延长 timeout 或放宽 API Gate 替代。

真实 Runtime 部署、SignalEvent 写入和企微发送必须等待新 source commit、精确交易日、
parent hash、23 条上限及范围全部签入新的 hash-bound Approval C2。宽泛实现批准或旧
Approval C 均不构成授权。无自然信号时只允许结论
`REMAINING_TRADING_DAY_STABILITY_PASSED_NATURAL_SIGNAL_PENDING`。
Approval C2 receipt 继续使用既有 `guiyi-owner / guiyi-htdy-s610` SSH detached
signature trust root；仅有 JSON 或 self-hash 不能启动 Runtime/dispatcher。

## schema-v4 历史合同（superseded）

## 硬前置

- S6-07 Ready、HTDY S6-08 Passed、S6-09 single-send Passed；
- full backup 和 isolated restore smoke Passed；
- autosend=false；
- SignalEvent 长稳策略只产生 observation event，不自动通知。

用户已明确选择当前扩展盘作为 S6-10 备份介质。精确目录为
`/Volumes/扩展盘/GuiyiBackup`，仅允许使用
`--same-device-milestone-snapshot` 创建 full/milestone/no-raw 快照。该证据验证
文件、DB、Profile 和 isolated restoreability，但
`independent_device_backup=false / disaster_recovery_ready=false`，不得表述为独立盘灾备。
禁止用历史 W7/W8 测试代替本次真实 full snapshot 与 isolated restore receipt。
当前 7 条 active Profile bindings 中有 7 条绑定到 S6-07 materializer 的 6 个
create-only canonical 文件，位于
`/Volumes/扩展盘/GuiyiApprovals/s607/4d05370f-20260727-materializerfix/retry-service`。
备份必须用 `--approved-external-profile-root` 精确声明该根并复制这些文件；禁止忽略或
将其伪装成仓库内文件。

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

备份前置不相信手写 JSON：Gate 会调用仓库 `verify_backup_artifact()` 重新验证同盘 milestone
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
S6_10_REAL_SAME_VOLUME_BACKUP_RESTORE=false
S6_10_DISASTER_RECOVERY_READY=false
APPROVAL_C_ISSUED=false
FIVE_DAY_WINDOW_STARTED=false
```
