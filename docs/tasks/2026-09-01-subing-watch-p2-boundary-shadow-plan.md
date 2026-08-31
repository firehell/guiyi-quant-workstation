# P2 — 15m 边界证明、Shadow Runtime 与 Health 计划

> **Execution:** Use TDD. This packet establishes trusted Runtime facts; no Watch Event or real send is allowed.

状态：`PLAN_READY_FOR_USER_REVIEW`

父计划：`docs/tasks/2026-09-01-alert-reliability-subing-watch-15m-implementation-plan.md`

Issue：`#286`

Lane：Lane 3 Runtime truth / operational evidence。

## Goal

建立 Session-aware `expected_symbols`、冻结 15m boundary ledger、短 TTL `alert:watch-runtime-status`、active60 隔离 evaluator 和 Shadow Runtime，使系统即使一条 completed-15m trigger 都没收到，也能在 grace 后显式证明 `missing_trigger`，而不是继续显示绿色 heartbeat。

P2 固定为 Shadow：不创建 Watch DB Rule、不写 Watch `AlertEvent`、不发送 Watch 通知、不修改生产 Scope。

## Workspace

```text
base: P1 合入后的最新 origin/develop
branch: feature/subing-watch-boundary-shadow
worktree: 新 task worktree
integration: develop
PR: Draft PR required
review: independent Sol/high Runtime checkpoint
human Gate: 允许集成 develop
```

## File Map

### New

```text
services/quant-api/app/alerts/watch_expectation.py
services/quant-api/app/alerts/watch_boundary.py
services/quant-api/app/alerts/watch_status.py
services/quant-api/app/alerts/subing_watch_runtime.py
services/quant-api/tests/test_watch_expectation.py
services/quant-api/tests/test_watch_boundary.py
services/quant-api/tests/test_watch_status.py
services/quant-api/tests/test_subing_watch_runtime.py
```

### Modified

```text
services/quant-api/app/alerts/runtime.py
services/quant-api/app/alerts/composition.py
services/quant-api/app/services/runtime_health.py
services/quant-api/app/schemas/runtime.py
services/quant-api/tests/test_alert_runtime.py
services/quant-api/tests/test_alert_notification_composition.py
services/quant-api/tests/test_runtime_health.py
```

## Task 1 — Resolve Session authority expected boundaries

### Files

- Create: `services/quant-api/app/alerts/watch_expectation.py`
- Test: `services/quant-api/tests/test_watch_expectation.py`

### Contracts

```python
@dataclass(frozen=True, slots=True)
class WatchBoundaryKey:
    trading_day: date
    frequency: Literal["15m"]
    bar_end: datetime

@dataclass(frozen=True, slots=True)
class WatchBoundaryExpectation:
    key: WatchBoundaryKey
    expected_symbols: tuple[str, ...]
    bucket_starts: Mapping[str, datetime]
    expectation_digest: str

class WatchExpectationError(RuntimeError):
    code: Literal[
        "BOUNDARY_EXPECTATION_UNAVAILABLE",
        "TRADING_DAY_UNAVAILABLE",
        "TRADING_SESSION_UNAVAILABLE",
        "TRADING_SESSION_INVALID",
    ]

class WatchBoundaryExpectationResolver:
    def due(
        self,
        *,
        now: datetime,
        not_before: datetime,
    ) -> tuple[WatchBoundaryExpectation, ...]: ...
```

The resolver reads only:

```text
operational_products.txt
Instrument.exchange_code
TradingCalendar
resolved_session_windows_for_trading_day
bucket_window_for_bar(session_window, BarFrequency.M15, probe_bar_end)
resolve_current_trading_day
```

It never reads Pub/Sub arrival counts to determine the denominator.

### RED fixtures

Use SQLite eight-table facts for:

```text
rb: night + morning + afternoon
jm: different night close + day
if: day only + lunch break
sc: crossing-midnight night + day
```

Tests prove:

- same `bar_end` can expect only a subset;
- expected count can be less than 60 and still valid;
- lunch/session gaps create no boundary;
- no-night product is absent from night expected set;
- short final session bucket ends at authoritative session end;
- night natural date maps to one trading-day identity;
- non-trading day creates no due boundary;
- duplicate/overlapping active Session rows fail closed.

### Zero-trigger regression

With no Pub/Sub message, heartbeat-time discovery alone must produce the due BoundaryExpectation. After grace, the ledger can classify every pending symbol as missing. Do not implement “open boundary when the first trigger arrives”.

### Restart-first-full-boundary

If Runtime starts at 09:32 during a 09:30–09:45 bucket, that partial bucket is excluded. The first eligible boundary is the next bucket whose start is not earlier than `not_before`.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_watch_expectation.py \
  services/quant-api/tests/data_foundation/test_session_clock.py \
  services/quant-api/tests/data_foundation/test_aggregation.py

git add \
  services/quant-api/app/alerts/watch_expectation.py \
  services/quant-api/tests/test_watch_expectation.py
git commit -m "feat(alerts): resolve expected Watch boundaries"
```

## Task 2 — Implement pure boundary ledger and normal silence

### Files

- Create: `services/quant-api/app/alerts/watch_boundary.py`
- Test: `services/quant-api/tests/test_watch_boundary.py`

### Contracts

```python
WatchProductOutcome = Literal[
    "evaluated_no_signal",
    "evaluated_candidate",
    "source_unavailable",
    "processing_failed",
    "missing_trigger",
]

@dataclass(frozen=True, slots=True)
class WatchBoundarySummary:
    schema_version: Literal[1]
    runtime_instance_id: str
    boundary: WatchBoundaryKey
    finalized_at: datetime
    expected_count: int
    evaluated_count: int
    no_signal_count: int
    candidate_count: int
    source_unavailable_count: int
    processing_failed_count: int
    missing_trigger_count: int
    event_created_count: int
    event_deduplicated_count: int
    transport_attempt_count: int
    provider_accepted_count: int
    notification_failure_count: int
    normal_silence: bool
    candidate_ids: tuple[str, ...]
    public_reason_codes: tuple[str, ...]
    late_duplicate_count: int

class WatchBoundaryLedger:
    def open(self, expectation: WatchBoundaryExpectation) -> None: ...
    def record_evaluation(self, key, symbol, evaluation) -> None: ...
    def record_event_created(self, key, candidate_id) -> None: ...
    def record_event_deduplicated(self, key, candidate_id) -> None: ...
    def record_event_failed(self, key, candidate_id, reason_code) -> None: ...
    def record_transport_attempt(self, key, candidate_id) -> None: ...
    def record_provider_accepted(self, key, candidate_id) -> None: ...
    def record_notification_failed(self, key, candidate_id, reason_code) -> None: ...
    def finalize_due(self, *, now: datetime, mode: Literal["shadow", "active"]) -> tuple[WatchBoundarySummary, ...]: ...
```

### State rules

Each expected symbol transitions once from `pending` to exactly one final product outcome. Same evaluation duplicate is no-op before freeze. Conflicting duplicate raises `WATCH_BOUNDARY_CONFLICT`.

`missing_trigger` appears only at finalize when `now >= bar_end + LIVE_SESSION_END_ARRIVAL_GRACE` and the expected symbol remains pending.

Finalize when:

```text
all expected product outcomes terminal
and in active mode all Candidate downstream paths terminal
or grace reached
```

Candidate downstream terminal values:

```text
event_deduplicated
event_persist_failed
event_created + notification_preparation_failed
event_created + transport_failed
event_created + provider_accepted
```

Shadow Candidate is terminal immediately and all Event/transport counters remain zero.

### Counter invariants

```text
expected_count
= no_signal_count
+ candidate_count
+ source_unavailable_count
+ processing_failed_count
+ missing_trigger_count

evaluated_count = no_signal_count + candidate_count

event_created_count <= candidate_count
event_deduplicated_count <= candidate_count
transport_attempt_count <= event_created_count
provider_accepted_count <= transport_attempt_count
```

`normal_silence=true` only when every expected symbol is `evaluated_no_signal` and all failure/missing/Candidate counts are zero.

### Freeze / late-arrival rules

After summary freeze:

- a late identical message increments `late_duplicate_count` in current in-memory diagnostics only;
- it cannot rewrite missing to evaluated;
- it cannot create delayed Event;
- it cannot cause delayed send;
- a conflicting late message records a fixed public conflict reason and leaves the frozen summary unchanged.

### RED matrix

- all no-signal normal silence;
- one Candidate;
- source unavailable;
- evaluator failure;
- partial arrival before grace;
- missing after grace;
- expected count non-60;
- duplicate and conflict;
- active downstream pending;
- Event persist failure;
- notification preparation/transport/acceptance failure;
- freeze and late arrival;
- all count invariants.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_watch_boundary.py

git add \
  services/quant-api/app/alerts/watch_boundary.py \
  services/quant-api/tests/test_watch_boundary.py
git commit -m "feat(alerts): add Watch boundary ledger"
```

## Task 3 — Add bounded TTL status and health projection

### Files

- Create: `services/quant-api/app/alerts/watch_status.py`
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/app/schemas/runtime.py`
- Test: `services/quant-api/tests/test_watch_status.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`

### Status contract

```text
key=alert:watch-runtime-status
schema_version=1
ttl_seconds=90
mode=shadow|active
recent_boundaries<=8
recent_candidates<=20
current_open_boundaries<=4
```

Payload:

```text
generated_at
runtime_instance_id
mode
formula_version
latest_finalized_boundary
recent_boundaries
recent_candidates
current_open_boundaries
```

Allowed public reason codes exactly:

```text
BOUNDARY_EXPECTATION_UNAVAILABLE
LIVE_TRIGGER_MISSING
SOURCE_WINDOW_UNAVAILABLE
SOURCE_IDENTITY_INVALID
PHYSICAL_SEGMENT_PENDING
EVALUATION_FAILED
EVENT_PERSIST_FAILED
NOTIFICATION_PREPARATION_FAILED
NOTIFICATION_TRANSPORT_FAILED
NOTIFICATION_ACCEPTANCE_INVALID
WATCH_STATUS_WRITE_FAILED
```

Reject unknown fields, count violations, naive/future timestamps, unsorted/duplicate Candidate IDs, provider references, token/Topic text, SQL, stack traces, raw exceptions or private paths.

### Redis store

```python
class RedisWatchStatusStore:
    KEY = "alert:watch-runtime-status"
    TTL_SECONDS = 90

    def write(self, status: WatchRuntimeStatus) -> None: ...
    def read(self) -> WatchRuntimeStatus | None: ...
```

A failed `SET`/TTL write raises `WATCH_STATUS_WRITE_FAILED`. Runtime health degrades and cannot continue reporting normal silence.

### Health shape

Extend existing `GET /api/runtime/health` under `components.alert.watch`:

```text
status=ok|degraded|unobserved
mode=shadow|active|unobserved
formula_version
last_generated_at
latest_finalized_boundary
recent_candidates
open_boundary_count
error_type
```

Rules:

- missing key = unobserved, never ok;
- stale/invalid key = degraded;
- normal-silence finalized boundary = ok;
- Candidate and complete active/shadow chain = ok;
- any unavailable/failure/missing/open-stale boundary = degraded;
- top-level `readonly=true` and all `would_*` flags remain false.

Health request only reads/validates; it does not write Redis or start work.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_watch_status.py \
  services/quant-api/tests/test_runtime_health.py

git add \
  services/quant-api/app/alerts/watch_status.py \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/schemas/runtime.py \
  services/quant-api/tests/test_watch_status.py \
  services/quant-api/tests/test_runtime_health.py
git commit -m "feat(runtime): expose Watch boundary proof"
```

## Task 4 — Current/restore source and isolated active60 evaluator

### Files

- Create: `services/quant-api/app/alerts/subing_watch_runtime.py`
- Test: `services/quant-api/tests/test_subing_watch_runtime.py`

### Contracts

```python
@dataclass(frozen=True, slots=True)
class SubingWatchRuntimeProductStatus:
    symbol: str
    state: Literal["warming", "ready", "unavailable"]
    cutoff_15m: datetime | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SubingWatchRuntimeResult:
    evaluation: SubingWatchEvaluation | None
    product_status: SubingWatchRuntimeProductStatus

class SubingWatchRuntimeEvaluator:
    @property
    def products(self) -> tuple[str, ...]: ...
    def restore_all(self, *, started_at: datetime) -> tuple[SubingWatchRuntimeResult, ...]: ...
    def process_completed_15m(self, *, symbol: str, bar: CanonicalBar, processing_at: datetime) -> SubingWatchRuntimeResult: ...
```

### Behavior

- one isolated state per operational product;
- restore current physical segment deterministically from P1 current service;
- startup restore/catch-up produces no natural Candidate evidence, Event or send;
- natural completed 15m after ready cutoff is eligible for boundary accounting;
- same-contract next trading day continues only when current identity is authoritative;
- formal MainContractMap rank1 rollover initializes a new segment;
- different/pending contract marks only that product unavailable;
- single-product failure does not block other Watch products or HTDY;
- no 1m/5m companion, Daily Context, Action or Episode dependency.

### Tests

- all products restore ready/unavailable independently;
- natural step equals Historical replay at same cutoff;
- restart then append equals full replay;
- same duplicate no-op;
- conflicting duplicate unavailable;
- same-contract trading-day continuation;
- rank1 physical rollover reset;
- different contract pending;
- one product source failure isolation;
- startup output excluded from natural boundary evidence.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/data_foundation/test_subing_watch_current_service.py \
  services/quant-api/tests/research/test_subing_watch_replay.py

git add \
  services/quant-api/app/alerts/subing_watch_runtime.py \
  services/quant-api/tests/test_subing_watch_runtime.py
git commit -m "feat(alerts): restore SuBing Watch active60 state"
```

## Task 5 — Wire Shadow into the existing Alert Runtime loop

### Files

- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_alert_notification_composition.py`

### Integration boundary

Do not add formula, Session SQL or status JSON logic to the existing large `alerts/runtime.py`. That file only:

```text
starts SubingWatchRuntime in shadow
forwards natural completed 15m triggers
calls Watch tick from existing heartbeat loop
keeps HTDY and legacy Strategy orchestration isolated
writes bounded Watch status through collaborator
```

No new scheduler, thread, process or second Pub/Sub subscription is added.

### Shadow hard lock

P2 composition always constructs:

```python
SubingWatchRuntime(mode="shadow", ...)
```

Any environment/config attempt to request active raises `WATCH_ACTIVE_MODE_UNAVAILABLE`. Active mode is not wired until P4 single-lineage support.

### Required tests

- natural 15m message records one product outcome;
- 1m/5m/30m/60m do not step Watch base formula;
- heartbeat discovers due boundary even with zero messages;
- grace creates missing trigger;
- startup drain does not create natural Candidate/boundary evidence;
- Shadow Candidate count increments but Event/transport counts remain zero;
- sender and Watch DB Rule queries remain zero;
- legacy Strategy failure does not block Watch boundary or HTDY;
- status write failure degrades Watch health;
- Runtime close cleans message source exactly once.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_watch_expectation.py \
  services/quant-api/tests/test_watch_boundary.py \
  services/quant-api/tests/test_watch_status.py \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_runtime_health.py

git add \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/app/alerts/composition.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_composition.py
git commit -m "feat(alerts): run SuBing Watch in shadow"
```

## Packet Verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_watch_expectation.py \
  services/quant-api/tests/test_watch_boundary.py \
  services/quant-api/tests/test_watch_status.py \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_runtime_health.py

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/alerts \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/schemas/runtime.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/alerts \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/schemas/runtime.py \
  services/quant-api/tests/test_watch_expectation.py \
  services/quant-api/tests/test_watch_boundary.py \
  services/quant-api/tests/test_watch_status.py \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/test_runtime_health.py
```

## Independent Runtime Review

Pin exact head and verify:

- expected set comes from Session authority, not arrivals;
- zero-trigger outage is detected;
- restart excludes already-open bucket;
- shared `LIVE_SESSION_END_ARRIVAL_GRACE` is reused;
- normal-silence and counter invariants;
- late arrival cannot rewrite frozen evidence or cause side effects;
- no scheduler/thread/third PostgreSQL table;
- Shadow has no Rule/Event/send;
- bounded status/TTL contains no private data;
- status missing/stale/incomplete never appears green;
- Watch failure isolation from HTDY and legacy research.

PR stops at `允许集成 develop`. No Runtime promotion or real Redis write outside tests is authorized.
