# Historical chart signal window

## Purpose

Provide bounded historical HTDY and SuBing chart markers independently from reference performance
windows, with authoritative physical-prefix inputs and explicit recording identities.

## Requirements

### Requirement: Chart signals are read by bounded completed-Bar window

`GET /api/v1/market/{symbol}/reference-signals` SHALL accept strategy (`htdy` or `subing`), frequency,
exchange trading-day `since`/`through`, exact inclusive completed-Bar timestamps `from`/`to`, and
optional `as_of`, `limit` (1–200) and cursor. A window SHALL contain at most 2000 authoritative owned
Bars; necessary physical warm-up prefixes SHALL remain intact, up to the bounded 100000-Bar input
budget. The reader SHALL use existing MDS loaders and kernels and SHALL NOT change strategy formulas,
reference returns, Canonical, Runtime, actual observations or notifications.

The response SHALL include recording mode `historical_replay`, exact requested time window, source
and formula/model identity, source history start, coverage count/endpoints, signal items and next
cursor. Coverage SHALL distinguish current canonical completion from a request extending beyond it.
The reader SHALL NOT inherit the reference list's default 20/120 trading-day window or 365-day date
limit. Source changes during reads SHALL reject the result; cursor identity SHALL bind source,
strategy, frequency and exact requested window. A missing persisted asset SHALL NOT be treated as an
empty signal set or trigger a legacy replay fallback when the configured reader mode is persisted.

#### Scenario: Earlier chart pages keep their true historical signals

- **WHEN** the user loads a chart page older than the default reference performance window
- **THEN** that page queries only its bounded display interval with complete necessary physical prefixes
- **AND** its historical signal source remains separate from actual observed events and reference statistics

#### Scenario: A request exceeds the display window budget

- **WHEN** the requested interval contains more than 2000 authoritative owned Bars
- **THEN** the service returns `SIGNAL_WINDOW_TOO_LARGE` rather than truncating history or changing formulas

### Requirement: Reference record windows navigate to the local history start

Both historical reference record responses SHALL include ISO-date `history_start` and nullable
`previous_window` containing the previous 20 completed trading days for intraday or 120 for daily.
The shared Calendar/Session reader SHALL determine these dates. Each window SHALL retain its own source
identity and summary. Appending earlier records SHALL NOT present multiple window sources as a single
snapshot or silently aggregate their performance.

#### Scenario: Current record cursor is exhausted

- **WHEN** the current window has no remaining records page and `previous_window` exists
- **THEN** the client may request that earlier window through the existing reference endpoint
- **AND** the initial summary remains attributed to its original performance window

### Requirement: Version two chart items are server-associated reference actions

The sole active `historical_signal_window_v2` response SHALL expose `items` as a stable paginated
sequence of reference action facts, rather than unpaired observation arrows. HTDY actions SHALL come
from its existing replay trades; SuBing actions SHALL come from the verified persisted reference
trades under exactly the same snapshot, revision and sequence as the saved source signals. The client
SHALL NOT infer trade pairing, exits, reference prices or returns from observed directions.

Each item SHALL contain stable `action_id`, `source_action_id`, `reference_trade_id`, `signal_id`,
`role` (`BUILD` or `CLEAR`), `side` (`LONG` or `SHORT`), exact Bar/time/trading-day, physical contract,
owner and calculation segment, reference price, trade status, recording mode and nullable `return_pct`.
The public reference trade identity SHALL match the corresponding record-list identity. A source
signal association SHALL match the exact Bar, physical contract, owner segment and calculation segment.
When present, source `action_ids`, `entry_trade_id` and `closed_trade_id` SHALL match the exact referenced
action and role-specific public trade identity; a missing or
ambiguous association SHALL fail explicitly. Prices and returns SHALL retain Decimal serialization.

Only an existing trade entry SHALL emit BUILD. Only a CLOSED trade's linked exit SHALL emit CLEAR;
only that exit may carry its existing percentage reference return. Same-direction repeated
observations SHALL NOT manufacture another BUILD. Interrupted references SHALL NOT manufacture a
CLEAR or realized return. Reversals SHALL expose two separately identified actions, old trade CLEAR
before opposite trade BUILD at the same Bar. Pagination SHALL bind the action schema and source
window and SHALL sort by exact time, CLEAR before BUILD, trade identity and action identity.

#### Scenario: A reversal creates two linked reference facts

- **WHEN** the established model closes a LONG reference and opens SHORT at one completed Bar
- **THEN** v2 emits that LONG trade's CLEAR followed by the distinct SHORT trade's BUILD
- **AND** the exit alone carries the established closed return without client-side pairing

#### Scenario: Historical references are interrupted

- **WHEN** a reference terminates because of a physical-owner or data-quality boundary
- **THEN** its entry may remain visible as BUILD with the interrupted trade status
- **AND** no executable exit, CLEAR action or realized percentage is invented
