# Unified Reference Trading

## Purpose

定义所有策略共用的 ReferenceTrading 领域合同。它只投影研究用途的参考交易，`executable=false`、
`auto_order=false`，绝不创建 Order、Fill、Position、Ledger、Account PnL、AlertEvent 或通知。本规格冻结
P0/P1 的公共身份和纯状态语义、P3 的持久化/原子批次/内部快照合同，以及 P4 的离线历史计划、构建、恢复、
增量与重建应用合同。HTTP 查询、Web 与 Runtime 仍是后续计划能力，不声明 active；代码与测试不授权生产
migration、历史 bootstrap、Canonical 写入或 Runtime enable。

## Requirements

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
| Newow trend / oscillation / main-rise | 1w, 1d, 60m | P4 bounded historical plan/build/resume/advance/rebuild implemented over P2/P3 | Temporary Canonical/Catalog/MDS wiring and fixtures are verified; real per-product/per-frequency data evidence remains separate | Not implemented | Disabled / no worker |
| SuBing reference | 15m, 30m, 60m, 1d | P4 bounded historical plan/build/resume/advance/rebuild implemented over P2/P3 | Temporary Canonical/Catalog/MDS wiring and formula fixtures are verified; D1 quality/readiness remains separately gated | Not implemented | Disabled / no worker |
| HTDY first-seen | observation policy frequencies | Not approved; repainting boundary | `MODEL_NOT_APPROVED`; P7 owner decision required | Proposed only | Disabled / no worker |

All rows are disabled by default. This matrix neither opens a Scope nor authorizes Canonical, database, notification,
release or Runtime work.

#### Scenario: Historical adapter tests pass

- **WHEN** a strategy/frequency adapter passes its isolated fixture and checkpoint tests
- **THEN** only that row's historical code support and fixture evidence may be recorded
- **AND** its Runtime remains disabled until a separate Runtime authorization and readback exist

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
