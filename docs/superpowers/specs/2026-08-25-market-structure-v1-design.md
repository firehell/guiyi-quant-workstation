# Market Structure V1 Design Spec

**Status:** Proposed — revised after independent review; awaiting re-review  
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

### 5.1 Input and identity

The pure engine accepts an immutable `SeriesContext` and one resolved physical series segment:

```python
SeriesContext(
    request_identity=LogicalSeriesIdentity(
        selector=LogicalSeriesSelector(
            series_kind, symbol, requested_contract,
        ),
        frequency=frequency,
    ),
    physical_dataset_key=DatasetKey(
        kind, symbol, series_or_contract, frequency,
    ),
    segment=SegmentIdentity(
        series_or_contract, segment_start_trading_day,
    ),
    segment_coverage_end_trading_day=date,
    tick_size=Decimal,
)

Sequence[BarInput]

BarInput(
    bar_end: datetime,
    trading_day: date,
    open: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    is_completed: bool,
)
```

`LogicalSeriesSelector` deliberately has no frequency: snapshot accepts one selector and derives seven `LogicalSeriesIdentity(selector, row_frequency)` values; history accepts one complete single-frequency identity.

`actual_dominant` is a logical `SeriesKind`, never a physical DatasetKey. For each actual-dominant segment, `physical_dataset_key.kind=contract`, `series_or_contract` is the exact uppercase contract, `request_identity.selector.series_kind=actual_dominant`, and `segment_start_trading_day` is the true rank1 segment start. For a contract request, `series_or_contract` is the exact contract and segment start is null; for continuous it is canonical `MAIN`, while segment start and physical contract are null.

`segment_id` is the full lowercase SHA-256 of canonical JSON containing the logical selector, physical DatasetKey, `series_or_contract`, and nullable stable `segment_start_trading_day`. Segment/coverage end is never part of segment or fact identity: it is response-level `segment_coverage_end_trading_day` and may advance without changing older ids.

Preconditions are enforced by the caller and checked again by the engine:

- `bar_end` is timezone-aware UTC, strictly increasing, and unique;
- bars are completed and lie inside the context segment;
- OHLC values are finite `Decimal` values and satisfy `low <= open/close <= high`;
- `tick_size > 0`, and every OHLC value is exactly aligned (`value % tick_size == 0`); the engine validates and never rounds;
- every bar lies inside the supplied segment bounds.

Per-bar DatasetKey/frequency consistency is the responsibility of `MarketDataService` and the authoritative segment loader because `CanonicalBar`/`BarInput` do not repeat physical DatasetKey. The engine does not claim to revalidate identity fields absent from the bar envelope.

The engine is pure: no DB, Redis, file, network, clock, logging side effect, or global state.

### 5.2 Closed formula

The fixed formula family is `symmetric_pivot_atr_filter_v1`. Stage A selects only its bounded `span` and `min_move_atr`; it does not select another algorithm family.

For candidate bar `i` and span `s`:

```text
raw_high(i) := high[i] > every high in [i-s, i) and
               high[i] > every high in (i, i+s]

raw_low(i)  := low[i]  < every low in [i-s, i) and
               low[i]  < every low in (i, i+s]
```

Strict comparison rejects plateaus. A raw pivot can be confirmed only when completed bar `i+s` exists. `pivot_time=bars[i].bar_end`; `confirmed_at=bars[i+s].bar_end`.

ATR is a dedicated Decimal implementation and does not reuse a float compatibility variant:

```text
TR[0] = high[0] - low[0]
TR[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
ATR[13] = sum(TR[0:14]) / 14
ATR[i] = (ATR[i-1] * 13 + TR[i]) / 14, for i > 13
```

No intermediate rounding is allowed. Serialization is tick-normalized only at input; calculated Decimal fields use their exact Decimal value.

The move filter is deterministic:

```text
high_move = candidate_high - latest_confirmed_low.price
low_move  = latest_confirmed_high.price - candidate_low
accept when move >= min_move_atr * ATR[i]
```

- `min_move_atr=0` disables ATR and the move filter.
- Before an opposite-kind confirmed pivot exists, the raw pivot is accepted as a state seed.
- When the filter is enabled and an opposite pivot exists but `ATR[i]` is unavailable, the candidate is not emitted and the result records `atr_warmup_insufficient` when no later usable structure exists.
- A negative move fails the filter.

If one bar satisfies both raw predicates, it is `ambiguous_outside_bar`: neither pivot is emitted and no earlier confirmed fact changes. Consecutive confirmed points of the same kind are allowed and never replace an earlier confirmed point.

The minimum bar count for any raw pivot is `2*s+1`. With the ATR filter enabled, the minimum for a filtered pivot is `max(2*s+1, 14+s)`. These are detection minima, not a promise that a ready structure exists; readiness also requires the state prerequisites below.

### 5.3 Labels and state

A high compares with the previous confirmed high; a low compares with the previous confirmed low:

| Kind | Comparison | Label |
|---|---|---|
| high | greater / less / equal | `HH` / `LH` / `EH` |
| low | greater / less / equal | `HL` / `LL` / `EL` |

Equality is exact because tick alignment was validated. A first high or low has `label=null` until a same-kind predecessor exists.

The current structure snapshot contains:

- `status`: `ready | insufficient | unavailable` plus one stable reason;
- `recent_labels`: last four non-null confirmed labels in event order;
- latest and previous same-kind high/low points;
- `high_direction` and `low_direction`: `up | down | equal | unavailable`;
- `active_leg`: `up` after the latest confirmed low, `down` after the latest confirmed high, otherwise `unresolved`; same timestamp or ambiguous ordering is unresolved;
- `regime`: only latest `HH + HL` is `bull`, only latest `LH + LL` is `bear`, equality/missing/conflict is `transition`, and absent prerequisites are `unavailable`;
- `range_position` and `breakout_state` are calculated only when both latest points exist and `latest_low.price < latest_high.price`; otherwise both are unavailable with `invalid_confirmed_range` or `structure_seed_incomplete`;
- for a valid range, `range_position=clamp((last_close-low)/(high-low), 0, 1)` and exactly one breakout state is selected in order `above_high`, `below_low`, `inside`.

Overall `status=ready` requires at least two confirmed highs and two confirmed lows so both latest directional labels exist, and `status_reason=null`. A valid source with fewer state seeds is `status=insufficient, status_reason=structure_seed_incomplete`; authoritative source or identity failure is `status=unavailable` with its stable reason. `range_position` and `breakout_state` each expose nullable `field_reason`; `invalid_confirmed_range` is field-level and does not downgrade an otherwise ready label/regime snapshot.

### 5.4 Confirmed fact identity and provenance

A confirmed fact contains kind, label, price, pivot/confirmation times, formula/policy ids, complete single-frequency logical identity, physical DatasetKey, stable segment identity, and tick size. Its id is the full lowercase SHA-256 of canonical JSON over exactly those fields. It never contains segment/coverage end.

Canonical JSON uses lexicographically sorted keys, no insignificant whitespace, UTF-8, uppercase symbol/contract, lowercase frequency/enum values, ISO dates, UTC datetimes formatted as `YYYY-MM-DDTHH:MM:SS.ffffffZ`, and fixed-point Decimal strings with trailing zeros removed (`-0` becomes `0`). Source and calculation timestamps are excluded from the fact id.

Provenance is response decoration, not part of the immutable fact:

- point provenance records the distinct ordered `fact_dependency_sources` used by strict-left/right predicates, ATR seed/recursion, opposite-pivot state, and the confirmation window through `confirmed_at`;
- response provenance records source mix, `resolved_cutoff`, `calculated_at`, and resolver decision;
- a completed-Live bar later materialized as Canonical may upgrade provenance without changing an identical fact id;
- any OHLC, identity, formula, policy, pivot, label, or confirmation change produces a different fact or a fail-closed mismatch.

### 5.5 Deterministic unstable preview

Preview is a separate nullable object and never a confirmed fact.

At completed-series length `n`, examine candidate indices `j` satisfying `j >= s` and `j+s >= n`; these are the left-confirmed, right-incomplete tail. Apply the left-side strict predicate and the same move filter using `ATR[j]`. A bar satisfying both left predicates is discarded as ambiguous.

Expected kind follows `active_leg`. If the leg is unresolved, a preview is permitted only when candidates exist for exactly one kind. Among multiple high candidates choose greatest price, then earliest `pivot_time`; among multiple low candidates choose lowest price, then earliest `pivot_time`. This winner rule is total and deterministic.

Preview has `confirmed_at=null`, `unstable=true`, and a provisional label compared with the latest confirmed same-kind point. The UI suffixes `?`. It may move, relabel, or disappear after a new completed bar and is never persisted, scored as a confirmed event, sent to Alert, or used by a strategy/order path.

Historical rendering places a confirmed label at `pivot_time`, while the tooltip always shows `confirmed_at`.

## 6. Initialization, segmentation, and time seams

### Window-independent initialization

Calculation never starts at the visible window plus a guessed warm-up. The service resolves the physical coverage start for every segment, computes from that segment start through one `resolved_cutoff`, and only then crops confirmed output to the requested display window.

- continuous starts at the continuous DatasetKey's available Canonical coverage start;
- contract starts at that contract DatasetKey's available Canonical coverage start;
- actual-dominant starts independently at each true rank1 segment start and resets state at every segment boundary.

If authoritative coverage or identity cannot be resolved, return `status=unavailable` with `source_unavailable` or `segment_unresolved`; do not create partial labels. If complete valid coverage has too few bars for detection, use `insufficient_bars` or `atr_warmup_insufficient`. If full calculation has fewer than two confirmed highs or lows, use `structure_seed_incomplete`. The initial design deliberately prefers full deterministic recomputation over cache/checkpoint state. Stage C measures the real cost; a cache or checkpoint requires a reviewed Spec amendment.

### Canonical segment seam

Actual-dominant calculation must reuse `ActualDominantResearchSegmentLoader` or a future canonical resolver that preserves all of its invariants: true containing rank1 segment restoration, coverage completeness, no overlap, probe/full identity agreement, and cross-frequency segment agreement. Ordinary query-returned W1 slices are not accepted as complete segment identity.

| Request kind | Logical identity | Physical DatasetKey | Live rule |
|---|---|---|---|
| `continuous` | continuous | continuous / `MAIN` | Canonical-only in V1 |
| `contract` | requested contract | exact contract | completed Live only when existing Market seam proves exact contract and trading-day match |
| `actual_dominant` | actual_dominant | exact contract per rank1 segment | completed Live only when current rank1 contract, trading day, and unique current segment all match |

Incomplete Live bars are always excluded. A roll, stale resolver, multiple candidate segment, contract mismatch, or Live trading day outside the current segment fails closed. Older segment points may render, but current snapshot state comes only from the current segment.

### Frequency and cutoff

The same accepted policy parameters apply to all seven frequencies. No frequency falls back to another.

- Intraday frequencies may use Canonical plus same-frequency completed Live only under the table above.
- D1/W1 use confirmed Canonical only and advance only through the existing `canonical_updated` seam; Live is never aggregated to day/week.
- One unavailable row does not suppress other frequency rows.

Public `since/through` are exchange trading dates, inclusive. The service uses `TradingSession`/Market time authorities to translate them to the canonical UTC `(start, end]` query contract. Snapshot resolution captures one timezone-aware UTC `observation_at` at request entry, or accepts an explicit RFC3339 UTC instant; naive or invalid future instants fail closed. All seven rows resolve their eligible cutoff at or before that one instant and return `resolved_cutoff`.

## 7. Stage A — Clean-room evaluator and calibration

### A0. Shared formula evaluator

Stage A is authorized to implement one pure, unregistered formula module under the indicator kernel namespace plus research-only tests and calibration tooling. It has no registry entry, application service, CLI, API, Web, DB, Redis, or Runtime consumer.

The evaluator implements Sections 5–6 exactly and is the sole formula implementation used by the grid. Stage B must promote this same module by adding typed policy loading and registry/capability wiring; copying or rewriting the formula is forbidden. The SHA-256 of the exact LF-normalized UTF-8 formula module and its exact evaluator commit are frozen with the calibration result. Any later formula-byte change returns to Stage A.

### A1. Observation corpus and holdout

Create a versioned fixture corpus from user-authorized visible observations and matching OHLC exports. No protected source is collected.

Acceptance corpus minimum:

- all seven canonical frequencies, at least two exact-series fixtures per frequency, and at least three products overall;
- at least 30 confirmed labeled pivots per frequency and at least 20 of each `HH/LH/HL/LL` overall;
- at least five label lifecycles per frequency with `first_seen_at` captured;
- at least 12 preview lifecycles, recorded as exploratory evidence only;
- exact feed/series/contract, timezone, tick size, and logical-to-physical identity mapping.

Each record has `evidence_tier=acceptance | exploratory`; only exact-series acceptance records enter metrics and there is no confidence weighting. Images support review but are not machine truth without matching structured observations.

Before running the grid, the manifest freezes non-overlapping calibration and holdout ids. Holdout contains at least 20% of accepted events, at least eight events per frequency, and every label class. Calibration contains at least three and holdout at least two `first_seen_at` lifecycles per frequency. Split ids and the manifest digest are committed before scores are generated; changing the split invalidates all results.

### A2. Bounded parameter grid

Evaluate only:

```text
span ∈ {2, 3, 5, 8, 13}
min_move_atr ∈ {0, 0.5, 1.0, 1.5}
atr_length = 14
atr_policy = decimal_wilder_sma_seed_v1
```

Candidate id is `s{span}-a{factor_token}`, where factor tokens are exactly `0`, `0p5`, `1`, and `1p5`. One global pair serves every symbol and frequency; per-symbol or per-frequency fitting is forbidden.

### A3. Mechanical scoring and selection

Expected and predicted events match one-to-one on `(fixture_id, kind, label, pivot_time, price)` after validated tick alignment. An unmatched expected event is FN and an unmatched prediction is FP. Each `HH/LH/HL/LL` class uses `2TP/(2TP+FP+FN)`. A class with zero expected and predicted support is excluded from that frequency/split mean; a prediction-only class is included with F1 zero. An empty supported-class set is invalid evidence. Macro event F1 is the arithmetic mean of included class F1 values; equality labels are reported separately.

Active-leg observations are keyed by `(fixture_id, observed_at)` on a completed bar and compare the model state at that exact cutoff; accuracy denominator is all acceptance observations with a non-null expected leg. Range-position MAE uses acceptance observations with an explicit dashboard value. There is no imputation.

When at least 20 accepted range observations exist, score is:

```text
0.70 * macro_event_f1 + 0.20 * active_leg_accuracy + 0.10 * (1 - range_mae)
```

Otherwise range is not scored and weights become `7/9` and `2/9`; the range threshold is not applicable.

Run the full grid on calibration only. Candidates must meet the thresholds below on calibration. Select the highest score; all candidates within `0.01` of that highest score form the tie set, then choose lower `min_move_atr`, lower `span`, and lexical candidate id. Evaluate exactly that one frozen winner on holdout. The holdout is never used to reselect parameters.

Both calibration and holdout must satisfy:

- macro event F1 `>= 0.85` overall and `>= 0.75` on every frequency;
- active-leg accuracy `>= 0.90`;
- range-position MAE `<= 0.08` when applicable;
- first-seen/confirmation delay within one completed bar on at least `85%` of captured lifecycles;
- no unexplained exact-series identity mismatch.

The evaluator must also pass `100%` prefix-immutability, confirmation-cutoff, and determinism tests. Preview lifecycles are exploratory: V1 makes no third-party preview-compatibility claim.

### A4. Frozen policy and approval manifest

The immutable policy id is:

```text
market_structure_v1-s{span}-a{factor_token}-c{corpus_digest_12}-f{formula_digest_12}
```

`corpus_digest` is full lowercase SHA-256 over LF-normalized UTF-8 canonical JSON for the manifest plus all referenced structured acceptance fixtures, ordered by fixture id; screenshots and exploratory evidence are excluded. `formula_digest` is defined in A0. `market_structure_v1` is only a friendly alias resolved through a checked-in approval manifest to one immutable id. The accepted files are:

- immutable policy JSON with exact parameters, formula/evaluator commit, corpus/split/formula digests, calibration and holdout metrics;
- deterministic calibration report;
- approval manifest containing the exact immutable policy SHA-256, digests, evaluator commit, independent review record path, reviewer identity, and review timestamp.

Tests recompute every digest and reject self-reported mismatch or an alias without an exact approved target. Changing formula bytes, corpus/split digest, or parameters creates a new immutable id and repeats Stage A.

### Stage A Gate

Proceed only when A0 code, corpus/split minimum, calibration and holdout thresholds, deterministic report/digests, causality tests, secret scan, and independent review all pass. This Gate permits Stage B registration of the already reviewed formula only.

## 8. Stage B — Indicator kernel promotion

Promote the unchanged Stage A formula module through typed models and the existing registry. Initial registration is `compatibility_validated`, `display_type=marker`, `output_schema=signal_state`, `web_capable=false`, and existing `live_capable=false` means no Runtime/formal live consumer. Add an explicit market-structure capability guard; do not create a generic policy DSL.

| Capability | Stage B/C | Stage D after human Gate |
|---|---:|---:|
| historical Canonical input | true | true |
| completed-Live observation input under Section 6 seam | true | true |
| internal research projection | true | true |
| Web/API projection | false | true |
| Runtime live consumer | false | false |
| backtest / strategy / Alert / notification / order | false | false |

Stage D must explicitly update the approved capability manifest/guard and registry `web_capable` flag in the reviewed Web change; code may not bypass a false guard.

The application layer validates the immutable policy and approval manifest, then passes a typed policy and `SeriesContext` into the pure engine. Formula code never reads files. Missing, malformed, unapproved, aliased-to-unknown, or digest-mismatched policy fails closed.

Required proof includes golden state fixtures; appended-prefix invariance; no dependency after `confirmed_at`; Decimal ATR/move behavior; equality/plateau/ambiguous/same-kind cases; tick and timestamp validation; deterministic preview winner; range invalidity; all status/reason mappings; canonical id serialization; all seven frequencies; and unchanged existing indicator/N/SuBing/JDJ/HTDY tests.

### Stage B Gate

Proceed only when the frozen formula digest is unchanged, kernel and capability tests pass, type/lint checks pass, and an independent formula review approves the exact head. This Gate permits Stage C internal projection only.

## 9. Stage C — Internal research projection

### Service and initialization

Add a source-specific read service that:

1. resolves logical request identity and physical DatasetKeys only through `MarketDataService`;
2. reuses the canonical actual-dominant segment loader/resolver described in Section 6;
3. expands calculation to each physical coverage/segment start, invokes the kernel, then crops output;
4. joins completed Live only under the exact contract/trading-day/segment rules;
5. returns immutable facts plus separate provenance, cutoff, coverage, policy, and status;
6. never cross-frequency/source falls back and never stores results.

### CLI

Expose one stdout-only command:

```text
guiyi research market-structure \
  --series-kind actual_dominant \
  --symbol jm \
  --frequency 15m \
  --since 2026-06-01 \
  --through 2026-08-25 \
  --observation-at 2026-08-25T08:00:00Z \
  --policy-id market_structure_v1
```

It emits deterministic JSON to stdout only. There is no output-path option, side effect, Runtime entry, or external mutation. JSON includes logical and physical identities, true segment summaries, confirmed facts, snapshot, preview, formula/policy/corpus digests, coverage, `resolved_cutoff`, provenance, and typed unavailable reasons. Byte-equivalence tests exclude only `calculated_at`.

### Internal acceptance and benchmark evidence

Evidence covers continuous, contract, and actual-dominant; a roll window; all seven frequencies; exact Live match and Live mismatch; W1 true segment restoration; canonical-only D1/W1; window-independent labels; and repeated deterministic output. Canonical-versus-Canonical-plus-completed-Live parity means immutable fact ids and derived state are identical through their common Canonical cutoff; Live may add only a strict suffix after that cutoff. Comparison excludes permitted provenance differences but includes identity, formula, policy, labels, range, regime, and state.

Benchmark evidence freezes commit, OS/architecture/CPU, Python version, policy/corpus/data digests, exact request fixtures and cutoffs, input/output bar counts, and cold first-run timing. For the Gate, run three unmeasured process warm-ups followed by 30 measured serial runs and calculate nearest-rank p95. Fixed targets are `history <= 500 ms` and seven-row `snapshot <= 1500 ms` on the documented development machine. A miss blocks Stage D and triggers profiling; it does not authorize cache/checkpoint infrastructure.

### Stage C Gate

Stage C ends with independently reviewed evidence, not a promotion claim. Stage D requires a new human decision based on Stage A holdout metrics, Stage B causality/digest evidence, Stage C identity/roll/seam evidence, and the frozen benchmark.

## 10. Stage D — Market observation UI

### API and time contract

Add two source-specific read-only endpoints:

```text
GET /api/v1/market/research/market-structure/history
GET /api/v1/market/research/market-structure/snapshot
```

`history` accepts exact logical identity, one frequency, inclusive exchange trading dates `since/through`, immutable-or-approved-alias policy id, bounded `limit/cursor`, and optional RFC3339 UTC `observation_at`. It calculates from authoritative segment/coverage start, crops to the display dates, and returns confirmed facts ordered by `(pivot_time, confirmed_at, id)`.

`snapshot` accepts one exact `LogicalSeriesSelector`, policy id, and optional RFC3339 UTC `observation_at`. Omission captures one server UTC instant before any frequency work. Seven independent rows construct complete frequency-bearing logical identities and derive eligible cutoffs from that instant. Intraday rows may include one unstable preview; D1/W1 are Canonical-only.

Invalid identity/policy/window/cursor/time is 4xx. Expected insufficiency is a typed row/result. Source/segment/resolver conflicts fail closed. The endpoints remain on-demand, use `MarketDataService`, and add no storage or cache.

### Web placement and preference migration

Keep `ResearchOverlayId` and `mainOverlay` unchanged. Bump the existing main-chart preference schema from v3 to v4, add `marketStructureVisible: boolean` with default `false`, and implement v3→v4 plus corrupt/unknown-version fail-safe migration without losing overlay/EMA settings.

When enabled:

- the current chart renders confirmed markers for the visible range after server-side full-context calculation;
- one unstable `HH?`/`LL?` marker and dashed candidate price line render separately;
- hover shows pivot and confirmation time, price, formula/policy, physical contract segment, provenance, and unstable warning;
- `ProductCheckSidebar` gets a compact seven-row `市场结构` block with range position, high/low direction, four labels, active leg, source/cutoff/status/reason;
- partial insufficient/unavailable rows remain visible;
- any product, logical series, contract, frequency, policy, or observation identity change cancels/discards stale responses and clears mismatched markers first.

Stable fact ids drive pagination dedupe. Web calculates no formula, label, regime, range, source, or cutoff. Existing overlays, SuBing/JDJ historical markers, HTDY, preferences, and K-line interactions work unchanged with the context layer on or off.

### Load and performance contract

K-line rendering never waits for structure. History requests contain the display window, but the server performs the Section 6 full-context initialization before crop. Snapshot executes at most seven bounded reads with independent row status; one row cannot fail the matrix. History request keys include full logical identity; snapshot keys include selector plus all derived row identities. Both include policy id and observation instant, and stale responses are discarded.

Stage D uses the exact Stage C benchmark schema and fixed targets. A performance miss blocks acceptance; adding persistence/cache/checkpoints requires a new reviewed design.

### Stage D Gate

Acceptance requires backend contract tests, frontend unit/component tests, route-intercepted browser tests, production Web build, v3→v4 preference migration, identity-switch regression, accessibility/empty/error states, no Web formula duplication, and independent review. It permits only a PR recommendation to `develop`; merge remains a human Gate.

## 11. Error and unavailable taxonomy

Stable machine reasons:

```text
insufficient_bars
atr_warmup_insufficient
structure_seed_incomplete
invalid_confirmed_range
identity_mismatch
segment_unresolved
stale_resolver
source_unavailable
tick_size_unavailable
tick_alignment_invalid
unsupported_frequency
unsupported_policy
policy_digest_mismatch
invalid_bar_sequence
ambiguous_current_segment
invalid_observation_at
calibration_evidence_insufficient
calibration_threshold_failed
```

The mapping is mutually exclusive:

| Condition | Status | Reason |
|---|---|---|
| authoritative coverage unavailable | unavailable | `source_unavailable` |
| logical/physical segment unresolved or conflicting | unavailable | `segment_unresolved` or `ambiguous_current_segment` |
| complete valid coverage below raw detection minimum | insufficient | `insufficient_bars` |
| ATR-enabled candidate lacks required ATR warm-up | insufficient | `atr_warmup_insufficient` |
| full valid calculation lacks two highs or two lows | insufficient | `structure_seed_incomplete` |
| complete valid structure | ready | null |

Tick, policy, invalid-bar, and time failures are unavailable when discovered during row calculation. `invalid_confirmed_range` is only `range_position.field_reason` / `breakout_state.field_reason`. Invalid client identity/policy/window/time is a 4xx before calculation. Expected insufficiency is never HTTP 500. Unexpected internal failures are logged without credentials or raw sensitive payloads and return a bounded 5xx.

## 12. Security, data, and operational constraints

- Validate symbol, contract, frequency, policy id, observation instant, time window, limit, and cursor before use.
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
