# Requirements Document

## Introduction

本 Spec 定义“纯个人开发迭代模式”的目标要求。目标是在本地单用户项目中，以 `develop` 作为日常开发分支，移除为多人协作、审计交接和自动合并设计的流程负担，同时保留量化研究业务正确性、安全编码边界和真实外部副作用的最小执行确认。

本 Spec 只定义待实现的目标状态，不表示现有 `AGENTS.md`、canonical 文档、ADR、hooks、rules、工程脚本、GitHub workflows 或 active task contracts 已经完成迁移。本次 Requirements 阶段不修改任何现有项目文件，不实施代码，不执行 release、tag、Runtime、live、通知、数据写入或删除。

## Glossary

- **Personal_Development_Mode**：面向单一项目所有者的开发执行模式，允许直接在 `develop` 上编辑、测试、提交和推送普通仓库变更。
- **Ordinary_Repository_Change**：仅影响 Git 跟踪的源码、测试、普通配置、研究实验或文档，且不执行 Controlled_External_Action 的变更。
- **Ordinary_Repository_Deletion**：删除 Git 跟踪的源码、测试、普通配置、过期文档或过期工程流程资产；Git 历史保留该删除前内容。
- **Collaboration_Gate**：为多人协作或审计交接设置的 Issue、任务合同、每任务 worktree、任务分支、Draft PR、独立 Review、required CI、exact-head 核对、merge readback、ancestry cleanup、approval packet/hash、签名收据或重复用户批准要求。
- **Business_Correctness_Constraint**：数据质量、数据身份、策略与回测语义、禁止未来函数、数值精度、幂等、默认关闭 live/Runtime/真实通知、禁止自动交易、密钥保护和输入校验等直接决定系统安全或研究结论可信度的约束。
- **Controlled_External_Action**：会改变仓库外真实状态或远端发布状态的操作，包括生产数据库或正式数据的不可逆变更、不可恢复的数据删除、Git 历史重写、Runtime/live 启用或切换、真实通知发送、远端 release/tag 发布和 GitHub 规则修改。
- **Explicit_Execution_Intent**：用户在执行前对一个 Controlled_External_Action 给出的单次明确指令；指令必须包含操作类别和可识别的目标范围，并仅授权紧随其后的该次执行。
- **Execution_Scope**：Controlled_External_Action 的目标环境、资源集合和操作类型；删除还包括待删除对象类别或边界，通知还包括渠道与发送范围，release/tag 还包括远端与目标 ref/tag。
- **Validation_Profile**：根据变更影响选择的定向测试、模块测试、类型检查、lint、构建、CLI smoke 或安全检查集合。
- **Historical_Fact**：已经发生的 migration、数据写入、事故、验收、通知、Runtime、release 或其他真实执行结果。
- **Historical_Canonical**：通过质量校验并由 Catalog/Manifest/Gap/MainContractMap 管理的正式历史数据。
- **Live_Observation**：仅用于观察、确认 bar、前向判断或盘后核对的实时数据，不属于 Historical_Canonical。
- **Windows_Development_Environment**：Windows 10/11、PowerShell 7、Git 和项目既有 Python/Node 工具组成的本地开发环境。

## Requirements

### Requirement 1: Direct personal development on develop

**User Story:** As the sole developer, I want to work directly on `develop`, so that ordinary iterations do not require collaboration ceremony.

#### Acceptance Criteria

1. WHEN a developer starts an Ordinary_Repository_Change, THE Personal_Development_Mode SHALL permit editing, testing, committing, and pushing from `develop`.
2. THE Personal_Development_Mode SHALL permit an Ordinary_Repository_Change without a GitHub Issue.
3. THE Personal_Development_Mode SHALL permit an Ordinary_Repository_Change without a per-task branch or worktree.
4. THE Personal_Development_Mode SHALL permit an Ordinary_Repository_Change without a Draft PR or pull request.
5. THE Personal_Development_Mode SHALL permit an Ordinary_Repository_Change without an independent Review.
6. THE Personal_Development_Mode SHALL permit an Ordinary_Repository_Change without exact-head binding, required CI, merge readback, ancestry verification, or worktree cleanup evidence.
7. WHERE a developer voluntarily uses a branch, worktree, pull request, Review, or CI workflow, THE Personal_Development_Mode SHALL treat the selected mechanism as optional tooling rather than an authorization prerequisite.
8. WHEN uncommitted changes from another task or user are present, THE Personal_Development_Mode SHALL preserve the unrelated changes and restrict modifications to the current task scope.

### Requirement 2: Removal of collaboration and audit gates

**User Story:** As the sole developer, I want obsolete collaboration gates removed consistently, so that no hidden enforcement restores the old workflow.

#### Acceptance Criteria

1. THE Personal_Development_Mode SHALL classify Issue, task worktree, Draft PR, independent Review, exact-head, required CI, merge readback, ancestry cleanup, approval packet/hash, detached signature, and repeated approval requirements as Collaboration_Gates.
2. WHEN an Ordinary_Repository_Change is performed, THE Personal_Development_Mode SHALL complete the change without a Collaboration_Gate.
3. WHEN a Controlled_External_Action is requested, THE Personal_Development_Mode SHALL use Explicit_Execution_Intent instead of an approval packet, content hash, exact code SHA, detached signature, or repeated approval sequence.
4. THE Personal_Development_Mode SHALL remove active instructions that require a Collaboration_Gate from `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/DEVELOPMENT.md`, `docs/WORKTREE_RELEASE_WORKFLOW.md`, and ADR-WS-003/004.
5. THE Personal_Development_Mode SHALL remove Collaboration_Gate enforcement from `.codex` hooks and rules, `scripts/engineering`, and GitHub workflows.
6. THE Personal_Development_Mode SHALL remove active Collaboration_Gate prerequisites from active task contracts while preserving Business_Correctness_Constraints.
7. WHEN an old document records a Historical_Fact involving a PR, Review, CI run, packet, hash, receipt, or Gate, THE Personal_Development_Mode SHALL preserve the factual meaning or rely on Git history rather than reinterpret the Historical_Fact as current authorization.
8. IF any active rule still blocks direct Ordinary_Repository_Change work on `develop` solely because a Collaboration_Gate is absent, THEN THE Personal_Development_Mode SHALL report the migration as incomplete.

### Requirement 3: Proportionate local validation

**User Story:** As the sole developer, I want validation matched to change impact, so that iteration remains fast without weakening correctness claims.

#### Acceptance Criteria

1. WHEN an Ordinary_Repository_Change modifies executable behavior, THE Personal_Development_Mode SHALL run a Validation_Profile covering the changed behavior before reporting completion.
2. WHEN a change affects only documentation or non-executable comments, THE Personal_Development_Mode SHALL require only applicable document, reference, formatting, or diff checks.
3. WHEN a change affects data identity, data quality, strategy semantics, backtest semantics, signal semantics, migration logic, Runtime logic, or notification logic, THE Personal_Development_Mode SHALL include the corresponding domain-specific tests in the Validation_Profile.
4. IF a required local validation fails, THEN THE Personal_Development_Mode SHALL report the failure and withhold a successful completion claim.
5. WHERE CI remains configured, THE Personal_Development_Mode SHALL treat CI results as supplementary validation rather than a prerequisite for local development, commit, push, merge, release, or cleanup.
6. THE Personal_Development_Mode SHALL provide direct local commands for targeted tests, module tests, lint, type checks, builds, and secret scanning without requiring a PR context.
7. WHEN validation cannot run in the Windows_Development_Environment, THE Personal_Development_Mode SHALL identify the unavailable check and provide the closest executable alternative.

### Requirement 4: Ordinary deletion without a gate

**User Story:** As the sole developer, I want to delete obsolete repository assets directly, so that the project can be substantially simplified.

#### Acceptance Criteria

1. WHEN a developer performs an Ordinary_Repository_Deletion, THE Personal_Development_Mode SHALL permit the deletion without a Collaboration_Gate or Explicit_Execution_Intent.
2. THE Personal_Development_Mode SHALL permit deletion of obsolete source files, tests, engineering workflow code, hooks, rules, CI definitions, ADRs, and stale documentation as an Ordinary_Repository_Deletion.
3. WHEN an Ordinary_Repository_Deletion removes a referenced asset, THE Personal_Development_Mode SHALL update or remove active references in the same change.
4. WHEN an Ordinary_Repository_Deletion is completed, THE Personal_Development_Mode SHALL use Git history as the recovery source without requiring a separate backup, quarantine, deletion packet, rollback tag, or deletion receipt.
5. IF a proposed deletion targets production database records, formal market data, Runtime state, remote refs, Git history, or another repository-external resource, THEN THE Personal_Development_Mode SHALL classify the operation as a Controlled_External_Action rather than an Ordinary_Repository_Deletion.
6. WHEN obsolete Historical_Fact documents are deleted, THE Personal_Development_Mode SHALL preserve the corresponding Git history without requiring a repository copy or archive.

### Requirement 5: Single explicit intent for external side effects

**User Story:** As the project owner, I want one clear execution boundary for real external effects, so that dangerous actions remain deliberate without multi-layer approvals.

#### Acceptance Criteria

1. WHEN a Controlled_External_Action is ready to execute, THE Personal_Development_Mode SHALL identify the operation category and Execution_Scope before execution.
2. WHEN the user directly requests a Controlled_External_Action with an identifiable Execution_Scope, THE Personal_Development_Mode SHALL treat the request as the Explicit_Execution_Intent for one execution attempt.
3. IF a Controlled_External_Action lacks an identifiable Execution_Scope or Explicit_Execution_Intent, THEN THE Personal_Development_Mode SHALL stop before the first external mutation.
4. THE Personal_Development_Mode SHALL avoid requiring a backup, rollback artifact, approval packet, hash binding, exact-head binding, signed receipt, dry-run approval, or second confirmation as a prerequisite for a Controlled_External_Action.
5. WHERE the user explicitly requests a dry-run, THE Personal_Development_Mode SHALL perform the dry-run without converting the dry-run request into mutation authorization.
6. WHEN a Controlled_External_Action exceeds the approved Execution_Scope, THE Personal_Development_Mode SHALL stop before executing the out-of-scope mutation.
7. WHEN a Controlled_External_Action finishes or fails, THE Personal_Development_Mode SHALL report the attempted scope and observed result without requiring a final receipt artifact.
8. WHEN the same Controlled_External_Action is retried after completion, failure, scope change, or a later session, THE Personal_Development_Mode SHALL require a new Explicit_Execution_Intent.
9. THE Personal_Development_Mode SHALL treat Business_Correctness_Constraints as non-overridable by Explicit_Execution_Intent.

### Requirement 6: Simplified release and tag workflow

**User Story:** As the sole developer, I want a short release and tag flow, so that publishing does not require a multi-stage approval protocol.

#### Acceptance Criteria

1. WHEN the user gives Explicit_Execution_Intent for a release, THE Personal_Development_Mode SHALL permit publishing the selected local commit to the selected remote release branch without a required release PR.
2. WHEN the user gives Explicit_Execution_Intent for a tag, THE Personal_Development_Mode SHALL permit creating and pushing the selected tag in one workflow.
3. THE Personal_Development_Mode SHALL permit release and tag operations without separate prepare, publish, tag, rollback-tag, packet, hash, exact-head, Review, required CI, or repeated approval stages.
4. WHEN a release or tag command is prepared, THE Personal_Development_Mode SHALL display the target remote, branch or tag name, and local target commit before mutation.
5. IF the selected local ref or tag name is invalid or unavailable, THEN THE Personal_Development_Mode SHALL stop before remote mutation.
6. IF Git rejects a non-fast-forward branch update or conflicting tag, THEN THE Personal_Development_Mode SHALL report the conflict without automatically force-pushing or rewriting history.
7. WHERE the user explicitly requests force-push or history rewrite with an identifiable Execution_Scope, THE Personal_Development_Mode SHALL treat the operation as a separate Controlled_External_Action.
8. THE Personal_Development_Mode SHALL keep release/tag authorization separate from Runtime/live enablement and real notification authorization.

### Requirement 7: Windows and PowerShell compatibility

**User Story:** As a Windows developer, I want the personal workflow to run natively in PowerShell, so that Bash, WSL, macOS paths, and launchd are not prerequisites for ordinary development.

#### Acceptance Criteria

1. THE Personal_Development_Mode SHALL provide PowerShell 7 compatible entrypoints for active engineering preflight, validation, secret scanning, and release/tag operations.
2. WHEN an active engineering command runs in the Windows_Development_Environment, THE Personal_Development_Mode SHALL avoid requiring Bash, WSL, `/Volumes/...`, POSIX-only utilities, or launchd.
3. WHEN an active engineering command receives a path containing spaces, non-ASCII characters, or Windows separators, THE Personal_Development_Mode SHALL pass the path as a discrete argument without shell interpolation.
4. WHEN an active engineering command fails, THE Personal_Development_Mode SHALL return a non-zero process exit code.
5. WHEN an active engineering command succeeds, THE Personal_Development_Mode SHALL return process exit code zero.
6. WHERE a Runtime-specific operation remains platform-specific, THE Personal_Development_Mode SHALL keep the Runtime-specific operation outside the prerequisites for Ordinary_Repository_Change work.
7. THE Personal_Development_Mode SHALL document one canonical PowerShell command for each active engineering workflow.
8. IF a retained workflow can run only on a non-Windows host, THEN THE Personal_Development_Mode SHALL label the workflow as an optional or Runtime-specific workflow.

### Requirement 8: Secrets, input validation, and safe execution

**User Story:** As the project owner, I want security controls retained, so that workflow simplification does not expose credentials or introduce injection and path risks.

#### Acceptance Criteria

1. THE Personal_Development_Mode SHALL keep credentials, tokens, webhook URLs, passwords, cookies, licenses, and private keys out of source code, documentation, test fixtures, logs, command output, and committed configuration.
2. WHEN code accepts CLI, file, network, database, environment, or user input, THE Personal_Development_Mode SHALL validate type, format, range, allowed values, and associated-field consistency before a sensitive operation.
3. WHEN code executes a system command, THE Personal_Development_Mode SHALL use a fixed executable and discrete argument list instead of concatenating untrusted input into a shell command.
4. WHEN code constructs a database query, THE Personal_Development_Mode SHALL use parameter binding or the existing ORM for untrusted values.
5. WHEN code resolves an input-derived file path, THE Personal_Development_Mode SHALL normalize the path and verify that the path remains within the allowed root.
6. WHEN an error crosses an API or UI boundary, THE Personal_Development_Mode SHALL return a bounded error without credentials, stack traces, SQL text, internal addresses, or secret-bearing paths.
7. IF authentication, validation, quality configuration, or a safety flag is missing or malformed, THEN THE Personal_Development_Mode SHALL reject the affected sensitive operation.
8. THE Personal_Development_Mode SHALL retain a local secret scan that reports file location and pattern family without printing detected secret values.

### Requirement 9: Data quality and canonical data boundaries

**User Story:** As a quantitative researcher, I want data correctness constraints preserved, so that faster development does not corrupt research inputs.

#### Acceptance Criteria

1. THE Personal_Development_Mode SHALL preserve the RQData to staging to validation to Historical_Canonical to Catalog/Manifest/Gap/MainContractMap to MarketDataService data boundary.
2. WHEN a consumer requests formal historical bars, THE Personal_Development_Mode SHALL require the consumer to use MarketDataService or the active canonical interface instead of selecting files by glob.
3. WHEN a consumer requests a dataset, THE Personal_Development_Mode SHALL require an explicit DatasetKey identity and explicit selection of `continuous` or `actual_dominant`.
4. IF requested Historical_Canonical coverage intersects a DataGap or failed quality region, THEN THE Personal_Development_Mode SHALL return a visible failure instead of silently filling, shortening, substituting, or cross-frequency falling back.
5. WHEN strict research, formal backtest, or formal historical signal logic reads market data, THE Personal_Development_Mode SHALL use data with `quality_status=passed`.
6. WHILE legacy compatibility remains active, THE Personal_Development_Mode SHALL restrict legacy reads to `provider in (rqdata, local_parquet)`, `data_role=primary`, and `quality_status!=failed`.
7. THE Personal_Development_Mode SHALL keep Historical_Canonical separate from Live_Observation.
8. WHEN EOD reconciliation updates formal history, THE Personal_Development_Mode SHALL use provider-final RQData and validate identity, coverage, manifest digest, checksum, and row count before publication.
9. IF staging or canonical validation fails, THEN THE Personal_Development_Mode SHALL preserve the last valid Historical_Canonical and expose the failure.
10. WHEN formal data or production database content will be irreversibly changed, THE Personal_Development_Mode SHALL require Explicit_Execution_Intent for the exact Execution_Scope.

### Requirement 10: Strategy, backtest, signal, and numerical correctness

**User Story:** As a quantitative researcher, I want research semantics preserved, so that personal-mode speed does not create false strategy conclusions.

#### Acceptance Criteria

1. THE Personal_Development_Mode SHALL keep automatic trading and order placement outside the project scope.
2. WHEN strategy, backtest, or formal historical signal logic evaluates market data, THE Personal_Development_Mode SHALL prevent future-data leakage, look-ahead bias, and unrecorded repainting.
3. WHEN trading-related prices, costs, positions, capital, profit, loss, or fees are calculated, THE Personal_Development_Mode SHALL use `Decimal` according to the project domain contract.
4. WHEN a backtest result is produced, THE Personal_Development_Mode SHALL retain enough strategy, parameter, data, order, trade, equity, and lineage information for reproducibility.
5. WHEN HTDY original behavior is used, THE Personal_Development_Mode SHALL restrict HTDY original behavior to the observation-only semantics defined by `docs/INDICATOR_KERNEL.md` and `docs/SIGNAL_EVENTS.md`.
6. THE Personal_Development_Mode SHALL preserve the `Strategy -> SignalEvent -> Notification Gate -> Channel` separation.
7. WHEN a signal or backtest result is presented, THE Personal_Development_Mode SHALL label the result as research observation rather than a trading instruction.
8. IF a requested workflow would create or submit an order, THEN THE Personal_Development_Mode SHALL reject the workflow.
9. WHEN strategy, data, backtest, signal, or notification semantics change, THE Personal_Development_Mode SHALL update the corresponding canonical document in the same change.

### Requirement 11: Live, Runtime, and real notification defaults

**User Story:** As the project owner, I want live operations disabled by default, so that ordinary development cannot accidentally affect real observation channels.

#### Acceptance Criteria

1. THE Personal_Development_Mode SHALL keep live execution disabled by default.
2. THE Personal_Development_Mode SHALL keep Runtime promotion or switching disabled by default.
3. THE Personal_Development_Mode SHALL keep real notification sending and WeChat autosend disabled by default.
4. THE Personal_Development_Mode SHALL keep `auto_order=false` for every signal and Runtime mode.
5. WHEN the user requests live enablement, Runtime switching, or real notification sending, THE Personal_Development_Mode SHALL require a separate Explicit_Execution_Intent for the requested Execution_Scope.
6. WHEN repair, replay, backfill, migration, or EOD recalculation runs, THE Personal_Development_Mode SHALL suppress historical notification replay.
7. IF live, Runtime, or notification configuration is absent, malformed, expired, or inconsistent, THEN THE Personal_Development_Mode SHALL keep the affected capability disabled.
8. WHEN a real notification is sent, THE Personal_Development_Mode SHALL include the observation-only and non-trading-instruction boundary in the message contract.
9. WHEN live enablement, Runtime switching, or real notification sending completes, THE Personal_Development_Mode SHALL avoid inferring trading readiness, profitability, long-running readiness, or production readiness from the execution result.

### Requirement 12: Consistent repository migration and acceptance

**User Story:** As the project owner, I want one coherent personal-mode rule set, so that documentation and automation do not contradict each other.

#### Acceptance Criteria

1. WHEN Personal_Development_Mode is implemented, THE Personal_Development_Mode SHALL align `AGENTS.md`, `STATUS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/DEVELOPMENT.md`, and `docs/WORKTREE_RELEASE_WORKFLOW.md` with the personal workflow.
2. WHEN Personal_Development_Mode is implemented, THE Personal_Development_Mode SHALL supersede or retire ADR-WS-003 and ADR-WS-004 as active workflow decisions.
3. WHEN Personal_Development_Mode is implemented, THE Personal_Development_Mode SHALL align `.codex/hooks`, `.codex/rules`, `scripts/engineering`, and `.github/workflows` with direct `develop` development.
4. WHEN Personal_Development_Mode is implemented, THE Personal_Development_Mode SHALL review every active task contract for Collaboration_Gates and replace active Collaboration_Gates with the rules in Requirements 3, 5, 8, 9, 10, and 11.
5. WHEN Personal_Development_Mode is implemented, THE Personal_Development_Mode SHALL keep completed execution records and incident descriptions as Historical_Facts without treating obsolete approval mechanics as active prerequisites.
6. IF any active canonical document says that ordinary work cannot occur on `develop`, THEN THE Personal_Development_Mode SHALL report the migration as incomplete.
7. IF any active hook, rule, script, or workflow rejects a normal commit or push to `develop` solely because the old task workflow was not used, THEN THE Personal_Development_Mode SHALL report the migration as incomplete.
8. IF any active task contract requires Issue, worktree, PR, independent Review, exact-head CI, packet hash, signed approval, merge readback, or ancestry cleanup for code-only work, THEN THE Personal_Development_Mode SHALL report the migration as incomplete.
9. IF an automated test demonstrates that live, Runtime, real notifications, or order placement becomes enabled by default, THEN THE Personal_Development_Mode SHALL reject the implementation.
10. IF an automated test demonstrates that invalid inputs, failed data quality, DataGap intersections, future-data leakage, or secret exposure are accepted, THEN THE Personal_Development_Mode SHALL reject the implementation.
11. WHEN the Windows_Development_Environment runs the documented engineering commands, THE Personal_Development_Mode SHALL complete preflight, targeted validation, secret scan, and release/tag dry-run without Bash or WSL.
12. WHEN implementation validation completes, THE Personal_Development_Mode SHALL produce a traceable result for every acceptance criterion in this Requirements Document.
