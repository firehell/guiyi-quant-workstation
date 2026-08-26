# SuBing Strategy V1 Design Spec

**Status:** Reviewed — ready for Stage 1 implementation<br>
**Date:** 2026-08-26  
**Implementation target branch:** `research/subing-strategy-v1`  
**Base:** `develop@b2cf5f1b57d59c770ab664d46c64267c8fc70b54`  
**Delivery lane:** Lane 3 / Plan-only / independent review required / no implementation in this change

## 1. Decision

Build `subing_strategy_v1` as the single product-level strategy projection above the existing SuBing Factor, Signal, Calibration, Lifecycle, Daily Context, and Alert capabilities.

The user-facing model is deliberately simple:

```text
苏冰策略 V1

空仓
→ 建多 / 建空
→ 持仓
→ 清多 / 清空
→ 下一轮机会
```

The internal implementation remains modular. This design does **not** collapse all SuBing logic into a mega file, mega DTO, or generic strategy framework. Existing Factor, Signal, Lifecycle, structure, Daily Watch, and Alert responsibilities remain independently testable and are composed behind one `SuBingStrategy` boundary.

V1 has exactly one public strategy decision frequency: `15m`. It supports only `actual_dominant`, uses D1 + 60m Daily Context as a direction gate, accepts all existing approved Lifecycle `ENTRY_CONFIRMED` sources as entry confirmation, and exits the complete virtual position when any one of four exit families first becomes true.

V1 is research-only. It produces deterministic reference actions and trade episodes for chart observation. It does not connect to an account, create an order, manage margin, size a real position, or claim realized PnL. `auto_order=false` remains unchanged.

Implementation is split into two separately gated stages:

| Stage | Outcome | External side effects |
|---|---|---|
| Stage 1 — Historical Strategy Projection | Deterministic 15m open/close actions, complete episodes, chart markers, compact episode list | None beyond expendable local cache files |
| Stage 2 — Completed-Live Runtime + Alert | Incremental active60 evaluation, `subing_strategy_v1` Formal Events, one PushPlus attempt for scoped products | Production migration, Rule/Scope, Runtime promotion, and real notification each require their own explicit Gate |

Approval of this document authorizes neither implementation nor any Stage 2 mutation. Stage 1 must be implemented, reviewed, and accepted before a Stage 2 implementation plan is approved.

## 2. Current canonical compatibility

This design is constrained by the active repository facts at the base commit:

- The product is a local, single-user futures research workstation.
- Web exposes only Market; the four public chart overlays remain `none | subing | jdj_strategy | htdy`.
- SuBing currently projects three independent facts: Daily Context, Current Signal State, and Formal Event.
- Daily Watch V2 is the accepted D1/60m direction-context capability.
- The current SuBing Alert Rule is `subing_entry_signal_v1`; it remains active until Stage 2 explicitly introduces a new Rule.
- Historical bars are consumed only through `MarketDataService`; `actual_dominant` is a logical rank1 stitched view over physical contract segments.
- RQAlpha and Execution Review are retired and must not be restored by this work.
- The only current strategy-style historical product is the source-specific JDJ reference replay. It is a useful orchestration pattern, not a generic adapter to extend.

`subing_strategy_v1` therefore remains the existing `subing` overlay. It is not a fifth overlay and does not create a generic strategy registry, backtest worker, queue, account model, or trading domain.

## 3. Goals and non-goals

### 3.1 Goals

1. Present one understandable SuBing strategy surface instead of exposing Factor/Signal/Lifecycle assembly to the user.
2. Deterministically transform existing SuBing research facts into a single virtual position state: `flat | long | short`.
3. Produce only four public action kinds: `open_long | open_short | close_long | close_short`.
4. Pair actions into immutable reference episodes with entry, exit, duration, reasons, and direction-adjusted reference price change.
5. Use one causal engine for historical replay and future completed-Live evaluation.
6. Preserve exact logical/physical data identity, contract segment, policy versions, cutoff, and opportunity identity.
7. Keep chart markers attached to K-line business time across pan, zoom, resize, identity changes, and left-side pagination.
8. Fail closed on missing identity, incomplete authoritative data, stale context, future companion data, cross-segment state, or unsupported frequency.

### 3.2 Non-goals

- No automatic or unattended trading.
- No account, order, commission, slippage, margin, leverage, contract-value PnL, capital curve, or portfolio allocation.
- No add, reduce, pyramid, partial exit, reverse-on-signal, or same-bar re-entry.
- No generic backtest engine, strategy adapter, formula DSL, scheduler, queue, or strategy database.
- No parameter optimizer, AI-selected entry/exit rule, promotion, ranking, or profitability claim.
- No public 5m strategy mode; 5m remains an internal Lifecycle input only.
- No true price-versus-MACD pivot divergence algorithm in V1.
- No historical reconstruction of all internal Lifecycle markers; the advanced process toggle exposes only the existing current Lifecycle projection.
- No restoration of RQAlpha or Execution Review.

## 4. Product architecture

```text
RQData -> Canonical Parquet -> MarketDataService
                                  |
                                  +-> Daily Watch V2 direction context
                                  |      D1 + 60m
                                  |
                                  +-> SuBing Factor / Formal Signal
                                  |      5m + 15m
                                  |
                                  +-> SuBing Lifecycle V2
                                         ENTRY_CONFIRMED / risk / closed
                                                   |
                                                   v
                                          SuBingStrategy V1
                                  flat / long / short + pending action
                                                   |
                         +-------------------------+-------------------------+
                         |                                                   |
                  Historical Projection                              Stage 2 Live
             Actions + Episodes + Markers                       Formal Event + Alert
```

The upper product layer consumes `SuBingStrategyResult`. It does not independently evaluate EMA, MACD, volume, Pivot, confirmation-source, or multi-timeframe conditions.

The implementation boundary must answer three questions without requiring callers to inspect internals:

- `replay(...)`: what strategy actions and episodes existed in a causal historical range?
- `current(...)`: what is the current virtual strategy state at the latest completed 15m boundary?
- `step(...)`: after one new completed input boundary, did one strategy decision or effective action occur?

Stage 1 requires `replay`. Stage 2 may add `current` and incremental orchestration, but all three must share the same pure reducer and policy.

## 5. Versioned strategy policy

Add one exact JSON policy artifact:

```text
data/research_policies/subing_strategy_v1.json
```

The loader must compare the complete payload against an exact expected contract and fail closed on missing, extra, changed, or malformed fields. This is not a generic DSL. It is a frozen configuration envelope for explicit V1 code.

The fixed semantic payload is:

```json
{
  "schema_version": 1,
  "strategy_id": "subing_strategy_v1",
  "formula_version": "subing_strategy_15m_v1",
  "research_only": true,
  "series_kind": "actual_dominant",
  "decision_frequency": "15m",
  "direction_context": {
    "projection_version": "subing_daily_watch_v2",
    "formula_version": "subing_ema21_rank1_stitched_raw_v2",
    "history_mode": "rank1_stitched_raw",
    "require_d1_h1_alignment": true,
    "allow_context_late_retroactive_entry": false,
    "context_change_exits_position": false
  },
  "entry": {
    "lifecycle_policy_id": "subing_lifecycle_v2_research_v1",
    "allowed_confirmation_sources": [
      "formal_v1",
      "momentum_hold",
      "pivot_break_hold",
      "pivot_retest_rebreak"
    ],
    "window_projection": "first_confirmation_after_previous_15m_through_current_15m",
    "cancel_when_window_ends_exit_risk_or_closed": true,
    "one_entry_per_opportunity_key": true
  },
  "execution": {
    "decision_basis": "completed_15m_close",
    "effective_fill_basis": "next_existing_same_segment_15m_open",
    "marker_anchor": "effective_bar_end",
    "allow_session_gap": true,
    "allow_overnight": true,
    "allow_reverse": false,
    "allow_same_effective_bar_reentry": false
  },
  "exit": {
    "logic": "any",
    "ema21": "close_beyond_ema21",
    "previous_bar": "close_beyond_previous_15m_extreme",
    "structure": "close_beyond_bound_lifecycle_pivot_when_available",
    "macd": "high_dead_cross_for_long_low_golden_cross_for_short",
    "preserve_all_same_bar_reason_codes": true
  },
  "segment": {
    "carry_position_across_segment": false,
    "terminal_position_fill_basis": "last_15m_close",
    "terminal_reason": "CONTRACT_SEGMENT_END"
  }
}
```

The implementation plan may choose exact Python class and field names, but it must not change these semantics without a reviewed amendment to this spec.

## 6. Data identity and authoritative inputs

### 6.1 Public request identity

Stage 1 accepts only:

```text
series_kind = actual_dominant
frequency   = 15m
symbol      = one active product
since       = date
through     = date
```

Every other series kind or frequency returns `422 INVALID_SUBING_STRATEGY_REQUEST`.

`actual_dominant` means the historical rank1 contract valid on each trading day. It never means projecting today's current contract backward through time. The existing authoritative actual-dominant segment loader must resolve physical contract segments and coverage; consumers must not glob files, infer rank1, or concatenate contracts themselves.

### 6.2 Required internal frequencies

Although the public strategy frequency is only 15m, the source-specific engine may load:

- 5m and 15m for the existing SuBing Factor/Signal/Lifecycle calculation;
- D1 and 60m stitched raw rank1 bars for Daily Watch V2 direction context.

The public response still identifies `frequency=15m`. No 5m action or 5m strategy Marker is created.

### 6.3 Segment isolation

Each physical rank1 contract segment is replayed independently:

```text
segment start
→ clean strategy state
→ segment-local Factor/Lifecycle/Strategy calculation
→ terminal close if a position remains
→ next segment starts flat
```

No Factor warm-up, opportunity key, pending action, virtual position, bound Pivot, or episode crosses a physical contract boundary.

### 6.4 Causality

All inputs used for a decision must be available no later than that decision's completed 15m `bar_end`.

- A Lifecycle confirmation with `confirmed_at > decision_bar.bar_end` is future data and invalid.
- A companion Factor later than the primary cutoff is invalid.
- A target trading day's direction context must come from the accepted Daily Watch V2 source-day logic, never from D1 or 60m data that completed later in the target day.
- A next-bar open is used only after the decision has already been frozen.

The engine must pass prefix-invariance tests: appending later bars cannot change an earlier action, episode identity, decision time, fill price, or reason set.

## 7. Direction context: D1 + 60m

### 7.1 Accepted context source

For target trading day `T`, the strategy uses the Daily Watch V2 classification prepared from its authoritative previous source trading day `S`:

```text
D1 long + 60m long   -> LONG_ONLY
D1 short + 60m short -> SHORT_ONLY
anything else        -> NO_NEW_ENTRY
```

Stage 2 consumes the immutable current Daily Watch V2 artifact targeted at `T`. If that artifact is missing, stale for another target day, or unavailable for the symbol, the symbol cannot open a new position.

Stage 1 reconstructs the same context causally by reusing the Daily Watch V2 pure classification and stitched raw rank1 history contract. It must not read today's current artifact as a substitute for historical days and must not invent a second direction formula.

### 7.2 Unavailable context

Context unavailability is per symbol and per target trading day:

- while flat: do not open a position on that day;
- while already holding: continue evaluating the four 15m exit families;
- other symbols continue normally;
- a fundamental source/identity failure for the requested segment still fails the request with a typed `409`.

The response records unavailable context days and reason codes. It does not silently classify them as neutral.

### 7.3 Context changes after entry

A later neutral or opposite Daily Context:

- blocks new entry;
- does not close an existing position;
- does not add a fifth exit rule;
- does not retroactively approve an old Lifecycle confirmation.

If an opportunity was confirmed while context was not aligned and context becomes aligned later, that old opportunity remains consumed as non-entered. A new `opportunity_key` and a new confirmation are required.

## 8. Entry projection onto the 15m clock

### 8.1 Allowed confirmation sources

All existing Lifecycle sources are accepted behind one entry boundary:

```text
formal_v1
momentum_hold
pivot_break_hold
pivot_retest_rebreak
```

Callers see only `open_long` or `open_short`. The confirmation source remains explanatory provenance in the Action and Tooltip.

### 8.2 Confirmation window

For consecutive completed 15m boundaries `B_prev` and `B_now`, inspect Lifecycle transitions satisfying:

```text
B_prev < confirmed_at <= B_now
```

Use the earliest `ENTRY_CONFIRMED` transition for each `opportunity_key`. If multiple observations of the same key occur in one window, they do not create multiple decisions.

At `B_now`, entry is permitted only when all conditions hold:

1. external strategy state is `flat` and no open Action is already pending;
2. the confirmation direction matches the target trading day's `LONG_ONLY` or `SHORT_ONLY` context;
3. the confirmation source is one of the four approved sources;
4. the opportunity belongs to the same symbol, contract, and segment;
5. the opportunity has not previously been used for an entry;
6. by the end of the window the opportunity is not `exit_risk` or `closed`;
7. the 15m decision Bar and required source data are authoritative and completed.

A confirmation later rejected by context is not held for future entry. A confirmation that enters `exit_risk` or `closed` before `B_now` is canceled.

### 8.3 Structure reference at entry

If the accepted Lifecycle snapshot has a valid `bound_reference_pivot`, freeze it into the Episode:

```text
long  -> bound low Pivot
short -> bound high Pivot
```

If no valid bound Pivot exists, entry is still allowed. The Episode records `structure_exit_available=false`, and only the other three exit families are evaluable for that Episode. The strategy must not search for a hidden fallback Pivot or use N Structure as an implicit substitute.

### 8.4 One opportunity, at most one entry

An `opportunity_key` can create at most one Episode. Closing the position while the old Lifecycle remains in `continuation` does not permit re-entry from the same key. A new opportunity key is mandatory.

Same-direction confirmations while holding are ignored. Opposite-direction confirmations while holding neither reverse nor close the position.

## 9. Strategy state machine and next-bar action semantics

### 9.1 Public state

The public position state is:

```text
flat | long | short
```

### 9.2 Internal pending state

Because decisions use a completed close and reference fills use the next Bar open, the reducer also owns one nullable pending action:

```text
pending_open_long
pending_open_short
pending_close_long
pending_close_short
```

Pending state is internal implementation detail, not a fourth public position state.

### 9.3 Decision and effective Action

At completed 15m Bar `B`:

```text
decision_at = B.bar_end
```

If a decision is created, it is applied at the next actual 15m Bar `N` in the same physical segment:

```text
effective_bar_end = N.bar_end
reference_price   = N.open
fill_basis         = next_bar_open
```

The chart Marker is anchored to `effective_bar_end`, while the Tooltip shows both `decision_at` and `effective_bar_end`.

Crossing a lunch break, night-session break, or overnight gap is allowed when `N` remains in the same physical contract segment. There is no daily forced close.

If no valid next same-segment 15m Bar exists, the pending Action is canceled with `NEXT_BAR_UNAVAILABLE`; it never falls back to the decision Bar close.

### 9.4 Re-entry timing

A close effective on Bar `N` cannot be followed by another open effective on the same Bar. The earliest new decision is evaluated after the next completed 15m boundary, and the earliest new effective open occurs on a later Bar.

## 10. Exit rules

While holding, evaluate all available exit families at every completed 15m decision Bar. The logical relation is `OR`: the first Bar with one or more true exit conditions schedules one complete close.

### 10.1 EMA21 exit

```text
long  -> current close < current EMA21
short -> current close > current EMA21
```

This is a state test, not a requirement to observe the first crossing transition.

Reason codes:

```text
EMA21_BREACH_LONG
EMA21_BREACH_SHORT
```

### 10.2 Previous 15m Bar extreme exit

```text
long  -> current close < previous completed 15m low
short -> current close > previous completed 15m high
```

Intrabar low/high touch does not exit in V1.

Reason codes:

```text
PREVIOUS_BAR_LOW_BREACH
PREVIOUS_BAR_HIGH_BREACH
```

### 10.3 Bound structure exit

When the Episode has a valid bound Lifecycle Pivot:

```text
long  -> current close < bound low Pivot price
short -> current close > bound high Pivot price
```

If the Episode has no bound Pivot, this family remains explicitly unavailable rather than silently passing or substituting another structure formula.

Reason codes:

```text
BOUND_LOW_PIVOT_BREACH
BOUND_HIGH_PIVOT_BREACH
```

### 10.4 MACD high/low reverse-cross exit

V1 does not implement true Pivot divergence. The user-facing phrase “MACD 背离” is frozen to the document-supported high/low reverse-cross rule:

```text
long:
  previous DIF >= previous DEA
  current DIF < current DEA
  cross_level > 0
  -> high dead cross

short:
  previous DIF <= previous DEA
  current DIF > current DEA
  cross_level < 0
  -> low golden cross
```

There is no near-zero tolerance or additional bps threshold in V1.

Reason codes:

```text
MACD_HIGH_DEAD_CROSS
MACD_LOW_GOLDEN_CROSS
```

### 10.5 Multiple reasons on one Bar

One Bar can create at most one close Action. The Action preserves every true reason code in fixed policy order:

```text
EMA21
previous Bar
bound structure
MACD
segment boundary
```

This makes the primary display simple while retaining complete explanation.

### 10.6 Non-exit observations

The following do not close a V1 position:

- opposite entry confirmation;
- same-direction re-confirmation;
- Daily Context becoming neutral or opposite;
- Lifecycle `exit_risk` by itself;
- current unrealized reference loss;
- elapsed time alone.

They may remain internal research facts, but they are not hidden fifth exits.

## 11. Segment and terminal behavior

### 11.1 Position at contract segment end

A position cannot cross a rank1 physical contract boundary. If it remains open at the final completed 15m Bar of the old segment, create one effective terminal close:

```text
decision_at         = terminal_bar.bar_end
effective_bar_end   = terminal_bar.bar_end
reference_price     = terminal_bar.close
fill_basis          = segment_terminal_close
reason              = CONTRACT_SEGMENT_END
```

If one or more ordinary exit conditions are also true on the terminal Bar, preserve those reason codes together with `CONTRACT_SEGMENT_END`.

### 11.2 Pending action at segment end

- pending open without a next same-segment Bar is canceled;
- an existing position is terminally closed at the old segment close;
- the new segment starts flat with no inherited opportunity, Pivot, or pending Action.

The terminal fill is a data-identity boundary projection, not a fifth discretionary trading rule.

## 12. Action and Episode contracts

### 12.1 Strategy Action

A Strategy Action contains at least:

```python
SubingStrategyAction(
    action_id: str,
    strategy_id: str,
    formula_version: str,
    kind: open_long | open_short | close_long | close_short,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    opportunity_key: str,
    decision_at: datetime,
    effective_bar_end: datetime,
    reference_price: Decimal,
    fill_basis: next_bar_open | segment_terminal_close,
    confirmation_source: str | None,
    reason_codes: tuple[str, ...],
    direction_context_source_day: date | None,
    direction_context_target_day: date | None,
    bound_reference_pivot: Pivot | None,
)
```

Open Actions carry the entry confirmation source and optional bound Pivot. Close Actions carry every same-Bar exit reason and reference the Episode entry.

### 12.2 Episode

A complete Episode contains:

```python
SubingStrategyEpisode(
    episode_id: str,
    entry_action: SubingStrategyAction,
    exit_action: SubingStrategyAction | None,
    state: open | closed,
    holding_bar_count: int,
    reference_change_percent: Decimal | None,
    latest_reference_price: Decimal | None,
    exit_reason_codes: tuple[str, ...],
    structure_exit_available: bool,
)
```

Direction-adjusted reference price change is:

```text
long  = (exit - entry) / entry * 100
short = (entry - exit) / entry * 100
```

For an open Episode, use the latest completed 15m close at the response cutoff only as `latest_reference_price` and an explicitly unrealized `current_reference_change_percent`. It is not included in completed Episode statistics.

The UI label is always `参考变动`, never account `盈亏` or realized return.

### 12.3 Deterministic identity

Action and Episode ids must be deterministic and prefix-stable. Their canonical identity includes:

- strategy and formula version;
- symbol and exact physical contract;
- segment start;
- opportunity key;
- Action kind;
- decision and effective Bar times;
- fill basis.

Price, explanatory labels, request window, cache location, and response generation time are not permitted to create duplicate logical Actions. A concrete canonical JSON + SHA-256 scheme or an equally deterministic readable identity may be selected in the implementation plan, but tests must prove stability and collision resistance for the supported domain.

## 13. Historical Strategy Projection

### 13.1 Service behavior

Add a source-specific read-only service, not a generic backtest adapter:

```text
SubingStrategyHistoricalProjectionService
```

For each validated physical segment:

1. resolve the true segment and complete source coverage;
2. load required 5m/15m and stitched D1/60m inputs;
3. reconstruct target-day Daily Context causally;
4. calculate existing SuBing Factor/Signal/Lifecycle facts;
5. run the pure Strategy reducer from segment start through `through`;
6. terminally close a remaining position at segment end;
7. crop the response to the requested display window only after full state reconstruction.

Calculation never begins at the first visible Bar with an assumed flat state.

### 13.2 Window intersection

The API returns every Action whose effective Bar lies inside the requested window and every Episode that intersects the window.

Therefore:

- an entry left of the visible window and an exit inside it returns the complete Episode and the exit Marker;
- the Tooltip can show the off-screen entry details;
- panning left later reveals the entry Marker;
- an Episode still open at `through` is returned as `state=open`.

### 13.3 HTTP endpoint

Add:

```text
GET /api/v1/market/research/subing-strategy/history
```

Request:

```text
series_kind=actual_dominant
symbol=<active product>
frequency=15m
since=YYYY-MM-DD
through=YYYY-MM-DD
```

Response includes:

```text
request identity
strategy policy identity
resolved cutoff and segment summaries
actions
episodes
context-unavailable days
cache state
```

It does not include equity curve, win rate, max drawdown, margin return, or simulated account balance.

### 13.4 Existing historical signal endpoint

After the Web is cut over and active references are closed, retire the public historical single-signal route and client:

```text
GET /api/v1/market/research/subing/history
```

The underlying Factor, Signal, Calibration, Historical Signal, and Lifecycle logic remains available as internal SuBing capability where still consumed by Current Signal State, Lifecycle, Stage 1 composition, or the existing Alert path. The old independent `买入信号 / 卖出信号` chart Markers are not shown together with Strategy Markers.

The retirement must be atomic with frontend/API/test/reference cleanup and must not alter immutable historical Alert Events.

## 14. Expendable local cache

### 14.1 Purpose

The user expects historical strategy results to be calculated once and then displayed quickly. Stage 1 may maintain a non-authoritative, versioned local file cache. It is not a report, evidence, Canonical dataset, DB record, or Runtime state.

Use a dedicated namespace under the already validated SuBing local observation base root:

```text
<subing-observation-root>/cache/subing-strategy-v1/
```

It must not write inside the Git repository, Canonical root, Daily Watch V1 bytes, or Daily Watch V2 artifact namespace.

### 14.2 Cache identity

A cache entry is valid only when all of the following exactly match:

```text
strategy policy bytes / strategy formula version
accepted calibration id
Lifecycle policy id and formula version
Daily Watch projection/formula/history-mode identity
symbol
physical contract
segment start and segment end
5m/15m/D1/60m authoritative coverage cutoffs
requested through cutoff
```

A source, policy, calibration, coverage, contract, or strategy change invalidates the entry automatically.

### 14.3 Safety and degradation

- validate the configured base root with the existing mount/path safety pattern;
- reject symlink traversal and paths outside the validated root;
- write to a same-filesystem temporary file and atomically replace the completed entry;
- never treat cache bytes as authoritative without revalidating the identity envelope;
- a cache read, parse, validation, or write failure must not change the calculated result;
- when authoritative inputs are available, calculate and return the projection with `cache_state=unavailable` rather than failing the strategy request solely because the expendable cache failed.

No cache cleanup scheduler is introduced in V1. Manual deletion is safe because the cache is reconstructible.

## 15. Market Web design

### 15.1 Overlay identity

The existing `subing` overlay remains the only SuBing overlay. Its public capability in V1 Strategy mode is:

```text
series_kind = actual_dominant
frequency   = 15m
```

Other currently supported SuBing observation frequencies may remain available to the internal/current research panel during migration, but Strategy Markers and Episodes appear only on `actual_dominant + 15m`.

### 15.2 Main chart indicators

EMA21 remains visible by default because it is both an observed trend fact and a V1 exit reference. Existing optional EMA10/EMA60 behavior remains unchanged unless the implementation plan finds a direct conflict.

### 15.3 Public Strategy Markers

Show only:

```text
▲ 建多
▼ 建空
× 清多
× 清空
```

Marker properties:

- `time = action.effective_bar_end`;
- long/open below Bar, short/open above Bar;
- close Marker placed on the side that avoids overlapping the entry convention;
- deterministic `id` and `dedupeKey` derived from Action identity;
- no screen-pixel coordinate storage.

Entry Tooltip includes:

```text
苏冰策略 V1 · 15m
动作
决策时间
模拟生效 Bar
下一根开盘参考价
D1/60m direction context
Lifecycle confirmation source
opportunity identity
bound Pivot or structure exit unavailable
```

Exit Tooltip includes:

```text
苏冰策略 V1 · 15m
动作
entry/exit reference price and time
参考变动
holding Bar count
all exit reason codes
fill basis
```

Every surface states `历史因果投影 / 模拟动作 / 非实际成交`.

### 15.4 Pan, zoom, and left pagination

Extend the current Historical Research Marker mechanism rather than creating an independent chart overlay engine.

Required behavior:

- identity change cancels stale requests and clears old Strategy results;
- `replace` loads the current confirmed range;
- `prepend` requests only the newly exposed earlier date range;
- Action ids dedupe overlapping API responses;
- Episodes merge by Episode id;
- Markers sort by business time;
- pan, zoom, resize, and scroll preserve Bar attachment through the chart library's time scale;
- a stale response for another symbol, frequency, series kind, or generation cannot mutate the current chart;
- a failed Strategy layer degrades only that layer and leaves K-lines usable.

### 15.5 SuBing Strategy record area

Add a compact `苏冰策略记录` section to the existing SuBing product panel/drawer rather than creating a new page.

For every returned Episode show:

```text
15m
entry date/time and reference price
exit date/time and reference price, or 持仓中
direction
参考变动
holding Bar count
exit reasons
```

Open Episodes display current reference change and current available exit references but are excluded from any completed count.

V1 does not show cumulative return, win rate, max drawdown, equity curve, or “收益” because no account/cost/margin model exists.

### 15.6 Internal research-process toggle

Add one advanced preference:

```text
显示苏冰内部研究过程
```

Default: off.

When enabled, it gates only the existing current Lifecycle projection such as `准备 / 研究确认 / 风险 / 结束`. It does not request or synthesize a complete historical Lifecycle trace. Factor/Signal/Lifecycle details remain under a collapsed internal-details area; Strategy status, Actions, and Episodes are the primary surface.

## 16. Stage 2: completed-Live Runtime and Alert

Stage 2 is designed now but implemented only after Stage 1 acceptance and a new Lane 3 Plan approval.

### 16.1 Runtime evaluation scope

At Runtime startup:

```text
for each active60 product
→ replay the current physical rank1 segment to latest completed boundary
→ restore flat/long/short, consumed opportunities, pending action, and current Episode
```

No strategy position table or Redis checkpoint is introduced. Runtime state is reconstructible from authoritative data and exact policies.

During trading:

```text
completed relevant Live boundary
→ update existing Factor/Lifecycle facts
→ evaluate the 15m Strategy clock
→ apply any pending next-Bar-open Action
→ emit at most one new Strategy Action per effective Bar
```

All active60 products may be evaluated. Data/context failure is per product. Only products in the new Rule's explicit `scope_products` may create a Formal Event and notification attempt.

### 16.2 New Alert Rule

Add a new immutable Rule code:

```text
subing_strategy_v1
```

Do not silently change the meaning of `subing_entry_signal_v1`.

The new Rule produces four result codes corresponding to the four public Strategy Action kinds. Both open and close Actions create Formal Events for explicitly scoped products and may attempt PushPlus once.

The old Rule:

- stops creating new Events only after the new Rule, migration, Scope, and Runtime path are explicitly approved;
- remains available as disabled historical lineage if required by the two-table Alert contract;
- does not delete or rewrite historical Events;
- does not transfer Scope implicitly.

The new Rule must initially be disabled or empty-scope. Any exact Scope migration from the old Rule is a production DB mutation requiring a separate, explicit, one-attempt authorization.

### 16.3 Event identity and idempotency

The existing Alert uniqueness model remains source-specific. For the new Rule, one effective 15m Bar cannot contain both a close and re-entry, so `(rule_id, symbol, effective_bar_end)` remains sufficient when the implementation confirms it fits the current DB contract. The Event payload includes Action kind, Episode id, entry reference, effective reference, and reason codes.

Runtime replay after restart must not duplicate an existing Event. Event insertion remains commit-first followed by at most one notification request. There is no replay, backfill, retry, queue, fallback, or automatic resend.

### 16.4 Stage 2 Gates

The following remain independent explicit approvals:

1. production migration;
2. exact Rule seed and Scope mutation;
3. release/tag;
4. Runtime promotion/switch;
5. real PushPlus canary or natural notification acceptance.

Provider acceptance does not prove WeChat delivery. Stage 2 never authorizes an order path.

## 17. Error and availability contract

### 17.1 Request errors

Return `422` for malformed symbol/date/range, unsupported series kind, or non-15m frequency.

### 17.2 Source and identity errors

Return typed `409` for:

```text
SUBING_STRATEGY_SOURCE_UNAVAILABLE
SUBING_STRATEGY_SEGMENT_IDENTITY_INVALID
SUBING_STRATEGY_CONTEXT_IDENTITY_INVALID
SUBING_STRATEGY_POLICY_INVALID
SUBING_STRATEGY_CALIBRATION_UNAVAILABLE
```

Exact names may be refined only to fit existing repository naming conventions; each class must remain stable and testable.

### 17.3 Partial daily context availability

A valid segment with one or more target days lacking Daily Context still returns a projection. Those days appear in `context_unavailable`, cannot open new Episodes, and do not block exit evaluation for an existing Episode.

### 17.4 Pending next Bar

At the response cutoff, a decision may have no next Bar yet. Historical response may expose it as a non-Marker pending decision only when the contract is explicit; it must not fabricate an effective Action or reference price. The simpler accepted V1 UI may omit pending decisions and show only effective Actions.

### 17.5 Fail-closed invariants

Never:

- substitute current close for missing next open;
- carry a position across contract segments;
- use future D1/60m context;
- infer a missing Pivot;
- treat unavailable context as aligned;
- silently fall back to another frequency;
- let cache bytes override authoritative source identity;
- create a Strategy Event from Historical API reads.

## 18. Testing and evidence

### 18.1 Pure policy and reducer tests

Cover:

- exact policy payload and rejection of any drift;
- all four confirmation sources;
- 5m confirmation projected once onto the next 15m decision boundary;
- confirmation at the exact 15m boundary;
- cancellation when the window ends in `exit_risk` or `closed`;
- late context alignment does not resurrect an old opportunity;
- one entry per opportunity key;
- same/opposite confirmation while holding;
- no reverse and no same-effective-Bar re-entry;
- next existing Bar across session breaks;
- missing next Bar cancellation;
- each long and short exit family;
- multiple same-Bar exit reasons with one close;
- entry without bound Pivot;
- contract terminal close and pending-open cancellation;
- public and internal state invariants.

### 18.2 Causality tests

For representative sequences:

- replay every prefix;
- append later Bars;
- prove all prior Actions and closed Episodes are byte-identical;
- prove a confirmation after the cutoff cannot affect an earlier 15m decision;
- prove target-day context uses only its accepted source day;
- prove next-Bar open is not read before the decision exists.

### 18.3 Historical service and API tests

Cover:

- exact active product and request identity;
- actual-dominant segment partitioning;
- no cross-segment state;
- full segment initialization before response cropping;
- entry outside the window with exit inside;
- open Episode at cutoff;
- context-unavailable day behavior;
- cache hit/miss/invalid/corrupt/write-failure equivalence;
- old historical signal route/client retirement;
- no DB/Redis/Alert mutation from Strategy history reads.

### 18.4 Web tests

Cover:

- only 15m actual-dominant Strategy capability;
- old independent buy/sell Markers absent;
- open/close Marker conversion and Tooltip labels;
- `参考变动` long/short calculation display;
- Episode merge and open-Episode state;
- advanced internal-process toggle default off;
- identity generation cancellation;
- replace/prepend dedupe;
- entry off-screen left with in-window exit;
- pan/zoom/resize/left-load Marker attachment;
- malformed or stale Strategy response degrades only the Strategy layer.

### 18.5 Manual acceptance corpus

Before Stage 1 is accepted, manually inspect at least:

```text
3 active products
>= 5 complete Episodes per product
```

The corpus must collectively include:

- long and short Episodes;
- all four exit families;
- one Bar with multiple exit reasons;
- an overnight/session-gap fill;
- a contract segment terminal close;
- an entry off-screen left and exit in the visible window;
- repeated horizontal pan and prepend loading.

Each sampled Action is checked against raw completed Bars, Factor/Lifecycle provenance, Daily Context source day, next-Bar open, and exit reason values.

### 18.6 Stage 2 tests

A future Stage 2 plan must additionally prove:

- active60 per-product isolation;
- restart reconstruction without a position table;
- exact Rule Scope enforcement;
- new Rule idempotency;
- open and close Event content;
- commit-first, at-most-once transport;
- no old Rule semantic mutation;
- no notification on Historical replay;
- no order path.

## 19. Delivery stages and Gates

### Stage 1A — Domain and policy

Deliver:

- exact strategy policy;
- pure reducer;
- Action/Episode contracts;
- direction-context resolver contract;
- unit and causality tests.

Gate: independent review of formula, time cutoffs, next-Bar fill, exit semantics, and segment boundaries.

### Stage 1B — Historical projection

Deliver:

- source-specific composition/service/API;
- versioned expendable cache;
- full-segment initialization and window cropping;
- API/service/cache tests.

Gate: no identity leakage, no authoritative writes, deterministic responses, and measured acceptable single-product latency.

### Stage 1C — Market Web

Deliver:

- existing `subing` overlay cutover;
- old historical signal Marker/API/client retirement;
- Strategy Markers and Tooltip;
- compact Strategy record area;
- current internal-process advanced toggle;
- pagination and browser tests.

Gate: automated checks plus the manual acceptance corpus.

### Stage 1D — Integration decision

After Stage 1A–C evidence and independent review, the user decides whether the implementation may integrate into `develop`. Integration does not authorize release, Runtime promotion, production migration, Scope changes, or real notification.

### Stage 2 — Runtime and Alert

Requires a new Plan-only Lane 3 session and separate approvals. Stage 2 cannot begin merely because Stage 1 entered `develop`.

## 20. Acceptance criteria

Stage 1 is accepted only when all of the following are true:

1. The upper chart surface exposes one `苏冰策略 V1` historical projection on `actual_dominant + 15m`.
2. Every public Marker corresponds to one deterministic effective Action and remains attached to its Bar during pan/zoom/prepend.
3. Open and close Actions pair into correct Episodes; no duplicate entry, reverse, same-Bar re-entry, or cross-segment position exists.
4. D1/60m direction is causally equivalent to Daily Watch V2 target-day classification.
5. All four approved Lifecycle confirmation sources can enter through the same boundary.
6. Any available exit family can close the full position, and all same-Bar reasons are retained.
7. High dead cross / low golden cross is not mislabeled internally as true MACD divergence.
8. Historical initialization starts at the physical segment boundary, not the visible window.
9. Cache failure cannot change Strategy output.
10. The UI uses `参考变动`, never an unsupported account PnL claim.
11. Old independent historical SuBing buy/sell Markers are absent from the active chart surface.
12. Daily Watch remains active and retains its existing responsibility: “今天重点看谁”.
13. No RQAlpha, Execution Review, generic backtest framework, DB strategy state, order, or auto-trading path is introduced.
14. Required focused tests, backend quality checks, Web type/build/tests, full relevant regressions, and manual acceptance all pass.
15. `STATUS.md` is updated only with observed implementation/evidence facts and does not declare Stage 2, OOS, profitability, release, or Runtime readiness prematurely.

## 21. Locked decision ledger

The dialogue approved all recommended choices:

| # | Locked choice |
|---|---|
| 1 | Project any first Lifecycle confirmation in `(previous 15m boundary, current 15m boundary]` onto the 15m decision clock |
| 2 | Cancel entry when the window ends in `exit_risk` or `closed` |
| 3 | First confirmation per opportunity key wins |
| 4 | No retroactive entry after direction context later aligns |
| 5 | D1 and 60m must both be available and aligned |
| 6 | Context change after entry is not an exit |
| 7 | Context/data unavailable is per product, fail-closed for new entry |
| 8 | One opportunity key may enter at most once |
| 9 | Same-direction confirmation while holding is ignored |
| 10 | Opposite confirmation while holding neither exits nor reverses |
| 11 | No re-entry on the close effective Bar |
| 12 | Structure exit uses Lifecycle bound Pivot |
| 13 | Missing bound Pivot does not block entry; structure exit is unavailable |
| 14 | Structure exit uses completed 15m close, not intrabar touch |
| 15 | EMA21 exit is current close beyond EMA21 |
| 16 | Previous-Bar exit is current close beyond prior 15m extreme |
| 17 | MACD exit requires strict positive high dead cross / negative low golden cross |
| 18 | One close Action retains all same-Bar reasons |
| 19 | Marker anchors to effective next-Bar-open Bar |
| 20 | Next existing same-segment Bar may cross session gaps |
| 21 | Overnight holding is allowed |
| 22 | Segment end terminally closes at old segment last close |
| 23 | Missing/invalid next open cancels Action; no close-price fallback |
| 24 | Historical replay initializes from physical segment start |
| 25 | Return complete Episodes intersecting the requested window |
| 26 | Use a versioned local file cache, not PostgreSQL |
| 27 | Replace old independent historical buy/sell Markers with Strategy Markers |
| 28 | Advanced internal research-process toggle, default off |
| 29 | EMA21 remains default visible |
| 30 | Add a compact Strategy Episode record area |
| 31 | Display `参考变动`, not `盈亏` |
| 32 | Display open Episode separately and exclude it from completed results |
| 33 | One design, two separately gated stages: Historical first, Runtime/Alert second |
| 34 | Stage 2 evaluates active60; only explicit Scope may notify |
| 35 | Stage 2 notifies both open and close Actions |
| 36 | New Rule code `subing_strategy_v1`; no semantic mutation of old Rule |
| 37 | Runtime restart restores state by replay, not a position table |
| 38 | Product name `苏冰策略 V1 · 研究回放 / 模拟动作` |
| 39 | Daily Watch remains independent and active |
| 40 | Manual acceptance uses 3 products and at least 5 complete Episodes per product |

## 22. Review focus

The written-spec review should concentrate on:

- whether Daily Watch V2 is the correct immutable direction context for each target trading day;
- whether projecting internal 5m confirmations onto one 15m clock matches the intended trading meaning;
- whether “four exits OR, full close” is represented without silently adding risk or time exits;
- whether next-Bar-open and segment-terminal-close reference fills are acceptable;
- whether the Stage 1 Web surface is simple enough despite retaining internal research capabilities;
- whether Stage 2 remains sufficiently isolated from Stage 1 and from all real external mutations.

## 23. Approved Lifecycle structure-binding correction

The Strategy structure exit consumes one authoritative Lifecycle fact. The two
previously conflated Pivot roles are split atomically:

- `trigger_reference_pivot` is the existing 5m breakout/retest Pivot: HIGH for
  long and LOW for short. Existing trigger, retest, and Lifecycle risk behavior
  continues to consume this field unchanged.
- `bound_reference_pivot` is the Strategy protective structure Pivot: LOW for
  long and HIGH for short. It is sourced only from the existing 5m strict
  2-left/2-right `ConfirmedPivot` stream and is frozen at the unique
  `ENTRY_CONFIRMED` transition.

At the entry confirmation Bar, Lifecycle selects the latest Pivot ordered by
`(confirmed_at, pivot_time, pivot_id)` whose `confirmed_at` is strictly earlier
than the entry boundary and whose physical contract, segment start, and trading
day equal the entry Bar. The selection has no opportunity-origin lower bound,
does not cross a day or segment, and never searches N Structure, 15m Pivots,
frontend state, previous-Bar fallbacks, or future Bars. Missing evidence freezes
`None` without blocking entry; the value is immutable for the Episode and makes
the structure-exit family unavailable.

This output-contract correction changes Lifecycle `formula_version` to
`subing_lifecycle_v2_structure_binding_v1`. Policy id
`subing_lifecycle_v2_research_v1` and every policy parameter remain unchanged.
Strategy cache identity receives the new formula version from Lifecycle;
retrospective candidate/protocol JSON remains pinned to its historical formula
identity and is not rewritten.

Acceptance must rerun all four confirmation-source cases, long/short direction,
exact-boundary exclusion, missing/day/segment isolation, trigger/retest/risk
regressions, prefix invariance, Strategy Action/Episode preservation, current
HTTP/Web dual-field projection, and cache identity checks. Existing natural-data
acceptance evidence is invalidated for the affected structure-exit cases and must
be rerun. Independent Review must bind to the exact corrected head and repeat
the original causal/exit/no-Stage-2 review focus plus this field split; until
those gates pass, the implementation does not open integration or acceptance.
