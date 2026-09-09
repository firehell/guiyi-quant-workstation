# historical-data-maintenance Specification

## Purpose

定义 Recent Trusted Window 内的 update、refresh、audit、physical-contract warm-up、固定水位和 quota natural resume。

## Requirements

### Requirement: 公开维护面
系统 SHALL 公开 `update`、`refresh`、`audit` 与 `contract-warmup`。`audit` SHALL 接受
`(--symbol X | --universe active)` 的互斥选择器。无 `--apply` 的 update/refresh MUST 只计划，
不得写 PostgreSQL/Parquet；audit MUST 只读。
系统还 SHALL 公开一次性 `session-anchor-repair` 三阶段 seam：`plan` 只读输出精确 session、Dataset、
分区、预计缺失首分钟与稳定 scope hash；`prepare --apply` 只在外部 shadow root 使用真实 RQData 重建完整
Canonical；`publish --apply` 只在五项 Runtime 全部停止、manifest/基线/hash 未漂移时切换 root、reconcile
Catalog、执行精确 0045 并清理 publish 执行时由 operational phase authority 唯一解析的当前交易日旧锚点 Live Bar；此 repair cleanup MUST 保留 after-market reconciliation 所需的不可变 rank1 subscription snapshot。
0044→0045 legacy repair MUST 保持原合同；固定 `part.parquet` 写入仅隔离在 shadow prepare，不用于普通 maintenance 发布。

#### Scenario: 已退出动作
- **WHEN** 用户调用任何已退出的维护操作
- **THEN** CLI 不暴露该入口

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
and durations; publishing counts MUST follow successful commit, and observer failure MUST stop the attempt.

#### Scenario: Old physical corruption is outside daily scope
- **WHEN** an old partition has complete Catalog edges but damaged Parquet
- **THEN** daily does not open that partition or claim its integrity; full update/audit remains responsible

#### Scenario: Derived partition missing after restart
- **WHEN** a mapped derived month is missing while its 1m source is complete
- **THEN** daily rebuilds that month from validated 1m without a provider request or success-checkpoint dependency

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
