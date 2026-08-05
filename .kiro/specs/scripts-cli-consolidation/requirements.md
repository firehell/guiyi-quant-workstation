# Requirements Document

## Introduction

本规格将分散的行情与运维脚本收口为稳定的 `guiyi data` 命令及按用途分类的少量运维脚本。系统必须保持 Data Core V2 的 canonical、质量、identity、DataGap 和 historical/live 分离合同，并在新入口等价实现与自动化验证完成后才删除旧入口。

本规格只定义仓库代码与测试变更。正式数据、生产数据库、Runtime/live 状态、receipt、report、evidence 或仓库外资源的实际变更不在本规格授权范围内。

## Glossary

- **Unified_Data_CLI**: 以 `uv run --project services/quant-api guiyi data` 调用的统一数据命令入口。
- **Target_Expander**: 将单品种参数或批量清单转换为确定性 `Data_Target` 集合的组件。
- **Data_Target**: 由 provider、`Dataset_Kind`、symbol、contract-or-series、frequency、adjustment、schema version 和时间窗口定义的数据目标。
- **Dataset_Kind**: 显式取值 `continuous` 或 `actual_dominant` 的数据种类；两个取值不可互换。
- **Direct_Frequency**: RQData 直接下载频率，取值仅为 `1m`、`1d` 或 `1w`。
- **Derived_Frequency**: 从 canonical `1m` 聚合的频率，取值仅为 `5m`、`15m`、`30m` 或 `60m`。
- **Historical_Canonical**: 通过 staging 与质量校验后发布的正式历史 Parquet 数据及对应 Catalog/Manifest 元数据。
- **Live_Observation**: 实时监听产生且只存储在 observation 层的数据，不属于 Historical_Canonical。
- **Trusted_Canonical_1m**: Dataset identity 匹配、Catalog/Manifest/物理证据一致、质量通过且请求窗口不与 DataGap 相交的 canonical `1m` 数据。
- **MainContractMap**: 将 trading day 映射到 RQData rank=1 actual contract 的 V2 元数据。
- **Metadata_Sync_Service**: 复用 `app.services.rqdata_ingest` 算法并统一编排 metadata 同步的应用服务。
- **Audit_V2**: 以 `catalog`、`coverage`、`schema`、`physical`、`gap` 或 `all` scope 执行的只读审计。
- **DataGap**: 表示某一 Dataset identity 和窗口不可作为可信数据使用的显式缺口记录。
- **Effect_Summary**: 命令结果中说明 RQData、staging、canonical、PostgreSQL、live observation、notification 和 order 副作用的结构化字段。
- **Disposition_Manifest**: 对设计基线中的 145 个 Git tracked `scripts/**` 路径逐一给出保留、移动、替换后删除或删除结论的有序规则。
- **Replacement_Gate**: 新 CLI 行为、自动化测试和 active reference 切换全部完成后才允许删除旧仓库入口的门槛。
- **External_Mutation_Gate**: 对正式数据、生产数据库、Runtime/live、receipt/report/evidence 或仓库外资源执行真实变更前所需的独立、精确、单次人工执行意图。
- **Task_Worktree**: 后续实现本规格时使用的独立 Git worktree；不得是 `develop` 的主工作区。
- **Stable_Error_Code**: 不包含秘密、SQL、stack trace、内部 URL 或敏感绝对路径的机器可读错误代码。
- **historical synchronization service**: 规划缺失窗口并编排 RQData、staging、质量校验、canonical 发布和 DataGap 的 V2 服务。
- **Historical_Canonical publisher**: 仅在完整质量与物理证据通过后原子发布 Historical_Canonical 分区及 metadata 的组件。
- **aggregation service**: 只从 Trusted_Canonical_1m 生成 Derived_Frequency 数据的应用服务。
- **live observation service**: 将实时 bar 限定写入 Live_Observation 层的应用服务。
- **repository**: 本规格实施时的 Git tracked 源码、测试、配置和 active 文档集合，不包含正式数据或仓库外资源。
- **disposition validator**: 校验 Disposition_Manifest 对 tracked scripts 完整、无重叠分类的工具。
- **reference-closure validator**: 校验被删除路径和命令不再被 active 非历史内容引用的工具。
- **migration implementation**: 按本规格新增、移动或删除 repository 文件的后续代码变更。
- **developer workflow**: 约束后续实现 worktree、分支和验证步骤的执行流程。
- **test suite**: 覆盖具体示例、边界和集成行为的自动化测试集合。
- **property test suite**: 使用生成输入验证 design correctness properties 的自动化测试集合。
- **validation suite**: 在删除和完成声明前运行的全部适用自动化检查集合。

## Requirements

### Requirement 1: Stable Unified Command Surface

**User Story:** As a data operator, I want one stable data command tree, so that I can perform supported data operations without selecting historical scripts.

#### Acceptance Criteria

1. THE Unified_Data_CLI SHALL expose `download`, `aggregate`, `live`, `sync`, `audit`, and retained `verify` commands under `guiyi data`.
2. THE Unified_Data_CLI SHALL require an explicit Dataset_Kind for every download, aggregate, and live Data_Target.
3. WHEN a user supplies one symbol, THE Target_Expander SHALL create Data_Target values only for the supplied symbol and contract-or-series values.
4. WHEN a user supplies a batch manifest, THE Target_Expander SHALL create a deterministic, duplicate-free Data_Target sequence from schema-valid manifest rows.
5. IF a user supplies both a symbol and a batch manifest or supplies neither selector, THEN THE Unified_Data_CLI SHALL reject the command before constructing a database session or provider client.
6. IF a command contains an invalid enum, malformed time, unpaired time boundary, non-increasing time window, oversized manifest, or path outside an allowed root, THEN THE Unified_Data_CLI SHALL return `CLI_ARGUMENT_INVALID` without a mutating effect.
7. THE Unified_Data_CLI SHALL emit a versioned JSON result containing command, status, readonly, Effect_Summary, per-target outcomes, and an optional Stable_Error_Code.

### Requirement 2: Direct Historical Download

**User Story:** As a data operator, I want one direct historical download command, so that single and batch canonical coverage use the same V2 ingestion path.

#### Acceptance Criteria

1. WHEN a valid download request is planned without `--apply`, THE Unified_Data_CLI SHALL return exact uncovered windows without calling RQData or writing staging, Historical_Canonical, or PostgreSQL state.
2. WHEN an applied download request targets a Direct_Frequency, THE Unified_Data_CLI SHALL delegate exact uncovered windows to the V2 historical synchronization service.
3. IF a download request specifies a frequency outside `1m`, `1d`, or `1w`, THEN THE Unified_Data_CLI SHALL reject the request before constructing an RQData client.
4. WHEN downloaded data passes identity, schema, session, duplicate, OHLCV, coverage, manifest digest, checksum, and row-count validation, THE Historical_Canonical publisher SHALL atomically publish the matching Data_Target partition and metadata.
5. IF downloaded data fails validation, THEN THE Historical_Canonical publisher SHALL preserve the last valid canonical partition and register an exact DataGap for the failed window.
6. IF transient provider failures exhaust the bounded retry policy, THEN THE historical synchronization service SHALL register an exact DataGap and report the target as failed.
7. WHEN a batch contains successful and failed targets, THE Unified_Data_CLI SHALL preserve each per-target outcome and return a non-success overall status.
8. THE Unified_Data_CLI SHALL keep `continuous` and `actual_dominant` download identities distinct without cross-kind fallback.

### Requirement 3: Date-Agnostic Historical Coverage

**User Story:** As a data operator, I want pre-2020 history to use the general download contract, so that calendar eras do not create permanent special commands.

#### Acceptance Criteria

1. WHEN a valid download window includes dates before 2020, THE historical synchronization service SHALL plan missing coverage by the same window-difference rules used for dates on or after 2020.
2. THE Unified_Data_CLI SHALL support pre-2020 requests only through `data download` for Direct_Frequency values.
3. IF a requested date precedes the instrument listing date or provider-supported start date, THEN THE historical synchronization service SHALL report the unavailable exact interval as DataGap instead of silently truncating the request.
4. THE Unified_Data_CLI SHALL omit a `backfill` command and SHALL reject legacy pre-2020 command aliases.
5. WHEN a pre-2020 request is executed in batch mode, THE Unified_Data_CLI SHALL apply the same general batch-size and bounded-retry controls used for other dates.

### Requirement 4: Canonical Aggregation

**User Story:** As a data operator, I want derived bars built only from trusted canonical minutes, so that aggregation is deterministic and independent of provider calls.

#### Acceptance Criteria

1. WHEN a valid aggregate request is planned, THE Unified_Data_CLI SHALL resolve only the matching Trusted_Canonical_1m source for the requested Dataset_Kind, identity, and window.
2. WHEN a valid aggregate request is applied, THE aggregation service SHALL produce only the requested Derived_Frequency by session-based deterministic OHLCV aggregation.
3. THE aggregation service SHALL complete every aggregate plan and execution with zero RQData client constructions and zero RQData calls.
4. IF any required source minute, session mapping, quality proof, or coverage interval is missing or ambiguous, THEN THE aggregation service SHALL block publication and return a DataGap error.
5. IF an aggregate request specifies a frequency outside `5m`, `15m`, `30m`, or `60m`, THEN THE Unified_Data_CLI SHALL reject the request before reading canonical data.
6. WHEN aggregation succeeds, THE Historical_Canonical publisher SHALL publish derived bars with the same provider, Dataset_Kind, symbol, contract-or-series, adjustment, schema version, and requested window identity as the Trusted_Canonical_1m source.
7. THE aggregation service SHALL avoid fill, truncation, cross-frequency fallback, cross-kind fallback, and Live_Observation input.

### Requirement 5: Live Observation Isolation

**User Story:** As a data operator, I want one single/batch live listener, so that real-time observations remain isolated from formal history.

#### Acceptance Criteria

1. WHEN a valid live request starts, THE Unified_Data_CLI SHALL listen only for explicit single or batch Data_Target identities at source frequency `1m`.
2. WHEN a live bar is received, THE live observation service SHALL persist the bar only as Live_Observation data.
3. THE live observation service SHALL produce zero Historical_Canonical writes and expose no live-to-canonical promotion operation.
4. IF live write configuration is missing, disabled, expired, or inconsistent, THEN THE live observation service SHALL refuse observation writes.
5. THE live observation service SHALL keep Runtime promotion, notification sending, and order creation disabled unless each capability is governed by a separate applicable contract.
6. WHEN live processing reports status, THE Effect_Summary SHALL report `writes_historical_active=false`, `sends_notification=false`, and `creates_order=false`.

### Requirement 6: Unified Metadata Synchronization

**User Story:** As a data operator, I want one metadata synchronization command, so that metadata algorithms have one reusable authority.

#### Acceptance Criteria

1. THE Unified_Data_CLI SHALL expose metadata scopes `instruments`, `contracts`, `calendar`, `sessions`, `main-contract-map`, and `all` under `data sync`.
2. WHEN metadata sync is planned without `--apply`, THE Metadata_Sync_Service SHALL report intended scope and effects without RQData or PostgreSQL writes.
3. WHEN metadata sync is applied, THE Metadata_Sync_Service SHALL delegate provider queries, normalization, mapping, reconciliation, and persistence to existing `app.services.rqdata_ingest` services.
4. THE Unified_Data_CLI SHALL contain no duplicate provider-query, MainContractMap resolution, reconciliation, or metadata upsert algorithm.
5. IF delegated metadata validation fails or MainContractMap is missing or ambiguous, THEN THE Metadata_Sync_Service SHALL roll back the transaction and return a failed target result.
6. WHEN `all` is selected, THE Metadata_Sync_Service SHALL execute scopes in dependency order: instruments, contracts, calendar, sessions, then main-contract-map.

### Requirement 7: Unified Audit V2

**User Story:** As a data maintainer, I want one read-only V2 audit, so that data defects are reported consistently without phase-specific scripts.

#### Acceptance Criteria

1. THE Unified_Data_CLI SHALL expose Audit_V2 scopes `catalog`, `coverage`, `schema`, `physical`, `gap`, and `all`.
2. WHEN any Audit_V2 scope runs, THE Audit_V2 service SHALL perform zero RQData calls and zero filesystem, Historical_Canonical, PostgreSQL, Runtime, notification, or order mutations.
3. WHEN Audit_V2 detects an inconsistency, THE Audit_V2 service SHALL return a stable scope, Stable_Error_Code, Dataset identity, and bounded non-sensitive facts for each finding.
4. WHEN `all` is selected, THE Audit_V2 service SHALL execute every defined audit scope and preserve each scope outcome in the result.
5. THE Unified_Data_CLI SHALL omit phase numbers, stage numbers, closeout labels, and fixed dates from Audit_V2 command names and scope names.
6. IF physical files, Catalog rows, Manifest identity, checksums, row counts, coverage, schema, or DataGap state disagree, THEN THE Audit_V2 service SHALL report a failed finding without repairing the disagreement.

### Requirement 8: Fail-Closed Identity and Error Boundary

**User Story:** As a system maintainer, I want unsafe or ambiguous operations rejected, so that consolidation cannot bypass V2 safety rules.

#### Acceptance Criteria

1. IF a Dataset_Kind is absent or ambiguous, THEN THE Unified_Data_CLI SHALL reject the request without inferring `continuous` or `actual_dominant`.
2. IF an `actual_dominant` target lacks one complete and unambiguous rank=1 MainContractMap resolution for the requested trading days, THEN THE Unified_Data_CLI SHALL block the target without substituting a continuous series or concrete contract.
3. IF a requested interval intersects DataGap or failed-quality coverage, THEN THE Unified_Data_CLI SHALL fail the target without fill, shortening, substitution, or cross-frequency fallback.
4. IF any command boundary catches an unexpected exception, THEN THE Unified_Data_CLI SHALL return a Stable_Error_Code without emitting exception text, stack trace, SQL, credentials, internal URL, or sensitive absolute path.
5. THE Unified_Data_CLI SHALL treat `--apply` and `--confirm-observation-write` as effect selectors that do not satisfy External_Mutation_Gate authorization.
6. THE Unified_Data_CLI SHALL keep `auto_order=false` for every command result.

### Requirement 9: Script Classification and Reference-Safe Migration

**User Story:** As a maintainer, I want every tracked script classified and migrated safely, so that no hidden legacy entrypoint survives or disappears prematurely.

#### Acceptance Criteria

1. THE Disposition_Manifest SHALL classify each of the 145 design-baseline tracked `scripts/**` paths exactly once.
2. THE Disposition_Manifest SHALL classify 9 `scripts/engineering/**` paths as keep-in-place, 14 operational paths as move, and 122 paths as replace/delete or delete.
3. WHEN the implementation task begins, THE disposition validator SHALL regenerate the tracked script inventory and fail on count drift, overlapping rules, or unmatched paths.
4. WHILE a legacy entrypoint lacks passing replacement behavior tests or has an active non-historical reference, THE Replacement_Gate SHALL preserve the legacy entrypoint.
5. WHEN replacement behavior tests pass and active references use the new entrypoint, THE Replacement_Gate SHALL permit deletion of the corresponding Git tracked legacy source, dedicated tests, and active references.
6. THE Replacement_Gate SHALL reject compatibility shims, forwarding Shell wrappers, Profile compatibility aliases, and phase-numbered aliases as migration completion mechanisms.
7. WHEN legacy files are removed, THE reference-closure validator SHALL report zero active references to removed paths and commands outside protected historical evidence.

### Requirement 10: Operational Script Layout

**User Story:** As an operator, I want retained operational scripts grouped by purpose and platform, so that script ownership is explicit.

#### Acceptance Criteria

1. THE repository SHALL retain the `scripts/engineering/` directory without consolidating the directory into the Unified_Data_CLI.
2. THE repository SHALL place local development scripts under `scripts/dev/`.
3. THE repository SHALL place launchd and Mac mini operational scripts under `scripts/ops/macos/`.
4. THE repository SHALL place systemd Linux operational scripts under `scripts/ops/linux/`.
5. THE repository SHALL place tunnel and public network health scripts under `scripts/ops/network/`.
6. WHEN an operational script moves, THE migration implementation SHALL update executable references and automated tests in the same change.

### Requirement 11: Authorized Repository Deletion Boundary

**User Story:** As the project owner, I want obsolete repository code removed without authorizing real data deletion, so that cleanup remains safe and scoped.

#### Acceptance Criteria

1. WHEN the Replacement_Gate passes, THE migration implementation SHALL delete repository backup/restore code, compatibility shims, one-time/history scripts and Shell wrappers, S6-07 through S6-10 entrypoints, after-market entrypoints, old Runtime Gate entrypoints, Profile compatibility entrypoints, and dedicated tests/active references.
2. THE migration implementation SHALL preserve formal data, production database state, Runtime state, receipts, reports, evidence, and repository-external resources.
3. IF a task proposes deleting or mutating formal data, production database state, Runtime state, a receipt, a report, evidence, or a repository-external resource, THEN THE External_Mutation_Gate SHALL block the operation until a separate exact human execution intent is supplied for that operation.
4. THE migration implementation SHALL use Git history as the source-code rollback mechanism without creating backup directories, rollback tags, approval packets, or deletion receipts.
5. THE migration implementation SHALL avoid modifying `.kiro/specs/personal-development-mode`.

### Requirement 12: Incremental Implementation and Validation

**User Story:** As a developer, I want incremental implementation in an isolated worktree, so that consolidation can be validated before destructive repository cleanup.

#### Acceptance Criteria

1. WHILE implementing this specification, THE developer workflow SHALL perform repository modifications only in a Task_Worktree and not in the `develop` main worktree.
2. WHEN each new command is implemented, THE test suite SHALL validate parser behavior, single-target behavior, batch behavior, effect boundaries, errors, and applicable V2 data invariants before legacy deletion.
3. WHEN a universal correctness property is implemented, THE property test suite SHALL run at least 100 generated cases and reference the corresponding design property and requirement clauses.
4. WHEN external services or side effects are tested, THE test suite SHALL use mocks or isolated fixtures for repeated tests and bounded representative integration cases for wiring.
5. WHEN the migration reaches deletion, THE validation suite SHALL run affected CLI, data-core, backend, engineering, reference, documentation, secret, script and build checks.
6. IF any required validation fails, THEN THE migration implementation SHALL preserve or restore the affected legacy entrypoint and report the migration as incomplete.
