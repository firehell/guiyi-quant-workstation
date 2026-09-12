# historical-data-maintenance Specification

## Purpose

定义 Recent Trusted Window 内的 update、refresh、audit、physical-contract warm-up、固定水位和 quota natural resume。

## Requirements

### Requirement: Interrupted after-market closeout is explicit and never success

Target database, Redis, Canonical and universe dependencies MUST be composed from pinned target sources, not
the executing checkout. The private configuration MUST be an owned 0600 file in an owned 0700 parent. Assignment
names MUST use an exact allowlist and closeout dependency values MUST use literal assignments only.
Repository-enumerated retired keys with no active consumer MAY remain only
when they match an exact inert-key allowlist. Exact settings consumed by another active process but irrelevant to
closeout MAY also remain on a separate enumerated allowlist. Both classes' right-hand sides MUST remain opaque and
MUST NOT be parsed, executed or retained. Both classes MUST be removed before closeout dependency composition, and
neither MAY directly or indirectly expand into a dependency value. Only exact enumerated dependency
source keys MAY participate in dependency expansion. Unknown keys MUST still block; prefixes and wildcards MUST NOT
expand any allowlist. Launcher arguments and installed/loaded
environments MUST exclude unsupported shell, HOME and libpq overrides; executing PG* overrides and any target
dotenv file/link MUST block.
All source files and target-directory identity/ctime/mtime MUST predate the interrupted run and remain unchanged.
The private configuration, exact-tag launcher, universe sources and target-directory metadata MUST additionally
predate the earliest current consumer process. A staged installer MAY recopy only the shared launcher and individual
service plists after an earlier consumer started, provided that the shared launcher bytes equal the exact-tag source
and each installed plist's arguments, working directory and explicit environment entries match the loaded job.
These facts MUST be rechecked with actual dependency and fresh heartbeat identity before reads and replacement.

The close-interrupted-after-market command MUST default to read-only and bind the exact existing Runtime root,
commit and status-byte SHA-256. Five installed/loaded service identities, clean detached annotated release,
enabled Live/Alert recovery guard and an idle after-market process MUST be verified. The existing OS guard
and Catalog maintenance lease MUST be acquired nonblocking before a fresh read-only transaction. Missing
guard files MUST NOT be created. A same-day or previous-day valid current_run MAY be closed only when its
start is not in the future and its scheduled_date matches the original start date.

All operational Catalog pointers MUST pass the shared physical reader, including pointers outside the audit
window. Existing audit MUST verify metadata, rank1 and expected windows through the interrupted date. Only
proven missing valid subsets may remain pending; extra endpoints, other findings or unknown results MUST block.
The original day's Live snapshot MUST be classified as verified_match only when complete, valid and matching
rank1. A successful read returning None MAY permit administrative interrupted closeout with
not_verified_missing and reconciliation not verified. Empty/partial/extra/invalid/mismatching snapshots and
read failures MUST block, never become missing. No cause of absence may be inferred and no snapshot synthesized.
The snapshot MUST be read during audit and again before replacement; changed classification or content MUST
block without retry. The after-market guard does not freeze ordinary Live initialization; recorded evidence
MUST describe its observation time, not claim snapshot immutability throughout the closeout window.

Explicit apply MUST recheck identity and status bytes under both locks and atomically replace only the original
status file via its pinned directory descriptor. New closeout schema v5 MUST express interrupted, not passed, retain the old
successful day, and preserve unknown legacy attempts as null. It MUST NOT send notifications, publish an update
event, clean Live, call a provider, write market data or retry. A post-replacement uncertainty MUST report unknown
write outcome and bounded readback, never claim unchanged state. Readers MUST accept v1-v5; v5 MUST persist
the original snapshot day, observation time, classification and reconciliation verification status. Public
API, health and Web MUST preserve missing evidence. Existing v1-v4 semantics MUST remain unchanged and
old readers that cannot parse v5 MUST degrade. A subsequent natural run MUST preserve the interrupted
evidence when carrying its summary, never inherit it as success. Health MUST remain degraded/interrupted;
natural reconciliation and promotion predicates MUST remain unchanged, and this terminal MUST NOT count
as after_market_complete.

Compatible recovery, Runtime-bound daily/current-day maintenance, and deployment promotion preflight MUST
share one Python authority for this stopped terminal. The stopped branch MUST require exact schema-v5
interrupted bytes, the unchanged installed after-market plist/root/commit/config, a readable launchd domain,
the writer label explicitly absent, exact identities for the other four required services, and fresh Live and
Alert heartbeats proving the recovery guard. It MUST pin and recheck status, plist, root, process, config and
heartbeat facts before use; permission/error/unreadable results are not absence, and writer reappearance or
any drift MUST fail closed. Normal after-market closeout MUST continue to require all five services loaded,
with after-market idle. A stopped terminal MUST NOT by itself satisfy any promotion predicate.

#### Scenario: Stopped terminal is used by a compatible read-only entry point
- **WHEN** the exact v5 terminal, installed writer identity, explicit launchd absence, other four services and both heartbeats remain pinned and valid
- **THEN** the entry point may continue to its own independent read-only or dry-run checks without treating the interruption as completion

#### Scenario: Stopped authority becomes ambiguous
- **WHEN** the writer reappears, a pinned fact changes, or launchd returns anything other than an exact loaded definition or exact not-found result
- **THEN** the entry point fails closed before provider access, data publication or promotion

#### Scenario: Legitimately partial interrupted maintenance
- **WHEN** committed pointers and metadata are valid but expected partitions remain missing
- **THEN** closeout may record interrupted and pending findings without claiming the update or weekly audit passed

#### Scenario: Same-day stopped run without original Live evidence
- **WHEN** the run is verified idle and all committed-data, identity, guard and CAS checks pass, but the original snapshot read returns None
- **THEN** closeout may record interrupted with persistent not_verified_missing evidence, without declaring reconciliation or promotion ready

#### Scenario: Snapshot changes during closeout
- **WHEN** the original snapshot changes between audit-time and pre-replacement reads
- **THEN** closeout blocks and preserves the original status bytes without retry

#### Scenario: Filesystem sync fails after replacement
- **WHEN** replacement may have occurred but durability cannot be established
- **THEN** report AFTER_MARKET_CLOSEOUT_OUTCOME_UNKNOWN and status_written null, perform no retry or rollback

### Requirement: 公开维护面
系统 SHALL 公开 `update`、`refresh`、`audit`、`contract-warmup`、显式 `daily-recovery` 与
`current-day-metadata-recovery`。`audit` SHALL 接受
`(--symbol X | --universe {active,operational})` 的互斥选择器。无 `--apply` 的 update/refresh MUST 只计划，
不得写 PostgreSQL/Parquet；audit MUST 只读。
系统还 SHALL 公开一次性 `session-anchor-repair` 三阶段 seam：`plan` 只读输出精确 session、Dataset、
分区、预计缺失首分钟与稳定 scope hash；`prepare --apply` 只在外部 shadow root 使用真实 RQData 重建完整
Canonical；`publish --apply` 只在五项 Runtime 全部停止、manifest/基线/hash 未漂移时切换 root、reconcile
Catalog、执行精确 0045 并清理 publish 执行时由 operational phase authority 唯一解析的当前交易日旧锚点 Live Bar；此 repair cleanup MUST 保留 after-market reconciliation 所需的不可变 rank1 subscription snapshot。
0044→0045 legacy repair MUST 保持原合同；固定 `part.parquet` 写入仅隔离在 shadow prepare，不用于普通 maintenance 发布。

#### Scenario: 已退出动作
- **WHEN** 用户调用任何已退出的维护操作
- **THEN** CLI 不暴露该入口

### Requirement: Runtime-bound daily recovery is an exact hash-locked seam
`guiyi data daily-recovery` SHALL require an exact Runtime root, 40-character lowercase commit,
64-character lowercase after-market status hash and explicit `through`. The product scope MUST come only from the
validated Runtime operational universe. The command MUST construct
`UpdateRequest(products=runtime_products, since=None, through=through, apply=phase,
sync_current_day_metadata=False, mode="daily")`; it MUST NOT accept an operator product list, retry, resume, widen to
full maintenance, bootstrap historical metadata, send a notification or synchronize current-day metadata.

Without `--apply`, the command MUST validate the Runtime binding, perform only the existing daily read plan, construct
no provider client/request and mutate no DB, Canonical, status, projection or Redis fact. It SHALL return the canonical
target windows and `plan_sha256 = SHA256(UTF8(json.dumps(target_windows, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)))`. Each bounded target window MUST include dataset/year/month, inspectable
expected and missing endpoints/counts, plus `expected_bar_ends_sha256` and `missing_bar_ends_sha256`. Each per-set hash
MUST cover the complete sorted UTC ISO timestamp sequence using the same compact UTF-8 JSON encoding, so any internal
expected or missing timestamp drift changes the outer plan hash even when endpoints and counts remain equal. A dry-run
MUST reject `--expected-plan-sha256`. This identity enrichment is exclusive to `daily-recovery`; ordinary `update`
and `refresh` target payloads MUST retain the existing dataset/year/month/window-start/window-end/missing-count schema
and MUST NOT expose recovery identity fields.

`--apply` MUST require the exact lowercase dry-run `--expected-plan-sha256`. It MUST acquire the shared maintenance
lease before revalidating Runtime identity, pinned status and both Live/Alert heartbeats and recomputing the complete
dry-run target windows. A lock miss or any identity, status, dependency, heartbeat, target-window or hash drift MUST
block before Market Home projection invalidation, provider access and Catalog/Canonical writes. Only after those
checks may it invalidate the existing Market Home projection and execute exactly the same immutable target plan that
produced the checked hash, without a second dynamic plan. The provider configuration MUST be parsed from the pinned
target Runtime configuration, matched against the composed lazy adapter during both binding checks, and used to create
the provider client only after those checks. It MUST NOT fall back to the executing checkout or ambient provider
configuration. The shared `HistoricalDataManager` performs exactly one attempt; provider failure, partial completion
and commit-unknown remain literal and MUST NOT trigger a retry.

The command SHALL emit credential-free bounded NDJSON progress to stderr using the shared maintenance event fields,
including `started`, `completed`, `failed` and `interrupted`; final JSON remains the only stdout payload. Progress is
observational and MUST NOT create a second persisted authority or alter maintenance scope.

`current-day-metadata-recovery` 的 capture/plan/apply 负责当前/下一交易日 metadata 的 source/write
解耦；它不属于 historical Bar update，不得调用 full/daily maintenance、写 Canonical、失效 projection、
通知、retry 或改变 after-market status。精确 snapshot/diff、既有事实冲突、lease 内 Runtime/Catalog CAS、
provider-free apply 与 commit-unknown 合同由 `data-foundation-metadata` canonical 定义。

#### Scenario: Runtime or target identity drifts before apply
- **WHEN** any pinned Runtime fact or recomputed target-window hash differs while the maintenance lease is held
- **THEN** daily recovery fails closed before projection invalidation, provider access and data publication

#### Scenario: An internal bar end drifts without changing target endpoints or count
- **WHEN** a recomputed target has different expected or missing bar ends but the same dataset, month, first/last bar and count
- **THEN** its per-set identity and outer plan hash differ, and apply stops before projection invalidation or provider/write work

#### Scenario: One source attempt partially commits
- **WHEN** one provider target fails after earlier targets committed through the formal publication path
- **THEN** the failure is not retried, completed targets remain readable through Catalog/MarketDataService and the
  final result reports the literal failed/partial counts

#### Scenario: session-anchor plan
- **WHEN** operator 执行 `session-anchor-repair --phase plan`
- **THEN** 不调用 RQData、不写 DB/Parquet/Redis，返回稳定 scope hash 与精确影响计数

#### Scenario: publish 前基线漂移
- **WHEN** active file、Catalog、revision、shadow hash、D1/W1 hash 或 Runtime stop proof 任一不匹配 manifest
- **THEN** publish 在 root switch 与 0045 前 fail closed

#### Scenario: 0045 后步骤失败
- **WHEN** root/Catalog 已切换且 0045 已成功后 Redis cleanup 失败
- **THEN** 系统保持维护状态并返回 forward recovery required，不恢复错误 session 或混用新旧锚点

### Requirement: Exact physical-contract warm-up is a hash-locked maintenance seam
`guiyi data contract-warmup --symbol SYMBOL --contract CONTRACT --through DATE [--frequency {1d,1w,15m,60m}]` SHALL 只接受 active、
non-retired symbol 与其 RQData Contract identity。窗口 MUST 为该 Contract 的
`[listed_date, min(through, expired_date - 1 day)]`，且 `through` 不得晚于最近完整交易日。无 `--apply`
时 MUST 只读 Catalog/Calendar/Session，零 RQData 请求、零 PostgreSQL/Parquet/Redis mutation，并返回稳定
plan hash、direct/derived target 数、预计 Bar 数和 provider request 数。省略 `--frequency` MUST 保持全部七周期；
显式 `1d` MUST 只规划/执行 `1d`，显式 `1w` MUST 只规划/执行同源 `1d + 1w`，显式 `15m` 或 `60m`
MUST 只规划/执行同 contract 的 `1m` 基础和所选周期派生。payload 与 plan hash MUST 绑定所选 frequency、
完整 frequency scope 及其 dependency，即使 targets 为空也不得跨 scope 复用 hash。其它显式
frequency MUST fail closed。`--apply` MUST 要求相同的 lowercase
SHA-256 `--expected-plan-sha256`，在 maintenance lock 内重算计划；identity、lifecycle、session 或 hash
漂移时，必须在首次 provider 请求和写入前 fail closed。

apply 只可为指定 physical contract 获取 `1m/1d` 基础事实；`1w` MUST 由同一交易所完整日行情在 adapter
边界聚合，`5m/15m/30m/60m` 只由质量通过的同 contract `1m` 派生；不得写 continuous、其它 contract、
MainContractMap、Rule、Scope、Runtime、Redis Live、
Event 或通知。月分区仍依次经过 staging 与完整发布校验。任一显式 scope 的 provider、发布或派生失败 MUST 立即
停止该 contract 的后续 target。仅同族同月存在待补 `1m` target 时，才可在开始派生前推迟至源发布后；
已开始的派生/发布失败 MUST NOT 按缺源错误码自动推迟或重试。额度耗尽 MUST 返回 `partial`，不得报告 `passed`。部分成功 MUST 显式返回 `partial/failed`；不得
自动 retry，任何真实 RQData/Canonical apply 仍需一次与 exact plan hash 对应的独立授权。

#### Scenario: Warm-up dry-run is read-only

- **WHEN** operator 未传 `--apply`
- **THEN** 系统只输出 stable plan payload，不连接 RQData、不取得写锁且不改变任何数据或运行状态

#### Scenario: Explicit daily and weekly scopes preserve source families

- **WHEN** operator 指定 `1d` 或 `1w`
- **THEN** `1d` 计划只含 D1，`1w` 计划只含同源 D1 + W1，且跨月 ISO 周的两侧 D1 与 W1 整组验证后再发布

#### Scenario: Plan changes after operator approval

- **WHEN** apply lock 后重新计算的 contract identity、window、target 或 hash 与 `--expected-plan-sha256` 不一致
- **THEN** 系统在首次 provider request 和任何写入前拒绝执行

#### Scenario: Bounded 60m reuses complete same-contract minute input

- **WHEN** operator 指定 `--frequency 60m`，且目标月的同 physical contract Canonical `1m` 完整
- **THEN** 计划只包含缺失 `60m` 派生目标；获准 apply 从这些 `1m` 聚合，零 provider 请求，不修改其它周期或合约

#### Scenario: Contract warm-up sessions precede the active history floor

- **WHEN** 同 physical contract 的合法分钟来源早于 active history floor
- **THEN** 派生 Session 查询 MUST 按该合约生命周期、`through` 与 `RQDATA_INTRADAY_HISTORY_START` 解析完整逐日 Calendar/Session，不因 active history floor 丢弃这些窗口
- **AND** 缺失逐日 metadata MUST fail closed；`continuous` 的 Session 查询仍使用既有维护起点

#### Scenario: Bounded scope cannot reuse another scope hash

- **WHEN** operator 对 `60m` apply 提供默认七周期或 `15m` 的 plan hash，即使两计划均无目标
- **THEN** 系统在 callback、provider 和发布前拒绝；反向复用同样拒绝

#### Scenario: Explicit scope stops on the first failed target

- **WHEN** `1d`、`1w`、`15m` 或 `60m` apply 的 provider、源发布或派生失败
- **THEN** 后续 target 不再执行；保留已成功分区，零成功返回 `failed`、部分成功返回 `partial`；quota 返回 `partial`，不自动 retry

### Requirement: Bounded missing metadata repair separates plan fetch and apply
系统 SHALL 提供默认只读的 `metadata-repair`，以显式 physical contract/owner-through 列表和现有
Catalog identity/lifecycle 规划精确缺失 Calendar 与整个缺失 Session 日期。plan MUST 绑定相关既有
事实、缺键、来源和固定请求参数的 SHA-256，并分别报告自然日期键、Session 日期、未知实际行数与请求数。
fetch 与 apply MUST 分别显式选择 phase 和 exact hash；每次真实操作仍需独立单次执行意图。

#### Scenario: Unknown Calendar requires a second explicit plan
- **WHEN** 分类 fetch 对精确未知日期返回交易日事实
- **THEN** 该次 fetch 不追加 Session 请求；只有新的显式 plan 可以纳入这些日期并重算 hash

#### Scenario: Night evidence cannot be inferred from missing rows
- **WHEN** 交易日缺少当日精确夜盘正证据，且单品种日盘不足以证明交易所无夜盘
- **THEN** snapshot 保留 `NIGHT_SESSION_EVIDENCE_REQUIRED` 并禁止 apply；非交易日才可明确无夜盘

#### Scenario: Explicit context evidence cannot recursively widen scope
- **WHEN** operator 为已分类交易日的原缺失 Calendar 键指定额外 physical contract/date 供证
- **THEN** 系统校验该来源 Catalog identity/lifecycle，把请求绑定进新 plan hash；不扩 Calendar 键集合，不写供证 Session，不制造 MainContractMap

#### Scenario: Provider failure or disagreement stops this attempt
- **WHEN** 精确请求的响应越界、重复、缺失、格式错误或同品种日期多个物理来源不一致
- **THEN** fetch 立即停止后续调用，不 retry、不补充查询，也不提供可 apply 的 snapshot

#### Scenario: Apply observes drift or occupied Session day
- **WHEN** 新事务锁定后重读发现计划漂移、已有部分日、重叠 template 或身份冲突
- **THEN** 在任何插入前拒绝，既有行保持原样；成功仅插入缺失 Calendar 与整个缺失 Session 日期并一次 commit，异常全部 rollback

### Requirement: 分类 audit finding
audit SHALL 为每个请求品种独立检查并返回 `code`、`category`、dataset、year、month 的结构化 finding。
已知历史 Session、交易日历和产品窗口元数据缺口 MUST 分别使用 `metadata_session`、
`metadata_calendar`、`metadata_window` 分类，并继续审计其余请求品种；主力映射、预期分区缺失和
Catalog/Parquet 物理一致性问题 MUST 分别使用 `main_contract_map`、`partition`、`physical` 分类。
无法分类的基础设施异常 MUST 继续 fail-closed，不得伪造 finding。

#### Scenario: 一个品种缺少历史 Session
- **WHEN** active universe 的某个品种无法解析完整交易日并产生 `TRADING_SESSION_MISSING`
- **THEN** audit 返回该品种的 `metadata_session` finding，并继续返回其他品种的审计结果

### Requirement: fixed through 和 natural resume
`effective_start(symbol)` SHALL 为 `max(product_window_start(symbol),2023-01-01)`。update SHALL 以
显式 `--through` 或在规划开始解析的最新完整交易日固定本轮水位，检查全域月度 coverage；完整月跳过，
合法子集仅请求缺失 bars，冲突或不可读月整月重建。已发布 Catalog + Parquet SHALL 是唯一进度状态。

#### Scenario: same-T NOOP
- **WHEN** 所有预期月完整且再次运行相同 fixed through update
- **THEN** 结果为零目标、零 provider request、零写入

### Requirement: Daily maintenance is Catalog-bounded
`UpdateRequest` SHALL default to `full`; optional `daily` MUST reject `since` and require existing continuous
1m/D1 Catalog baseline, complete Calendar and gap-free rank1 mapping. It SHALL select current months,
Catalog-identifiable missing months and exact endpoint gaps, including mapped new dominant contracts.
Missing contract W1 MUST refresh same-contract D1 for its exact complete ISO week within valid lifecycle,
including pre-rank1 dates, in the same provider batch; other valid persisted D1 rows MUST be preserved.
It MUST NOT open other historical Parquet or automatically bootstrap historical metadata or contract lifecycle.
Missing baseline or indeterminate mapping/boundaries MUST fail closed with historical maintenance required.
Daily groups MUST be bounded by product, family and month and reuse the shared validation, provider and atomic
publication path. Complete ISO-week D1/W1 context and natural quota/restart semantics MUST remain unchanged.
Calendar/Session checks MUST use batch queries. Validated source reuse MUST be limited to one group and
invalidate on Catalog pointer change. Optional typed progress MUST carry bounded identities, stage counters
and durations; completed values MUST count successful operations rather than distinct partitions, unknown totals
MUST be absent, and nested phase durations MUST NOT be added as wall-clock time. Publishing counts MUST follow
successful commit, and observer failure MUST stop the attempt.

#### Scenario: Old physical corruption is outside daily scope
- **WHEN** an old partition has complete Catalog edges but damaged Parquet
- **THEN** daily does not open that partition or claim its integrity; full update/audit remains responsible

#### Scenario: Derived partition missing after restart
- **WHEN** a mapped derived month is missing while its 1m source is complete
- **THEN** daily rebuilds that month from validated 1m without a provider request or success-checkpoint dependency

### Requirement: After-market progress is observable but never resumable authority

Supervised after-market MUST publish schema v3 `current_run` before Calendar/provider/maintenance work and
MUST whitelist attempt, stage, timestamps, current product/partition, per-stage counters/durations and retry time.
Stage transitions MUST publish immediately; ordinary progress MAY be throttled to five seconds. A valid running
snapshot MUST degrade Runtime health until a terminal result is durably published; after two hours without an
updated snapshot it MUST be `stuck`. Invalid, unreadable, failed initial/intermediate/terminal status publication
MUST fail closed with `AFTER_MARKET_PROGRESS_UNAVAILABLE`, never retain an old success as current health.
A terminal failed result for the expected day MUST remain `status=failed, run_state=failed`.

Before establishing a run, the writer MUST safely invalidate and sync the same owned regular status file before
atomically publishing v3. If invalidation cannot produce any durable byte change, startup MUST be rejected before
a run is established; a file-only reader is not required to claim an unobservable attempt occurred. Progress,
status and log copies MUST NOT become a checkpoint or change maintenance results.

Current-day classification MUST require an exact `provider=rqdata` Calendar fact for every relevant exchange.
A missing or non-authoritative current-day row MUST terminate as `TRADING_CALENDAR_MISSING` with zero maintenance
attempts and no provider/data work; only an exact authoritative non-trading-day fact MAY produce
`NON_TRADING_DAY`. Relevant exchanges resolving to different maintenance days MUST terminate as
`TRADING_CALENDAR_CONFLICT` rather than choosing the earliest day. Once `current_run` is established, an ordinary Calendar-stage exception MUST durably finalize
the run as failed. Process interruption MUST remain observable as an unfinished run rather than being relabeled
as success. Any unhandled after-market execution exception at the CLI or supervised Runtime boundary MUST report
`readonly=false`; weekly audit exceptions remain read-only.

#### Scenario: Current Calendar fact is unknown

- **WHEN** yesterday has a trading Calendar row but any relevant exchange lacks today's exact authoritative row
- **THEN** after-market records `failed / attempts=0 / TRADING_CALENDAR_MISSING`, performs no provider or data work, and does not report `NON_TRADING_DAY`

#### Scenario: Mutation-capable boundary fails

- **WHEN** an after-market process boundary receives an exception before the final side effects are known
- **THEN** its sanitized error payload reports `readonly=false` and does not assert zero writes

#### Scenario: A current run was persisted but not finalized

- **WHEN** schema v3 contains a valid `current_run` updated within two hours
- **THEN** Runtime health reports `status=degraded, run_state=running` and exposes bounded progress without asserting the writer is alive

#### Scenario: Initial publication fails after durable invalidation

- **WHEN** the old summary was durably invalidated but the initial atomic v3 write fails
- **THEN** readers observe invalid/unknown state rather than the old passed result, and no Calendar/provider work starts

### Requirement: Weekly operational full-history audit remains optional and read-only

The weekly adapter MUST select the exact ordered `operational_products.txt` scope with identity
`operational_full_history`, acquire a nonblocking local writer guard for the status path, then atomically persist
running before acquiring the shared maintenance lock, and open a fresh read-only transaction only after that lock
succeeds. The writer guard MUST use a stable adjacent `.lock` inode, never the atomically replaced status inode;
it MUST NOT be unlinked or replaced and MUST remain held through all status writes and maintenance lease cleanup.
A competitor without status ownership MUST return `skipped_busy` only to its caller, without changing the owner's
file or acquiring the maintenance lock. An exclusive attempt encountering a busy maintenance lock MUST persist
its own `skipped_busy`; a maintenance-lock exception MUST persist sanitized `failed`, replacing any previous success.
Unsafe or failed writer-guard setup MUST reject startup before establishing a run, without unlocked status writes
or claiming that this attempt was persisted. Only guard acquisition contention MAY be classified as guard busy;
audit or status-write exceptions MUST NOT be misclassified. Process interruption MUST retain the unfinished run,
and process exit MUST release the writer guard. No status
MAY cause wait, retry, provider access, metadata/data write, repair or notification. The audit MUST cover the
existing full-history Calendar/Session, rank1, expected partition, Catalog pointer and physical integrity checks.

Its latest-result file represents the latest run established by a status owner, not every invocation. It MUST bind
exact Runtime root/40-hex commit, scope/products, timestamps, progress, findings,
`provider_requests=0` and `data_writes=0`. Health MUST map absence to `not_run`, unchanged running older than two
hours to `stuck`, terminal older than eight days to `stale`, and malformed identity/scope/counts/chronology/counters
to `invalid`. `passed` MUST require a resolved audited `through`, all products complete and zero findings. This
optional component MUST be appended after existing operational overall is calculated; old or missing audit fields
MUST NOT imply historical health, current freshness, release acceptance or Runtime readiness.

#### Scenario: Historical findings coexist with healthy services

- **WHEN** operational service components are healthy and the latest valid weekly audit has findings
- **THEN** Runtime overall remains the independently calculated service result while `components.weekly_audit.status=findings` remains visible

#### Scenario: Weekly audit conflicts with maintenance

- **WHEN** the shared maintenance lock is busy
- **THEN** an audit holding status ownership records its own `skipped_busy`, performs no database audit/provider/data write/notification, and exits without retry

#### Scenario: Concurrent weekly invocation cannot overwrite the owner

- **WHEN** A owns the status path and B starts before A's maintenance acquisition, during audit, or during terminal publication/lease cleanup
- **THEN** B returns `skipped_busy` without changing A's status bytes, timestamps or progress, and later health reads A's success, findings, failure or unfinished run

#### Scenario: New exclusive attempt cannot reuse old success on lock failure

- **WHEN** the previous run passed and a new status owner encounters a maintenance-lock exception
- **THEN** the latest file and health report this attempt as failed with no previous cutoff or completed count, and no audit/provider/data work occurs

### Requirement: quota 中止和续传
明确的 provider quota/limit 异常 SHALL 映射为 `PROVIDER_QUOTA_EXHAUSTED`；该轮 MUST 立即停止后续
provider 调用，保留已发布月且不发布当前未完成月，并返回 `status=partial` 和
`stop_reason=provider_quota_exhausted`。

#### Scenario: 下次续传
- **WHEN** 以相同参数重新执行 quota 中止的 update
- **THEN** 系统从第一个未完整 target 自然继续，不读取 checkpoint 或进度文件

### Requirement: refresh 完整月重建
refresh SHALL 接受 symbol、since、through，并强制重建相交月份的 continuous 与所涉 rank1 contract
基础 provider `1m/1d` 与日线派生 `1w`；新 1m 发布后 MUST 重建四个日内派生月。

#### Scenario: refresh dry-run
- **WHEN** refresh 未传 `--apply`
- **THEN** 输出计划的 month/series 范围且不调用 provider 或写入

### Requirement: Pending minute source publication precedes dependent derivation

同一 maintenance 调用中，若某物理 family/month 的 1m 属于待发布来源，依赖它的 5m、15m、30m、60m 目标 MUST 等待该来源按现有分区发布合同成功提交，不能因旧 1m 完整而提前派生。此规则 MUST 独立于 refresh/update 路径、fail_stop 与 source cache。成功派生 MUST 使用该次已发布来源；不得用旧来源结果消耗待处理目标。

#### Scenario: Refresh replaces an already complete minute partition

- **WHEN** 旧 1m 及派生分区完整，本次 refresh 将同一 family/month 的 1m 更新为不同值
- **THEN** 派生分区在新来源成功发布之后计算，最终数值来自新来源
- **AND** 普通无缓存路径与 streaming 路径遵守相同顺序

#### Scenario: Pending source cannot be published

- **WHEN** 待更新 1m 发生校验失败、quota interruption 或 commit outcome unknown
- **THEN** 依赖目标不得使用旧 1m 标为成功，返回既有准确的失败或部分完成状态
- **AND** commit outcome unknown 保持全局停批，不重试、不隐式回滚

#### Scenario: Existing source is outside the current update set

- **WHEN** 派生目标的 1m 完整有效且不在本次待更新集合中
- **THEN** 它可保持既有提前派生行为，不必等待无关 family/month 的 provider 请求

#### Scenario: Dependencies remain partition specific

- **WHEN** 两个目标的物理 family 或月份不同
- **THEN** 来源依赖不会错误关联两者，成功结果与失败传播仍遵守既有维护合同
