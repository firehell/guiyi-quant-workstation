# SuBing Strategy V1 Stage 2 and v1.8.7 Design Spec

**Status:** Self-reviewed — user written-spec review pending  
**Date:** 2026-08-26  
**Design base:** `develop@ee4a7d7091acc4139931fc56c8a5a61421aa3ad4`  
**Target release:** `v1.8.7`  
**Delivery lane:** Lane 3 — strategy causality, production migration, Runtime, real notification, release  
**Implementation authorization:** Not granted by this document

## 1. Decision

Extend the already integrated `SuBing Strategy V1` Stage 1 Historical Strategy Projection into one completed-Live product for release `v1.8.7`:

```text
Stage 1 Historical
actual_dominant + 15m
Actions + Episodes + chart markers
                  |
                  | same exact policy, identities and reducer
                  v
Stage 2 Completed-Live
active60 strategy state
→ open_long / open_short / close_long / close_short
→ immutable AlertEvent
→ owner PushPlus once
→ live chart marker and current Episode
```

The user-facing strategy remains deliberately small:

```text
空仓
→ 建多 / 建空
→ 持仓
→ 清多 / 清空
→ 下一轮机会
```

The existing `subing_entry_signal_v1` Alert product is not retained as an active or historical compatibility surface. Migration `20260826_0042` will:

1. delete every `AlertEvent` owned by `subing_entry_signal_v1`;
2. preserve the existing `AlertRule.id`, `enabled`, and `scope_products`;
3. replace its `rule_code` with `subing_strategy_v1`;
4. remove the obsolete `lower_tf_confirmation` public/storage contract;
5. introduce Strategy Action event identity and payload fields;
6. preserve HTDY Rule, Scope and Event history unchanged.

This is a forward-only product replacement. No archive table, compatibility reader, dual Rule period, replay, backfill, or notification retry is introduced.

`v1.8.7` includes all of the following as one coherent product version:

- the existing Stage 1 Historical Strategy Projection;
- completed-Live active60 strategy evaluation;
- direct Alert Rule replacement with `subing_strategy_v1`;
- production schema migration `20260826_0042`;
- live Strategy Action Marker and current Episode projection;
- owner PushPlus messages for all four Strategy Action kinds;
- exact release identity synchronization across API, Web, packages, health and release metadata.

The release, production migration, Runtime promotion and real owner canary remain four separate external-operation Gates. Approval of this design authorizes none of them.

## 2. Current repository facts and compatibility

At the design base:

- Stage 1 is integrated in `develop` and supports only active single-product `actual_dominant + 15m` Historical Strategy Projection.
- Stage 1 produces deterministic `SubingStrategyAction` and `SubingStrategyEpisode` objects from the true rank1 physical segment start.
- Ordinary historical Actions decide on a completed 15m close and use the next existing same-segment 15m open as reference price.
- Lifecycle already separates `trigger_reference_pivot` from the protective `bound_reference_pivot`.
- The current Alert Rule is still `subing_entry_signal_v1`, with only `buy / sell` result codes.
- The active Alert Application Domain still has only `alert_rules` and `alert_events`.
- Alert Runtime is a single foreground process subscribed to completed Live Bar messages and `market:state`; it has no replay, backfill, queue or automatic retry.
- SuBing notifications use the owner PushPlus audience, not the HTDY Topic.
- Current release and production Runtime are `v1.8.5`; Stage 1 and this Stage 2 design are not yet in a formal release.

Stage 2 must reuse these boundaries. It must not create a generic StrategyAdapter, a strategy-position table, an order domain, a second Alert process, a second Daily Context formula or a second Historical data path.

## 3. Goals

1. Run the exact SuBing Strategy V1 semantics automatically for active60 during the trading day.
2. Preserve Historical/Live causality and Action identity parity.
3. Apply a pending Action at the next actual 15m open using the first completed 1m Bar of that interval.
4. Create one immutable Strategy Action Event for each newly effective scoped Action.
5. Send one owner PushPlus request for each newly created scoped Event.
6. Present the same Action immediately on the Market chart and update the current Episode.
7. Delete the old SuBing entry-signal Alert history and product surface atomically.
8. Release the complete result as `v1.8.7` with an explicit forward-only production migration.
9. Keep failures isolated per product wherever data identity permits.
10. Keep `auto_order=false` and every output research-only.

## 4. Non-goals

- No automatic order, account, position, margin, leverage, commission, slippage or portfolio management.
- No add, reduce, partial exit, pyramid, reverse-on-signal or same-Bar re-entry.
- No preservation or archival of old `subing_entry_signal_v1` AlertEvent rows.
- No dual-running old and new SuBing Alert Rules.
- No Strategy Event replay, backfill, catch-up notification or retry queue.
- No Redis or PostgreSQL strategy-position checkpoint.
- No new launchd service, worker, port, scheduler, message bus or outbox.
- No public 5m Strategy mode; 5m remains an internal Lifecycle clock.
- No true MACD Pivot-divergence formula.
- No profitability, OOS, promotion or trading-readiness claim.
- No automatic release, migration, Runtime switch, Scope mutation or real notification.

## 5. Final architecture

```text
RQData → Canonical Parquet → MarketDataService
                                  |
                                  +→ Historical Daily Watch V2 reconstruction
                                  |     prior target days during restore
                                  |
                                  +→ Daily Watch V2 current artifact
                                  |     current target day D1 + 60m direction
                                  |
Market Runtime → Redis completed Live Bars
                  1m / 5m / 15m  |
                                  v
                    Existing Alert Runtime process
                    ├─ HTDY evaluator
                    ├─ SuBingStrategyRuntimeEvaluator
                    │   ├─ active60 in-memory state
                    │   ├─ Factor step
                    │   ├─ Lifecycle step
                    │   ├─ Strategy step
                    │   └─ pending next-15m-open application
                    ├─ AlertService
                    │   └─ immutable Strategy Action Event
                    └─ PushPlus owner one-shot
                                  |
                    +-------------+-------------+
                    |                           |
                 Market Web                 Runtime health
          live marker/current Episode    ready/degraded counts
```

A separate read-only `SubingStrategyCurrentProjectionService` serves the currently opened product in Web. It reconstructs Canonical plus completed Live state by using the same engine; it does not read private in-memory state from the Alert process and does not treat AlertEvent as the strategy state authority.

## 6. Shared Historical and Live strategy engine

### 6.1 One semantic owner

Stage 2 refactors the existing Stage 1 orchestration into one incremental, pure state machine boundary:

```python
state, output = machine.step(state, input_event)
```

The state machine owns:

- segment identity;
- Factor streaming state for 5m and 15m;
- Lifecycle V2 state and confirmed Pivots;
- consumed opportunity ids;
- public position state `flat | long | short`;
- pending open or close Action;
- current Episode and frozen protective Pivot;
- latest processed 1m / 5m / 15m watermarks.

Historical replay becomes:

```python
for input_event in historical_stream:
    state, output = machine.step(state, input_event)
```

Completed-Live evaluation calls the exact same `step` operation. Formula branches may not be copied into Alert Runtime.

### 6.2 Input event types

The machine consumes four explicit inputs:

```text
Completed1mBar
Completed5mBar
Completed15mBar
AuthoritativeSegmentTerminal
```

Daily Context is supplied as a versioned target-day input to the relevant 15m decision. Scope is never part of strategy calculation.

### 6.3 Prefix invariance

Appending later completed Bars must not change any earlier:

- Action id;
- Episode id;
- decision time;
- effective 15m Bar;
- reference price;
- confirmation source;
- bound Pivot;
- exit reason set or order.

Recorded Live streams and Historical streams with the same authoritative inputs must produce byte-equivalent Action payloads after normalizing processing-only timestamps.

## 7. Runtime scope and state ownership

### 7.1 Calculation scope

The Runtime maintains strategy state for every product in active60, regardless of Alert Scope:

```text
active60              → calculate and maintain state
scope_products        → allow Event creation and PushPlus
```

Changing Scope does not create, destroy or reset a strategy state. A newly scoped product can notify from the next newly effective Action without waiting for a fresh segment rebuild.

### 7.2 In-memory only

No strategy state table and no Redis checkpoint are added. State is reconstructible from:

- exact strategy, calibration and Lifecycle policies;
- Canonical data from the current rank1 segment start;
- completed Live 1m / 5m / 15m data;
- causally reconstructed Daily Watch V2 direction for completed prior target days;
- the immutable Daily Watch V2 artifact for the current target trading day.

AlertEvent is notification history, not position authority.

### 7.3 Per-product degradation

A source, identity or context failure for one symbol makes that symbol unavailable while the remaining products continue. Runtime status records counts and symbol codes without exposing private configuration.

A fundamental process-level failure, invalid policy, invalid schema or unavailable database keeps the Runtime fail-closed.

## 8. Startup recovery and no-backfill boundary

### 8.1 Startup sequence

```text
1. Subscribe to Redis completed-Bar and market:state channels.
2. Record runtime_started_at.
3. Restore current rank1 segment state for active60.
4. Perform one final completed-Live catch-up read for every restored symbol.
5. Record strategy_ready_at and per-symbol cutoffs.
6. Enter normal message processing.
```

For each target day before the current day, restoration uses the exact Stage 1 Historical Daily Watch V2 reconstruction. For the current target day, it consumes the immutable current Daily Watch V2 artifact. A current artifact is never projected backward over earlier days.

The final catch-up closes the subscription/warm-up race without generating delayed notifications.

### 8.2 Notification watermark

Actions that already became effective before the product's ready cutoff are used only to restore state:

```text
past Action during downtime or warm-up
→ restore position / pending / consumed opportunity
→ no AlertEvent
→ no PushPlus
```

A pending Action whose effective next 15m interval has not started remains pending and may create a new Event after readiness.

No startup replay, same-day catch-up message or “latest missed signal” is sent.

### 8.3 Runtime status

Extend the existing `alert:runtime-status` to schema v3 with additive fields:

```text
strategy_state: warming | ready | degraded
strategy_started_at
strategy_ready_at
strategy_product_count
strategy_ready_product_count
strategy_unavailable_product_count
strategy_unavailable_symbols
last_strategy_action_at
last_strategy_restore_at
```

Schema v1/v2 reads remain supported only for upgrade compatibility; every v1.8.7 write uses schema v3. Existing notification failure and acknowledgment semantics remain unchanged.

## 9. Completed-Bar processing

### 9.1 Completed 5m Bar

A completed 5m Bar updates:

- 5m Factor state;
- 5m Pivot state;
- Lifecycle trigger, hold, retest and confirmation state.

It never creates a public 5m Strategy Action or Event.

### 9.2 Completed 15m Bar

A completed 15m Bar updates:

- 15m Factor state;
- Lifecycle anchor facts;
- the unique public Strategy decision clock;
- all four exit predicates while holding.

A qualifying decision creates one internal pending Action:

```text
pending_open_long
pending_open_short
pending_close_long
pending_close_short
```

No Event exists yet because the Action has not reached the next 15m open.

### 9.3 First completed 1m Bar in the next actual 15m interval

For a pending Action decided on completed 15m Bar `B`, resolve the next actual session-aware same-contract 15m interval `N`.

The exact reference open is the `open` of the first completed 1m Bar belonging to `N`:

```text
decision_at        = B.bar_end
effective_open_at  = first 1m interval start
effective_bar_end  = N.bar_end
reference_price    = first 1m.open
fill_basis         = next_bar_open
```

The first 1m message normally arrives about one minute after the 15m interval starts. At that time the Action becomes effective, the Event is committed and PushPlus is attempted.

Crossing lunch, night-session breaks and overnight is allowed when the next actual 15m interval remains in the same physical contract segment.

### 9.4 Missing first 1m Bar

If a later 1m message arrives first, the evaluator may query the existing completed-Live read seam for the exact first 1m Bar of the target interval.

It may not substitute:

- a later 1m open;
- the decision 15m close;
- a synthetic arithmetic time;
- a Bar from another contract or segment.

If the target 15m interval completes without an authoritative first 1m Bar, cancel the pending Action with:

```text
NEXT_BAR_OPEN_UNAVAILABLE
```

No Strategy Action, Event or notification is produced.

### 9.5 Duplicate, stale and conflicting messages

- An identical message at or below a processed watermark is idempotently ignored.
- A conflicting message with the same identity degrades the product and produces no Event.
- Out-of-order future data is rejected.
- An Action id already persisted is not notified again.
- A stale contract or segment message cannot mutate the current state.

## 10. Daily Context

### 10.1 One formula, two read modes

There is one Daily Watch V2 formula and identity, but restoration has two causal read modes:

```text
prior target trading days
→ reuse Stage 1 historical Daily Watch V2 reconstruction

current target trading day
→ read the immutable Daily Watch V2 current artifact
```

The Runtime may not use today's current artifact for an earlier target day and may not create a second D1/60m formula.

### 10.2 Current artifact contract

For the current target day, require:

```text
projection_version = subing_daily_watch_v2
formula_version    = subing_ema21_rank1_stitched_raw_v2
history_mode       = rank1_stitched_raw
target_trading_day = current strategy trading day
```

Direction remains:

```text
D1 long + 60m long   → LONG_ONLY
D1 short + 60m short → SHORT_ONLY
other                → NO_NEW_ENTRY
unavailable/stale    → UNAVAILABLE
```

While flat, unavailable or mismatched context blocks new entry. While already holding, the four 15m exit families continue. A later neutral or opposite context is not a fifth exit.

## 11. Rank1 segment rollover

A strategy state never crosses a physical rank1 segment.

When `canonical_updated` makes the old segment terminal authoritative:

```text
old segment still holding
→ terminal close at old segment final completed 15m close
→ fill_basis = segment_terminal_close
→ reason_codes include CONTRACT_SEGMENT_END
→ create scoped Event and owner notification
→ new segment starts flat
```

This Event is not a replay; it is emitted when the terminal identity first becomes authoritative.

If Runtime was not running at that moment, later startup restores the already closed state and does not send a delayed terminal notification.

A pending open without a next same-segment Bar is canceled. An ordinary request cutoff or temporary Live cutoff never impersonates segment terminal.

## 12. Direct Alert Rule replacement

### 12.1 Active registry

After migration and v1.8.7 startup, the only active Rule codes are:

```text
htdy_original_15m
subing_strategy_v1
```

Replace the SuBing registry definition with:

```text
rule_code: subing_strategy_v1
display_name: 苏冰策略
kind: strategy_action
input_frequencies: 1m, 5m, 15m
series_kind: actual_dominant
scope authority: scope_products
notification audience: owner
```

The Event's public frequency remains `15m`; the Rule input-frequency list describes the completed Live inputs required to operate the state machine.

Remove the old formal-signal evaluator from Alert Runtime. Current Signal State and Lifecycle remain internal SuBing research capabilities because Strategy entry still consumes them.

### 12.2 Scope and enablement

Migration preserves the existing SuBing Rule row's:

- primary key;
- `enabled` value;
- normalized `scope_products`;
- empty `scope_product_frequencies` authority.

It changes only the Rule code and active semantics after deleting old SuBing Event rows.

No automatic expansion to active60 occurs. active60 is calculation scope; `scope_products` remains notification scope.

## 13. Migration `20260826_0042`

### 13.1 Forward-only preflight

Before mutation, the migration must verify:

1. exactly one `subing_entry_signal_v1` Rule exists;
2. no `subing_strategy_v1` Rule exists;
3. the old Rule's `scope_products`, `scope_product_frequencies` and enabled state satisfy the current contract;
4. the HTDY Rule exists and its Event/Scope state is structurally valid;
5. there are no unknown active Rule codes;
6. existing result-code values satisfy their current Rule contracts;
7. the database is at exact parent revision `20260826_0041`.

Any mismatch aborts the migration before partial product conversion.

### 13.2 Data changes

In one database transaction:

1. delete all `alert_events` whose Rule is `subing_entry_signal_v1`;
2. rename the existing Rule row to `subing_strategy_v1`;
3. preserve Rule id, enabled state and product Scope;
4. drop `alert_events.lower_tf_confirmation`;
5. widen the result-code array element type for Strategy Action codes;
6. replace the global result-code check with the finite union:
   `buy | sell | open_long | open_short | close_long | close_short`;
7. add nullable `action_id` with a partial unique index for non-null values;
8. add nullable `strategy_payload` JSON;
9. preserve existing HTDY Event rows unchanged.

Application validation, not a cross-table database subquery, enforces exact per-Rule result-code and payload contracts:

```text
HTDY:
  result_codes = buy | sell | buy+sell
  action_id = null
  strategy_payload = null

SuBing Strategy:
  exactly one of open_long | open_short | close_long | close_short
  action_id = required
  strategy_payload = required and exact-schema valid
```

### 13.3 Identity constraints

Retain the existing unique Event identity:

```text
(rule_id, symbol, frequency, bar_end)
```

Add the authoritative Strategy Action identity:

```text
UNIQUE(action_id) WHERE action_id IS NOT NULL
```

For Strategy Events:

```text
AlertEvent.bar_end    = Action.decision_at
AlertEvent.trading_day = Action.trading_day of the effective Action
AlertEvent.frequency  = 15m
```

A decision may occur on the preceding trading day while its next-open Action belongs to the next trading day. Current-day Event reads therefore use the effective Action's trading day.

The Marker anchor is not `AlertEvent.bar_end`; it is `strategy_payload.effective_bar_end`.

### 13.4 No archive and no downgrade

No backup or archive table is created. The old SuBing Alert history is intentionally deleted.

```python
def downgrade() -> None:
    raise RuntimeError("SUBING_STRATEGY_ALERT_DOWNGRADE_UNSUPPORTED")
```

After migration, v1.8.5 is not schema-compatible and is not a permitted production rollback target.

### 13.5 Required readback

After production migration, verify without creating Events:

- old Rule count is zero;
- new Rule count is one;
- new Rule id, enabled and Scope equal the preflight values;
- old SuBing Event count is zero;
- HTDY Rule, Scope and Event counts are unchanged;
- `lower_tf_confirmation` no longer exists;
- `action_id` and `strategy_payload` exist;
- Alembic head is `20260826_0042`.

## 14. Strategy Event payload

`strategy_payload` uses an exact JSON schema. Decimal values are canonical finite strings, timestamps are timezone-aware ISO-8601 UTC strings, dates are ISO dates, extra fields are rejected.

Common payload:

```json
{
  "schema_version": 1,
  "strategy_id": "subing_strategy_v1",
  "formula_version": "subing_strategy_15m_v1",
  "action_id": "subing-action:...",
  "episode_id": "subing-episode:...",
  "kind": "open_long",
  "symbol": "jm",
  "contract": "JM2601",
  "trading_day": "2026-08-27",
  "segment_start_trading_day": "2026-08-01",
  "opportunity_id": "subing-opportunity:...",
  "decision_at": "2026-08-27T02:15:00+00:00",
  "effective_open_at": "2026-08-27T02:15:00+00:00",
  "effective_bar_end": "2026-08-27T02:30:00+00:00",
  "reference_price": "1234.5",
  "fill_basis": "next_bar_open",
  "confirmation_source": "pivot_retest_rebreak",
  "reason_codes": [],
  "direction_context_source_day": "2026-08-26",
  "direction_context_target_day": "2026-08-27",
  "bound_reference_pivot": null,
  "entry": null,
  "holding_bar_count": null,
  "reference_change_percent": null
}
```

For `segment_terminal_close`, `effective_open_at` is null and `effective_bar_end` is the terminal 15m Bar end.

Close payloads require an exact `entry` object containing the entry Action id, kind, effective Bar, reference price and confirmation source, plus:

```text
holding_bar_count
reference_change_percent
all ordered reason_codes
```

The payload must be derivable from and consistent with the immutable core Action/Episode. The Event layer may not recalculate price change or reasons independently.

## 15. Event creation and one-shot notification

For a newly effective Action whose product is in the new Rule Scope:

```text
1. Validate Action and exact payload.
2. Insert AlertEvent and commit.
3. If action_id already exists with identical facts, do nothing.
4. If action_id exists with conflicting facts, fail closed.
5. Prepare the owner message from the committed payload.
6. Attempt PushPlus once.
7. Record Runtime transport status.
```

If Event persistence fails, no notification is attempted.

If message preparation or PushPlus fails, the committed Event remains. There is no retry, queue, replay, backfill, fallback or second audience.

Provider acceptance remains only request acceptance, not proof of WeChat delivery.

## 16. PushPlus message contract

### 16.1 Audience

All SuBing Strategy messages use the existing owner audience and `pushplus-wechat`. They never use the HTDY Topic.

### 16.2 Open messages

Long example:

```text
【苏冰策略】焦煤 · JM2601

15m 建多
建仓参考：xxx
原因：
- Pivot 回踩再突破
- 结构保护：前低 xxx
```

Short is symmetric:

```text
【苏冰策略】焦煤 · JM2601

15m 建空
建仓参考：xxx
原因：
- Pivot 回踩再突破
- 结构保护：前高 xxx
```

The confirmation-source line is required. The structure-protection line is included only when a valid bound Pivot exists.

### 16.3 Close messages

The user-approved format is exact:

```text
【苏冰策略】焦煤 · JM2601

15m 清多
建仓参考：xxx
清仓参考：xxx
参考变动：+x.xx%
原因：
- 跌破 EMA21
- MACD 高位死叉
```

`清空` is used for short exits. Multiple reason lines follow the Strategy policy order.

User-facing reason labels are fixed:

```text
EMA21_BREACH_LONG          → 跌破 EMA21
EMA21_BREACH_SHORT         → 突破 EMA21
PREVIOUS_BAR_LOW_BREACH    → 跌破上一根 15m 低点
PREVIOUS_BAR_HIGH_BREACH   → 突破上一根 15m 高点
BOUND_LOW_PIVOT_BREACH     → 跌破结构前低
BOUND_HIGH_PIVOT_BREACH    → 突破结构前高
MACD_HIGH_DEAD_CROSS       → MACD 高位死叉
MACD_LOW_GOLDEN_CROSS      → MACD 低位金叉
CONTRACT_SEGMENT_END       → 主力合约切换
```

Prices use canonical Decimal formatting without scientific notation. Reference change always shows an explicit sign and two decimal places.

No technical id, processing timestamp, provider reference, additional disclaimer or automatic link is appended to these message bodies.

## 17. HTTP and Web contracts

### 17.1 Alert HTTP

Replace old `buy / sell`-only SuBing presentation with a typed Strategy Action union.

`AlertEventOut` removes `lower_tf_confirmation` and adds:

```text
action_id: string | null
strategy_action: exact typed payload | null
```

HTDY returns null Strategy fields. SuBing Strategy requires both.

Current Formal Signal naming is replaced on the SuBing surface with:

```text
苏冰策略事件
建多 / 建空 / 清多 / 清空
```

No old Rule code or old Event compatibility branch remains.

### 17.2 Current strategy read

Add a read-only endpoint for the currently opened product:

```text
GET /api/v1/market/research/subing-strategy/current
series_kind=actual_dominant
symbol=<active product>
frequency=15m
```

It returns:

- exact policy and physical-segment identity;
- current `flat | long | short` state;
- pending Action summary, if any;
- current open Episode or latest completed Episode;
- latest completed 15m cutoff;
- target-day Daily Context availability;
- source mode `canonical | canonical_live`.

It reconstructs prior target days with the Historical Daily Watch V2 seam and the current target day with the current artifact. It uses the shared engine and performs no Event, Scope, Redis-status or notification write.

### 17.3 Live chart Marker and later Canonical reconciliation

A persisted Strategy Event maps to the same logical Marker identity as Historical Projection:

```text
marker dedupe key = action_id
marker.time       = strategy_payload.effective_bar_end
marker label      = 建多 / 建空 / 清多 / 清空
```

Before Canonical publication, Web displays the immutable Live Event facts. When Canonical later returns a Historical Action with the same `action_id`:

- exact matching contract, kind, decision time, effective Bar, fill basis and reference price dedupe to one Marker;
- a factual mismatch is not silently merged;
- Canonical Historical facts become the research-chart display authority;
- the original Event remains immutable as the notification fact;
- Web/API exposes `STRATEGY_ACTION_FACT_MISMATCH` rather than rewriting, duplicating or re-notifying.

This handles later Canonical corrections while preserving deterministic identity and Event immutability.

The existing old SuBing `buy / sell` Alert Marker conversion is removed.

### 17.4 Current Episode

On completed Live mutations, Web refreshes the current Strategy projection for the displayed `actual_dominant + 15m` product.

The strategy record area may show:

```text
持仓中
建仓参考
持有 Bar 数
当前参考变动
结构保护点
```

A close Event/current projection replaces it with the completed Episode.

A Strategy read failure degrades only the Strategy layer; Canonical K-lines and other Market facts remain usable.

## 18. Error handling

### 18.1 Product-level unavailable

A product becomes unavailable without stopping others for:

- missing or stale current Daily Context;
- unavailable causal Historical Context needed for restore;
- incomplete current-segment Canonical/Live data;
- contract/segment identity mismatch;
- missing exact first 1m open;
- out-of-order or conflicting Bar identity;
- Factor/Lifecycle warm-up insufficiency.

Missing current Daily Context blocks entry but does not block exits. Missing exact effective open cancels only the pending Action. A restore-context identity failure degrades the product rather than inventing an entry history.

### 18.2 Process-level fail-closed

The Runtime does not enter ready for:

- invalid Strategy, Lifecycle or calibration policy;
- unsupported schema or migration state;
- unavailable database or Redis transport;
- invalid Rule registry/database parity;
- invalid active/operational universe identity;
- notification configuration that fails existing security checks.

### 18.3 Scope and Event failures

- Invalid Scope isolates the Rule and marks processing degraded.
- Event conflict prevents notification.
- HTDY and SuBing processing remain isolated by Rule.
- Notification failures do not roll back committed Events.

## 19. Release `v1.8.7`

### 19.1 Release contents

The release candidate must contain:

- Stage 1 Historical Strategy Projection already in `develop`;
- Stage 2 shared incremental engine and Runtime evaluator;
- migration `20260826_0042`;
- direct Rule and Event replacement;
- owner notification formatter;
- live current Strategy HTTP/Web projection;
- Marker/Event dedupe and Canonical reconciliation;
- Runtime status schema v3;
- version synchronization to `1.8.7`.

### 19.2 Version identity

The release task updates every active identity together, including at least:

- API `APP_VERSION`;
- Web package/build identity;
- relevant Python/package metadata and lockfiles;
- `/api/health` release output;
- release notes and exact commit assertions.

No component may report `1.8.5`, `1.8.6` or an untagged development identity inside the final release artifact.

### 19.3 Release object

After independent release review and explicit approval:

```text
release PR → main
annotated tag v1.8.7
GitHub Release target = exact peeled tag commit
```

Creating `main`, tag or GitHub Release changes is a separate external-operation Gate.

## 20. Production migration and Runtime promotion

### 20.1 Coordinated cutover

After the release exists and the production-migration Gate is granted:

```text
1. Stop Alert first.
2. Stop API/Web and Market Live in a bounded maintenance window.
3. Verify exact v1.8.7 release/tag and production parent revision 0041.
4. Run migration 0042 once.
5. Read back Rule, Event, column, Scope and Alembic identities.
6. Do not start an older Runtime against the migrated schema.
```

After a separate Runtime-promotion Gate:

```text
1. Point the detached Runtime worktree at exact v1.8.7 tag.
2. Start Market Live and API/Web.
3. Validate Canonical, Redis, DB, Daily Watch and health.
4. Start Alert Runtime only when the Gate explicitly permits the preserved
   subing_strategy_v1 enabled/Scope state to produce future natural one-shot notifications.
5. Wait for active60 strategy recovery and read strategy_state=ready/degraded.
6. Do not synthesize a Strategy Event.
```

If the Runtime-promotion request does not explicitly include natural Strategy notification activation, Alert remains stopped or the Rule remains non-operational.

### 20.2 Forward-only failure posture

After migration 0042, do not switch back to v1.8.5. On startup failure:

- keep incompatible services stopped;
- retain the migrated database;
- diagnose and fix forward with a reviewed v1.8.7 patch or later release;
- do not downgrade the schema or restore deleted old Event history.

## 21. Owner canary

A fourth explicit external-operation Gate may send one existing generic owner canary after v1.8.7 promotion.

The canary:

- validates only the PushPlus owner transport request;
- creates no Strategy Event;
- does not fake a Strategy Action;
- does not prove WeChat delivery;
- does not authorize retries.

Natural `open_long / open_short / close_long / close_short` evidence is observed separately when the strategy genuinely acts.

## 22. Verification strategy

### 22.1 Shared engine parity

Tests must prove Historical and Live streaming equivalence for:

- all four entry confirmation sources;
- open long and short;
- all four ordinary exit families;
- multiple exit reasons on one 15m Bar;
- missing protective Pivot;
- session and overnight gaps;
- pending open and close;
- missing exact first 1m open;
- contract rollover terminal close;
- no reverse and no same-Bar re-entry;
- restart before and after effective open;
- prior-day Historical Context plus current-day artifact restoration;
- prefix invariance and stable ids.

### 22.2 Runtime tests

Use fake Redis, clock, DB session, Market reads and notification transport to verify:

- subscribe → restore → catch-up → ready ordering;
- active60 calculation independent of Scope;
- per-symbol degraded isolation;
- no Events during recovery;
- a pending future Action can notify after readiness;
- duplicate messages and duplicate action ids are idempotent;
- conflicting identity fails closed;
- Event commit precedes one-shot send;
- no retry or backfill;
- Runtime status schema v3.

### 22.3 Migration tests

Run against a disposable PostgreSQL database with realistic old Rule, Scope, SuBing Events and HTDY Events. Verify:

- preflight failures are atomic;
- old SuBing Events are deleted;
- HTDY Events are byte-equivalent at the logical field level;
- Rule id/enabled/Scope are preserved;
- Rule code is replaced;
- result-code constraints and widths accept only designed values;
- partial `action_id` uniqueness;
- lower_tf column removal;
- downgrade refusal.

### 22.4 Notification tests

Use exact string assertions for all four Action kinds, multiple reasons, missing bound Pivot and terminal close. The close fixture must match exactly:

```text
【苏冰策略】焦煤 · JM2601

15m 清多
建仓参考：xxx
清仓参考：xxx
参考变动：+x.xx%
原因：
- 跌破 EMA21
- MACD 高位死叉
```

### 22.5 Web tests

Verify:

- no old Rule code or buy/sell SuBing labels;
- typed Strategy Event rendering;
- event Marker anchored to effective 15m Bar;
- `action_id` dedupe against Historical Projection;
- factual mismatch produces `STRATEGY_ACTION_FACT_MISMATCH` and Canonical display authority;
- current open Episode update;
- symbol/frequency/series stale-response isolation;
- pan/prepend behavior remains stable;
- Strategy-layer failure does not break K-lines.

### 22.6 Full validation

Before integration/release, run the applicable repository commands from `TESTING.md`, including:

- complete/focused Python tests;
- Ruff and Mypy;
- isolated Alembic tests;
- canonical consistency;
- Web unit, typecheck, production build and Playwright;
- OpenSpec strict validation;
- secret scan and diff check;
- exact release-version consistency.

### 22.7 Read-only shadow acceptance

Before production mutation, run the completed-Live evaluator with no Event writer and no notification sender against an authorized read-only stream or recorded production-format Bar stream.

Required evidence:

- state restoration succeeds or reports bounded per-symbol degradation;
- no Historical/Live Action divergence for identical input prefixes;
- no source identity crossing;
- no external writes;
- absence of a natural Action is not manufactured into evidence.

After Runtime promotion, natural Event and provider-acceptance evidence remains observational and does not convert the strategy into an OOS-validated trading strategy.

## 23. Delivery and Gate sequence

### Repository-development Gates

```text
1. User approves this written Spec.
2. Create and approve a detailed Lane 3 Implementation Plan.
3. Implement in an isolated task branch/worktree.
4. Independent exact-head Review.
5. Human decision: 允许集成 develop.
```

### External-operation Gates

```text
A. 允许发布 main / annotated tag / GitHub Release v1.8.7
B. 允许执行 production migration 20260826_0042
C. 允许 Runtime promotion to exact v1.8.7, with explicit wording if
   future natural Strategy notifications are also activated
D. 允许一次真实 owner PushPlus canary
```

No Gate implies the next one. Migration success does not authorize Runtime; Runtime promotion does not authorize canary; canary acceptance does not prove delivery.

## 24. Design review findings

The following issues were found during design review and are resolved by this Spec:

1. **Future Marker time conflict:** `AlertEvent.bar_end` cannot be the future incomplete effective Bar. It is fixed to `decision_at`; the typed payload owns `effective_bar_end`.
2. **Effective trading-day ambiguity:** Event `trading_day` follows the effective Action, not necessarily the decision Bar.
3. **Historical/Live duplicate risk:** a partial unique `action_id` and Web `action_id` dedupe are mandatory.
4. **Live/Canonical factual correction:** same-id price or fact mismatch is surfaced; Canonical becomes chart authority without rewriting the immutable Event.
5. **Old result-code width:** current storage sized for `buy/sell` cannot safely hold `close_short`; migration widens the array element type.
6. **Rule-specific payload validity:** the database permits the finite global code union, while application contracts enforce exact HTDY versus Strategy combinations.
7. **Warm-up message gap:** subscribe-first plus final completed-Live catch-up restores state without delayed notifications.
8. **Historical Context restoration:** prior target days are reconstructed causally; today's artifact is never projected backward.
9. **Event-history-as-state risk:** current Strategy state is reconstructed from market facts, never inferred from scoped AlertEvents.
10. **Direct replacement rollback risk:** deleting old history and changing schema makes the cutover explicitly forward-only.
11. **Implicit real-notification risk:** Runtime promotion must explicitly mention whether preserved enabled/Scope state may begin natural Strategy notifications.
12. **Scope/state coupling:** active60 calculation and product Scope are separated.
13. **Trigger/protective Pivot confusion:** Stage 2 consumes the already corrected `bound_reference_pivot`; it never substitutes `trigger_reference_pivot`.
14. **Notification format drift:** exact user-approved close text and fixed reason labels are contractual tests.
15. **Over-design risk:** no extra process, state table, queue, retry, archive or generic strategy framework is introduced.

Placeholder scan: no `TBD`, `TODO`, `FIXME` or unresolved choice remains.  
Consistency review: Runtime, migration, Event, Web and release identities use the same four Action kinds and the same Stage 1 strategy policy.  
Scope review: this Spec covers only Stage 2, direct Alert replacement and release/deployment `v1.8.7`; OOS and automatic trading remain separate future work.

## 25. Acceptance conclusion

When the implementation satisfies this Spec and its Plan, the correct repository-level conclusion may be:

```text
允许集成 develop
```

Only after the separately approved external-operation sequence may later conclusions be considered:

```text
允许发布 main/tag
允许 Runtime promotion
```

This Spec itself authorizes no implementation or external mutation.
