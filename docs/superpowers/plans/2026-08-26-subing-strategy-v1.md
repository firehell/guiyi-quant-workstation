# SuBing Strategy V1 Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the read-only `SuBing Strategy V1` historical projection on `actual_dominant + 15m`, with deterministic open/close Actions, complete Episodes, time-anchored chart markers, and a compact strategy-record panel.

**Architecture:** A source-specific SuBing strategy package composes the existing Daily Watch V2 direction context, SuBing Factor/Signal/Lifecycle facts, and one pure 15m reducer. The historical service reconstructs each physical rank1 segment from its true segment start, optionally uses a non-authoritative local cache, then crops Actions and Episodes to the requested window. Web consumes one strict Strategy response; it never re-evaluates formulas.

**Tech Stack:** Python 3.13+, `Decimal`, frozen dataclasses, exact JSON contracts, Pydantic/FastAPI, SQLAlchemy read-only calendar resolution, `MarketDataService`, pytest, Ruff, Mypy, Vue 3, TypeScript, Vitest, Naive UI, Lightweight Charts, Playwright.

**Spec:** [SuBing Strategy V1 Design Spec](../specs/2026-08-26-subing-strategy-v1-design.md)

**Planning base:** `develop@fee29d2f8a2528b0f5ab05ce99be97c7072fc8de`; implementation must branch from the then-latest `origin/develop` containing both approved documents.

## Global Constraints

- This plan implements **Stage 1 only**. Do not add completed-Live evaluation, `subing_strategy_v1` Alert Rule, migration, Scope mutation, notification, Runtime switch, release, tag, or `main` change.
- Work from the latest `origin/develop` that contains this plan and the approved Spec. Create one isolated worktree and branch: `research/subing-strategy-v1`.
- Integration target is `develop`; require an independent Review and a human `允许集成 develop` decision. Do not auto-merge.
- Never touch the `main` or Runtime worktree. Delete the task worktree and merged branch only after the merge is confirmed in `develop`.
- Preserve `auto_order=false`. No account, order, commission, slippage, margin, leverage, contract-value PnL, portfolio state, or automatic trading path.
- Keep the four public overlays exactly `none | subing | jdj_strategy | htdy`; `subing_strategy_v1` replaces only the old SuBing historical single-signal projection inside the existing `subing` overlay.
- Historical reads go only through `MarketDataService` and `ActualDominantResearchSegmentLoader` / `ActualDominantStitchedResearchLoader`. Do not glob Canonical files, infer rank1, or synthesize cross-frequency fallbacks.
- Public strategy identity is exactly `actual_dominant + 15m`. Existing 5m/15m current SuBing observation may remain, but no 5m Strategy Action, Episode, Marker, or API request is valid.
- Use only completed bars. D1/60m context must be causally equivalent to Daily Watch V2 for the target trading day. The decision Bar never reads the next Bar open before the decision exists.
- Every physical contract segment starts flat and ends flat. No Factor state, opportunity, pending action, position, Pivot, Action, or Episode crosses a segment boundary.
- Entry confirmation sources are exactly `formal_v1 | momentum_hold | pivot_break_hold | pivot_retest_rebreak`.
- Exit logic is full-position `OR`: EMA21, previous 15m Bar extreme, bound Lifecycle Pivot when available, or strict high-dead/low-golden MACD reverse cross. Preserve every same-Bar reason in policy order.
- Decision time is the completed 15m Bar end. Ordinary effective price is the next existing same-segment 15m Bar open. Missing next Bar cancels the pending action; never substitute the current close.
- Segment terminal close is the old segment final 15m close with `CONTRACT_SEGMENT_END`.
- The cache is expendable and non-authoritative. A cache failure must not alter the calculated projection. Unit tests use disposable temporary roots; real-data acceptance runs cache-disabled unless the user separately authorizes a real observation-root write.
- Web displays `参考变动`, `历史因果投影`, `模拟动作`, and `非实际成交`. Do not display account `收益`, `盈亏`, win rate, max drawdown, or an equity curve.
- Each task follows red → green → refactor. Write the named failing test, run it and observe the expected failure, implement the minimum behavior, rerun focused and affected regression tests, then commit only the task files.
- Do not update `STATUS.md` with intended results. Update it only after the tests, read-only smoke, manual corpus, and independent Review have actually completed.

## Codex Execution Card

| Field | Value |
|---|---|
| Lane | Lane 3 — strategy formula, causality, historical projection |
| Entry | Codex App |
| Model | Sol |
| Reasoning | High |
| Session | New implementation session; separate new Review session at the end |
| Plan | Plan-then-execute after explicit implementation approval |
| Workspace | New task worktree from latest `develop`, branch `research/subing-strategy-v1` |
| Integration | PR to `develop`; no automatic merge |
| Human Gates | Plan approval, independent Review, `允许集成 develop`; Stage 2 remains separately blocked |

## File Map and Locked Interfaces

### New backend package

```text
services/quant-api/app/market_data/subing_strategy/
├── __init__.py             public exports only
├── policy.py               exact V1 JSON loader and immutable policy contract
├── contracts.py            enums, Action/Episode/frame contracts, canonical ids
├── direction_context.py    historical Daily Watch V2 target-day direction projection
├── entry_projection.py     Lifecycle trace -> one 15m entry candidate per opportunity
├── engine.py               pure flat/long/short + pending-action reducer
├── replay.py               segment-local Factor/Lifecycle/frame construction
├── cache.py                safe expendable file cache
└── service.py              actual-dominant multi-segment historical projection
```

### Locked public Python interfaces

```python
class SubingStrategyPositionState(StrEnum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


class SubingStrategyActionKind(StrEnum):
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


class SubingStrategyFillBasis(StrEnum):
    NEXT_BAR_OPEN = "next_bar_open"
    SEGMENT_TERMINAL_CLOSE = "segment_terminal_close"


class SubingStrategyDirection(StrEnum):
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    NO_NEW_ENTRY = "no_new_entry"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SubingStrategyHistoricalRequest:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    since: date
    through: date


class SubingStrategyHistoricalProjectionService:
    def history(
        self,
        request: SubingStrategyHistoricalRequest,
    ) -> SubingStrategyHistoricalProjection:
        """Return a read-only, deterministic historical Strategy projection."""
```

### Locked HTTP surface

```text
GET /api/v1/market/research/subing-strategy/history
```

The old route is retired atomically with the Web cutover:

```text
GET /api/v1/market/research/subing/history
```

### Task dependency order

```text
Task 1 policy/contracts
  -> Task 2 Daily Watch context equivalence
  -> Task 3 Lifecycle entry projection
  -> Task 4 pure reducer
  -> Task 5 segment replay + historical service
  -> Task 6 expendable cache + composition
  -> Task 7 HTTP contract + old route retirement
  -> Task 8 Web contract + pagination/markers
  -> Task 9 Strategy record UI + acceptance + Review Gate
```

---

## Task 1: Create the worktree, exact policy, contracts, and deterministic identities

**Files:**

- Create: `data/research_policies/subing_strategy_v1.json`
- Create: `services/quant-api/app/market_data/subing_strategy/__init__.py`
- Create: `services/quant-api/app/market_data/subing_strategy/policy.py`
- Create: `services/quant-api/app/market_data/subing_strategy/contracts.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_policy.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_contracts.py`

**Interfaces:**

- Produces: `SubingStrategyPolicy`, `load_subing_strategy_policy`, all public enums/dataclasses, `subing_opportunity_key_id`, `subing_strategy_action_id`, and `subing_strategy_episode_id`.
- Consumes: existing `SubingOpportunityKey`, `ConfirmedPivot`, `ConfirmationSource`, `SubingDirection`, `CanonicalBar`, and `SubingFactorSnapshot`.

- [ ] **Step 1: Create the isolated Stage 1 worktree from the latest `origin/develop`.**

```bash
git fetch origin
git worktree add ../guiyi-subing-strategy-v1 \
  -b research/subing-strategy-v1 origin/develop
git -C ../guiyi-subing-strategy-v1 status --short
git -C ../guiyi-subing-strategy-v1 rev-parse HEAD
```

Expected: clean status and a base SHA containing the approved Spec and this plan.

- [ ] **Step 2: Prepare locked dependencies before writing code.**

```bash
cd ../guiyi-subing-strategy-v1
uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

- [ ] **Step 3: Write failing exact-policy tests.**

```python
from copy import deepcopy
from pathlib import Path

import pytest

from app.market_data.subing_strategy.policy import (
    SubingStrategyPolicyError,
    load_subing_strategy_policy,
)


def test_loads_exact_subing_strategy_v1_policy() -> None:
    policy = load_subing_strategy_policy()
    assert policy.strategy_id == "subing_strategy_v1"
    assert policy.formula_version == "subing_strategy_15m_v1"
    assert policy.decision_frequency.value == "15m"
    assert tuple(source.value for source in policy.allowed_confirmation_sources) == (
        "formal_v1",
        "momentum_hold",
        "pivot_break_hold",
        "pivot_retest_rebreak",
    )


def test_policy_rejects_one_changed_field(tmp_path: Path) -> None:
    payload = deepcopy(EXACT_POLICY_PAYLOAD)
    payload["execution"]["allow_reverse"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SubingStrategyPolicyError) as exc:
        load_subing_strategy_policy(path)
    assert exc.value.code == "SUBING_STRATEGY_POLICY_INVALID"
```

- [ ] **Step 4: Write failing contract and identity tests.**

```python
def test_action_identity_is_stable_when_reference_price_changes() -> None:
    first = action_fixture(reference_price=Decimal("100"))
    second = action_fixture(reference_price=Decimal("101"))
    assert subing_strategy_action_id(first.identity_fields()) == first.action_id
    assert subing_strategy_action_id(second.identity_fields()) == second.action_id
    assert first.action_id == second.action_id


def test_action_identity_changes_for_effective_bar() -> None:
    first = action_fixture(effective_bar_end=aware_dt(10, 15))
    second = action_fixture(effective_bar_end=aware_dt(10, 30))
    assert first.action_id != second.action_id


def test_episode_rejects_cross_contract_exit() -> None:
    with pytest.raises(SubingStrategyContractError):
        SubingStrategyEpisode.from_actions(
            entry_action=open_action(contract="JM2601"),
            exit_action=close_action(contract="JM2605"),
            completed_bars=bars,
            latest_reference_price=None,
        )
```

- [ ] **Step 5: Run the focused tests and confirm import failures.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_policy.py \
  services/quant-api/tests/research/test_subing_strategy_contracts.py
```

Expected: FAIL because the package and policy do not exist.

- [ ] **Step 6: Add the exact policy JSON.**

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

- [ ] **Step 7: Implement the exact loader with `load_exact_json`.**

```python
_POLICY_PATH = PROJECT_ROOT / "data/research_policies/subing_strategy_v1.json"
_STRATEGY_ID = "subing_strategy_v1"
_FORMULA_VERSION = "subing_strategy_15m_v1"


class SubingStrategyPolicyError(ValueError):
    code = "SUBING_STRATEGY_POLICY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyPolicy:
    strategy_id: str
    formula_version: str
    research_only: bool
    series_kind: SeriesKind
    decision_frequency: BarFrequency
    lifecycle_policy_id: str
    allowed_confirmation_sources: tuple[ConfirmationSource, ...]


def load_subing_strategy_policy(path: Path | None = None) -> SubingStrategyPolicy:
    payload = load_exact_json(
        path or _POLICY_PATH,
        _EXPECTED_PAYLOAD,
        SubingStrategyPolicyError,
    )
    return SubingStrategyPolicy(
        strategy_id=payload["strategy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
        series_kind=SeriesKind(payload["series_kind"]),
        decision_frequency=BarFrequency(payload["decision_frequency"]),
        lifecycle_policy_id=payload["entry"]["lifecycle_policy_id"],
        allowed_confirmation_sources=tuple(
            ConfirmationSource(value)
            for value in payload["entry"]["allowed_confirmation_sources"]
        ),
    )
```

The dataclass `__post_init__` must reject every value not exactly equal to the V1 constants.

- [ ] **Step 8: Implement immutable contracts and canonical ids.**

Use compact sorted UTF-8 JSON and full lowercase SHA-256:

```python
def _canonical_id(prefix: str, payload: Mapping[str, object]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{sha256(body).hexdigest()}"


def subing_opportunity_key_id(key: SubingOpportunityKey) -> str:
    return _canonical_id(
        "subing-opportunity",
        {
            "policy_id": key.policy_id,
            "symbol": key.symbol,
            "contract": key.contract,
            "segment_start_trading_day": key.segment_start_trading_day.isoformat(),
            "direction": key.direction.value,
            "origin_at": key.origin_at.astimezone(UTC).isoformat(),
        },
    )
```

Define the complete immutable contracts in `contracts.py`:

```python
class SubingStrategyEpisodeState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SubingStrategyAction:
    action_id: str
    episode_id: str
    strategy_id: str
    formula_version: str
    kind: SubingStrategyActionKind
    symbol: str
    contract: str
    trading_day: date
    segment_start_trading_day: date
    opportunity_id: str
    decision_at: datetime
    effective_bar_end: datetime
    reference_price: Decimal
    fill_basis: SubingStrategyFillBasis
    confirmation_source: ConfirmationSource | None
    reason_codes: tuple[str, ...]
    direction_context_source_day: date | None
    direction_context_target_day: date | None
    bound_reference_pivot: ConfirmedPivot | None


@dataclass(frozen=True, slots=True)
class SubingStrategyEpisode:
    episode_id: str
    direction: SubingDirection
    entry_action: SubingStrategyAction
    exit_action: SubingStrategyAction | None
    state: SubingStrategyEpisodeState
    holding_bar_count: int
    reference_change_percent: Decimal | None
    current_reference_change_percent: Decimal | None
    latest_reference_price: Decimal | None
    exit_reason_codes: tuple[str, ...]
    structure_exit_available: bool

```

Implement this exact classmethod on `SubingStrategyEpisode`:

```text
from_actions(
  *,
  entry_action: SubingStrategyAction,
  exit_action: SubingStrategyAction | None,
  completed_15m_bars: Sequence[CanonicalBar],
  latest_reference_price: Decimal | None,
) -> SubingStrategyEpisode
```

It performs real validation and derivation in this task and enforces:

```text
same strategy/formula/symbol/contract/segment/opportunity
entry kind is open_long or open_short
exit kind matches the entry direction
exit decision/effective time is not before entry effective time
holding_bar_count counts completed 15m Bars from entry effective Bar through exit decision Bar, inclusive
open Episode uses latest completed close only as current reference
```

`SubingStrategyAction.identity_fields()` includes strategy/formula version, symbol, contract, segment start, opportunity id, kind, decision time, effective Bar time, and fill basis. It excludes reference price, display labels, request window, cache state, and generation time. `episode_id` is deterministically derived from the entry Action identity; a close Action must carry that same Episode id.

- [ ] **Step 9: Run focused and existing SuBing contract regressions.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_policy.py \
  services/quant-api/tests/research/test_subing_strategy_contracts.py \
  services/quant-api/tests/research/test_subing_lifecycle_contracts.py \
  services/quant-api/tests/test_indicator_registry_v1.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/subing_strategy \
  services/quant-api/tests/research/test_subing_strategy_policy.py \
  services/quant-api/tests/research/test_subing_strategy_contracts.py
```

- [ ] **Step 10: Commit Task 1.**

```bash
git add data/research_policies/subing_strategy_v1.json \
  services/quant-api/app/market_data/subing_strategy \
  services/quant-api/tests/research/test_subing_strategy_policy.py \
  services/quant-api/tests/research/test_subing_strategy_contracts.py
git commit -m "feat(subing): define strategy v1 policy and contracts"
```

---

## Task 2: Reuse Daily Watch V2 as the exact historical D1/60m direction context

**Files:**

- Modify: `services/quant-api/app/market_data/subing_daily_watch.py`
- Modify: `services/quant-api/app/market_data/subing_daily_watch_calendar.py`
- Create: `services/quant-api/app/market_data/subing_strategy/direction_context.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_daily_watch.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_direction_context.py`

**Interfaces:**

- Produces: `SubingDailyWatchItemProjector.project(symbol, source_trading_day)`, `resolve_previous_common_trading_day`, and `SubingStrategyDirectionContextResolver.resolve(symbol, target_days)`.
- Consumes: `ActualDominantStitchedResearchLoader`, `classify_daily_watch`, accepted Daily Watch V2 EMA calculation, active60 products, and the shared trading calendar.

- [ ] **Step 1: Write failing tests proving Builder and single-symbol projection are byte-equivalent.**

```python
def test_single_product_projector_matches_builder_item() -> None:
    projector = SubingDailyWatchItemProjector(
        stitched_loader=loader,
        product_metadata=metadata,
    )
    item = projector.project("jm", source_trading_day=date(2026, 8, 25))
    snapshot = SubingDailyWatchBuilder(
        projector=projector,
        products=("jm",),
        expected_universe_size=1,
    ).build(
        source_trading_day=date(2026, 8, 25),
        target_trading_day=date(2026, 8, 26),
        generated_at=aware_dt(18, 10),
    )
    assert snapshot.items == (item,)
```

- [ ] **Step 2: Write failing calendar and direction tests.**

```python
def test_previous_common_trading_day_is_inverse_of_next() -> None:
    source = date(2026, 8, 25)
    target = resolve_next_common_trading_day(
        session,
        products=active60,
        source_trading_day=source,
    )
    assert resolve_previous_common_trading_day(
        session,
        products=active60,
        target_trading_day=target,
    ) == source


def test_context_maps_daily_watch_long_to_long_only() -> None:
    result = resolver.resolve("jm", (date(2026, 8, 26),))
    assert result[date(2026, 8, 26)].direction is SubingStrategyDirection.LONG_ONLY
    assert result[date(2026, 8, 26)].source_trading_day == date(2026, 8, 25)
```

Also cover short, excluded → `NO_NEW_ENTRY`, unavailable → `UNAVAILABLE`, missing previous common day, and one unavailable day not blocking another target day.

- [ ] **Step 3: Run the tests and confirm missing-interface failures.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py \
  services/quant-api/tests/research/test_subing_strategy_direction_context.py
```

- [ ] **Step 4: Extract the existing `_build_item` behavior into one reusable projector without changing formulas.**

```python
class SubingDailyWatchItemProjector:
    def __init__(
        self,
        *,
        stitched_loader: _StitchedLoader,
        product_metadata: Mapping[str, SubingDailyWatchProduct],
    ) -> None:
        self._stitched_loader = stitched_loader
        self._product_metadata = product_metadata

    def project(
        self,
        symbol: str,
        *,
        source_trading_day: date,
    ) -> SubingDailyWatchItem:
        return _project_daily_watch_item(
            stitched_loader=self._stitched_loader,
            metadata=self._product_metadata.get(symbol),
            symbol=symbol,
            source_trading_day=source_trading_day,
        )
```

Change `SubingDailyWatchBuilder` to accept `projector` and call `projector.project` with the current symbol and source trading day. In the same task, update `build_subing_daily_watch_generator` in `composition.py` to construct one `SubingDailyWatchItemProjector` and pass it to the Builder, so the repository remains green after this commit. Keep the existing active60 scope validation and every existing reason code unchanged.

- [ ] **Step 5: Implement reverse common-trading-day resolution.**

`resolve_previous_common_trading_day` must use the same active60 exchange set as `resolve_next_common_trading_day`, verify the target day is a trading day on every exchange, select the immediately preceding trading day for each exchange, and require one identical date. Return `PREVIOUS_TRADING_DAY_UNAVAILABLE` on any disagreement or calendar gap.

```python
def resolve_previous_common_trading_day(
    session: Session,
    *,
    products: tuple[str, ...],
    target_trading_day: date,
) -> date:
    exchanges = _resolve_product_exchanges(session, products)
    previous_days = tuple(
        _previous_trading_day_for_exchange(
            session,
            exchange=exchange,
            target_trading_day=target_trading_day,
        )
        for exchange in exchanges
    )
    if len(set(previous_days)) != 1:
        raise SubingDailyWatchCalendarError("PREVIOUS_TRADING_DAY_UNAVAILABLE")
    return previous_days[0]
```

- [ ] **Step 6: Implement target-day context projection.**

```python
@dataclass(frozen=True, slots=True)
class SubingStrategyDirectionContext:
    symbol: str
    target_trading_day: date
    source_trading_day: date | None
    direction: SubingStrategyDirection
    reason_codes: tuple[str, ...]
    daily_bar_end: datetime | None
    hourly_bar_end: datetime | None
    physical_contract: str | None


class SubingStrategyDirectionContextResolver:
    def resolve(
        self,
        symbol: str,
        target_days: Sequence[date],
    ) -> Mapping[date, SubingStrategyDirectionContext]:
        resolved: dict[date, SubingStrategyDirectionContext] = {}
        for target_day in dict.fromkeys(target_days):
            resolved[target_day] = self._resolve_one(symbol, target_day)
        return MappingProxyType(resolved)
```

Mapping is exact:

```text
LONG_WATCH  -> LONG_ONLY
SHORT_WATCH -> SHORT_ONLY
EXCLUDED    -> NO_NEW_ENTRY
UNAVAILABLE -> UNAVAILABLE
```

Do not use current Daily Watch artifacts for historical dates and do not copy `_trend_direction` into the strategy package. Preserve Daily Watch provenance on the context object. Treat `D1_HISTORY_INSUFFICIENT`, `H1_HISTORY_INSUFFICIENT`, `SOURCE_TRADING_DAY_MISSING`, and `PREVIOUS_TRADING_DAY_UNAVAILABLE` as per-day `UNAVAILABLE` context; escalate `DATA_IDENTITY_MISMATCH`, `DOMINANT_SEGMENT_UNAVAILABLE`, or `PRODUCT_METADATA_UNAVAILABLE` to `SubingStrategyContextIdentityError` because those are authoritative identity failures, not ordinary no-entry days.

- [ ] **Step 7: Run Daily Watch V2 and strategy-context regressions.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py \
  services/quant-api/tests/test_subing_daily_watch_api.py \
  services/quant-api/tests/research/test_subing_strategy_direction_context.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/subing_daily_watch.py \
  services/quant-api/app/market_data/subing_daily_watch_calendar.py \
  services/quant-api/app/market_data/subing_strategy/direction_context.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py \
  services/quant-api/tests/research/test_subing_strategy_direction_context.py
```

- [ ] **Step 8: Commit Task 2.**

```bash
git add services/quant-api/app/market_data/subing_daily_watch.py \
  services/quant-api/app/market_data/subing_daily_watch_calendar.py \
  services/quant-api/app/market_data/subing_strategy/direction_context.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py \
  services/quant-api/tests/research/test_subing_strategy_direction_context.py
git commit -m "refactor(subing): expose daily watch direction projector"
```

---

## Task 3: Project Lifecycle confirmations onto the unique 15m strategy clock

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/entry_projection.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_entry_projection.py`
- Reuse fixtures: `services/quant-api/tests/research/subing_lifecycle_fixtures.py`

**Interfaces:**

- Produces: `SubingStrategyEntryCandidate` and `project_lifecycle_entries(trace, bars_15m)`.
- Consumes: `SubingLifecycleTrace`, `SubingLifecycleTransition`, `SubingLifecycleSnapshot`, `ConfirmationSource`, `LifecycleStage`, and `SubingOpportunityKey`.

- [ ] **Step 1: Write failing tests for all four confirmation sources and boundary rules.**

```python
@pytest.mark.parametrize(
    "source",
    (
        ConfirmationSource.FORMAL_V1,
        ConfirmationSource.MOMENTUM_HOLD,
        ConfirmationSource.PIVOT_BREAK_HOLD,
        ConfirmationSource.PIVOT_RETEST_REBREAK,
    ),
)
def test_projects_each_allowed_source_once(source: ConfirmationSource) -> None:
    projected = project_lifecycle_entries(trace_for_source(source), bars_15m)
    candidate = projected[bar_end(10, 30)][0]
    assert candidate.confirmation_source is source
    assert candidate.decision_bar_end == bar_end(10, 30)


def test_confirmation_equal_to_boundary_belongs_to_that_boundary() -> None:
    projected = project_lifecycle_entries(trace_confirmed_at(bar_end(10, 30)), bars_15m)
    assert projected[bar_end(10, 30)][0].confirmed_at == bar_end(10, 30)
```

- [ ] **Step 2: Add failing cancellation and dedupe tests.**

```python
def test_window_ending_in_exit_risk_cancels_candidate() -> None:
    projected = project_lifecycle_entries(trace_confirmed_then_exit_risk(), bars_15m)
    assert projected[bar_end(10, 30)] == ()


def test_first_confirmation_for_opportunity_wins() -> None:
    projected = project_lifecycle_entries(trace_with_duplicate_observations(), bars_15m)
    assert len(projected[bar_end(10, 30)]) == 1
    assert projected[bar_end(10, 30)][0].confirmed_at == bar_end(10, 20)
```

Also cover `closed`, mismatched symbol/contract/segment, disallowed source, missing bound Pivot, wrong Pivot kind, and future confirmation after the 15m boundary.

- [ ] **Step 3: Run and confirm the new module is absent.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_entry_projection.py
```

- [ ] **Step 4: Implement the immutable entry candidate.**

```python
@dataclass(frozen=True, slots=True)
class SubingStrategyEntryCandidate:
    opportunity_key: SubingOpportunityKey
    opportunity_id: str
    direction: SubingDirection
    confirmation_source: ConfirmationSource
    confirmed_at: datetime
    decision_bar_end: datetime
    bound_reference_pivot: ConfirmedPivot | None
```

- [ ] **Step 5: Implement the single forward scan.**

For consecutive boundaries `previous < current`, select transitions with:

```text
previous < transition.transition_at <= current
transition.to_stage == ENTRY_CONFIRMED
```

Resolve the confirmation snapshot by the transition identity, not by timestamp alone: require exactly one snapshot whose `latest_transition.transition_id` equals the selected transition id, whose `observed_at == transition.transition_at`, and whose opportunity key matches. Missing or duplicate matches are `SUBING_STRATEGY_CONTEXT_IDENTITY_INVALID`. Use that snapshot for confirmation source and bound Pivot. Before emitting at `current`, inspect the latest snapshot for that same opportunity at or before `current`; suppress the candidate when its stage is `EXIT_RISK` or `CLOSED`.

Return one immutable mapping entry for every 15m Bar, including empty tuples. Sort candidates by `(confirmed_at, opportunity_id)`.

- [ ] **Step 6: Prove prefix stability.**

```python
def test_appending_later_lifecycle_snapshots_does_not_change_prior_projection() -> None:
    prefix = project_lifecycle_entries(trace_prefix, bars_15m[:5])
    extended = project_lifecycle_entries(trace_extended, bars_15m)
    for boundary in prefix:
        assert prefix[boundary] == extended[boundary]
```

- [ ] **Step 7: Run projection and Lifecycle regressions.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_entry_projection.py \
  services/quant-api/tests/research/test_subing_lifecycle_transitions.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/subing_strategy/entry_projection.py \
  services/quant-api/tests/research/test_subing_strategy_entry_projection.py
```

- [ ] **Step 8: Commit Task 3.**

```bash
git add services/quant-api/app/market_data/subing_strategy/entry_projection.py \
  services/quant-api/tests/research/test_subing_strategy_entry_projection.py
git commit -m "feat(subing): project lifecycle entries to 15m"
```

---

## Task 4: Implement the pure strategy reducer, four exits, pending actions, and Episodes

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/engine.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_engine.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_causality.py`

**Interfaces:**

- Produces: `SubingStrategyDecisionFrame`, `SubingStrategySegmentResult`, and `run_subing_strategy_segment`.
- Consumes: policy/contracts from Task 1, target-day direction contexts from Task 2, and entry candidates from Task 3.

- [ ] **Step 1: Write failing tests for next-Bar-open entry and context rejection.**

```python
def test_long_entry_decides_on_close_and_fills_next_open() -> None:
    result = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=frames_with_long_entry(),
        policy=policy,
        terminal_bar_end=None,
    )
    action = result.actions[0]
    assert action.kind is SubingStrategyActionKind.OPEN_LONG
    assert action.decision_at == bar_end(10, 15)
    assert action.effective_bar_end == bar_end(10, 30)
    assert action.reference_price == Decimal("100.5")
    assert action.fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN


def test_unaligned_context_consumes_but_does_not_enter_old_opportunity() -> None:
    result = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=frames_where_context_aligns_late(),
        policy=policy,
        terminal_bar_end=None,
    )
    assert result.actions == ()
```

- [ ] **Step 2: Write failing tests for each long and short exit family.**

```python
@pytest.mark.parametrize(
    ("frames", "reason"),
    (
        (long_ema_breach_frames(), "EMA21_BREACH_LONG"),
        (long_previous_low_breach_frames(), "PREVIOUS_BAR_LOW_BREACH"),
        (long_bound_pivot_breach_frames(), "BOUND_LOW_PIVOT_BREACH"),
        (long_high_dead_cross_frames(), "MACD_HIGH_DEAD_CROSS"),
        (short_ema_breach_frames(), "EMA21_BREACH_SHORT"),
        (short_previous_high_breach_frames(), "PREVIOUS_BAR_HIGH_BREACH"),
        (short_bound_pivot_breach_frames(), "BOUND_HIGH_PIVOT_BREACH"),
        (short_low_golden_cross_frames(), "MACD_LOW_GOLDEN_CROSS"),
    ),
)
def test_each_exit_family_closes_full_position(frames, reason: str) -> None:
    result = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=frames,
        policy=policy,
        terminal_bar_end=None,
    )
    close = result.actions[-1]
    assert close.kind in {
        SubingStrategyActionKind.CLOSE_LONG,
        SubingStrategyActionKind.CLOSE_SHORT,
    }
    assert reason in close.reason_codes
    assert result.episodes[-1].state is SubingStrategyEpisodeState.CLOSED
```

- [ ] **Step 3: Add failing state-machine and terminal tests.**

Cover:

```text
same-direction confirmation while holding is ignored
opposite confirmation does not exit or reverse
one opportunity enters at most once
one Bar with four exit reasons creates one close Action
missing bound Pivot still permits entry and disables only structure exit
missing next Bar cancels pending open/close without close-price fallback
session/overnight gap still fills on the next existing same-segment Bar
close effective Bar cannot also contain another effective open
segment terminal close uses final close and includes ordinary reasons plus CONTRACT_SEGMENT_END
request cutoff before segment end leaves the Episode open and preserves pending_action
terminal_bar_end not equal to the final frame is rejected
```

Representative assertion:

```python
def test_multiple_exit_reasons_preserve_policy_order() -> None:
    close = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=frames_with_all_long_exit_reasons(),
        policy=policy,
        terminal_bar_end=None,
    ).actions[-1]
    assert close.reason_codes == (
        "EMA21_BREACH_LONG",
        "PREVIOUS_BAR_LOW_BREACH",
        "BOUND_LOW_PIVOT_BREACH",
        "MACD_HIGH_DEAD_CROSS",
    )
```

- [ ] **Step 4: Run and observe missing-engine failures.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py
```

- [ ] **Step 5: Implement the decision frame and reducer result.**

```python
@dataclass(frozen=True, slots=True)
class SubingStrategyDecisionFrame:
    bar: CanonicalBar
    previous_bar: CanonicalBar | None
    factor: SubingFactorSnapshot
    direction_context: SubingStrategyDirectionContext
    entry_candidates: tuple[SubingStrategyEntryCandidate, ...]


@dataclass(frozen=True, slots=True)
class SubingStrategySegmentResult:
    actions: tuple[SubingStrategyAction, ...]
    episodes: tuple[SubingStrategyEpisode, ...]
    consumed_opportunity_ids: tuple[str, ...]
    canceled_pending: tuple[SubingStrategyPendingCancellation, ...]
    pending_action: SubingStrategyPendingAction | None
    final_position: SubingStrategyPositionState


def run_subing_strategy_segment(
    *,
    symbol: str,
    contract: str,
    segment_start: date,
    frames: Sequence[SubingStrategyDecisionFrame],
    policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    """Reduce one physical segment prefix; terminal close only at an authoritative segment end."""
```

- [ ] **Step 6: Implement pending-action ordering.**

For each frame:

```text
1. Apply the pending action at current Bar open.
2. Materialize or close the Episode.
3. Evaluate the just-completed current Bar.
4. If holding, evaluate all four exits and schedule one pending close.
5. If flat, evaluate this boundary's candidates in chronological order.
6. Consume every evaluated opportunity even when context rejects it.
7. Schedule at most one pending action.
```

The exit helper must be one pure function:

```python
def exit_reason_codes(
    *,
    position: SubingStrategyPosition,
    frame: SubingStrategyDecisionFrame,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if position.state is SubingStrategyPositionState.LONG:
        if frame.bar.close < frame.factor.ema21:
            reasons.append("EMA21_BREACH_LONG")
        if frame.previous_bar is not None and frame.bar.close < frame.previous_bar.low:
            reasons.append("PREVIOUS_BAR_LOW_BREACH")
        pivot = position.bound_reference_pivot
        if pivot is not None and frame.bar.close < pivot.price:
            reasons.append("BOUND_LOW_PIVOT_BREACH")
        if frame.factor.macd_cross is MacdCross.DEAD and frame.factor.macd_cross_level > 0:
            reasons.append("MACD_HIGH_DEAD_CROSS")
    else:
        if frame.bar.close > frame.factor.ema21:
            reasons.append("EMA21_BREACH_SHORT")
        if frame.previous_bar is not None and frame.bar.close > frame.previous_bar.high:
            reasons.append("PREVIOUS_BAR_HIGH_BREACH")
        pivot = position.bound_reference_pivot
        if pivot is not None and frame.bar.close > pivot.price:
            reasons.append("BOUND_HIGH_PIVOT_BREACH")
        if frame.factor.macd_cross is MacdCross.GOLDEN and frame.factor.macd_cross_level < 0:
            reasons.append("MACD_LOW_GOLDEN_CROSS")
    return tuple(reasons)
```

- [ ] **Step 7: Implement terminal behavior and Episode metrics.**

At the final frame, distinguish an ordinary response cutoff from the authoritative physical-segment terminal:

```text
terminal_bar_end is None (request cutoff before true segment end)
  pending open/close -> retain as pending_action; do not fabricate an Action
  open position      -> return an open Episode and non-flat final_position

terminal_bar_end == final frame bar_end (true segment end)
  pending open       -> cancel with NEXT_BAR_UNAVAILABLE
  pending close      -> emit one terminal close at final close, preserving ordinary reasons and appending CONTRACT_SEGMENT_END
  open position      -> emit one terminal close at final close with CONTRACT_SEGMENT_END
  flat               -> no terminal Action
```

Reject any non-null `terminal_bar_end` that is not the final frame Bar. The service may pass a terminal only when authoritative segment identity and complete coverage prove that the loaded final Bar is the true old-contract terminal. `holding_bar_count` is the number of completed 15m Bars from the entry effective Bar through the close decision Bar, inclusive. For an open Episode, count through the latest completed response Bar. Closed `reference_change_percent` and open `current_reference_change_percent` use unquantized `Decimal` arithmetic.

- [ ] **Step 8: Implement ordinary-cutoff prefix invariance and authoritative-terminal tests separately.**

Every ordinary prefix call, including the longest request cutoff, passes `terminal_bar_end=None`. Compare it only with a longer ordinary-cutoff replay. The authoritative full-segment call is a separate assertion because its terminal close is intentionally absent from a normal `through` cutoff.

```python
def test_all_prior_ordinary_actions_and_closed_episodes_are_prefix_stable() -> None:
    ordinary_full = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=all_frames,
        policy=policy,
        terminal_bar_end=None,
    )
    for end in range(3, len(all_frames) + 1):
        prefix = run_subing_strategy_segment(
            symbol="jm",
            contract="JM2601",
            segment_start=date(2026, 8, 1),
            frames=all_frames[:end],
            policy=policy,
            terminal_bar_end=None,
        )
        cutoff = all_frames[end - 1].bar.bar_end
        assert tuple(
            action for action in ordinary_full.actions
            if action.effective_bar_end <= cutoff
        )[:len(prefix.actions)] == prefix.actions
        expected_closed = tuple(
            episode for episode in ordinary_full.episodes
            if episode.state is SubingStrategyEpisodeState.CLOSED
            and episode.exit_action is not None
            and episode.exit_action.decision_at <= cutoff
        )
        assert expected_closed[:len(tuple(
            item for item in prefix.episodes
            if item.state is SubingStrategyEpisodeState.CLOSED
        ))] == tuple(
            item for item in prefix.episodes
            if item.state is SubingStrategyEpisodeState.CLOSED
        )


def test_authoritative_terminal_adds_only_the_segment_terminal_projection() -> None:
    ordinary = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=all_frames,
        policy=policy,
        terminal_bar_end=None,
    )
    terminal = run_subing_strategy_segment(
        symbol="jm",
        contract="JM2601",
        segment_start=date(2026, 8, 1),
        frames=all_frames,
        policy=policy,
        terminal_bar_end=all_frames[-1].bar.bar_end,
    )
    assert terminal.actions[:len(ordinary.actions)] == ordinary.actions
    assert terminal.actions[-1].fill_basis is SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE
    assert terminal.actions[-1].reason_codes[-1] == "CONTRACT_SEGMENT_END"
```

- [ ] **Step 9: Run focused tests, Ruff, and Mypy.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/subing_strategy/engine.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py
PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app/market_data/subing_strategy
```

- [ ] **Step 10: Commit Task 4.**

```bash
git add services/quant-api/app/market_data/subing_strategy/engine.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py
git commit -m "feat(subing): add causal 15m strategy reducer"
```

---

## Task 5: Compose full-segment Factor/Lifecycle replay and the historical projection service

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/replay.py`
- Create: `services/quant-api/app/market_data/subing_strategy/service.py`
- Create: `services/quant-api/tests/research/subing_strategy_fixtures.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_replay.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_service.py`

**Interfaces:**

- Produces: `build_subing_strategy_frames`, `replay_subing_strategy_segment`, `SubingStrategyHistoricalProjection`, and `SubingStrategyHistoricalProjectionService.history`.
- Consumes: authoritative actual-dominant loaders, accepted calibration/Lifecycle policy, Task 2 context resolver, Task 3 entry projection, and Task 4 reducer.

- [ ] **Step 1: Write failing replay tests for exact segment-local composition.**

```python
def test_replay_uses_factor_and_lifecycle_from_segment_start() -> None:
    result = replay_subing_strategy_segment(
        symbol="jm",
        segment=segment,
        bars_5m=bars_5m,
        bars_15m=bars_15m,
        direction_contexts=contexts,
        calibration=calibration,
        lifecycle_policy=lifecycle_policy,
        strategy_policy=strategy_policy,
        terminal_bar_end=None,
    )
    assert result.actions[0].segment_start_trading_day == segment.start_trading_day
    assert result.actions[0].contract == segment.contract


def test_frame_rejects_future_factor_or_lifecycle_confirmation() -> None:
    with pytest.raises(SubingStrategyReplayError) as exc:
        replay_subing_strategy_segment(
            symbol="jm",
            segment=segment,
            bars_5m=bars_5m,
            bars_15m=bars_15m,
            direction_contexts=contexts,
            calibration=calibration,
            lifecycle_policy=lifecycle_policy,
            strategy_policy=strategy_policy,
            terminal_bar_end=None,
        )
    assert exc.value.code == "SUBING_STRATEGY_CONTEXT_IDENTITY_INVALID"
```

- [ ] **Step 2: Write failing service tests for full initialization and response cropping.**

```python
def test_entry_left_of_window_and_exit_inside_returns_complete_episode() -> None:
    result = service.history(
        SubingStrategyHistoricalRequest(
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            symbol="jm",
            frequency=BarFrequency.M15,
            since=date(2026, 8, 10),
            through=date(2026, 8, 20),
        )
    )
    episode = result.episodes[0]
    assert episode.entry_action.trading_day < date(2026, 8, 10)
    assert date(2026, 8, 10) <= episode.exit_action.trading_day <= date(2026, 8, 20)
    assert tuple(action.kind for action in result.actions) == (
        SubingStrategyActionKind.CLOSE_LONG,
    )


def test_new_contract_segment_starts_flat() -> None:
    result = service.history(request_covering_two_segments())
    assert result.segment_summaries[0].final_position is SubingStrategyPositionState.FLAT
    assert result.segment_summaries[1].initial_position is SubingStrategyPositionState.FLAT
```

Also cover active-product validation, exact `actual_dominant + 15m` request, no cross-segment opportunity, open Episode at cutoff, one context-unavailable target day, and an authoritative loader failure becoming the expected typed error.

- [ ] **Step 3: Run the new tests and confirm missing-service failures.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_replay.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py
```

- [ ] **Step 4: Build segment-local factors and Lifecycle exactly once.**

```python
def replay_subing_strategy_segment(
    *,
    symbol: str,
    segment: ResolvedContractSegment,
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
    direction_contexts: Mapping[date, SubingStrategyDirectionContext],
    calibration: SubingCalibration,
    lifecycle_policy: SubingLifecyclePolicy,
    strategy_policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    factors_5m = calculate_subing_factor_series(
        bars_5m,
        timeframe=BarFrequency.M5,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        latest_bar_source="canonical",
    )
    factors_15m = calculate_subing_factor_series(
        bars_15m,
        timeframe=BarFrequency.M15,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        latest_bar_source="canonical",
    )
    trace = evaluate_subing_lifecycle(
        symbol=symbol,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        bars_5m=bars_5m,
        factors_5m=factors_5m,
        bars_15m=bars_15m,
        factors_15m=factors_15m,
        calibration=calibration,
        policy=lifecycle_policy,
    )
    entries = project_lifecycle_entries(trace, bars_15m)
    frames = build_subing_strategy_frames(
        bars_15m=bars_15m,
        factors_15m=factors_15m,
        entries_by_boundary=entries,
        direction_contexts=direction_contexts,
    )
    return run_subing_strategy_segment(
        symbol=symbol,
        contract=segment.contract,
        segment_start=segment.start_trading_day,
        frames=frames,
        policy=strategy_policy,
        terminal_bar_end=terminal_bar_end,
    )
```

Reject insufficient or mismatched factor lengths, non-ready factor snapshots at evaluable boundaries, future confirmation, wrong contract, wrong segment, and any non-monotonic Bar sequence with typed replay errors.

- [ ] **Step 5: Implement the validated multi-segment service.**

```python
class SubingStrategyHistoricalProjectionService:
    def __init__(
        self,
        segment_loader: ActualDominantResearchSegmentLoader,
        *,
        products: tuple[str, ...],
        direction_context_resolver: SubingStrategyDirectionContextResolver,
        calibration: SubingCalibration,
        lifecycle_policy: SubingLifecyclePolicy,
        strategy_policy: SubingStrategyPolicy,
    ) -> None:
        self._segment_loader = segment_loader
        self._products = products
        self._direction_context_resolver = direction_context_resolver
        self._calibration = calibration
        self._lifecycle_policy = lifecycle_policy
        self._strategy_policy = strategy_policy
```

Load `(5m, 15m)` through `ActualDominantResearchSegmentLoader`. Partition each frequency by the exact returned segment tuple. Resolve direction contexts for every unique 15m trading day before replaying that segment. Replay from the restored true segment start. The service computes `terminal_bar_end`: use the true final 15m `bar_end` only when the loaded coverage reaches the returned segment's authoritative end trading day and the final Bar is the last covered Bar of that day; otherwise pass `None` and preserve an open position/pending decision at the response cutoff. Then crop:

```text
Actions: effective Bar trading day inside [since, through]
Episodes: entry/exit/open interval intersects [since, through]
```

Return complete intersecting Episodes even when the entry Action is outside the visible window. Until Task 6 adds cache composition, return `cache_state="unavailable"`; Task 5 must not reference a cache type that does not yet exist.

- [ ] **Step 6: Define stable typed errors.**

```python
class SubingStrategySourceUnavailableError(RuntimeError):
    code = "SUBING_STRATEGY_SOURCE_UNAVAILABLE"


class SubingStrategySegmentIdentityError(RuntimeError):
    code = "SUBING_STRATEGY_SEGMENT_IDENTITY_INVALID"


class SubingStrategyContextIdentityError(RuntimeError):
    code = "SUBING_STRATEGY_CONTEXT_IDENTITY_INVALID"
```

Policy and calibration errors retain their own stable codes. A context-unavailable day is response data, not a request-level error, unless the underlying segment or source identity itself is invalid.

- [ ] **Step 7: Run replay/service tests plus existing actual-dominant and Lifecycle regressions.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_replay.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/research/test_subing_lifecycle_transitions.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/subing_strategy/replay.py \
  services/quant-api/app/market_data/subing_strategy/service.py \
  services/quant-api/tests/research/subing_strategy_fixtures.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_replay.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py
```

- [ ] **Step 8: Commit Task 5.**

```bash
git add services/quant-api/app/market_data/subing_strategy/replay.py \
  services/quant-api/app/market_data/subing_strategy/service.py \
  services/quant-api/tests/research/subing_strategy_fixtures.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_replay.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py
git commit -m "feat(subing): add historical strategy projection service"
```

---

## Task 6: Add the safe expendable cache and dependency composition

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/cache.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_cache.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_composition.py`

**Interfaces:**

- Produces: `SubingStrategyCacheIdentity`, `SubingStrategyCache`, `NullSubingStrategyCache`, and `build_subing_strategy_historical_service`.
- Consumes: the validated SuBing observation root and the Task 5 per-segment projection.

- [ ] **Step 1: Write failing cache tests for identity and degradation.**

```python
def test_cache_hit_requires_exact_identity(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    cache.write(identity, projection)
    assert cache.read(identity) == projection
    changed = replace(identity, calibration_id="other")
    assert cache.read(changed) is None


def test_corrupt_cache_does_not_change_calculated_result(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    cache_path = cache.path_for(identity)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("not-json", encoding="utf-8")
    result = service_with_cache(cache).history(request)
    assert result.actions == expected_actions
    assert result.cache_state == "unavailable"
```

Also cover symlink root/path rejection, atomic replace, policy-byte digest change, segment end change, 5m/15m/D1/60m cutoff change, 5m/15m content digest change with unchanged cutoff, direction-context digest change, `through` change, write failure, and manual deletion followed by recomputation.

- [ ] **Step 2: Run and confirm missing-cache failures.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_composition.py
```

- [ ] **Step 3: Implement the complete cache identity envelope.**

```python
@dataclass(frozen=True, slots=True)
class SubingStrategyCacheIdentity:
    strategy_policy_sha256: str
    strategy_id: str
    formula_version: str
    calibration_id: str
    lifecycle_policy_id: str
    lifecycle_formula_version: str
    daily_watch_projection_version: str
    daily_watch_formula_version: str
    daily_watch_history_mode: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    segment_end_trading_day: date
    cutoff_5m: datetime
    cutoff_15m: datetime
    cutoff_d1: datetime
    cutoff_60m: datetime
    bars_5m_digest: str
    bars_15m_digest: str
    direction_context_digest: str
    through: date
```

Compute `bars_5m_digest` and `bars_15m_digest` from canonical compact JSON over each Bar's time, trading day, OHLCV/OI/turnover facts, and physical segment identity. Compute `direction_context_digest` from the ordered target-day context objects, including source day, direction, reasons, D1/60m Bar ends, and physical contract. These digests are calculated only after authoritative reads and prevent stale cache hits when content changes without advancing a cutoff.

The digest names a file below:

```text
<validated-observation-base-root>/cache/subing-strategy-v1/<symbol>/<contract>/<segment-start>/<digest>.json
```

Composition must resolve and revalidate the observation **base** root directly. Do not reuse `_subing_daily_watch_v2_root()`: Daily Watch artifacts remain under `base/v2/`, while the strategy cache remains a sibling under `base/cache/subing-strategy-v1/`.

- [ ] **Step 4: Implement safe read/write behavior.**

Use the same root revalidation, symlink rejection, `0700` directories, same-filesystem temporary file, `fsync`, and `os.replace` pattern as `SubingDailyWatchStore`. Serialize Decimals as canonical strings and verify the full envelope before parsing the projection.

`NullSubingStrategyCache` must return misses and ignore writes while reporting `unavailable`; it is the composition fallback when the observation root is absent or invalid.

- [ ] **Step 5: Integrate cache lookup after authoritative input resolution.**

The service order is mandatory:

```text
resolve authoritative segments and all source cutoffs
build exact cache identity
attempt validated cache read
on hit return parsed projection
on miss calculate projection, best-effort write, return calculation
on cache error calculate projection and return cache_state=unavailable
```

Never let cache bytes determine source identity or segment boundaries.

- [ ] **Step 6: Add composition.**

```python
def build_subing_strategy_historical_service(
    session: Session,
) -> SubingStrategyHistoricalProjectionService:
    market_data = build_market_data_service(session)
    active = load_active_products()
    stitched_loader = ActualDominantStitchedResearchLoader(market_data)
    dominants = market_data.list_latest_dominants()
    metadata = {
        item.symbol: SubingDailyWatchProduct(
            symbol=item.symbol,
            product_name=item.product_name,
            sector=item.sector,
        )
        for item in dominants
        if item.symbol in set(active)
    }
    return SubingStrategyHistoricalProjectionService(
        ActualDominantResearchSegmentLoader(market_data),
        products=active,
        direction_context_resolver=SubingStrategyDirectionContextResolver(
            session=session,
            active_products=active,
            projector=SubingDailyWatchItemProjector(
                stitched_loader=stitched_loader,
                product_metadata=metadata,
            ),
        ),
        calibration=load_accepted_subing_calibration(_SUBING_CALIBRATION),
        lifecycle_policy=load_subing_lifecycle_policy(_SUBING_LIFECYCLE_POLICY),
        strategy_policy=load_subing_strategy_policy(),
        cache=_build_subing_strategy_cache_or_null(),
    )
```

- [ ] **Step 7: Run cache, composition, service, and store safety tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/subing_strategy/cache.py \
  services/quant-api/app/market_data/subing_strategy/service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_composition.py
```

- [ ] **Step 8: Commit Task 6.**

```bash
git add services/quant-api/app/market_data/subing_strategy/cache.py \
  services/quant-api/app/market_data/subing_strategy/service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_composition.py
git commit -m "feat(subing): add strategy projection cache"
```

---

## Task 7: Add the strict Strategy HTTP response while temporarily preserving the old route

**Files:**

- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Keep temporarily: `services/quant-api/app/market_data/subing_historical_signal_service.py`
- Keep temporarily: `services/quant-api/tests/data_foundation/test_subing_historical_signal_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_composition.py`

**Interfaces:**

- Produces: `GET /api/v1/market/research/subing-strategy/history` and its Pydantic response.
- Preserves temporarily: public `GET /api/v1/market/research/subing/history` so this backend-only commit does not break the still-old Web. Task 8 performs the atomic cross-stack cutover and retirement.

- [ ] **Step 1: Write failing API tests for the new exact request.**

```python
def test_subing_strategy_history_returns_actions_and_episodes(client, monkeypatch) -> None:
    monkeypatch.setattr(
        market_research_overlays,
        "build_subing_strategy_historical_service",
        lambda session: fake_service,
    )
    response = client.get(
        "/api/v1/market/research/subing-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
            "since": "2026-08-01",
            "through": "2026-08-20",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"]["strategy_id"] == "subing_strategy_v1"
    assert payload["actions"][0]["kind"] == "open_long"
    assert payload["episodes"][0]["state"] in {"open", "closed"}
```

- [ ] **Step 2: Add failing error and retirement tests.**

Cover:

```text
422: malformed symbol/date/range, non-actual-dominant, non-15m
409: source, segment identity, context identity, policy, calibration
200 partial: context-unavailable days remain response data
200: old /subing/history remains temporarily available until Task 8
no SQL mutation, Redis call, AlertEvent creation, or notification from a history GET
```

- [ ] **Step 3: Run and confirm the new route is absent.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/data_foundation/test_composition.py
```

- [ ] **Step 4: Add explicit Pydantic models.**

Create dedicated models for:

```text
SubingStrategyHistoricalRequestOut
SubingStrategyPolicyOut
SubingStrategySegmentSummaryOut
SubingStrategyBoundPivotOut
SubingStrategyActionOut
SubingStrategyEpisodeOut
SubingStrategyContextUnavailableOut
SubingStrategyHistoricalResponse
```

The response includes request, policy, resolved cutoff, segment summaries, cropped top-level Actions, complete intersecting Episodes, context-unavailable days, and overall cache state. `SubingStrategyEpisodeOut` embeds its complete `entry_action` and nullable `exit_action`; these nested Actions remain present even when their effective Bars lie outside the request window, while the top-level `actions` list remains window-cropped for Marker rendering. Decimal fields remain `Decimal` at the FastAPI boundary.

- [ ] **Step 5: Implement the endpoint and typed error mapping.**

```python
@router.get(
    "/subing-strategy/history",
    response_model=SubingStrategyHistoricalResponse,
)
def subing_strategy_history(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> SubingStrategyHistoricalResponse:
    request = SubingStrategyHistoricalRequest(
        series_kind=SeriesKind(series_kind),
        symbol=symbol,
        frequency=BarFrequency(frequency),
        since=since,
        through=through,
    )
    projection = build_subing_strategy_historical_service(session).history(request)
    return to_subing_strategy_response(projection)
```

Map typed policy, calibration, active-universe, source, segment, and context failures to their stable `409` codes **before** the generic `ValueError` handler. Only malformed request construction is `422 INVALID_SUBING_STRATEGY_REQUEST`; a policy error must never be swallowed by the generic validation branch.

- [ ] **Step 6: Record the exact retirement reference scan, but do not delete yet.**

```bash
rg -n "SubingHistoricalSignal|build_subing_historical_signal_service|/subing/history" \
  services/quant-api apps/quant-web
```

Expected: only the old API/client/tests/service/composition references that Task 8 lists for atomic removal. If any Alert, current-state, or Lifecycle consumer appears, stop and amend the plan before deleting an internal dependency.

- [ ] **Step 7: Run API, composition, service, and no-mutation regressions.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/test_alert_runtime.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/market_data/subing_strategy \
  services/quant-api/tests/test_market_research_overlays_api.py
```

- [ ] **Step 8: Commit Task 7.**

```bash
git add services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/market_data/subing_strategy \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/data_foundation/test_composition.py
git commit -m "feat(api): expose subing strategy history"
```

---

## Task 8: Replace Web single-signal markers with Strategy Actions and merge Episodes across pagination

**Files:**

- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/utils/historicalResearchMarkers.ts`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Create: `apps/quant-web/tests/subingStrategyHistory.test.ts`
- Modify: `apps/quant-web/tests/marketOverlayConvergence.test.ts`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/data_foundation/test_composition.py`
- Delete after final reference scan: `services/quant-api/app/market_data/subing_historical_signal_service.py`
- Delete after replacement coverage passes: `services/quant-api/tests/data_foundation/test_subing_historical_signal_service.py`

**Interfaces:**

- Produces: strict browser types/normalizer, `getSubingStrategyHistory`, `subingStrategyActionToMarker`, merged `subingStrategyEpisodes`, and 15m-only Strategy history capability.
- Removes atomically: `getSubingHistoricalSignals`, `SubingHistoricalSignalRequest/Response/Event`, old buy/sell marker conversion, Alert-rule-based historical dedupe keys, public `/subing/history`, its composition builder, and the now-unconsumed historical single-signal service/tests.

- [ ] **Step 1: Write failing wire-normalization tests.**

```typescript
it('normalizes Decimal strings and preserves deterministic ids', () => {
  const normalized = normalizeSubingStrategyHistory(strategyWireResponse())
  expect(normalized.actions[0].reference_price).toBe(100.5)
  expect(normalized.episodes[0].reference_change_percent).toBe(7.97)
  expect(normalized.actions[0].action_id).toBe('subing-action:abc')
})

it('rejects an episode whose nested entry identity conflicts with its episode', () => {
  const payload = strategyWireResponse()
  payload.episodes[0].entry_action.action_id = 'different'
  expect(() => normalizeSubingStrategyHistory(payload)).toThrow(
    'SUBING_STRATEGY_INVALID_RESPONSE',
  )
})
```

Validate request identity, exact policy ids, action kinds, fill basis, timestamps, symbol/contract/segment identity, unique top-level action ids, unique episode ids, nested entry/exit Action invariants, and finite Decimal strings. A complete Episode may embed an Action absent from the cropped top-level list; the normalizer validates the nested Action directly rather than requiring every nested id in the top-level Marker list.

- [ ] **Step 2: Write failing marker tests.**

```typescript
it('anchors an open-long marker to the effective Bar', () => {
  expect(subingStrategyActionToMarker(openLongAction(), episodeById)).toMatchObject({
    time: '2026-08-07T02:30:00+00:00',
    label: '▲ 建多',
    position: 'belowBar',
    shape: 'arrowUp',
  })
})

it('shows every close reason and reference change', () => {
  const marker = subingStrategyActionToMarker(closeLongAction(), episodeById)
  expect(marker?.label).toBe('× 清多')
  expect(marker?.tooltip).toContain('EMA21 跌破')
  expect(marker?.tooltip).toContain('MACD 高位死叉')
  expect(marker?.tooltip).toContain('参考变动 +7.97%')
})
```

- [ ] **Step 3: Write failing composable tests for replace/prepend merge.**

Cover:

```text
subing Strategy fetch occurs only for subing + actual_dominant + 15m
5m current observation remains usable but no Strategy history request is sent
replace clears old identity
prepend requests only earlier dates
Actions dedupe by action_id
Episodes merge by episode_id
closed Episode replaces an older open projection only when entry identity matches
stale request cannot mutate the new symbol/frequency/generation
entry outside the loaded range and exit inside produces only the exit Marker while retaining the complete Episode
Strategy failure leaves other K-line layers intact
```

- [ ] **Step 4: Run and confirm the old types/client are still active.**

```bash
pnpm --dir apps/quant-web exec node --test \
  tests/subingStrategyHistory.test.ts \
  tests/historicalResearchMarkers.test.ts \
  tests/mainIndicators.test.ts \
  tests/marketOverlayConvergence.test.ts
```

- [ ] **Step 5: Add strict Strategy browser contracts.**

Use wire types with Decimal strings and normalized display types with numbers. The normalized response must include:

```typescript
export interface SubingStrategyHistoricalResponse {
  request: SubingStrategyHistoricalRequest
  policy: SubingStrategyPolicy
  resolved_cutoff: string
  segment_summaries: SubingStrategySegmentSummary[]
  actions: SubingStrategyAction[]
  episodes: SubingStrategyEpisode[]
  context_unavailable: SubingStrategyContextUnavailable[]
  cache_state: 'hit' | 'miss' | 'mixed' | 'unavailable'
}
```

- [ ] **Step 6: Change the internal overlay source from `subing` to `subing_strategy`.**

Keep overlay id `subing`; update only the internal `historicalSource` union and definition. Add:

```typescript
export function subingStrategyHistoricalCapability(
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): boolean {
  return seriesKind === 'actual_dominant' && frequency === '15m'
}
```

Do not narrow `SUBING_PUBLIC_FREQUENCIES`; current SuBing observation remains 5m/15m.

- [ ] **Step 7: Implement factual Strategy Marker conversion.**

```typescript
const actionLabels = {
  open_long: '▲ 建多',
  open_short: '▼ 建空',
  close_long: '× 清多',
  close_short: '× 清空',
} as const

export function subingStrategyActionToMarker(
  action: SubingStrategyAction,
  episodeById: ReadonlyMap<string, SubingStrategyEpisode>,
): KlineMarker {
  const episode = episodeById.get(action.episode_id)
  const opening = action.kind === 'open_long' || action.kind === 'open_short'
  const long = action.kind === 'open_long' || action.kind === 'close_long'
  return {
    id: `historical:subing-strategy:${action.action_id}`,
    dedupeKey: `subing-strategy:${action.action_id}`,
    time: action.effective_bar_end,
    label: actionLabels[action.kind],
    tooltip: subingStrategyTooltip(action, episode),
    tone: long ? 'up' : 'down',
    position: opening ? (long ? 'belowBar' : 'aboveBar') : (long ? 'aboveBar' : 'belowBar'),
    shape: opening ? (long ? 'arrowUp' : 'arrowDown') : 'square',
  }
}
```

- [ ] **Step 8: Extend the existing historical composable rather than adding a second chart engine.**

Return:

```typescript
return {
  markers,
  subingStrategyEpisodes,
  subingStrategyContextUnavailable,
  loading,
  error,
  sync,
  dispose,
}
```

Maintain `Map<string, KlineMarker>` by Action id and `Map<string, SubingStrategyEpisode>` by Episode id. A conflicting response for the same id must set `SUBING_STRATEGY_INVALID_RESPONSE` and leave the prior valid state unchanged.

- [ ] **Step 9: Atomically remove the old Web and backend historical single-signal surface.**

Run the full cross-stack scan first:

```bash
rg -n "getSubingHistoricalSignals|SubingHistoricalSignal|build_subing_historical_signal_service|historicalResearchEventToMarker|subingMarkerDedupeKey|/subing/history" \
  services/quant-api apps/quant-web
```

Expected before deletion: only the old route/client/types/marker/tests/service/composition references already listed in this Task. Remove those references and files in the same commit. Do not delete `subing_research.py`, Factor/Signal evaluation, Calibration, Lifecycle, current SuBing APIs, or immutable Alert lineage. Then run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py
pnpm --dir apps/quant-web exec node --test \
  tests/subingStrategyHistory.test.ts \
  tests/historicalResearchMarkers.test.ts \
  tests/mainIndicators.test.ts \
  tests/marketOverlayConvergence.test.ts
pnpm --dir apps/quant-web build
```

After the tests, rerun the cross-stack `rg`; expected result is no old historical single-signal source or test reference.

- [ ] **Step 10: Commit Task 8.**

```bash
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/src/utils/historicalResearchMarkers.ts \
  apps/quant-web/src/composables/useHistoricalResearchMarkers.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/subingStrategyHistory.test.ts \
  apps/quant-web/tests/marketOverlayConvergence.test.ts \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/data_foundation/test_composition.py
git add -u services/quant-api/app/market_data/subing_historical_signal_service.py \
  services/quant-api/tests/data_foundation/test_subing_historical_signal_service.py
git commit -m "feat(market): cut over subing strategy history"
```

---

## Task 9: Integrate the chart, Strategy record area, advanced toggle, E2E acceptance, and Review Gate

**Files:**

- Create: `apps/quant-web/src/components/market/SubingStrategyRecords.vue`
- Create: `apps/quant-web/src/utils/subingStrategyRecords.ts`
- Modify: `apps/quant-web/src/components/market/SubingPanel.vue`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Create: `apps/quant-web/tests/subingStrategyRecords.test.ts`
- Modify: `apps/quant-web/tests/subingPanel.test.ts`
- Modify: `apps/quant-web/tests/marketOverlayConvergence.test.ts`
- Modify: `apps/quant-web/tests/subingResearch.test.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Modify after observed evidence: `STATUS.md`
- Modify after final active-surface review: `PROJECT_SOURCE.md`
- Modify after final active-surface review: `AGENTS.md`

**Interfaces:**

- Produces: the primary `苏冰策略 V1` chart/record surface and one default-off `显示苏冰内部研究过程` preference.
- Consumes: Strategy markers/Episodes from Task 8 and existing current Lifecycle projection.

- [ ] **Step 1: Write failing pure record-view-model tests.**

Do not add `@vue/test-utils` or another frontend test framework. Put formatting and ordering in `subingStrategyRecords.ts`, exercise it with the repository's existing `node:test`, and reserve real component behavior for Playwright.

```typescript
import assert from 'node:assert/strict'
import test from 'node:test'

import { buildSubingStrategyRecordRows } from '../src/utils/subingStrategyRecords.ts'

test('formats a closed long Episode with reference change and all exit reasons', () => {
  const [row] = buildSubingStrategyRecordRows([closedLongEpisode()])
  assert.equal(row.directionLabel, '建多 → 清多')
  assert.equal(row.referenceChangeLabel, '参考变动 +7.97%')
  assert.deepEqual(row.exitReasonLabels, ['EMA21 跌破', 'MACD 高位死叉'])
  assert.equal(row.disclaimer, '历史因果投影 · 模拟动作 · 非实际成交')
})

test('formats an open Episode as holding without completed-result language', () => {
  const [row] = buildSubingStrategyRecordRows([openShortEpisode()])
  assert.equal(row.stateLabel, '持仓中')
  assert.match(row.referenceChangeLabel, /^当前参考变动 /)
  assert.doesNotMatch(row.referenceChangeLabel, /收益|盈亏/)
})
```

- [ ] **Step 2: Write failing preference and chart-integration tests.**

Cover:

```text
preference schema v5 preserves v4 overlay/EMA/N-band values
showSubingInternalProcess defaults false
Lifecycle markers absent by default and present only when toggle is on
Strategy markers remain visible regardless of internal-process toggle
SubingPanel receives Episodes only for actual_dominant + 15m
5m panel keeps current observation but shows Strategy-unavailable guidance
Strategy layer error does not hide K-lines, current SuBing facts, Alert controls, or other overlays
```

- [ ] **Step 3: Run and confirm the UI is absent.**

```bash
pnpm --dir apps/quant-web exec node --test \
  tests/subingStrategyRecords.test.ts \
  tests/subingPanel.test.ts \
  tests/marketOverlayConvergence.test.ts \
  tests/subingResearch.test.ts \
  tests/mainIndicators.test.ts
```

- [ ] **Step 4: Add a v5 preference with lossless v4 migration.**

```typescript
export interface MainChartPreferences {
  version: 5
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showNStructureBands: boolean
  showSubingInternalProcess: boolean
  period?: string | null
  realtimeFollow?: boolean
}
```

Read v5 first. When only the v4 key exists, preserve `selectedOverlay`, `optionalEmaIndicators`, `showNStructureBands`, `period`, and `realtimeFollow`, add `showSubingInternalProcess: false`, write v5, then remove v4. Do not purge v4 before migration.

- [ ] **Step 5: Add the toggle under `图表设置`.**

Show it only when `selectedOverlay === 'subing'`:

```vue
<div v-if="selectedOverlay === 'subing'" class="toolbar__settings-title">
  <span>显示苏冰内部研究过程</span>
  <NSwitch
    :value="showSubingInternalProcess"
    size="small"
    aria-label="显示苏冰内部研究过程"
    @update:value="emit('update:show-subing-internal-process', $event)"
  />
</div>
<small v-if="selectedOverlay === 'subing'" class="toolbar__settings-help">
  默认关闭；仅显示当前准备 / 研究确认 / 风险 / 结束事实
</small>
```

- [ ] **Step 6: Build `SubingStrategyRecords.vue` and keep `SubingPanel.vue` focused.**

`subingStrategyRecords.ts` maps exact API Episodes to immutable display rows without calculating Strategy facts. `SubingStrategyRecords` accepts:

```typescript
defineProps<{
  episodes: SubingStrategyEpisode[]
  loading: boolean
  error: string | null
}>()
```

Sort Episodes by entry effective time descending. Display frequency, direction, entry/exit time and reference price, holding Bar count, all exit reasons, structure-exit availability, and `参考变动`. Never compute the value in the component; display the normalized API fact. In `SubingPanel.vue`, place Factor/Signal/Lifecycle details under the existing collapsed details area and render current Lifecycle markers only through the advanced toggle; Strategy Actions/Episodes become the primary surface without removing current research or Alert controls.

- [ ] **Step 7: Wire Strategy state into `chart.vue`.**

Pass the composable's Episodes/loading/error to `SubingPanel`. Gate current Lifecycle markers:

```typescript
const lifecycleMarkers = computed(() => {
  if (!showSubingInternalProcess.value) return []
  if (!overlayCapability.value.supported || subingLoading.value || subingError.value) return []
  return selectedOverlay.value === 'subing' && subing.value
    ? lifecycleSnapshotToMarkers(subing.value.lifecycle)
    : []
})
```

Keep Strategy Action markers in the normal historical marker set. Do not merge Episode UI state into persistent Alert markers.

- [ ] **Step 8: Add E2E coverage for time anchoring and left pagination.**

In `market-research.spec.mjs`, route-intercept:

```text
/market/bars/page
/market/research/subing-strategy/history
/market/research/subing
```

Prove:

```text
open/close markers attach to effective 15m Bars
horizontal pan and zoom retain attachment
prepend fetches an earlier Strategy range once
overlapping responses do not duplicate markers or Episodes
entry outside the first visible window and exit inside still shows exit and full Episode details
panning left reveals the entry marker
identity change while an old request is pending cannot leak old markers/episodes
advanced internal-process toggle defaults off and persists on reload
```

Use marker ids and chart business-time test hooks; do not assert pixel coordinates as the persistence contract.

- [ ] **Step 9: Run the complete Stage 1 automated verification.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m "not isolated_postgresql" \
  services/quant-api/tests
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests \
  packages/quant-core/guiyi_quant tests/engineering
PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Any failure blocks completion. Do not substitute CI for a missing local required check.

- [ ] **Step 10: Run read-only manual acceptance with cache disabled.**

Use an isolated local API/Web process against authoritative production Catalog/Canonical in read-only mode. Do not load/switch Runtime, run RQData, update Canonical, write production DB, change Scope, send notification, or write the real SuBing observation root.

For at least three active products and at least five complete Episodes per product, record:

```text
symbol and physical contract segment
entry opportunity id and confirmation source
D1/60m source day and target-day classification
entry decision Bar and next-Bar open
exit decision Bar and effective price
all exit reasons and raw reference values
holding Bar count and 参考变动
pan/prepend result
```

The combined corpus must include long, short, every exit family, multiple same-Bar reasons, session/overnight gap, terminal segment close, and off-screen entry with visible exit. If natural data does not contain one required case, report the gap and keep the Gate blocked; do not fabricate evidence.

- [ ] **Step 11: Measure single-product cold projection latency without declaring a performance claim.**

Run the same exact request five times with cache disabled, record wall-clock values, median, input Bar counts, segment count, and response Action/Episode counts. The reviewer decides whether latency is acceptable for this local workstation; no threshold is invented in code or docs.

- [ ] **Step 12: Update canonical docs only with observed facts.**

After all automated checks and manual acceptance:

```text
STATUS.md
- exact task branch/head
- actual focused/full test counts
- actual manual corpus coverage and any gaps
- cache disabled for real-data acceptance unless separately authorized
- Stage 2 remains not implemented and not authorized

PROJECT_SOURCE.md / AGENTS.md
- existing subing overlay now projects SuBing Strategy V1 historical Actions/Episodes on actual_dominant + 15m
- Daily Watch remains independent
- old public historical single-signal route is retired
- no account/order/backtest framework/Runtime/Alert Strategy path
```

Do not claim OOS, profitability, release, Runtime readiness, or notification delivery.

- [ ] **Step 13: Commit the UI and observed documentation.**

```bash
git add apps/quant-web/src/components/market/SubingStrategyRecords.vue \
  apps/quant-web/src/utils/subingStrategyRecords.ts \
  apps/quant-web/src/components/market/SubingPanel.vue \
  apps/quant-web/src/components/market/ProductCheckSidebar.vue \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/subingStrategyRecords.test.ts \
  apps/quant-web/tests/subingPanel.test.ts \
  apps/quant-web/tests/marketOverlayConvergence.test.ts \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs \
  STATUS.md PROJECT_SOURCE.md AGENTS.md
git commit -m "feat(web): present subing strategy episodes"
```

- [ ] **Step 14: Open a PR to `develop` and request an independent Lane 3 Review.**

The Review session reads the Spec, this plan, PR diff, test output, and manual corpus. Review focus:

```text
Daily Watch V2 equivalence and no future context
5m confirmation projection onto the unique 15m clock
next-Bar-open causality
four exits only, with no hidden fifth exit
segment isolation and terminal close
prefix-stable ids and Episodes
cache non-authority
old route/client/marker retirement
Marker attachment during pan/prepend
no Stage 2, notification, order, Runtime, DB mutation, or unsupported PnL language
```

- [ ] **Step 15: Stop at the integration Gate.**

Final implementation conclusion must be one of:

```text
允许集成 develop
要求修正后再集成
阻塞
```

Do not merge until the user explicitly chooses `允许集成 develop`. After a confirmed merge, clean the temporary worktree and merged branch; do not touch `main`, tag, release, or Runtime.

---

## Stage 2 Explicitly Deferred

Do not implement any of the following under this plan:

```text
completed-Live 15m Strategy evaluation
active60 Runtime reconstruction
new Alert Rule subing_strategy_v1
production migration or Rule seed
Scope transfer from subing_entry_signal_v1
open/close Formal Events
PushPlus attempt
release/tag
Runtime promotion/switch
```

After Stage 1 enters `develop` and is accepted, create a new Lane 3 Plan-only session and a separate Stage 2 Spec amendment if observed Stage 1 behavior changes any Runtime assumption.
