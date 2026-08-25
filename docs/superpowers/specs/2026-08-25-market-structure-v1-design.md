# Market Structure V1 Design Spec

**Status:** Proposed — awaiting independent review  
**Date:** 2026-08-25  
**Target branch:** `research/market-structure-v1`  
**Base:** `develop@ad30633da59668f5d9a3496238c4c15ec72e7aab`  
**Delivery lane:** Lane 3 / Plan-only / no implementation in this change

## 1. Decision

Build `market_structure_v1` as a causal, read-only market-context capability for the local single-user futures research workstation.

It is not a strategy, entry signal, Alert rule, formal backtest result, or replacement for SuBing, N Structure, JDJ, or HTDY. It will eventually appear as a separate Market context layer that may coexist with the four canonical chart overlays; it will not become a fifth `ResearchOverlayId`.

The implementation is divided into four gated stages:

| Stage | Outcome | Public surface |
|---|---|---|
| A — Clean-room calibration | Select and freeze a causal pivot policy from independently observed behavior | None |
| B — Indicator kernel | Produce versioned confirmed pivots, labels, structure state, and unstable preview | None |
| C — Internal research projection | Validate the kernel through read-only research service/CLI and evidence | Internal CLI only |
| D — Market observation UI | Add current-chart structure markers and a seven-frequency structure matrix | Read-only Market context |

Stages are sequential. Failure of a stage Gate blocks every later stage. Stage D requires a separate human approval after Stage C evidence; approval of this document does not authorize Stage D implementation, merge, release, Runtime promotion, real data mutation, notification, or order activity.

## 2. Context and compatibility

The current canonical product facts are:

- Market chart overlays remain exactly `none | subing | jdj_strategy | htdy`.
- N Structure and raw JDJ remain internal research capabilities.
- SuBing owns its existing Factor, Signal, Calibration, FormalPolicy, and Lifecycle logic.
- HTDY remains observation-only/repainting and follows its completed-Live versus D1/W1 Canonical seam.
- Historical bars are read only through `MarketDataService`; Redis Live is observation, not Canonical.
- All outputs are research observations with `auto_order=false`.

`market_structure_v1` therefore receives its own formula identity, policy artifact, service namespace, API schema, tests, and UI preference. Existing N/SuBing/JDJ/HTDY formulas and DTOs are not reused as substitutes and are not silently changed.

## 3. Clean-room boundary

The referenced TradingView indicator is protected source. This project may study only behavior visible to an authorized user: plotted labels, timestamps, prices, dashboard values, and their evolution over completed bars. It must not extract, deobfuscate, copy, bypass protection for, or claim identity with protected source code.

The resulting implementation is an independent design. Product naming, code identifiers, documentation, and UI must use `Market Structure` / `市场结构`, never the third-party script or author name. A compatibility claim is limited to measured visible behavior in the accepted calibration corpus.

## 4. Goals and non-goals

### Goals

1. Deterministically label confirmed swing highs and lows as `HH`, `LH`, `EH`, `HL`, `LL`, or `EL`.
2. Keep confirmed facts prefix-immutable and expose repainting only as an explicitly unstable preview.
3. Produce a compact current state for all seven canonical frequencies: `1m/5m/15m/30m/60m/1d/1w`.
4. Show the current chart's confirmed points, one optional candidate point, distance within the last confirmed range, and the recent structure sequence.
5. Preserve DatasetKey, series identity, contract segment, data source, cutoff, and formula/policy provenance on every service boundary.
6. Fail closed on insufficient bars, ambiguous identity, cross-contract comparisons, source mismatch, or unsupported policy.

### Non-goals

- No trading recommendation, order, position sizing, PnL, ranking, promotion, or automatic action.
- No Alert rule/event, replay, backfill, retry, queue, scheduler, DB table, Redis cache, or Runtime worker.
- No mutation of Canonical, Live, Scope, production configuration, or external data.
- No generic strategy adapter or formula DSL.
- No attempt to reproduce the screenshot's volume regime or volatility classification in V1; their visible thresholds are not sufficiently identified.
- No synthetic D1/W1 aggregation from Live observations.
- No fifth public strategy overlay and no replacement of existing Product Workspace panels.

## 5. Domain contract

### 5.1 Input

The kernel accepts a single, already resolved series segment:

```python
Sequence[BarInput]

BarInput(
    bar_end: datetime,
    open: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    is_completed: bool,
)
```

Preconditions are enforced by the caller and checked again by the kernel:

- bars are non-empty, strictly increasing by `bar_end`, and contain no duplicate timestamp;
- OHLC values are finite `Decimal` values and satisfy `low <= open/close <= high`;
- every consumed bar is completed;
- all bars share one DatasetKey/frequency/physical-contract segment;
- at least `2 * span + 1` bars exist, otherwise the result is `unavailable`.

The kernel is pure: no DB, Redis, file, network, clock, logging side effect, or global state.

### 5.2 Formula identity

The fixed formula family is `symmetric_pivot_atr_filter_v1`. Stage A selects only its bounded policy parameters; it does not select an unrelated algorithm family.

For candidate bar `i` and policy span `s`:

```text
pivot_high(i) := high[i] > every high in [i-s, i) and
                 high[i] > every high in (i, i+s]

pivot_low(i)  := low[i]  < every low in [i-s, i) and
                 low[i]  < every low in (i, i+s]
```

Strict comparison intentionally rejects plateaus. A pivot can be confirmed only when bar `i+s` is completed. `pivot_time` is bar `i`; `confirmed_at` is bar `i+s`.

An optional minimum-move filter is expressed as `min_move_atr × ATR(14)` from the most recent confirmed opposite-kind pivot. The ATR value uses data available at `pivot_time`; no later bar may enter it. `min_move_atr=0` disables the filter.

If the same bar satisfies both pivot predicates, it is `ambiguous_outside_bar`: no pivot is emitted for that bar, preview is cleared, and later processing continues without changing previously confirmed facts.

Consecutive confirmed points of the same kind are allowed and never rewrite an earlier confirmed point. The state becomes `transition` until both a comparable high and low exist. This causal rule is preferred over retroactively replacing a confirmed point.

### 5.3 Labels and equality

A high compares with the previous confirmed high; a low compares with the previous confirmed low:

| Kind | Comparison | Label |
|---|---|---|
| high | greater / less / equal | `HH` / `LH` / `EH` |
| low | greater / less / equal | `HL` / `LL` / `EL` |

Equality is exact after the caller normalizes prices to the series tick size. The kernel receives normalized `Decimal` values and never guesses tick size. A first high or low has `label=null` until a same-kind predecessor exists.

### 5.4 Confirmed state

Each confirmed point contains:

```text
id = sha256(formula_version, policy_id, dataset_key, segment_id,
            frequency, kind, pivot_time, confirmed_at, price)
kind, label, pivot_time, confirmed_at, price
formula_version, policy_id
dataset_key, series_kind, symbol, frequency
physical_contract, segment_start_day, source, as_of
```

`id` is a stable dedupe identity, not a database key. `physical_contract` and `segment_start_day` are required for `actual_dominant`; they are nullable only where the DatasetKey genuinely has no physical contract.

The current structure snapshot contains:

- `status`: `ready | insufficient | unavailable`;
- `recent_labels`: last four non-null confirmed labels in event order;
- `latest_high` and `latest_low` plus their previous same-kind point;
- `high_direction`: `up | down | equal | unavailable`;
- `low_direction`: `up | down | equal | unavailable`;
- `active_leg`: `up | down | unresolved` (`up` after the latest confirmed low, `down` after the latest confirmed high);
- `regime`: `bull | bear | transition | unavailable`, where only `HH + HL` is bull and only `LH + LL` is bear;
- `range_position`: clamped `(last_close - latest_low.price) / (latest_high.price - latest_low.price)`, or unavailable for a missing/zero-width range;
- `breakout_state`: `above_high | below_low | inside | unavailable`, computed before clamping;
- `as_of`, identity, formula, policy, and source provenance.

An equality label does not manufacture a trend. Any latest `EH` or `EL`, missing counterpart, or conflicting high/low pair produces `transition`.

### 5.5 Unstable preview

Preview is a separate nullable object, never a confirmed point:

- it uses completed bars only;
- it examines only the unconfirmed tail shorter than `span` right bars;
- expected kind follows `active_leg`; with unresolved leg, only an unambiguous single-kind candidate is shown;
- it must satisfy the left-side pivot predicate and the minimum-move rule;
- its label is suffixed `?` in the UI and `unstable=true` in the schema;
- it may move, change label, or disappear after any new completed bar;
- it is never persisted, emitted as an event, used by Alert, or included in confirmed-history scoring.

Historical rendering places a confirmed label at `pivot_time`, but the tooltip must show `confirmed_at` so the confirmation delay is visible.

## 6. Identity, segmentation, and time seams

### Dataset and contract identity

- `continuous`: calculate within the requested continuous DatasetKey and label it as continuous observation.
- `contract`: calculate within exactly one requested physical contract.
- `actual_dominant`: resolve through `MarketDataService`, partition at every rank1 physical-contract change, reset structure state at the segment boundary, and never compare points across segments.

The response includes the segment that produced each point and snapshot. If the visible chart spans rolls, older segment points may render, but the current state uses only the current segment.

### Frequency and current data

The same accepted policy parameters apply to all seven frequencies. No frequency silently falls back to another.

- Intraday (`1m/5m/15m/30m/60m`): Historical Canonical plus same-frequency completed Live may form current observation through the existing Market seam. Incomplete Live bars are excluded.
- `1d/1w`: read confirmed Canonical only and update only after the existing `canonical_updated` seam. Never aggregate Live bars into day/week bars.
- A row unavailable at one frequency does not suppress ready rows at other frequencies.

Every result carries `source=canonical | completed_live | canonical_plus_completed_live`, `as_of`, and a stale/identity decision. Identity ambiguity or stale resolver state fails closed rather than falling back.

## 7. Stage A — Clean-room calibration

### A1. Observation corpus

Create a versioned, reviewable fixture corpus from user-authorized chart observations and matching OHLC exports. No protected source is collected.

Acceptance corpus minimum:

- all seven canonical frequencies;
- at least two exact-series fixtures per frequency and at least three products overall;
- at least 20 observable confirmed labeled pivots per frequency;
- at least 20 examples of each `HH/LH/HL/LL` overall;
- at least 12 captured preview lifecycles showing candidate move, confirmation, or invalidation;
- exact series/feed/contract and timezone mapping recorded; unmatched feeds are exploratory only and cannot count toward acceptance.

Fixture records contain observation id, capture time, authorized source description, DatasetKey mapping, frequency, timezone, completed OHLC bars, observed point kind/label/time/price, optional dashboard range position, and confidence. Images may support review but are not machine truth without matching structured observations.

### A2. Bounded parameter grid

Evaluate only:

```text
span ∈ {2, 3, 5, 8, 13}
min_move_atr ∈ {0, 0.5, 1.0, 1.5}
atr_length = 14
```

One global `(span, min_move_atr)` pair must serve all seven frequencies. Per-symbol or per-frequency fitting is forbidden in V1.

### A3. Scoring and selection

For each fixture, compare confirmed events by exact kind, label, and pivot bar after tick normalization. The corpus score is:

```text
0.70 × macro event F1
+ 0.20 × active-leg accuracy
+ 0.10 × (1 - mean absolute range-position error)
```

Missing dashboard position omits that fixture from the last component and re-normalizes weights. Preview lifecycles are reported separately because the third-party confirmation rule is not fully observable.

Acceptance requires:

- macro event F1 `>= 0.85` overall and `>= 0.75` on every frequency;
- active-leg accuracy `>= 0.90`;
- range-position MAE `<= 0.08` when at least 20 observations exist;
- `100%` prefix-immutability and causality tests for our implementation;
- no exact-series fixture with an unexplained identity mismatch.

Ties within `0.01` total score choose lower `min_move_atr`, then lower `span`, then lexical policy id. If no candidate passes, Stage A ends as `blocked`; parameters must not be guessed and Stages B–D must not proceed.

### A4. Frozen evidence

The accepted output is:

- `data/research_policies/market_structure_v1.json` — selected parameters, corpus digest, formula version, accepted metrics, and review commit;
- a deterministic calibration report generated from the fixture manifest;
- tests proving the report and digest are reproducible.

Changing formula logic, corpus digest, or selected parameters requires a new policy id and a new Stage A review. Existing result identities remain tied to their original policy.

### Stage A Gate

Proceed only when the corpus minimum, thresholds, deterministic report, secret scan, and independent review all pass. This Gate permits Stage B implementation only.

## 8. Stage B — Pure indicator kernel

Add a dedicated `market_structure_v1` module under the existing indicator kernel. Register it with explicit capabilities:

- `consumer=research_observation` only;
- `causality=confirmed_with_unstable_preview`;
- seven supported frequencies;
- no formal policy, Alert, strategy, or order capability.

The registry loads the frozen policy by explicit id; missing, malformed, unreviewed, or mismatched policies fail closed. Formula code cannot read the policy file directly—the application layer validates the artifact and passes a typed policy into the pure kernel.

Required proof:

- golden fixtures for labels/state/range position;
- prefix invariance: appending bars never changes an earlier confirmed point;
- no use of bars after `confirmed_at`;
- equality, plateau, ambiguous outside bar, duplicate timestamp, insufficient data, and zero-width range cases;
- property-style parameterized tests across all seven frequencies;
- Decimal preservation and deterministic point ids;
- existing indicator, N, SuBing, JDJ, and HTDY tests remain unchanged and pass.

### Stage B Gate

Proceed only when kernel tests, registry/capability tests, type/lint checks, and an independent formula review pass. This Gate permits Stage C internal projection only.

## 9. Stage C — Internal research projection

### Service

Add a source-specific read service that:

1. resolves the exact DatasetKey and requested frequency through `MarketDataService`;
2. applies actual-dominant segmentation before calculation;
3. optionally joins same-frequency completed Live for intraday current observation through the existing resolver;
4. invokes the kernel per segment;
5. returns confirmed history and current snapshot with full identity/provenance;
6. represents insufficient/unavailable explicitly and never cross-frequency/source falls back.

No result is stored in PostgreSQL, Redis, Canonical, or an external artifact root.

### CLI

Expose one read-only internal command:

```text
guiyi research market-structure \
  --series-kind actual_dominant \
  --symbol jm \
  --frequency 15m \
  --since 2026-06-01 \
  --through 2026-08-25 \
  --policy-id market_structure_v1
```

It writes deterministic JSON to stdout and supports an explicit output path only for a user-selected local research artifact. It performs no DB/Redis/Canonical mutation and does not enter Runtime.

The JSON contains request identity, segment summaries, confirmed points, snapshot, preview, formula/policy/corpus digest, input coverage, and unavailable reasons.

### Internal acceptance evidence

Run representative checks for:

- one `continuous`, one `contract`, and one `actual_dominant` query;
- an actual-dominant window crossing a roll;
- all seven frequencies;
- intraday canonical-only versus canonical-plus-completed-live parity at the same cutoff;
- D1/W1 canonical-only enforcement;
- repeated run byte-equivalent JSON after volatile metadata is excluded.

### Stage C Gate

Stage C ends with a reviewable evidence summary, not a promotion claim. Stage D requires a new human decision based on Stage A metrics, Stage B causality evidence, Stage C identity/roll/seam evidence, and measured response cost.

## 10. Stage D — Market observation UI

### API

Add two source-specific, read-only endpoints; do not merge them into existing strategy endpoints:

```text
GET /api/v1/market/research/market-structure/history
GET /api/v1/market/research/market-structure/snapshot
```

`history` accepts exact series identity, one frequency, `since`, `through`, `policy_id`, and bounded `limit/cursor`. It returns confirmed points only, ordered by `(pivot_time, confirmed_at, id)`.

`snapshot` accepts exact series identity and `policy_id`, then returns independent rows for the seven canonical frequencies. Intraday rows may include the one unstable preview; D1/W1 rows remain Canonical-only. Each row carries its own status, source, as-of, segment, policy, and unavailable reason.

Both endpoints reject unsupported policy, identity mismatch, inverted/unbounded windows, limits above the configured cap, and requests that would bypass `MarketDataService`. Initial implementation is on-demand and has no DB/Redis cache.

### Web placement

Keep `mainOverlay` unchanged. Add `marketStructureVisible: boolean` to chart preferences as an independent context-layer toggle.

When enabled:

- the current chart renders confirmed markers for the visible range;
- one unstable marker such as `HH?`/`LL?` and a dashed candidate price line may render separately;
- hover shows pivot time, confirmation time, price, formula/policy, contract segment, source, and unstable warning;
- `ProductCheckSidebar` gets a compact `市场结构` block with seven rows: frequency, low-to-high range position, latest high/low direction, last four labels, active leg, source/as-of/status;
- partial unavailable rows remain visible and explain why;
- changing product, series kind, contract, frequency, or policy invalidates stale requests and clears mismatched markers before repaint.

Markers use stable point ids for pagination dedupe. The UI does not calculate pivots, labels, range position, or regime; it only projects API facts. Existing overlay selection, historical SuBing/JDJ markers, HTDY rendering, and K-line interactions must continue to work when the context layer is on or off.

### Load and performance contract

- K-line loading and interaction do not wait for structure requests.
- History fetch covers the visible chart window plus bounded warm-up, not all available history.
- Snapshot fans out to at most seven bounded service reads with independent timeout/status; one failure cannot fail the full matrix.
- Request keys include complete series identity and policy id; stale responses are discarded.
- Stage C records a baseline and Stage D may proceed only if the agreed local p95 budgets are met without adding cache infrastructure. The initial target is `<= 500 ms` for one history request and `<= 1500 ms` for the seven-row snapshot on the documented development machine; misses block D acceptance and trigger profiling, not silent cache introduction.

### Stage D Gate

Acceptance requires backend contract tests, frontend unit/component tests, route-intercepted browser tests, production Web build, full identity-switch regression, accessibility/empty/error states, no formula duplication in Web, and independent review. It permits only a PR recommendation to `develop`; merge remains a human Gate.

## 11. Error and unavailable taxonomy

Stable machine reasons:

```text
insufficient_bars
identity_mismatch
segment_unresolved
stale_resolver
source_unavailable
unsupported_frequency
unsupported_policy
policy_digest_mismatch
invalid_bar_sequence
ambiguous_current_segment
calibration_evidence_insufficient
calibration_threshold_failed
```

API responses use existing project error conventions. Expected data insufficiency is represented as a typed row/result, not an HTTP 500. Invalid client identity/policy/window is a 4xx. Unexpected internal failures are logged without credentials or raw sensitive payloads and return a bounded 5xx.

## 12. Security, data, and operational constraints

- Validate symbol, contract, frequency, policy id, time window, limit, cursor, and output path before use.
- Never interpolate untrusted values into shell, file, SQL, or network targets.
- Fixtures and reports contain no credentials, cookies, protected script source, account data, or brokerage identifiers.
- No production DB migration, live scope change, Runtime load, notification, release, tag, main merge, or external order is part of A–D.
- Real RQData fetch, Canonical mutation, Runtime action, and notification remain separately gated external operations.
- Documentation may update stable canonical files only when the corresponding stage is actually accepted; `STATUS.md` changes only for real current-state changes.

## 13. Review and change control

Review each stage against this document and the repository canonical sources. Critical or Important findings block the next stage. Formula/policy changes return to Stage A; domain/API contract changes require this Spec to be amended and reviewed before code changes continue.

The final implementation PR must state:

- exact base/head and stage reached;
- policy id, formula version, corpus digest, and evidence paths;
- tests and fresh verification outputs;
- known unavailable cases and performance measurements;
- explicit confirmation that existing overlays/formulas, Alert, Runtime, DB, Redis, Canonical, and order paths were not expanded.

## 14. Acceptance summary

`market_structure_v1` is acceptable only when it is independently derived, causal, versioned, identity-complete, segment-safe, source-explicit, and read-only. Confirmed facts never repaint; preview is visibly unstable. The capability remains internal until calibration, kernel, and research evidence pass, and the Market UI remains a context layer rather than a strategy product.

