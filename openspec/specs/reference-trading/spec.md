# Unified Reference Trading

## Purpose

定义所有策略共用的 ReferenceTrading 领域合同。它只投影研究用途的参考交易，`executable=false`、
`auto_order=false`，绝不创建 Order、Fill、Position、Ledger、Account PnL、AlertEvent 或通知。本规格冻结
P0/P1 的公共身份和纯状态语义；持久化、历史构建、查询、Web 与 Runtime 仍是后续计划能力，不声明 active。

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
| Newow trend / oscillation / main-rise | 1w, 1d, 60m | Existing pure projector; P2 adapter required | Per-strategy/per-frequency evidence remains separate | Not implemented | Disabled / no worker |
| SuBing reference | 15m, 30m, 60m, 1d | Existing pure projector; P2 adapter required | D1 quality/readiness remains separately gated | Not implemented | Disabled / no worker |
| HTDY first-seen | observation policy frequencies | Not approved; repainting boundary | `MODEL_NOT_APPROVED`; P7 owner decision required | Proposed only | Disabled / no worker |

All rows are disabled by default. This matrix neither opens a Scope nor authorizes Canonical, database, notification,
release or Runtime work.
