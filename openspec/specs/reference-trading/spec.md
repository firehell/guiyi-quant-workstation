# Unified Reference Trading

## Purpose

定义所有策略共用的 ReferenceTrading 领域合同。它只投影研究用途的参考交易，`executable=false`、
`auto_order=false`，绝不创建 Order、Fill、Position、Ledger、Account PnL、AlertEvent 或通知。本规格冻结
P0/P1 的公共身份和纯状态语义、P3 的持久化/原子批次/内部快照合同，以及 P4 的离线历史计划、构建、恢复、
增量与重建应用合同，以及 P5 历史 HTTP 查询与 Web 读取合同。P6/P7 forward 编码为默认关闭的开发候选，
不声明 Runtime active；代码与测试不授权生产
migration、历史 bootstrap、Canonical 写入或 Runtime enable。

## Requirements

### Requirement: Lossless bounded historical plan and manifest storage

Historical plan files SHALL preserve the logical plan hash. Legacy inline JSON SHALL remain
readable with its existing 16 MiB bound. Larger plans SHALL use a bounded descriptor and
fixed sibling compressed chunks, validating each chunk and complete compressed and decoded
hashes before use. Decoded payloads SHALL be bounded at 256 MiB. Duplicate keys, non-finite
numbers, symlinks, nonregular files, path escapes, incomplete publication and extra streams
SHALL fail closed. Publication SHALL not overwrite existing evidence.

SuBing historical calculation batches MAY replace large repeated source vectors with a direct
reference to an earlier committed inline manifest in the same stream and revision. The reader
SHALL authenticate its complete digest and retained fields and SHALL reject reference chains,
missing anchors and identity mismatches. Logical dependency and batch payload hashes SHALL
remain unchanged. Legacy inline assets and other strategies SHALL remain unchanged. Readers
SHALL be upgraded before producing this storage representation. No storage change SHALL
alter trading semantics, source coverage or formula identities.

#### Scenario: Compact storage preserves full history
- **WHEN** a SuBing history since 2023 exceeds the inline plan bound or repeats large manifests
- **THEN** bounded storage retains the complete logical history and identities without shortening the window
- **AND** corruption or missing evidence blocks processing without fallback or fabricated trades

### Requirement: Forward activation and capture are separate from historical publication

Forward enablement SHALL require an exact, unexpired activation plan bound to stream/revision,
checkpoint hash, dependency digest, host/environment, recording start, resource budget, recovery policy
and accepted model. The default recovery policy SHALL be `block`; `interrupt_and_restart` requires an exact
activation plan and shall persist the detected endpoints, authoritative trading day and observation time.
Its seed MUST be FLAT at the exact recording start; a historical OPEN or watermark SHALL NOT be copied.
Activation and disable SHALL change a persistent generation under the stream lock. A worker holding an older
generation SHALL fail before committing. Forward calculation SHALL consume one immutable bounded capture in the
same transaction as actions, marks, presentation and checkpoint. A capture alone SHALL NOT advance sequence.
An unknown commit result SHALL be read back by exact batch identity before any retry decision.
An interruption boundary SHALL NOT be presented as a completed market Bar watermark; coverage and health
SHALL expose it separately from the last completed Bar.

#### Scenario: Bounded renewal after a proven missing forward interval

- **WHEN** an exact unexpired recovery plan freezes the active checkpoint, immutable old activation receipt,
  retained completed-journal cursor/envelope identity and authoritative missing Session endpoints
- **THEN** renewal appends a new generation receipt and its single hash-bound interruption capture atomically
- **AND** the old receipt, checkpoint and batches remain immutable; the active revision remains the same
- **AND** the interruption advances the internal resume boundary only to the last missing endpoint, while
  recording its actual recovery observation time separately; coverage excludes it from completed market Bars
- **AND** the new receipt permits only that exact interruption capture, and later automatic gaps remain blocked
- **AND** `RECOVERY_PENDING` returns to `READY` only in the transaction that commits and consumes that receipt-bound interruption under the current revision, generation and checkpoint token, with no remaining pending capture or current source conflict; rollback and unrelated health states never grant readiness
- **AND** no journal cursor is skipped and no missing Bar or notification is manufactured

#### Scenario: Completed journal consumption after Live cleanup

- **WHEN** an original retained completed envelope is consumed after Live cache/subscription cleanup or
  Canonical advancement
- **THEN** Newow consumes its frozen Bar, physical contract, original confirmed/raw receipt timestamps and
  journal identity directly, still validating the authoritative owner and expected Session endpoints
- **AND** all routes commit before the journal cursor acknowledges the observation
- **AND** a predictable blocked route retains its unacknowledged envelope and fixed diagnostic with bounded
  backoff in the same worker process, without claiming readiness or repeatedly crashing

#### Scenario: A worker finishes after disable

- **WHEN** disable increments activation generation before a prepared calculation commits
- **THEN** the stale calculation is rejected while its captured observation remains durable
- **AND** no action, mark or checkpoint from that calculation becomes visible

### Requirement: HTDY first-seen candidate stays separate from Alert and retrospective history

`htdy_first_seen_reverse_close_v1` SHALL evaluate exactly the latest Bar of a verified 32 Bar
completed-input window. A `buy` opens LONG and `sell` opens SHORT; a reverse creates an explicitly linked CLOSE
followed by opposite OPEN at the same Bar Close. Same-direction observations add no trade, while still persisting
the observed signal and state. Simultaneous buy/sell is a conflict. Subsequent repainting SHALL NOT rewrite a
previously observed action. Code availability SHALL NOT count as owner model acceptance or production activation.

#### Scenario: A scan finds an old uncaptured candidate

- **WHEN** a worker scan discovers a completed Bar whose first observation was not durably captured
- **THEN** it reports an observation gap rather than claiming the old Bar was first seen now
- **AND** it creates no AlertEvent or notification

### Requirement: Recording modes are isolated

ReferenceTrading SHALL use either `historical_replay` or `forward_observation`. Stream identity MUST include
strategy/formula/profile/reference-model/futures-adaptation/product/frequency/series-kind/recording-mode and,
for forward mode, observation-policy version. Historical results and observed results MUST NOT share a stream,
transaction identity, statistics, or return curve. Historical replay MUST NOT manufacture `observed_at`; forward
mode MUST preserve observed facts and begin FLAT at its explicit recording start.

#### Scenario: Forward mode starts while the strategy already holds

- **GIVEN** the forward stream is enabled FLAT and its strategy is already HOLD after indicator warm-up
- **WHEN** the first observed source action is CLEAR
- **THEN** the action is retained with `NO_OBSERVED_ENTRY`
- **AND** no reference trade, zero return, or historical-lifecycle `INITIAL_CLEAR_NO_ENTRY` is manufactured

### Requirement: Reference actions have exact identity and ownership

Every action MUST carry stream, source action ID, physical contract, owner segment, calculation segment,
timezone-aware `bar_end`, input-provided trading day, sequence, action kind, Decimal reference price/type and,
for CLOSE, an explicit entry action ID. A generic reducer MUST NOT infer a pairing by searching for a prior OPEN.
Action order is `(bar_end, sequence)` and duplicate or conflicting sequence inputs MUST fail closed.
An authoritative boundary is ordered after all actions at its own `bar_end`; it may therefore interrupt an OPEN
created at that Bar, while a preceding CLOSE remains a real close. Boundaries at later Bars apply after earlier
actions. A batch watermark MUST cover every action/boundary and no input may precede a stream's watermark.

#### Scenario: A same-Bar reverse is projected

- **GIVEN** an OPEN reference trade for one contract and segment
- **WHEN** a CLOSE explicitly links its entry and precedes a new opposite OPEN at the same `bar_end`
- **THEN** the reducer emits CLOSED before OPEN
- **AND** the new trade has an independent entry identity

#### Scenario: A cross-segment close arrives

- **WHEN** a CLOSE links an entry but has another contract, owner segment, calculation segment, stream or version
- **THEN** the reducer rejects the complete transition without changing its input state

### Requirement: Reducer transitions are pure and deterministic

`reduce_reference` SHALL have no DB, provider, Redis, wall-clock or runtime dependency. It consumes validated,
ordered actions and authoritative boundaries and returns a new immutable state, changed trades and diagnostics.
HINT has no trade/return/position effect. A completed Bar with no action SHALL advance `computed_through`; an OPEN
trade's holding-bar count advances only from such authoritative completed inputs, never wall-clock elapsed time.
Exact replay of the same preceding state and input MUST yield the same output; P3 durable idempotency is separate.
An unsealed same-Bar sub-batch may omit `completed_bar_end`, but must strictly follow the prior event key. A sealing
batch MUST provide the completed watermark, cover every action/boundary, and thereafter rejects further input at or
before that Bar. For an OPEN trade, a sealed completed Bar MUST supply a Decimal reference mark and return an
immutable mark; no price is invented.

#### Scenario: An OPEN receives a rollover boundary

- **WHEN** an authoritative rollover boundary matches its physical contract and both segments
- **THEN** its status becomes `ROLLOVER_INTERRUPTED` and the state becomes FLAT
- **AND** no exit action, exit reference price or return is invented

#### Scenario: A data or observation interruption occurs

- **WHEN** a proven data interruption occurs in either mode
- **THEN** a matching OPEN becomes `DATA_INTERRUPTED` without a synthetic exit
- **WHEN** an observation interruption is supplied
- **THEN** it is accepted only for `forward_observation` and produces `OBSERVATION_INTERRUPTED`

### Requirement: Capability evidence is explicit

The initial capability matrix SHALL separate code support, independently verified evidence and Runtime enablement.
No row may infer enabled Runtime from tests, a page, a script or a historical result.

| Strategy family | Frequencies | Historical code support | Independently verified evidence | Forward code support | Runtime enablement |
|---|---|---|---|---|---|
| Newow trend / oscillation / main-rise | 1w, 1d, 60m | P4 bounded historical plan/build/resume/advance/rebuild implemented over P2/P3 | Temporary Canonical/Catalog/MDS wiring and fixtures are verified; real per-product/per-frequency data evidence remains separate | Candidate code for completed Live 60m and completed Canonical D1/W1 capture, durable projection and restart recovery; per-product capability remains gated | Disabled / no worker |
| SuBing reference | 5m, 15m, 30m, 60m, 1d, 1w | P4 bounded historical plan/build/resume/advance/rebuild implemented over P2/P3 | Temporary Canonical/Catalog/MDS wiring and formula fixtures are verified; D1 quality/readiness remains separately gated | Completed Live 5m/15m/30m/60m and completed Canonical D1/W1 capture; activation and per-route data evidence remain separate | Disabled / no worker |
| HTDY first-seen | Accepted operational scope: 60m | Historical repainting remains separate | `htdy60m_first_seen_reference_v1` accepts only `htdy_first_seen_reverse_close_v1` / `latest_only_32_v1` on the exact operational 60-product scope | Durable completed-original capture, 32-Bar current-prefix evaluation and atomic forward projection | Requires exact scoped activation; actual deployment and natural acceptance are recorded in STATUS.md |

All rows are disabled by default. This matrix neither opens a Scope nor authorizes Canonical, database, notification,
release or Runtime work.

#### Scenario: A supported model has no scoped activation

- **WHEN** code and isolated tests support a model but its exact scope has not been activated
- **THEN** capability remains separate from Runtime enablement and natural acceptance

### Requirement: Accepted HTDY 60m first-seen reference recording

The accepted operational scope SHALL use `huotian_dayou_original_v0`, `htdy_first_seen_reverse_close_v1`
and `latest_only_32_v1` at 60m. `buy` opens LONG and `sell` opens SHORT; an opposite observation closes the
old reference trade and opens the new side, while a same-side observation never adds. Reference prices are
completed Bar closes with zero fees/slippage; results are non-executable page references, not broker fills.

The full operational scope SHALL activate in one transaction with flat reference seeds and a common future
recording start. Acceptance MUST remain an exact model/policy/product/frequency allowlist; other scopes remain
`MODEL_NOT_APPROVED`. Previously stored Alert Events MUST NOT be converted into historical reference trades.
Historical context Bars warm the current 32-Bar prefix without producing historical actions.

A 60m capture MUST bind an immutable eligible journal observation, its confirmation time, physical contract,
cutoff and exact current Bar, plus a verified 32-Bar window and hash. A scan or a later Live snapshot MUST NOT
invent first-seen evidence. Input conflict, missing endpoints or changed window overlap MUST fail closed.
A later Live recovery watermark SHALL NOT retroactively revoke an already accepted eligible 60m original.
The current 32-Bar prefix, physical owner, exact original tail and source/recovery-current checks SHALL still
be verified; recovery-generated ineligible originals SHALL remain rejected, and snapshot/legacy eligibility
rules SHALL remain unchanged.
Actions, trades, checkpoint and Inbox completion SHALL retain the existing atomic commit and unknown-result
readback contracts. Reference recording MUST NOT create Alert Events or send notifications.

#### Scenario: Delivery fails after a signal is persisted

- **WHEN** a new HTDY observation produces a signal and its notification transport fails
- **THEN** the persisted Event and separately committed reference actions/trades remain available
- **AND** no notification retry or historical reference replay is introduced

#### Scenario: HTDY commit acknowledgement is lost

- **WHEN** the calculation transaction result is uncertain
- **THEN** only exact persisted-batch readback may establish completion
- **AND** an unproven result remains UNKNOWN without polling a second calculation

#### Scenario: Historical adapter tests pass

- **WHEN** a strategy/frequency adapter passes its isolated fixture and checkpoint tests
- **THEN** only that row's historical code support and fixture evidence may be recorded
- **AND** its Runtime remains disabled until a separate Runtime authorization and readback exist

### Requirement: Explicit HTDY context conflict retirement and future flat restart

`htdy_conflict_recovery_v1` SHALL be an explicit maintenance operation for the exact owner-selected
48 HTDY 60m streams affected by the 2026-10-30 context conflict. It SHALL NOT relax the normal overlap
comparison, change the formula or observation policy, replay an original or grant a broker operation.
The native MDS verifier SHALL prove immutable original/capture/checkpoint hashes, the exact 32-Bar
windows, unchanged overlapping endpoint/physical-owner identities, Calendar/Session continuity and
finite numeric differences. Every changed Bar SHALL match the current verified physical Canonical
content and its RQData 1m / Canonical-derived 60m publication provenance. Unknown or changed facts block.

Planning and applying SHALL hold the existing Reference stopped-writer fence and Canonical maintenance
lease. They SHALL freeze the complete exact scope, old revisions/checkpoints/receipts, batches, reference
trade projections and all unresolved Inbox originals/routes. UNKNOWN or a changed preimage blocks the
operation. The authoritative rest window SHALL exclude active Sessions and leave at least 660 seconds
before the next Session; a later valid window requires a new plan. Applying revalidates source and fence
inside one transaction, checks time after slow verification, and consumes a durable exclusive attempt
before any business write. Failed or unknown attempts are not reused; only exact readback proves commit.

The operation SHALL invalidate each old revision with `DATA_CONFLICT`, append its exact conflict boundary
and retain every old Capture, original, action, reconciliation and actual processing timestamp. An old OPEN
reference trade SHALL receive an appended `DATA_INTERRUPTED` projection with explicit `DATA_CONFLICT`
boundary evidence, without an exit price, realized return or fictitious CLOSE action. No old trade carries
into the successor. All selected successors SHALL atomically activate with empty strategy windows, FLAT
reference state, a common future recording start and ordinary `block` recovery policy. The remaining
unaffected streams and all broker/account state SHALL remain unchanged.

An independent typed retirement proof SHALL bind each unresolved old delivery's complete immutable
original and frozen route to the exact old/new revisions, receipts, boundary and future seed. Such a
delivery is terminal for that conflict interval, not successfully calculated: its original status, timestamps
and bytes SHALL remain unchanged, and no CALCULATED recovery result is fabricated. The existing actual
CALCULATED proof remains separately verified; already resolved deliveries SHALL NOT be retired again.
Ordering, capacity, health, readiness and handover SHALL share the exact union of these two independently
verified sets. Generic diagnostics, superseded revision identity or a status string SHALL NOT grant closure.
Later natural successor progress or a legitimate subsequent activation SHALL NOT invalidate a historical
terminal proof. Missing, duplicate, partial, altered or UNKNOWN retirement facts SHALL fail closed.

#### Scenario: An old blocked head is explicitly retired
- **GIVEN** the exact stopped-writer plan proves a context conflict and all old unresolved originals
- **WHEN** the atomic future flat restart commits with complete typed retirement evidence
- **THEN** the old blocked head is excluded from new processing without changing its original status
- **AND** the new stream waits for a genuine completed original after its future recording start
- **AND** no past signal, notification or account order is replayed

#### Scenario: Retirement evidence is incomplete or the successor later progresses
- **GIVEN** a retired interval with a verified successor seed and receipt
- **WHEN** a bound original or boundary is missing or changed
- **THEN** closure fails rather than hiding the unresolved original
- **AND** ordinary later successor progress alone does not reintroduce a valid retired head

### Requirement: Durable revisions commit atomically and idempotently

ReferenceTrading persistence SHALL use disabled streams, isolated candidate revisions and a monotonic commit sequence.
Each calculation batch MUST atomically persist its source-action references, trade validity changes, marks, complete
adapter checkpoint and evidence. A repeated `(stream, revision, batch_key)` with the same payload MUST return the
durable receipt before checking a stale checkpoint; the same identity with different content MUST fail closed. A new
batch MUST compare revision, sequence, stream row version and checkpoint hash under a fixed stream-to-revision lock
order. Before advancing the checkpoint, the repository MUST verify monotonic watermarks and reconcile the durable
unique OPEN projection with both the stored pre-state and proposed post-state. Diagnostics and seed chunks MUST NOT
advance valid calculation sequence.

#### Scenario: Two writers submit the same prepared batch

- **GIVEN** both writers start from the same durable checkpoint
- **WHEN** they concurrently submit the same batch identity and payload
- **THEN** exactly one commit advances the revision
- **AND** the other returns the same sequence as a no-op without duplicating actions, trades or marks

#### Scenario: A write fails after actions are inserted

- **WHEN** any failure occurs after an intermediate table write but before transaction commit
- **THEN** batch, actions, trade versions, marks and checkpoint all remain at the prior sequence

### Requirement: Complete strategy checkpoints are strict and seed publication is fail-closed

The repository MUST persist the exact canonical text produced by `adapter_checkpoint_to_json` and MUST validate it
with `adapter_checkpoint_from_json` against the expected stream and strategy schema before commit and after read.
Initialization chunks MUST be bounded, content-addressed and complete before a seal can create a readable checkpoint.
Candidate revisions MUST remain invisible until a compare-and-swap publication verifies the expected dependency
digest and sealed sequence. No public repository method may enable a stream.

#### Scenario: One seed chunk is missing

- **WHEN** a caller attempts to seal or publish an incomplete seed generation
- **THEN** the candidate remains unreadable through the active stream pointer
- **AND** no partial checkpoint becomes the stream's effective state

### Requirement: Snapshot reads never mix revisions or future facts

An internal snapshot SHALL bind stream, published revision and commit sequence. Trade versions use half-open
`[valid_from_seq, valid_to_seq)` intervals; an old snapshot MUST remain stable after later commits. A cutoff before a
close MUST return the prior OPEN version and its latest eligible mark, never the future exit or realized return.
Forward reads MUST additionally require each action's actual `observed_at` not to exceed the cutoff. Candidate and
invalid revisions MUST fail explicitly rather than switching to another revision. Forward marks and non-action
interruptions MUST persist their own input observation time; interruption versions MUST also persist their effective
event Bar, so neither a later mark nor an unsealed future boundary can leak into an earlier cutoff.

#### Scenario: A trade closes after a captured snapshot

- **GIVEN** sequence 2 contains an OPEN trade and a reader captures that snapshot
- **WHEN** sequence 3 closes the trade
- **THEN** the captured sequence 2 still returns OPEN with its sequence-2 mark
- **AND** sequence 3 returns CLOSED only for cutoffs that include the close and, in forward mode, its observation time

### Requirement: Historical plans bind exact read-only inputs and budgets

P4 historical operations SHALL consume only the existing Canonical/Catalog/MainContractMap/MarketDataService path.
A plan MUST bind operation, complete stream identity, requested window/as-of, storage start, final completed event,
ordered full-source Bar fingerprints, effective Calendar/Session endpoints, rank-1 ownership, quality boundaries,
formula/model versions, byte/count limits, one task-wide monotonic elapsed budget and a canonical plan hash. Warm-up MAY
precede owner eligibility and MAY overlap another physical owner's prefix; replay order is calculation-segment order,
while only owner-eligible completed Bars advance the formal reference watermark. Provider, Redis, notification and
Runtime access are forbidden.

#### Scenario: A later owner needs an overlapping physical warm-up prefix

- **WHEN** the next calculation segment begins with Bars earlier than the prior owner's formal watermark
- **THEN** those Bars advance only that segment's strategy kernel in their supplied order
- **AND** they create no Action, mark or trade until owner eligibility begins

#### Scenario: Source content changes without changing Close

- **WHEN** an old physical OHLCV record, effective Session/Calendar endpoint, rank-1 interval or quality boundary changes
- **THEN** source revalidation changes and normal append is rejected
- **AND** the operation requires a new reviewed plan and rebuild rather than silently accepting the revision

### Requirement: Historical build, resume and revision transitions fail closed

Build and rebuild SHALL write only a disabled candidate, commit bounded batches through P3 and publish only after the
exact source token and dependency digest are revalidated. Resume MUST derive its next position from the durable
checkpoint batch receipt and stored source evidence; caller-supplied indices are assertions, never authority. A commit
or publish with unknown outcome MUST use authoritative readback and MUST NOT retry automatically. Advance SHALL process
only an append-proven suffix; changed prefixes, earlier storage starts, revised metadata or missing durable progress
return `REBUILD_REQUIRED`. Rebuild invalidates only the selected active revision and its interrupted candidate remains
resumable. Per-stream failures are isolated and a mixed result is partial.

#### Scenario: A boundary has no physical Bar at its effective instant

- **WHEN** a rollover or proven data interruption falls between completed Bars or at a Session start
- **THEN** P4 inserts a separately fingerprinted boundary replay event in calculation-segment order
- **AND** a matching OPEN becomes interrupted without inventing a price, exit action or return

#### Scenario: A resume token index is edited

- **WHEN** its claimed next index or last batch differs from the durable checkpoint batch evidence
- **THEN** resume is blocked before calculation or publication
- **AND** the candidate remains unpublished

### Requirement: Historical CLI is explicit and non-promoting

The `reference` CLI SHALL expose strict `plan`, `build`, `advance`, `rebuild` and `resume` commands. Planning and commands
without `--apply` are read-only. Mutation requires `--apply` plus the exact plan hash; JSON rejects duplicate/unknown
fields, non-finite values and invalid identities. Execution errors cross the shared redacted JSON boundary. P4 SHALL
NOT enable streams, migrate a production database, write Canonical data, expose HTTP/Web, start a worker or promote
Runtime.

#### Scenario: Apply is omitted

- **WHEN** a valid build, advance, rebuild or resume plan is supplied without `--apply`
- **THEN** the CLI validates and reports the exact plan as read-only
- **AND** it performs no repository mutation, provider access, notification or Runtime action

### Requirement: Historical reference presentation is persisted with the calculation

P5 historical calculation batches SHALL persist a versioned, bounded `presentation_v1` envelope in their existing
source evidence. It contains the strategy display facts needed by readers, including SuBing same-direction signals
and indicators and Newow actions, hints, availability and trade identity. Reading MUST NOT run the strategy kernel,
project trades, infer a missing presentation from actions, or write a replacement envelope. A published revision
without this envelope SHALL report `PRESENTATION_NOT_MATERIALIZED` until a separately authorized rebuild.
Canonical prices and daily quality bars remain read-only MarketDataService facts, bound to the same source identity.

#### Scenario: A published older revision has no display envelope

- **WHEN** a reader requests historical signals from an older calculation batch
- **THEN** the response reports `PRESENTATION_NOT_MATERIALIZED`
- **AND** it does not replay the strategy or return an empty signal list as if calculation were complete

### Requirement: P5 historical queries use one bounded published snapshot

The read-only `/api/v1/reference-trading` capability, stream, trade, signal, indicator and summary endpoints SHALL
accept only registered historical streams and validated trading-day windows. A snapshot binds stream, revision,
sequence, cutoff, window, dependency digest and statistics policy. A cursor additionally binds its resource and
last stable sort key. Candidate and invalid revisions are unreadable; an old valid sequence remains stable after
advance. Trade pages use database keyset and `limit + 1` selection, batch actions and marks, and never scan every
trade into memory. Summary is independent of page size and preserves Decimal arithmetic. A past cutoff MUST NOT
expose a future exit, mark or realized return. Complete-window readiness remains unknown without authoritative proof.

#### Scenario: A trade closes after the selected cutoff

- **WHEN** a historical reader requests a snapshot whose trade has a later close
- **THEN** that reader sees the eligible OPEN version and eligible mark only
- **AND** all subsequent pages and summary retain the same snapshot and cutoff

### Requirement: Persisted page adapters fail closed during migration

The existing SuBing history and Newow reference section MAY use an explicit `persisted` reader mode after isolated
verification. The default `legacy` mode preserves current production behavior. Persisted mode SHALL verify the
stored source identity against the bounded chart/quality read, use saved presentation and trade facts, and preserve
the existing page fields and statistics. It SHALL NOT silently fall back to a replay on missing schema, build,
presentation, snapshot or source identity. The page SHALL label saved history as optimistic reference with its
cutoff and statistics window; it SHALL NOT imply a fill, account return, live observation or Runtime promotion.

#### Scenario: The source identity differs from the saved build

- **WHEN** a persisted adapter reads chart facts whose dependency digest does not match the selected snapshot
- **THEN** the reference section is unavailable with an explicit identity error
- **AND** old and new facts are not drawn together


### Requirement: Authoritative Newow forward health separates seed and observation

The Newow `newow_recording_matrix_v2` SHALL enumerate the sixty-product, four-strategy,
D1/W1/60m configuration independently of actual observation acceptance. Health SHALL read
completed published Canonical endpoints through MDS/Catalog once per unique product-period
and share those facts across strategy routes. `expected_source=canonical_completed` SHALL
not claim that unconfirmed or unpublished Live input has become Canonical. Missing endpoint
proof SHALL return UNKNOWN and no fabricated endpoint.

`historical_computed_through` SHALL expose indicator/checkpoint preheating separately from
`observed_through` and `last_observed_at`. Natural observations SHALL require a committed
forward calculation with actual observation time at or after recording start; seed and
observation-gap batches SHALL NOT count. `latest_state_source` SHALL distinguish
`historical_seed` from `observed`. `configured_count`, `enabled_count`, and `seeded_count`
SHALL NOT be presented as naturally observed or Runtime accepted counts. Reference trading
at activation remains FLAT; preheating does not import a historical OPEN or invent a BUILD.

`latest_reconciliation_status` SHALL derive from the latest actual capture. Base captures
read existing reconciliation records; dual captures derive status through both exact base
capture stream/revision/hash/source-evidence identities. The reduction SHALL return
pending, matched, source_revised, mismatch or not_applicable without inventing a dual Canonical market hash.
Bulk status reads SHALL share set-based queries across routes.

#### Scenario: Complete configuration has no naturally observed Bar
- **GIVEN** all 720 routes are configured and their historical indicator seed is ready
- **WHEN** no new completed observation has been committed after activation
- **THEN** observed_count is zero even when seeded_count is 720
- **AND** historical and natural watermarks are displayed separately

#### Scenario: Four strategy routes share one endpoint fact
- **GIVEN** four strategies for one product-period
- **WHEN** health constructs their expected watermark
- **THEN** one bounded MDS endpoint read serves all four routes
- **AND** source failure remains UNKNOWN rather than a zero-gap or observed-success claim

### Requirement: Fusion full input manifests bind transformed execution inputs

Full saved-source fusion manifests SHALL use reader version
`newow_fusion_saved_sources_v2`. Their `input_fingerprints` SHALL match the ordered
fusion execution inputs after source actions are attached, and `input_sha256`
SHALL hash that same ordered sequence. The original shadow sequence SHALL remain
under `source_input_fingerprints`; source revisions, sequences and dependency
digests SHALL remain frozen independently. Compact intraday manifests without an
explicit fingerprint array retain their existing reader version and input hash.
This is a lineage correction, not a formula, reference-return or stream-identity
change. Published prior batches SHALL remain immutable; correction requires a
new exact plan and revision with equivalent strategy and trade results.

#### Scenario: Fusion inputs differ from their shadow market inputs

- **GIVEN** a full daily or weekly fusion input snapshot with saved base actions
- **WHEN** source actions transform the execution input fingerprints
- **THEN** the full manifest array equals the returned execution sequence
- **AND** the shadow sequence remains separately attributable without being
  mistaken for fusion execution inputs

### Requirement: Daily owner-eligible quality-boundary projection is source-versioned

Newow D1 historical input manifests SHALL include
`reference_boundary_policy_version=owner_eligible_quality_boundary_v1` in their
source token and dependency digest, including saved-source dual manifests.
This corrects reference projection of physical lifecycle warm-up facts without
changing indicator formulas or the reference model identity. Prior D1 revisions
SHALL remain immutable; current D1 source assets require new revisions with this
policy proof. W1 and intraday input-policy scopes SHALL remain unchanged.

Physical D1 quality interruptions SHALL continue to label calculation segments
and remain in `data_interruptions` provenance. A DATA_INTERRUPTED boundary SHALL
advance reference state only within its proven rank1 owner interval. The verified
first observation-eligible Bar MAY associate a segment with that authoritative
owner interval; the interval, rather than a global reference watermark, determines
ownership. An owned interruption before the first eligible price Bar SHALL remain
a reference boundary. Unproven or ambiguous owner context SHALL fail closed;
ROLLOVER validation SHALL NOT be weakened.

Saved daily fusion sources SHALL verify the current boundary policy against each
base strategy's own exact source manifest. Missing or different policy proof SHALL
reject the source rather than silently adopting an old D1 asset.

#### Scenario: A new owner's old physical-prefix quality gap

- **GIVEN** a physical contract's quality gap precedes its verified rank1 owner interval
- **WHEN** that contract's lifecycle prefix preheats a Newow D1 strategy
- **THEN** the raw quality gap remains in provenance and calculation-segment resets
- **AND** it does not create a reference event or rewind the previous owner's reference state

#### Scenario: An interruption during actual ownership

- **GIVEN** a quality interruption is inside the verified owner interval
- **WHEN** the D1 reference projection consumes it
- **THEN** the boundary remains eligible for the normal interruption/close rules
- **AND** an unproven interval cannot be repaired by skipping input behind a global watermark

#### Scenario: A saved daily source has the previous projection policy

- **WHEN** a current dual-source D1 build reads a saved base source without the required policy proof
- **THEN** it fails with a source snapshot conflict
- **AND** the previous revision is retained for readback without rewriting its identity or evidence


### Requirement: Newow completed intraday observations and matrix v4

Newow 5m/15m/30m/60m forward recording SHALL read genuine saved completed Live observations after a
Session closes through the dedicated MarketReadService recording seam. Calendar, Session,
rank1 physical owner, subscription, typed provenance and exact completed endpoint coverage
SHALL be proven; closed phase civil date SHALL NOT replace a night Bar's trading day.
The read SHALL preserve actual observed_at, stable capture identity and completed-only
ordering. It SHALL NOT change HTDY/SuBing realtime notification eligibility, fabricate
first_seen or consume preview/display bars. Unknown identity or a missing endpoint SHALL
fail closed; multiple missed observations retain the existing interruption policy.

The current recording matrix SHALL use newow_recording_matrix_v4. D1/W1 expected endpoints
SHALL remain Canonical publication endpoints. For each intraday frequency the expected endpoint SHALL also
include authoritative already-completed Session endpoints, even when Redis has not saved
the corresponding Bar. expected_source=completed_live denotes that observation expectation,
not proof that Redis contains the Bar. When the expected endpoint is on or after recording_start
and actual observed progress is behind, READY SHALL be replaced by OBSERVATION_LAGGING;
a historical seed or empty capture queue SHALL NOT prove observation completeness.
Unproved endpoint authority SHALL be SOURCE_UNAVAILABLE. Health SHALL remain read-only.
A persisted OBSERVATION_LAGGING status SHALL be reassessed from the same actual post-start
observation watermark: if it reaches the authoritative expected endpoint, its read projection
may return READY without rewriting stored health. Seed and interruption-only watermarks SHALL
NOT clear lag; other persisted failure states and conflict/quarantine/warm-up precedence remain.

Historical intraday input estimation and MDS reads SHALL honor the exact aware as_of cutoff
inside the authoritative trading-day Session window, including a completed Friday night owned
by Monday. The default trading-day query remains full-day; D1/W1 SHALL NOT accept this intraday
cutoff. Missing completed endpoints still fail; future Sessions SHALL NOT be required merely
because their trading-day identity matches. No historical replay becomes a natural observation.

#### Scenario: A completed night terminal Bar is processed after the Session closes
- **GIVEN** the actual night trading day, rank1 physical owner and saved completed 23:00 Bar are proven
- **WHEN** Newow reads the next observation at 23:10 after that product's night Session closes
- **THEN** the saved Bar is captured with its original trading day and actual 23:10 observed_at
- **AND** existing strict realtime Alert eligibility is unchanged

#### Scenario: An eligible Bar was never captured and the durable queue is empty
- **GIVEN** Session authority proves a completed 23:00 endpoint after recording_start
- **AND** actual observations only reach 22:00 and pending_capture_count is zero
- **WHEN** matrix v4 is read
- **THEN** the route is OBSERVATION_LAGGING rather than READY

### Requirement: Short-minute continuous recording uses the existing deterministic projection

Matrix v4 SHALL enumerate 60 products with four strategies at 1w/1d/60m and
trend/oscillation/dual_fusion at 5m/15m/30m, totalling 1260 routes. Main-rise
short-minute routes and Newow 1m SHALL remain closed. Each intraday completed
Live Bar SHALL originate from validated same-physical-contract 1m aggregation
by authoritative Session (start,end], without gap fill, cross-period fallback
or unfinished bars. Capture, state, action, Hint and reference identities SHALL
bind the actual frequency. Reconciliation SHALL compare the same physical
contract and frequency against published Canonical; publication absence is pending.

Bootstrap scope v2 SHALL bind selected frequencies and support enabling only the
nine new short-minute routes per product. Existing enabled day/week/hourly streams
SHALL NOT be reseeded or assigned a new recording_start as a side effect. Historical
prewarm SHALL carry no observed position and SHALL NOT count as natural observation.
Worker grouping SHALL include all six frequencies and keep base streams before
fusion; bounded queue fairness and restart idempotence SHALL be verified.

#### Scenario: Three new short-minute periods preserve existing observations
- **GIVEN** the existing twelve routes per product are enabled
- **WHEN** an exact scope v2 plan selects 5m,15m,30m
- **THEN** nine new routes are planned and the existing twelve identities,
  activation generations, recording_start and observed records are unchanged

#### Scenario: Per-K state records without an action
- **GIVEN** a completed 5m Bar with no BUILD or CLEAR action
- **WHEN** the corresponding enabled route processes it
- **THEN** its actual observed_at and versioned Bar state are persisted once
- **AND** absence of an action does not create a trade or fabricate a flat state

### Requirement: Known-conflict observation isolation preserves each original

An unexplained active-revision Canonical mismatch MAY isolate its complete enabled product/frequency
routing group, including fusion, without blocking unrelated products. Before acknowledging a durable
observation, the worker SHALL atomically persist one immutable diagnostic receipt per group route,
including the full original envelope, journal day/id, exact active revisions and activation generations,
and links to the original mismatch evidence. Receipt identity SHALL reject altered content at the same
journal day/id. `observed_at` remains the original confirmed time; `processed_at` is the actual transfer
clock. Ownership SHALL be checked after flush and before commit and again before journal acknowledgement.
Unknown commits, incomplete groups and unrelated input failures SHALL NOT grant transfer or acknowledgement.

#### Scenario: A mismatched base route and dependent fusion are isolated together
- **GIVEN** a completed original and a proven active Canonical mismatch in its routing group
- **WHEN** all route receipts commit under the current owner fence
- **THEN** the global journal may advance while the original conflict and captured data remain unchanged
- **AND** health and the recording matrix report DATA_CONFLICT with no current strategy state for that group
- **AND** restart finds the exact receipts rather than recomputing successful observations or inventing old processing times

### Requirement: RQData Live and historical numeric source revisions remain separate facts

`rqdata_live_history_revision_v1` SHALL preserve first-seen H1 observations and their existing
reference computations, positions, actions and actual processing times. RQData documents that realtime
minutes may omit late ticks and that post-market history is cleaned from the complete tick set; historical
Canonical is authoritative for independent historical replay, not a replacement for a prior observation.

Only the native MDS reader, after exact physical contract, rank1 owner/calculation segment, Session endpoint,
immutable content and quality validation, MAY classify a finite valid same-endpoint numeric difference as a
source revision. The classification SHALL bind the exact capture hash/revision/generation, original activation
lineage, reconciliation id and both complete Bar hashes, pinned Canonical source revision, policy and actual
field differences. Unknown values, identity changes, invalid prices, quality gaps, unverified provider or
corrupt hashes SHALL remain unexplained conflicts. Fixed waiting periods or numeric tolerances SHALL NOT
stand in for this evidence.

The original comparison SHALL remain append-only `mismatch`; an idempotent versioned diagnostic in the same
transaction records its qualified source revision. Guards, quarantine, health and fusion status SHALL share
the same exact per-comparison resolver. A valid classification MAY project `source_revised`; it SHALL NOT
waive another mismatch or any original-observation conflict. Same active-revision captures from an older
generation require their own exact activation receipt and actual capture processing time within that receipt.

Classification SHALL NOT fill a missing calculation, remove a quarantine, replay a journal, change a cursor,
reset FLAT, alter an OPEN trade or send notifications. Any outstanding terminal quarantine continues to block
normal computation until a separately verified recovery. If all actual computations already reach the expected
endpoint and no pending/quarantine exists, classification alone requires no calculation or position reset.

The independent disabled historical identity SHALL use the existing full Canonical planner and driver.
An exact `P4_SOURCE_REVISION_REBUILD` invalidation MAY generate a fresh bounded native rebuild plan in the
existing rest-window worker; unknown invalidations, inflight outcomes and blocked attempts SHALL NOT be
automatically retried. Source token, complete prefix, budget, publication and resume checks remain mandatory.
Formal historical prices, indicators, signals and reference trades SHALL use post-market Canonical as their
single authority. Newow and SuBing public historical reference pages SHALL use their existing saved historical
identity with current complete-prefix source verification; HTDY SHALL retain its dedicated Canonical historical
model. The retired reader-mode environment switch SHALL NOT select another public history implementation.
Missing, incomplete, stale or quality-invalid historical assets SHALL remain unavailable and SHALL NOT fall
back to first-seen observations or an alternate calculation path. A checkpoint endpoint alone does not prove
current source identity.

The UI SHALL use Canonical historical signals without giving prior actual events priority in historical chart
slots. First-seen records and notifications SHALL remain immutable and accessible in an explicitly separate
audit view; generic snapshot readers do not prove current Canonical identity and SHALL NOT be presented as a
second formal history. Later numeric source corrections require independent native historical recomputation,
not rewriting observations or resending notifications. Individual source differences, historical cutoff,
unresolved missing originals and incomplete recalculation SHALL remain explicit; field differences SHALL NOT
be presented as an attributed profit change.

Historical signal pages SHALL verify the same saved complete-prefix source as the reference page, before and
after reading saved presentation points. A revision to an earlier warmup prefix must invalidate the result even
when visible chart bars are unchanged. Canonical chart replacements or changed Bar/owner identities SHALL
invalidate browser signal caches and in-flight generations; failures SHALL NOT retain a stale formal signal
or substitute a realtime event. Pagination remains bound to the exact historical snapshot and source.

#### Scenario: A prior realtime event disagrees with corrected formal history
- **GIVEN** a preserved first-seen observation and a later verified Canonical revision
- **WHEN** the user opens formal historical reference or chart signals
- **THEN** the page uses the current verified Canonical historical calculation only
- **AND** a missing or stale saved calculation is unavailable instead of using the realtime result
- **AND** the original event remains visible only as an audit fact without notification replay

#### Scenario: A revision affects an earlier warmup prefix only
- **GIVEN** a COMPLETE cached chart range whose visible prices have not changed
- **WHEN** the formal Canonical series is refreshed or the saved source changes
- **THEN** the range is revalidated against the complete source prefix
- **AND** an old in-flight result cannot replace the new generation
- **AND** a stale source or a changed pagination source is rejected explicitly

#### Scenario: A later cleaned minute changes H1 volume
- **GIVEN** a valid retained H1 capture and same physical Canonical endpoint differ numerically
- **WHEN** the native reader verifies both identities and appends exact revision evidence
- **THEN** the old mismatch and realtime reference records remain unchanged
- **AND** only that comparison projects source_revised and historical replay is recomputed independently

#### Scenario: Another mismatch or quarantined original is not explained
- **GIVEN** one comparison has valid source revision evidence
- **WHEN** another comparison is unclassified or a terminal quarantine still lacks its calculation
- **THEN** normal forward processing remains blocked without replay, reset or notification

### Requirement: Explicit conflict recovery creates an independent forward revision

Conflict recovery SHALL freeze an exact bounded group, old checkpoint/batch/receipt identities, original
mismatch evidence, and published Canonical historical checkpoints with the same strategy identity.
Historical reference trades SHALL remain unchanged and SHALL NOT be copied to the new flat forward state.
The caller SHALL revalidate their manifests against current authoritative data and
hold a stopped-writer fence through commit. Recovery SHALL use a future recording start, create independent
flat forward revisions and activation receipts atomically, and append a DATA_CONFLICT boundary on the old
revision. Existing captures, reconciliations, actions, trades and original processing times SHALL remain
unchanged; old conflicting revisions remain invalid and cannot provide current positions. New revision
pairing SHALL NOT carry an old open trade. Recovery SHALL NOT change a journal cursor, replay observations,
create a fake Bar, query the provider or send notifications. Failed or unknown commits SHALL be reported
explicitly; an exact persisted recovery receipt is required to prove idempotent completion.

#### Scenario: Canonical source changes after a recovery plan was frozen
- **GIVEN** a conflict recovery plan bound to exact source and target identities
- **WHEN** the source proof, target preimage or stopped-writer fence changes
- **THEN** recovery fails closed without committing a new active revision
- **AND** preserved conflict evidence and existing forward records remain available for diagnosis

### Requirement: Sealed original observation conflict transfer v1

`original_observation_conflict_v1` is independent of capture reconciliation. A bounded maintenance
caller holding stopped producer and Reference writer fences MAY compare a sealed original completed
60m envelope with fresh finalized MDS Canonical at its exact physical contract, owner/calculation
segment, trading day and Bar end. The proof SHALL bind complete original bytes, verified physical
partition content and quality hashes, source manifest, and nonempty finite Decimal field differences.
Scale-only differences, missing facts, future endpoints and uncertain identity SHALL NOT establish
`ORIGINAL_OBSERVATION_CANONICAL_CONFLICT`. No Capture or Reconciliation row is fabricated.

The exact complete four-route enabled group and sealed interval SHALL be frozen before mutation.
One immutable `diagnostic` receipt per original per route SHALL commit atomically with its exact
revision/generation, full original, conflict anchor and interval manifest. An otherwise matched original
within the explicitly retired interval MAY receive `ORIGINAL_OBSERVATION_TERMINAL_FOR_CONFLICT_BOUNDARY`;
this records an explicit group retirement, never a claim that this original itself mismatched or was
processed naturally. This includes matched predecessors of a later conflict in the same frozen interval.
These receipts have no observed_at, strategy action, trade, notification or successful calculation.
Missing even an entire four-route receipt set makes the interval incomplete. Active typed conflict
receipts SHALL make health, the recording matrix and commit guards report DATA_CONFLICT and suppress
current strategy state; unrelated diagnostic kinds SHALL NOT imply a conflict.

`reference_original_observation_recovery_v1` MAY admit only this complete durable typed evidence through
its independent recovery entry. Existing capture-mismatch recovery SHALL NOT treat it as reconciliation.
The same physical source/future-start/atomic flat-revision and immutable-old-facts requirements apply.
Every fresh source proof and sealed original proof SHALL be revalidated in the applying transaction.
Old revisions retain their typed evidence and DATA_CONFLICT boundary; the new revision does not inherit
those conflicts. Transfer and recovery SHALL NOT ACK, replay, create a provider, expand Scope or send.
The normal consumer alone may ACK old envelopes after a proven future-start boundary. Unknown commits
stop without retry; a persisted result requires explicit readback. Existing runtime/install CLOSED
requirements are unaffected by this source-only maintenance protocol.

#### Scenario: A matched predecessor is preserved when its sealed group is retired
- **GIVEN** an exact four-route interval containing a matched original and a later numerically conflicting original
- **WHEN** fresh Canonical proof and stopped-writer fences hold through the atomic transfer
- **THEN** the conflicting original receives the typed conflict reason and the matched original references that anchor as an explicit terminal boundary
- **AND** neither original becomes a Capture, Reconciliation, strategy calculation or notification
- **AND** removal of any original's route receipts prevents recovery admission

### Requirement: Final warm recovery from existing capture mismatches

`reference_capture_final_warm_recovery_v1` MAY renew only the complete enabled H1 group of
trend, oscillation, main-rise and dual-fusion streams after native active-revision Capture
Reconciliation mismatch evidence is present. Fusion need not fabricate its own Capture when
its base routes establish the group conflict. Original-observation diagnostics, including
receipts on retired revisions, SHALL NOT establish this admission and SHALL NOT be reinserted.

The source loader SHALL freshly materialize and hash-validate `original_conflict_warm_seed_v1`
for every source on planning and applying. Only final_observation / WARM_SEED_VERIFIED is
admitted; each base interval must prove no remaining completed endpoint before the exact
future recording start. Provisional, incomplete, untyped, changed-binding and altered seeds
SHALL fail closed. The future recording start in every source manifest and flat checkpoint
must equal the recovery plan boundary.

The existing stopped-writer, Canonical maintenance, fresh source verification, locked complete
preimage and atomic flat-revision protocol SHALL remain in force. All original Capture,
Reconciliation, typed diagnostics and old revisions remain preserved. Recovery emits no
new Capture, Reconciliation, action, trade, notification, journal replay or ACK. Unknown
outcomes retain the exact attempt and park state; this source-only path changes no Runtime
promotion or trading-stage policy.

#### Scenario: A captured group is warmed without repeating old original transfers

- **GIVEN** three base routes have current Capture mismatches and the complete four-route group has final independently verified warm seeds
- **AND** old OriginalTransfer keys remain on retired revisions
- **WHEN** the frozen final-warm capture recovery is applied
- **THEN** all four future-start flat revisions activate atomically using the verified strategy state
- **AND** existing Capture and Reconciliation rows remain unchanged and no OriginalTransfer receipt is inserted

### Requirement: Independently verified conflict warm seeds and pending boundaries

`original_conflict_warm_seed_v1` MAY reuse an immutable Historical checkpoint only after a fresh read
of its exact original query proves equal stream/formula/quality/schema, input hash/count and computed
endpoint. The only permitted manifest difference is `source_evidence_sha256`; fresh physical, Session,
owner and quality evidence SHALL prove that metadata change independently. Other differences require
Historical rebuild. The old checkpoint, manifest and records remain unchanged; a materialized seed has
its own checkpoint/dependency hashes and explicitly links the original source binding.

Warm-up SHALL actually step the existing strategy kernel over a complete ordered completed prefix,
including explicit physical/calculation rollover boundaries. Coverage alone does not advance state.
A fresh interval authority SHALL prove every expected Session endpoint from the old watermark through
the cutoff, including the absence of an omitted tail. Canonical may be followed by independently verified
Live recovery observations; those inputs remain Live, are not first-seen observations, and bind their
actual repair plan/readback. All bars are strict-before the future recording start. Zero-step warm-up
requires independent proof that the entire interval has no completed endpoint and preserves the old
computed_through. Fusion binds all three verified base seeds to the same complete input chain and final
endpoint. Pure warm-up SHALL emit no persisted Capture, strategy action, trade or notification and SHALL
reset only the new reference state to flat.

When a day barrier prevents obtaining the future start's full Live warm prefix, the explicitly separate
`reference_original_observation_pending_warmup_v1` stage MAY retire the sealed old group and create a
future-start flat revision with only its proven prefix. It SHALL persist PENDING_WARMUP in both its seed
manifest and health; it SHALL NOT claim first-observation readiness. A worker heartbeat with ready=true
does not supersede this business status. The old consumer may briefly resume solely to ACK preserved
old originals normally, then SHALL return to a verified cooperative park while final warm-up is pending.
This protocol does not modify any journal cursor or old-day barrier.

`reference_original_observation_finalize_warmup_v1` SHALL admit only the exact four active pending
revisions, activation receipts and seed hashes. Any capture, non-seed batch, action (under either origin
or batch revision), trade, mark or unproven external claim change blocks finalization. A complete final
warm seed creates another independent future-start flat revision atomically and preserves the pending
revision with a WARMUP_COMPLETED boundary. Old conflict evidence is never copied into the pending revision
to manufacture recovery eligibility. The maintenance caller SHALL prove protected claims and journals
and hold the stopped-writer fence through both stages. Unknown outcomes retain the exact attempt and
park state. Reference remains parked on incomplete final warm-up; the status label is not itself a stop
mechanism for older runtime code. Installer and Runtime promotion CLOSED gates remain unchanged.

#### Scenario: A pending warm-up has already observed a Bar
- **GIVEN** an active PENDING_WARMUP revision with a new capture or calculation
- **WHEN** final warm-up admission verifies the exact current revision
- **THEN** finalization fails without replacing it or relabelling the capture as a conflict

### Requirement: Canonical forward scans distinguish completed Sessions from publication

D1/W1 forward input SHALL use the existing MDS published endpoint to bound the incremental
quality read. Session metadata describing a newly completed period is not proof of its Canonical
publication. Before the existing 18:05 local publication schedule, an unpublished current-day tail
MAY wait without creating a capture or treating it as a missing historical dataset. A missing earlier
due period, missing physical dataset, invalid owner, quality interruption or missing map SHALL remain
fail-closed. After the publication deadline, an absent due period SHALL report
`CANONICAL_PUBLICATION_LAGGING`. Weekly due periods SHALL come from the existing completed-calendar-week
resolver, not from a daily fallback. Newly published input SHALL still pass unchanged quality, owner,
calculation identity and observation-gap validation.

#### Scenario: A completed daily Session precedes the scheduled Canonical publication
- **GIVEN** yesterday's Canonical endpoint and today's completed Session before 18:05
- **WHEN** the forward worker scans before today's Canonical publication
- **THEN** it waits without creating an observation or requesting the unpublished daily range
- **AND** missing older periods or failed authoritative input checks still block the route

### Requirement: Unified bounded read-only message presentation

`GET /api/market/messages` SHALL project committed Newow messages and immutable Alert history into one
20-row paged list, ordered by parsed signal timestamp descending, source descending and stable source event
identity descending. It MUST reuse authoritative source readers and MUST NOT create events, transport attempts,
reference trades or account facts. Product, trading-date, source, supported frequency, strategy/rule and
product-name/code/contract search filters SHALL execute on the server.

The reader SHALL retain the Newow 93-day date-span and 500-message cap, and the Alert 366-calendar-day
window and 5000-event scan cap. Search applies inside these bounds. Responses SHALL disclose source
availability, truncation, limits, available count and full bounded `dataset_hash`; incomplete empty results
MUST NOT claim no matching history. Alert read diagnostics include `scanned_count` and `scan_batches`.

Web SHALL reuse a query-bound cache without requests for 30 seconds from the last successful first-page
validation, retain it for at most five minutes, and enforce eight entries, 2MiB total and 300 retained rows.
Pagination MUST NOT extend first-page freshness. Older cached results MAY remain visible during revalidation.
Only identical full dataset hashes may retain older loaded rows; their snapshot and continuation cursor MUST
be rebound to the newly validated snapshot via bounded first-page `resume_count` (any integer0..300, including short final pages)
and response `resume_cursor`. Changed background results SHALL await explicit user acceptance; manual refresh
replaces the first page directly. Failed reads retain the old snapshot with an explicit failure status.
Search SHALL debounce350ms; Enter submits immediately. Query changes isolate late responses.

The single API process SHALL retain frozen query snapshots for120 seconds from creation, with at most16
entries and32MiB of serialized snapshot content, using synchronized LRU eviction. Oversized snapshots fail
with `MESSAGE_QUERY_BUDGET_EXCEEDED`. First-page reads always scan current authoritative sources. Version2
opaque cursors bind the server-held snapshot token, normalized query, cutoff, Alert ID high-water mark,
dataset digest and page offset. Missing, expired, evicted, restarted or mismatched snapshots return409
`MESSAGE_SNAPSHOT_STALE`; continuation MUST NOT rebuild silently or rescan calculation batches.

New Alert insertions and Newow batches after snapshot creation MUST NOT enter its frozen pages. Event and
notification-attempt fields represent their snapshot-time values; refresh reads current values. Source
availability and partial coverage remain frozen and visible for that snapshot, including initial failures.
For initially ready Newow sources, each continuation SHALL cheaply revalidate matching stream membership,
active revision identity, revision status and health; changes or failed identity reads reject continuation.
A new first-page read re-evaluates all sources. No message cache constitutes Runtime or delivery evidence.

#### Scenario: A new Alert arrives between pages
- **WHEN** the user loads a next page while newer Alert IDs have been committed
- **THEN** pagination continues using the original Alert ID high-water mark, with no duplicates or skipped
  rows from the accepted snapshot; refreshing starts a new snapshot.

#### Scenario: Source revision changes or a source fails
- **WHEN** a persisted Newow revision changes between pages
- **THEN** continuation returns a stale-snapshot response and keeps the already displayed facts available.
- **WHEN** a source fails on an initial read
- **THEN** successful sources remain readable with explicit partial coverage and no false completeness claim.

### Requirement: Normal retained observation conflict warm provenance

`retained_conflict_warm_seed_v1` SHALL be a distinct source identity from
`original_conflict_warm_seed_v1`. It MAY warm an unchanged Historical baseline with
normal, retained, completed Live originals, without claiming a provider repair or
fabricating repair plan/readback hashes. The existing v1 repair proof requirements
remain unchanged. `reference_capture_retained_warm_recovery_v1` SHALL use the same
complete four-route mismatch admission, locked fresh source revalidation, atomic
future FLAT activation and unknown-outcome recovery conditions as final-warm recovery.

The concrete read-only authority SHALL bind each original's exact completed-journal
key, trading day, stream ID, observation ID, original envelope bytes and identity-index
bytes. Index ID and payload must match the retained row; when the native index format
includes content, its canonical completed content must match too. Original received,
observed and confirmed times SHALL be preserved, with bar end no later than confirmation
and confirmation no later than knowledge time. Duplicate, missing, changed, unconfirmed,
wrong-contract, wrong-period or unexpected originals SHALL fail closed.

A fresh MDS Session/owner authority SHALL prove the complete ordered interval from the
baseline watermark through every warm input and no remaining endpoint before the exact
future start. A future exclusive start does not permit future inputs: every input must
already be confirmed at knowledge time. The original baseline query and all existing
formula, quality, physical and checkpoint proofs remain mandatory. Normal retained input
provenance and interval readback hashes SHALL never be labelled repair receipts. The
same strategy kernel advances state; source facts are not republished as Canonical.

The initial retained loader SHALL reject physical/owner/calculation changes and require
an independently proved rollover path; choosing the current contract to bypass an old
checkpoint mismatch is forbidden. Fusion SHALL bind three base seeds of the same retained
version and complete input chain. Warm materialization creates no Capture, action, trade,
notification or journal ACK. Maintenance writes only the newly approved independent FLAT
revision and its existing activation/boundary facts; old immutable facts remain unchanged.

#### Scenario: A normal retained night prefix warms a conflict without a fake repair
- **GIVEN** an exact Historical seed and a complete, confirmed night prefix retained with matching native journal indexes
- **WHEN** fresh Session, owner, baseline and repeated original readback proofs all pass
- **THEN** the retained seed advances the existing kernel to the night frontier and remains future-start FLAT
- **AND** no repair receipt is fabricated and no original is replayed to the normal consumer

#### Scenario: A retained original or its index changes during warm verification
- **GIVEN** a candidate retained warm interval
- **WHEN** an original is missing, duplicated, altered or disagrees with its native index on fresh readback
- **THEN** no new revision is activated and the failure evidence is preserved


### Requirement: Explicit retained rank1 owner transition

`retained_rank1_owner_transition_v1` MAY admit exactly one adjacent authoritative
rank1 physical-contract transition through a separate opt-in retained warm loader.
The ordinary retained loader SHALL continue rejecting owner changes. The proof SHALL
bind the previous authoritative trading day, old rank1 effective end, new rank1
start, both Session windows and owner/calculation identities. The baseline must be
exactly the old day's final completed endpoint with no omitted old-owner tail;
nonadjacent, changed old-contract or unproven mapping cases SHALL fail closed.

The new physical contract SHALL be chosen only from that independently proved new
rank1 segment. Complete retained originals and expected endpoints SHALL be checked
under the new day owner, and every input must match it. The first input SHALL take
the existing kernel's explicit rollover branch with seed_replay_state; later inputs
continue only this new state. Old-contract indicator state and reference positions
SHALL NOT carry into the new contract. The warm proof SHALL retain exactly one old/
new owner transition and a final no-remaining-endpoints proof. A new FLAT revision
means reference consumption recovery only; the new physical segment's actual WARMING
or unavailable strategy facts SHALL remain unchanged and disclosed.

#### Scenario: A complete night prefix follows an authoritative rank1 rollover
- **GIVEN** a Historical checkpoint at the previous rank1 contract's exact final endpoint
- **AND** authoritative adjacent-day rank1/Session evidence and complete new-contract originals
- **WHEN** the opt-in transition loader warms the existing kernel
- **THEN** the result equals a fresh kernel fed only the new-contract inputs
- **AND** no old-contract indicator state, reference position, Capture or notification is carried forward


### Requirement: October 22 retired-day absence is sealed by native day advancement

The explicit October 22 repair MAY use `RETIRED_DAY_ABSENCE_V1` only for H1
checkpoints no earlier than October 21 15:00 Asia/Shanghai and missing completed
endpoints through October 22 15:00. Source Live and completed Alert/Reference
registration keys SHALL actually exist and equal October 23. Native monotonic
NEW_DAY and pre-write APPEND/COMMIT registration checks seal the retired day;
wall-clock silence or expiration of arrival grace alone is insufficient.

Both source and completed October 21/22 journals and identity indexes SHALL
exist, be fully read and match original IDs, payloads and native content
fingerprints. Their old consumers SHALL be at tails. A saved target H1 after the
checkpoint blocks absence, even when acknowledged. Missing keys, invalid indexes,
changed rank1/Session endpoints, missing cleanup evidence or lost writer fences
SHALL fail closed. Plans bind exact Runtime, checkpoint, receipt and source proof,
reuse the native one-shot interruption calculation, and preserve old facts and
unknown provider buffers. No October 23 endpoint is admitted by this proof.

For the complete four-route L H1 conflict group only,
`reference_retired_day_conflict_reset_v1` MAY atomically retire the conflicted
revision and create an independent future FLAT revision. Its native product or
fusion kernel SHALL be empty, with an explicit retired-day interruption watermark
and provenance; it SHALL NOT be represented as a historical or retained warm seed.
Old DATA_CONFLICT evidence remains unchanged. Health remains
OBSERVATION_LAGGING; the open October 23 gap and subsequent natural warm-up remain
separate acceptance conditions. No maintenance replay, cursor changes or notices
are authorized by either repair entry.

#### Scenario: Retired-day source keys expired
- **GIVEN** a retired day's journal or identity index no longer exists
- **WHEN** the task attempts to prove absence
- **THEN** it fails closed instead of treating expiration as an empty observation day

#### Scenario: A new day still has an open gap
- **GIVEN** the October 22 interruption is committed and October 23 is active
- **WHEN** no complete natural H1 has closed the new-day prefix gap
- **THEN** that gap remains unproven and the repair does not claim full natural readiness

### Requirement: Pristine L reset uses retained originals for preactivation warm-up

Only the complete four-route L H1 group with the pristine October 22 empty-reset
seed MAY use `reference_retired_original_warmup_v1`. The active revision SHALL
contain only its seed chunk and seal, retain the explicit 15:00 interruption,
empty kernel and 22:55 future-FLAT boundary, and have no captures or actions.
A separate atomic revision SHALL warm native product kernels using the retained
October 23 trading-day 22:00 and 23:00 completed H1 originals. Authoritative
endpoints, each original ID/index/content, contract/owner, metadata and frontier
SHALL be re-read before admission. Missing or changed evidence fails closed.

This operation SHALL preserve old conflict and empty-reset revisions and all
immutable facts. It SHALL NOT fabricate a reconciliation conflict, missing gap,
natural capture or first-seen time; no journal replay, ACK, cursor change,
notification or reference trade is created. The new checkpoint uses a future
FLAT boundary and typed original provenance; health remains OBSERVATION_LAGGING
until a subsequent actual Session H1 is consumed normally. Existing strategy
availability/warming semantics and formulas remain unchanged.

#### Scenario: An existing pre-start original must warm the kernel
- **GIVEN** the pristine L reset starts after the retained 22:00 original
- **WHEN** both 22:00 and 23:00 originals and the complete frontier are proved
- **THEN** the dedicated atomic warm revision preserves future FLAT and original times
- **AND** subsequent natural acceptance remains pending, without manufacturing a missing gap

### Requirement: HTDY retrospective fixed-window reference is independently identified

The read-only `/api/v1/market/{symbol}/htdy/reference` endpoint SHALL replay each completed
physical-prefix Bar using the existing HTDY evaluator's fixed 32-Bar window. Its model identity
SHALL be `htdy_historical_window32_reverse_close_v1`, recording mode `historical_replay`, with
no observation policy or fabricated observed timestamp. It SHALL reuse the existing reverse-close
reference policy rather than introduce new buy/sell rules. This is retrospective reconstruction,
not proof of a first-seen event or account execution.

The reader SHALL obtain storage-wide physical prefixes and authoritative quality/owner boundaries
through the existing MDS-backed historical loader. Presentation since/through SHALL NOT truncate
warm-up or change signal pairing. Quality interruption and rollover SHALL terminate reference
trades explicitly and restart window warm-up. It SHALL NOT write reference storage, AlertEvent,
notifications, Canonical, or Runtime state. Date filtering and trade pagination SHALL be independent
of graph pagination; the cursor SHALL bind full source content, model identity and cutoff. Source
metadata changes during the read SHALL reject the result.

#### Scenario: Historical reconstruction differs from an actual observation

- **WHEN** a completed prefix is replayed without an original captured observation
- **THEN** its signals and reference trades are labeled historical reconstruction only
- **AND** no actual observation stream, event or notification is created or rewritten

#### Scenario: Paging cannot change the reconstructed trade

- **WHEN** a user changes the displayed date window or requests the next records page
- **THEN** computation starts from the same authoritative storage prefix and fixed model
- **AND** records retain stable action/trade identities while changed source invalidates the cursor

The HTDY reader MAY retain a bounded process cache of pure replay results, keyed by full input
content, owner/quality segment boundaries, source metadata, formula/model identity and cutoff.
Every request MUST still verify MDS input identity; TTL or cache presence MUST NOT prove validity.
Record pagination and summary use the same replay result without re-evaluating unchanged prefixes.
HTDY summary SHALL aggregate the entire selected entry-day window before record pagination.
Win/loss/flat counts, win rate, mean return and summed percentage points SHALL use only CLOSED
reference returns with Decimal arithmetic; OPEN and interrupted records SHALL NOT count as
completed returns. These values SHALL NOT be labeled account equity or compound return.
The cache SHALL NOT be a historical fact authority and SHALL NOT write Redis or persistent events.


### Requirement: Retained forward reference performance panel

SuBing and HTDY detail performance SHALL use only `forward_observation` retained
reference streams. Historical replay and HTDY repainting SHALL NOT fill missing
forward trades, summaries, curves or action labels. These are zero-cost reference
facts, not Paper or broker fills. An absent, disabled, ambiguous or unsupported
stream SHALL display its actual unavailable state, never a zero-performance claim.

`GET /api/v1/reference-trading/streams/{stream_id}/panel` SHALL read one frozen
snapshot for the first trade page, complete closed-trade curve and existing
`entry_in_window_v1` summary. Collection is bounded to 10,000 records; excess,
changed cursors/snapshots or count/sum disagreement SHALL fail closed. Decimal
sums and drawdown use every eligible CLOSED trade, excluding initial, OPEN and
interrupted trades. Drawdown is the maximum peak-to-trough difference of the
cumulative percentage-point curve, not account equity drawdown or annualization.
Curve sampling (at most 800 points) SHALL NOT recalculate statistics or join
physical/calculation segment boundaries. GET SHALL NOT replay, build, enable,
write production data or send notifications.

The Web panel SHALL show the curve and summary together, three recent cards,
on-demand full records and exact-snapshot pagination. It SHALL NOT download all
signal/indicator presentation pages before displaying performance. Cached results
are memory-only successes, bounded to 20 entries/15 seconds, partitioned by stream,
revision, sequence, activation generation, health, strategy/product/frequency and
window. Every refresh SHALL re-resolve the live stream before cache reuse;
failures SHALL NOT be cached or replace another identity. Late responses and
subscriber cancellation SHALL NOT corrupt other views. Audit events remain
separate from reference trades and are not evidence of recipient delivery.


The Web reference panel and its reference-source caption SHALL appear only for
HTDY `60m`, or SuBing `5m/15m/30m/60m/1d/1w`. Other periods SHALL render no reference
panel or unsupported-reference placeholder and SHALL NOT query reference streams.
This presentation policy SHALL preserve the chart and independent signal audit.

#### Scenario: SuBing six periods expose independently identified reference records

- **WHEN** the SuBing workspace selects 5m or 1w
- **THEN** the chart, Event audit and reference panel remain available; the panel queries the same selected period, and missing saved records remain explicitly unavailable

#### Scenario: Missing retained reference stream

- **WHEN** no readable retained forward stream exists for the selected identity
- **THEN** the panel displays the missing state without synthesizing trades or a return curve

### Requirement: HTDY realtime presentation uses only 60m

HTDY detail SHALL query and display realtime AlertEvent and retained forward
reference records only at `60m`. Other periods SHALL retain their historical chart
selection and display “实时信号统一记录于60分钟”; they SHALL NOT query realtime
Event or reference streams. Leaving 60m SHALL invalidate outstanding Event reads
and stop polling. Old Event and transport facts SHALL remain available for audit;
this presentation restriction SHALL NOT delete generic API capabilities, replay
signals, create reference streams or change SuBing behavior.

#### Scenario: A legacy HTDY 15m link is opened

- **WHEN** the HTDY workspace opens a 15m URL
- **THEN** its chart remains 15m, the 60m realtime notice is shown, and no realtime Event or reference stream request is sent

### Requirement: SuBing six-period historical and forward reference identity

SuBing reference SHALL support exactly `5m/15m/30m/60m/1d/1w`, using the same per-period
kernel and formula versions as SuBing Alert. Existing four-period historical identities SHALL remain unchanged.
5m and W1 SHALL use `subing_ths_5m_v1` and `subing_ths_1w_v1` with independently identified streams.
Same-direction signals SHALL NOT add positions; opposite signals SHALL close and reverse at signal close,
with zero fees/slippage and `executable=false`. These are reference facts, never orders or fills.

New forward streams SHALL use `subing_physical_prefix_forward_v2`. Their first input, owner/calculation
change and restart-after-gap SHALL warm only the shared indicator from an authority-validated physical
strict-before prefix. Historical positions/actions SHALL NOT carry into forward state. Continuous Live
inputs SHALL resume the durable kernel checkpoint; completed Canonical D1/W1 captures SHALL bind their
validated source prefix. The authoritative owner Session start SHALL interrupt the old reference before
any new-owner action. Missing or conflicting source proof SHALL fail closed.

W1 SHALL use the authoritative Calendar and final Session of the complete week, including holiday-short
weeks; a midweek date SHALL NOT confirm a partial week. Explicit `through` bounds the final selected week,
while actual `as_of` proves completion. Physical-prefix warmup SHALL remain independent of rank1 ownership;
owner intervals with no authoritative W1 endpoint SHALL create no synthetic Bar. Unknown/missing data
SHALL NOT be treated as a legitimate empty interval.

Activation SHALL use exact plan hashes, per-route atomic flat seeds and existing activation receipts.
Before activation no new stream is enabled. Capture SHALL admit only one newly confirmed input after
recording start; multiple missed endpoints use the existing interruption policy, never fake first-seen
history. Historical assets advance through the existing bounded refresh thread after Canonical publication.
SuBing notification remains disabled; new reference streams SHALL NOT route to Newow transport.

#### Scenario: A first completed observation arrives after activation

- **GIVEN** an exact enabled SuBing v2 route with a flat reference seed
- **WHEN** one new completed Bar arrives with its authoritative physical strict-before prefix
- **THEN** only indicator state is warmed and the current Bar may create a reference action, without replaying historical positions or Event notifications

#### Scenario: A weekly physical prefix contains an unprovable or classified missing Bar

- **WHEN** the requested W1 physical prefix cannot prove continuous valid input
- **THEN** the route reports data unavailable and creates no synthetic Bar, reference trade, or return

### Requirement: Durable intake is independent of ordered Reference calculation

The `reference_receiving_v2` protocol SHALL persist the exact completed original and frozen stream/revision/generation
routes atomically in PostgreSQL before acknowledging its existing Redis cursor. Intake progress SHALL mean durable
acceptance, not completed calculation. Conflicting content and uncertain commits SHALL fail closed with exact independent
readback; no cursor recreation, skipped originals, replacement prices or duplicate transactions are permitted.

Each stream SHALL process its earliest unfinished delivery in numeric journal order. Fair bounded rotation SHALL let
other streams proceed when one waits for physical history. Delivery completion SHALL commit with its matching Reference
calculation. Identity drift, actual observation gaps and unknown mutations SHALL remain explicit and SHALL NOT be
converted into automatic replay or successful history preparation.

Original source/received/confirmed timestamps SHALL remain immutable. Ingestion and calculation times SHALL be separate,
with `delivery_timing_v2` exposing delayed-original processing without changing formulas, trades or notification deadlines.
The immutable accepted originals SHALL remain readable after Redis retention expires; missing intake cursors SHALL block
intake, but SHALL NOT prevent calculation of already accepted deliveries. Intake failure SHALL survive restart.

#### Scenario: A newly dominant contract is waiting for history

- **GIVEN** one enabled stream cannot prove its new physical contract prefix
- **WHEN** its confirmed original is accepted
- **THEN** its delivery SHALL wait for shared normal contract preparation and other streams SHALL continue
- **AND** after verified preparation it SHALL resume original order without sending expired notifications.

#### Scenario: Intake ownership changes or the Redis journal expires

- **GIVEN** version two was requested after additive schema installation
- **WHEN** the exclusive new Runtime owner starts at the native handover boundary
- **THEN** it SHALL freeze the existing cursor without resetting it and activate version two
- **AND** read-only warmup SHALL NOT persist protocol state or intake failure
- **AND** accepted originals SHALL continue calculation even if subsequent Redis intake is blocked.

#### Scenario: A fresh activation has no natural calculation yet

- **GIVEN** the original generation-one flat seed, activation receipt, complete manifest and chunk/hash chain are independently verified
- **WHEN** no capture or calculation has ever existed for that stream
- **THEN** read-only prewarm MAY count the stream as initialized, SHALL NOT count it as calculated, and SHALL NOT manufacture a replay input
- **AND** a calculated stream with missing predecessor evidence SHALL remain blocked.

#### Scenario: Durable receiving runs while calculation is pending

- **WHEN** a bounded receiving round completes with a valid owner and no drain request
- **THEN** it MAY publish a receiving_cycle proof distinct from calculation readiness
- **AND** native handover MAY accept only independently reverified active-v2/schema/cursor evidence and the exact current immutable heads in a read-only repeatable snapshot
- **AND** every worker block SHALL match a permitted WAITING_HISTORY head, ordinary PENDING heads SHALL have no error code, and activation/identity/hash drift, BLOCKED, UNKNOWN, intake failure or unproved fusion dependency SHALL reject the proof
- **AND** receiving, backlog and history-wait modes SHALL NOT rewrite calculation ready/blocked facts or claim that Redis is caught up.

### Requirement: Bounded forward scheduling and cooperative drain

Durable-minute scans SHALL discover scheduling groups from enabled stream metadata and actual pending captures;
they SHALL NOT deserialize idle strategy checkpoints merely to discover frequency. Group completeness, fair
rotation, per-stream numeric journal order and pending-capture recovery SHALL remain unchanged.

One closure readback MAY reuse identical original, receipt and bounded-bridge proofs inside that readback only.
Every delivery SHALL still prove its own original/plan/capture/calculation/checkpoint links and its position after
the bridge. Later readbacks SHALL independently revalidate, including legal receipt disablement and corruption.
Accepted originals SHALL be loaded for a physical warm-up only when that capture actually needs the prefix.

Unfinished accepted deliveries or pending captures SHALL withhold new historical-refresh permission. An active
refresh SHALL cooperate at its existing safe planning/batch boundary, without releasing a source lease early.
Scanning, pure reads and evaluation SHALL check cooperative drain between bounded units. Cancellation before a
new mutation SHALL preserve its original and any committed pending capture; it SHALL NOT mark BLOCKED/UNKNOWN.
An entered commit SHALL complete or receive exact independent readback under the existing unknown-outcome rule.
Drained status SHALL require actual background-thread and resource closure; the existing ten-second native
handover budget SHALL NOT be enlarged. Stage timings SHALL be bounded aggregates outside immutable evidence.

#### Scenario: Drain interrupts a long scan or pure preparation

- **WHEN** an owned worker receives a drain request between routes or during cancellable pure work
- **THEN** it stops claiming subsequent work and retains the unfinished route/capture for ordered continuation
- **AND** it neither advances an uncommitted delivery nor records a calculation failure for cancellation

#### Scenario: A shared bridge is valid but the next original is not after it

- **GIVEN** a bounded bridge already validated within the current readback
- **WHEN** another linked original has an invalid time or calculation sequence relative to that bridge
- **THEN** closure verification rejects it despite reuse of the bridge's common immutable proof

## Requirement: Live observation handover preserves capture identity

With the explicitly enabled completed observation journal, new Live captures SHALL
originate only from its real completed observation envelopes. Each capture SHALL use
that envelope's first actual `confirmed_at`, never the current scan or restart time. Original `raw_received_at` is preserved separately and may precede Bar end; it never grants completed eligibility by itself.
D1/W1 canonical capture, pending-capture recovery and recording activation generations
remain unchanged. A scan MAY recover an existing pending Live capture but SHALL NOT
recapture new Live bars at scan time.

The Reference consumer SHALL acknowledge an envelope only after all affected routes
have safely persisted and projected the existing capture identity. The capture's `observed_at` is the first real completed confirmation time; `source_proof.raw_received_at` and the committed batch's `observation_timing_v1` separately retain the original receipt for notification freshness. Invalid physical
identity, a blocked route or unknown commit SHALL keep the observation unacknowledged.
The consumer SHALL preserve its explicit cursor across publication roots; missing or
expired progress SHALL block rather than silently start at the latest Bar. First
migration SHALL initialize only an empty journal before its publisher is started.

Candidate prewarm SHALL read scoped checkpoints/input facts and run pure evaluation
without capture, batch, historical refresh or notification writes. When caught up, it
MAY recalculate an immutable prior capture from its actual predecessor checkpoint;
missing preimage SHALL fail closed and SHALL NOT create a synthetic observation.

## Requirement: Explicit stopped-publisher interruption remains one-shot

A task-local fault repair MAY append a new activation receipt and exact
`observation_interruption` capture for proven missing completed Session endpoints.
It SHALL preserve every previous receipt, checkpoint and original envelope time.
A previous bounded receipt MAY be renewed only after its unique generation/hash
capture is linked to a committed calculation in the same active revision with the
exact sequence. Pending, unknown, changed budget, broken receipt hash chain or
unproven source SHALL block. The effective source policy remains `block` for all
future unplanned gaps.

For the exact generation16 to17 repair, `SERVICE_OUTAGE` authority SHALL require
old publishers stopped, actual Feed close, released old owners, parked new
Reference, calendars absent and old source/completed consumers at retained tails.
It SHALL freeze authoritative rank1/Session past endpoints at one fixed cutoff
and check the entire real completed journal for saved originals and integrity.
No future endpoint, synthetic Bar or historical observation may fill the gap.
Before normal Feed NEW_DAY, absent day13 journal/cursor/identity keys SHALL remain
absent and registration SHALL remain on the drained old day. Only the existing
Feed NEW_DAY initializes the new day.

The interruption boundary SHALL be the last missing completed endpoint, not repair
wall time. It is interrupted evidence, never natural observation. Saved originals
require durable replay with original confirmed/raw times; missing observations
cannot be given original first-seen times. These task-local proofs SHALL NOT
authorize automatic failover, new Scope, notification replay or formula/return changes.

## Requirement: Explicit immutable Inbox recovery closure

`reference_inbox_recovery_v1` SHALL be an explicit, stopped-writer maintenance operation,
not an automatic worker retry. `InboxRecoveryPlan` SHALL freeze the original input and
route preimage, source and target activation receipts, checkpoint token, capture hash,
expiry, stopped-writer fence and its fixed private attempt namespace. A delivery-level
exclusive, no-follow, fsynced claim SHALL precede any mutation. Unknown results consume
that claim; changing the plan or namespace SHALL NOT authorize another attempt. A complete
independent exact readback MAY return a prior committed result without another mutation.
A separately versioned `al_proven_rollback_v1` continuation MAY be explicitly planned only
for the accepted AL HTDY 60m identity after stopped-writer fencing and independent proof
that the old transactions ended, no calculation or closure committed, the checkpoint did
not advance, and the unique original capture remains unconsumed. It SHALL retain the old
claim and namespace, bind its parent plan/claim hashes and capture identity into the new
JSON proof, and consume a separate exclusive fsynced continuation claim in that same
namespace before mutation. It SHALL reuse that capture and commit the calculation,
projections, checkpoint and closure atomically. Upgraded closure readers SHALL validate the
continuation linkage; normal apply SHALL reject continuation plans. Recursive continuation,
automatic retries and namespace changes SHALL NOT grant another attempt. A failed or
unknown continuation SHALL consume its sole claim; only exact committed-result readback
may subsequently succeed. Source verification SHALL not acquire Reference row locks in
another session; the commit guard SHALL use the existing transaction's session.
The continuation closure SHALL additionally require a live, one-use admission bound to
the exact invocation, plan and successfully guarded commit Session; a durable marker alone
SHALL NOT authorize direct service submission. Once the continuation claim exists, a
parent plan SHALL NOT authorize another submission through the lower-level service.
For this one closed-session AL repair, newly released maintenance code MAY write the
closure while v1.16.32 owners are fenced, before native promotion (which requires zero
pending captures). Unchanged v1.16.32 read-only consumers MAY use their complete v1
receipt/capture/calculation/checkpoint validation during this bounded transition; this
SHALL NOT be described as verification of the new linkage. The old Reference writer
SHALL remain parked until new-code exact readback verifies the closure, or an independent
ended-transaction/readback proof establishes no calculation committed. An unresolved
commit SHALL keep that writer parked while Feed/Live are safely restored. Only after
native foreground catch-up and zero pending captures may a fresh cohort plan promote
the upgraded consumers. No new retry, Scope, formula or notification authority is granted.
An `HTDY_WINDOW_UNAVAILABLE` delivery MAY use this same closure only for the exact accepted
HTDY 60m identity and an original-bound capture that passes all existing source, window,
checkpoint, receipt, fence and atomic calculation checks. Other identities and genuinely
unavailable/conflicting windows SHALL remain blocked; the original BLOCKED row SHALL remain intact.

Additive schema `20261028_0054` SHALL append `reference_inbox_recovery_results` without
changing 0053 originals, frozen routes, BLOCKED/UNKNOWN states or immutable guards. Each
result uniquely links one original delivery to its actual capture, committed calculation,
sequence, target receipt/revision/generation and frozen plan. The result SHALL commit in
the calculation/projection/checkpoint transaction. No result SHALL be inserted before
successful calculation or by a later repair of an uncertain transaction.

Ordering, health, receiving and native handover SHALL share complete closure verification.
Receiving MAY avoid a closure read when no new unfinished route is created, or when
capacity is sufficient even with every recovered delivery conservatively counted as
unfinished. This upper bound SHALL NOT establish recovery success or release a head.
Reclaiming recovered capacity SHALL still require fresh complete closure verification
inside the existing serialized capacity transaction; no verification conclusion is
cached across transactions. Every accepted original and its frozen routes remain durable
before journal acknowledgement, including originals with no matching routes.
A valid result may exclude its preserved old delivery from unfinished-head selection;
all other heads retain numeric journal ordering and all UNKNOWN facts remain blocking.
Health SHALL distinguish recovered calculation counts from original completed deliveries
and preserved historical BLOCKED records. Merely inserting a result row is insufficient:
original, receipt, capture, calculation, checkpoint and plan hashes SHALL match. Later
legitimate receipt disablement SHALL preserve historical closure; other receipt changes
or disablement preceding closure SHALL fail verification.

Same-generation retained-original recovery SHALL not renew activation. A separately proven
missing prefix MAY use the existing one-shot bounded interruption and a single generation
bridge. The exact old and new receipts and the consumed gap capture/calculation chain SHALL
be independently verified on every closure readback. A second gap is not authority to
bridge multiple generations or discard surviving originals. Missing source retention,
internal holes, changed ownership or unknown commitment SHALL stop the affected stream.

The explicit bounded scope policy `reference_inbox_recovery_v1`, also frozen in the journal
proof, MAY include existing SuBing `subing_physical_prefix_forward_v2` streams at
5m/15m/30m/60m. The default bounded entrance remains Newow H1 only. SuBing's original
unbounded activation policy is not proof of a consumed bounded receipt; only this explicit
first recovery may replace it with a hash-bound one-shot receipt. Later unplanned gaps
remain blocked. Existing kernels, prices, interrupted-reference semantics and notification
expiry remain unchanged; no historical observation, action or notification becomes newly
first-seen.

### Scenario: A delayed original recovers without resetting its old blocked fact

- **GIVEN** an exact original and frozen route, a valid stopped-writer plan and an unused delivery claim
- **WHEN** its verified calculation, projection, checkpoint and recovery result commit atomically
- **THEN** the original BLOCKED row remains unchanged and the next ordered delivery becomes eligible
- **AND** transaction failure or a broken bounded bridge never releases that head or sends an expired notification

本次 AL 维护的休市窗口沿用原生 cohort 的 CLOSED/BREAK 判定：无当前 Session、Feed确认宽限结束，
距离下一Session超过660秒；BREAK不等于允许盘中执行。每次来源fence仍fresh重验，不放宽未知/互斥或退出预算。
