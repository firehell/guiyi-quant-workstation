# JDJ Active60 1m Strategy Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the existing JM-only `jdj_intraday_futures_v1` Historical reference replay to every product in the current active60 universe without changing JDJ Candidate or Strategy Core semantics, while preserving exact JM public behavior.

**Architecture:** Keep the existing single-product HTTP/Market path. The service admits symbols from `load_active_products()`, resolves each symbol's exchange/multiplier/session from existing Catalog facts, and passes the loader's existing `ResolvedContractSegment` into the unchanged Strategy lifecycle. No Strategy framework, batch endpoint, per-product override, tick/margin/fees execution model, Alert, Runtime, or OOS integration is added.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / `Decimal` / pytest / Vue 3 + TypeScript / Vitest(Node test runner as configured) / Playwright / existing `MarketDataService` and `ActualDominantResearchSegmentLoader`.

**Spec:** `docs/superpowers/specs/2026-08-24-jdj-active60-1m-strategy-design.md`

## Global Constraints

- Lane 3. Use **Sol + high reasoning** in a new implementation session.
- This user-approved plan is the narrow `AGENTS.md` / `DECISIONS.md` formal-plan exception: it is a reviewable design contract, not active task governance, current-status evidence, or authorization for any external operation.
- Before implementation, read `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, this plan, and the Spec.
- Create an isolated task worktree/branch from the then-current `develop`; recommended branch: `feature/jdj-active60-1m-strategy`.
- Do not modify `main` or any Runtime worktree. Do not create a release/tag or perform Runtime promotion.
- Strategy Core values and the three JDJ Candidate reducers are frozen. No per-product Strategy override.
- `actual_dominant + 1m` remains the only Strategy Replay request identity; trend context remains `5m`.
- Active membership comes only from `load_active_products()`; future OOS universe identity remains a separate concern.
- `reference_price` and `quantity` remain research reference semantics; do not add tick-size, margin, commission, slippage, account, order, or real-execution claims.
- No DB/Canonical/Redis writes, no Alert, no prospective OOS consumption, no RQAlpha sidecar/Bundle smoke, no order path.
- The first implementation commit MUST be test-only JM golden freeze. Do not touch Strategy production files before that commit exists.
- Existing JM golden must never be regenerated to make later code pass. A parity mismatch blocks this task.
- A code PR targets `develop` only. It must receive an independent Review conclusion of **允许集成 develop** before merge.
- The fixed-window active60 read-only capability smoke runs only after automated verification and independent code Review; it uses `2026-08-18..2026-08-20` and does not touch embargo/prospective dates.

---

## File Structure / Responsibility Map

**Strategy contract**
- `data/strategy_profiles/jdj_v1.json` — exact V2 profile payload; one active60-scope profile and globally frozen rules.
- `services/quant-api/app/research/jdj_strategy/contract.py` — exact JSON validation and immutable `JdjV1Config` objects.

**Deterministic replay**
- `services/quant-api/app/research/jdj_strategy/replay.py` — single physical-segment lifecycle; explicit `symbol + ResolvedContractSegment` identity.
- `services/quant-api/app/research/jdj_strategy/service.py` — request normalization, active-product admission, confirmed segment loading, candidate reduction, segment replay orchestration.
- `services/quant-api/app/research/jdj_strategy/engine.py` — public action DTO only; no semantic change expected.

**Composition / HTTP**
- `services/quant-api/app/research/composition.py` — per-symbol Catalog/session fact resolvers; no symbol cached at builder construction.
- `services/quant-api/app/research/historical_overlay_api.py` — stable endpoint and 422/409 error mapping.

**Backend tests**
- `services/quant-api/tests/research/fixtures/jdj_jm_1m_v1_reference_golden.json` — immutable pre-change JM action projection.
- `services/quant-api/tests/research/test_jdj_strategy_jm_parity.py` — exact golden comparison.
- `services/quant-api/tests/research/test_jdj_strategy_contract.py` — V2 exact profile contract.
- `services/quant-api/tests/research/test_jdj_strategy_engine.py` — replay lifecycle and explicit segment identity unit coverage.
- `services/quant-api/tests/research/test_jdj_strategy_replay_service.py` — active admission, segment orchestration, no cross-symbol/segment state leak.
- `services/quant-api/tests/test_research_composition.py` — DCE/SHFE/CZCE/INE dynamic fact resolution.
- `services/quant-api/tests/test_market_research_overlays_api.py` — endpoint identity and typed error matrix.

**Web tests only unless a real bug is proven**
- `apps/quant-web/tests/historicalResearchMarkers.test.ts` — non-JM symbol request identity and stale-response rejection.
- `apps/quant-web/e2e/market-research.spec.mjs` — non-JM active product strategy request/marker behavior.
- `apps/quant-web/src/**` — expected unchanged.

**Canonical / commands**
- `PROJECT_SOURCE.md` — replace JM-only replay wording with current-active-product replay wording after code is true.
- `AGENTS.md` — same stable engineering boundary update; retain research-only/no-order constraints.
- `TESTING.md` — exact JDJ active60 verification commands.
- `STATUS.md` — update only after code/tests/independent Review/fixed-window read-only smoke all pass.

---

### Task 1: Freeze the Pre-Change JM Golden Projection

**Files:**
- Create: `services/quant-api/tests/research/fixtures/jdj_jm_1m_v1_reference_golden.json`
- Create: `services/quant-api/tests/research/test_jdj_strategy_jm_parity.py`
- Read only: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Production files: **MUST remain untouched in this task**

**Interfaces:**
- Consumes: current JM-only `JdjStrategyReplayService`, plus the deterministic `_Reader/_contexts/_service/_request` fixture already present in `test_jdj_strategy_replay_service.py`.
- Produces: immutable JSON action projection and a test that compares every public `JdjAction` field in order.

- [ ] **Step 1: Verify the current JM strategy tests are green before capturing anything**

Run from repository root:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS. If baseline fails, stop; do not capture a golden from a failing baseline.

- [ ] **Step 2: Generate the golden from current code before any Strategy production edit**

Run exactly from `services/quant-api` so `app` is importable:

```bash
cd services/quant-api
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline python - <<'PY'
from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import app.research.jdj_strategy.service as strategy_service
from app.research.jdj_strategy.engine import JdjAction

fixture_path = Path("tests/research/test_jdj_strategy_replay_service.py")
spec = spec_from_file_location("_jdj_replay_fixture", fixture_path)
assert spec is not None and spec.loader is not None
fixture = module_from_spec(spec)
spec.loader.exec_module(fixture)

strategy_service.build_jdj_context_series = fixture._contexts
result = fixture._service(fixture._Reader()).history(fixture._request())


def normalize(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [normalize(item) for item in value]
    raise TypeError(type(value).__name__)


def project(action: JdjAction) -> dict[str, object]:
    return {
        item.name: normalize(getattr(action, item.name))
        for item in fields(JdjAction)
    }

out = Path("tests/research/fixtures/jdj_jm_1m_v1_reference_golden.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps([project(action) for action in result.actions], indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(f"wrote {out} actions={len(result.actions)}")
assert result.actions
PY
cd ../..
```

Expected: one fixture file is created and action count is greater than zero.

- [ ] **Step 3: Add a parity test that cannot rewrite its own expected data**

Create `services/quant-api/tests/research/test_jdj_strategy_jm_parity.py` with the same normalization rules and a dynamic load of the existing deterministic service fixture. The core assertion must be:

```python
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import app.research.jdj_strategy.service as strategy_service
from app.research.jdj_strategy.engine import JdjAction

_GOLDEN = Path(__file__).with_name("fixtures") / "jdj_jm_1m_v1_reference_golden.json"
_FIXTURE = Path(__file__).with_name("test_jdj_strategy_replay_service.py")


def _normalize(value: object):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    raise TypeError(type(value).__name__)


def _project(action: JdjAction) -> dict[str, object]:
    return {item.name: _normalize(getattr(action, item.name)) for item in fields(JdjAction)}


def test_jm_reference_projection_matches_pre_active60_golden(monkeypatch):
    spec = spec_from_file_location("_jdj_replay_fixture", _FIXTURE)
    assert spec is not None and spec.loader is not None
    fixture = module_from_spec(spec)
    spec.loader.exec_module(fixture)
    monkeypatch.setattr(strategy_service, "build_jdj_context_series", fixture._contexts)

    actual = fixture._service(fixture._Reader()).history(fixture._request())
    expected = json.loads(_GOLDEN.read_text(encoding="utf-8"))

    assert [_project(action) for action in actual.actions] == expected
```

Do not add an update-golden flag or helper.

- [ ] **Step 4: Run the new parity test twice**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
```

Expected: PASS both times, proving deterministic fixture output.

- [ ] **Step 5: Verify this commit is test-only, then commit**

```bash
git diff --name-only
git diff --cached --name-only
```

Expected changed paths: only the new golden JSON and parity test.

```bash
git add \
  services/quant-api/tests/research/fixtures/jdj_jm_1m_v1_reference_golden.json \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
git commit -m "test(strategy): freeze JDJ JM 1m reference parity"
```

---

### Task 2: Make Segment Identity Explicit Without Expanding Product Scope Yet

**Files:**
- Modify: `services/quant-api/app/research/jdj_strategy/replay.py`
- Modify: `services/quant-api/app/research/jdj_strategy/service.py`
- Modify: `services/quant-api/tests/research/test_jdj_strategy_engine.py`
- Modify: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Test: `services/quant-api/tests/research/test_jdj_strategy_jm_parity.py`

**Interfaces:**
- Consumes: existing `ResolvedContractSegment`, current JM-only config, candidate events/contexts.
- Produces: `run_jdj_reference_segment(*, symbol: str, segment: ResolvedContractSegment, ...)` with no fake contract fallback.

- [ ] **Step 1: Add failing unit coverage for no-event/no-pivot and identity mismatches**

Add tests that call the desired signature and assert explicit identity is authoritative. The key cases must look like:

```python
segment = ResolvedContractSegment(
    contract="JM2701",
    start_trading_day=_SEGMENT_START,
    end_trading_day=_DAY,
)

result = replay.run_jdj_reference_segment(
    symbol="jm",
    segment=segment,
    bars_1m=bars,
    contexts=contexts_without_pivots,
    candidate_events=(),
    contract_multiplier=_MULTIPLIER,
    terminal_bar_end_by_day={_DAY: bars[-1].bar_end},
    config=load_jdj_v1_config(),
)
assert result.actions == ()
```

Also add negative cases for:

```python
# event symbol mismatch
symbol="rb" with an event whose symbol == "jm"

# event contract mismatch
event.contract != segment.contract

# event segment start mismatch
event.segment_start_trading_day != segment.start_trading_day

# bar outside segment window
bar.trading_day < segment.start_trading_day or > segment.end_trading_day

# terminal map must have neither missing nor extra trading days
set(terminal_bar_end_by_day) != {bar.trading_day for bar in bars}
```

All negative cases must raise `JdjStrategyReplayError`.

- [ ] **Step 2: Run the new tests and verify they fail on the old signature/fallback**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

Expected: FAIL because `symbol/segment` are not yet accepted or fake identity is still used.

- [ ] **Step 3: Change the replay signature and validation minimally**

In `replay.py`, import `ResolvedContractSegment` and change the public function to:

```python
def run_jdj_reference_segment(
    *,
    symbol: str,
    segment: ResolvedContractSegment,
    bars_1m: Sequence[CanonicalBar],
    contexts: Sequence[JdjBarContext],
    candidate_events: Sequence[JdjTriggerEvent],
    contract_multiplier: Decimal,
    terminal_bar_end_by_day: Mapping[date, datetime],
    config: JdjV1Config,
) -> JdjReferenceReplay:
```

Pass `symbol` and `segment` into `_validate_inputs`. Validation must reject unless:

```python
isinstance(symbol, str)
and symbol
and symbol == symbol.strip().lower()
and isinstance(segment, ResolvedContractSegment)
and all(segment.start_trading_day <= bar.trading_day <= segment.end_trading_day for bar in bars)
and set(terminal_bar_end_by_day) == {bar.trading_day for bar in bars}
and all(
    event.symbol == symbol
    and event.contract == segment.contract
    and event.segment_start_trading_day == segment.start_trading_day
    and segment.start_trading_day <= event.trading_day <= segment.end_trading_day
    for event in events
)
```

For context fact validation, call the existing `valid_context_fact_identity(...)` with:

```python
contract=segment.contract
segment_start_trading_day=segment.start_trading_day
```

Delete `_context_segment_identity()` entirely; do not replace it with another fallback.

- [ ] **Step 4: Pass the loader's exact segment from the service**

In `JdjStrategyReplayService.history()`, change only the replay call:

```python
replay = run_jdj_reference_segment(
    symbol=request.symbol,
    segment=segment,
    bars_1m=bars_1m,
    contexts=contexts,
    candidate_events=candidate_events,
    contract_multiplier=multiplier,
    terminal_bar_end_by_day=terminals,
    config=self._config,
)
```

Do not generalize JM admission/profile in this task.

- [ ] **Step 5: Update existing engine test helper calls to the explicit identity**

Where `_run()` calls `run_jdj_reference_segment`, construct the existing JM segment from fixture constants and bar days:

```python
segment = ResolvedContractSegment(
    contract=events[0].contract if events else _CONTRACT,
    start_trading_day=(
        events[0].segment_start_trading_day if events else _SEGMENT_START
    ),
    end_trading_day=max(bar.trading_day for bar in bars),
)
```

Then call with `symbol="jm", segment=segment`.

- [ ] **Step 6: Run lifecycle, service, and frozen parity tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
```

Expected: PASS; golden must remain byte-unchanged.

- [ ] **Step 7: Commit the identity refactor**

```bash
git add \
  services/quant-api/app/research/jdj_strategy/replay.py \
  services/quant-api/app/research/jdj_strategy/service.py \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
git commit -m "refactor(strategy): make JDJ segment identity explicit"
```

Do not add the golden file to this commit; it must already be unchanged and committed from Task 1.

---

### Task 3: Upgrade the Strategy Profile to V2 and Add Active-Product Admission

**Files:**
- Modify: `data/strategy_profiles/jdj_v1.json`
- Modify: `services/quant-api/app/research/jdj_strategy/contract.py`
- Modify: `services/quant-api/app/research/jdj_strategy/service.py`
- Modify: `services/quant-api/tests/research/test_jdj_strategy_contract.py`
- Modify: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Test: `services/quant-api/tests/research/test_jdj_strategy_jm_parity.py`

**Interfaces:**
- Consumes: explicit segment replay from Task 2 and current `load_active_products()` at composition time.
- Produces: one exact `jdj_active60_1m_v1` config and `JdjStrategyReplayService(..., products=tuple[str, ...], ...)` admission behavior.

- [ ] **Step 1: Change contract tests first**

Replace JM profile assertions with exact V2 assertions:

```python
config = contract.load_jdj_v1_config()
assert config.strategy_id == "jdj_intraday_futures_v1"
assert config.profile.profile_id == "jdj_active60_1m_v1"
assert config.profile.product_scope_source == "active_products"
assert not hasattr(config.profile, "symbol")
assert config.profile.series_kind == "actual_dominant"
assert config.profile.execution_frequency is BarFrequency.M1
assert config.profile.trend_context_frequency is BarFrequency.M5
```

Retain every current Core/Decimal value assertion unchanged.

Drift tests must mutate `profiles["jdj_active60_1m_v1"]`, and add explicit failures for:

```python
product_scope_source="all_products"
unexpected per_product_overrides={"jm": {}}
schema_version=1
```

- [ ] **Step 2: Add service tests for static request shape vs dynamic membership**

Desired request behavior:

```python
# accepted by request shape; membership is not checked here
request = JdjStrategyReplayRequest(
    series_kind="actual_dominant",
    symbol="rb",
    frequency="1m",
    since=_FIRST_END,
    through=_SECOND_END,
)
assert request.symbol == "rb"
```

Desired service behavior:

```python
service = JdjStrategyReplayService(..., products=("jm", "rb"), ...)
assert service.history(rb_request).request.symbol == "rb"
```

And before Historical load:

```python
service = JdjStrategyReplayService(..., products=("jm",), ...)
with pytest.raises(JdjStrategyProfileUnavailableError):
    service.history(rb_request)
assert loader.calls == []
```

The same task must also prove that one service has no cached product identity. Generalize the existing `_Reader` fixture to accept this exact per-symbol segment map:

```python
_SEGMENTS_BY_SYMBOL = {
    "jm": (
        ResolvedContractSegment("JM2701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("JM2705", _SECOND_START, _SECOND_END),
    ),
    "rb": (
        ResolvedContractSegment("RB2701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("RB2705", _SECOND_START, _SECOND_END),
    ),
    "cf": (
        ResolvedContractSegment("CF701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("CF705", _SECOND_START, _SECOND_END),
    ),
    "sc": (
        ResolvedContractSegment("SC2701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("SC2705", _SECOND_START, _SECOND_END),
    ),
}


def test_one_service_replays_symbols_sequentially_without_cached_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series", _contexts
    )
    reader = _Reader(segments_by_symbol=_SEGMENTS_BY_SYMBOL)
    service = _service(
        reader,
        products=("jm", "rb", "cf", "sc"),
    )

    for symbol in ("jm", "rb", "cf", "sc"):
        result = service.history(_request(symbol=symbol))
        assert result.request.symbol == symbol
        assert all(
            action.contract.startswith(symbol.upper())
            for action in result.actions
        )

    assert list(dict.fromkeys(call.symbol for call in reader.calls)) == [
        "jm", "rb", "cf", "sc"
    ]
```

`_Reader.query_actual_dominant_trading_days()` must choose `resolved_contract_segments` from `segments_by_symbol[request.symbol]`, and `_Reader.dominant_segment_for_day()` must use the same map. The generic multiplier and terminal callbacks must record their received `symbol` and validate the matching mapped contract; they must not rewrite a JM event after candidate reduction. This is the service-level proof required by the Spec; Task 4 separately proves Catalog exchange/session lookup.

Keep request rejection for `continuous`, `5m`, invalid dates, blank/unnormalizable symbol.

- [ ] **Step 3: Run contract/service tests and verify they fail**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

Expected: FAIL on old JM-only profile and request membership behavior.

- [ ] **Step 4: Replace `jdj_v1.json` with the exact V2 payload from the Spec**

The profile section must be exactly:

```json
"profiles": {
  "jdj_active60_1m_v1": {
    "product_scope_source": "active_products",
    "series_kind": "actual_dominant",
    "execution_frequency": "1m",
    "trend_context_frequency": "5m",
    "base_risk_fraction": "0.005",
    "first_profit_take_fraction": "0.40",
    "historical_reference_start_equity": "1000000",
    "entry_limit_valid_bars": 1,
    "terminal_flatten_lead_bars": 1
  }
}
```

All Core fields/values remain byte-for-value equivalent to V1.

- [ ] **Step 5: Update the exact Python contract**

In `contract.py`:

```python
_DEFAULT_PROFILE_ID = "jdj_active60_1m_v1"
```

Change `JdjStrategyProfile` from `symbol: str` to:

```python
product_scope_source: str
```

Update `_EXPECTED_PAYLOAD` to `schema_version=2` and exact `product_scope_source="active_products"`. `load_jdj_v1_config()` still accepts only the single default profile id.

- [ ] **Step 6: Separate request shape from service membership**

`JdjStrategyReplayRequest.__post_init__()` must no longer require `symbol == "jm"`; it still normalizes to trimmed lowercase and rejects blank/non-string values.

Add `products` to the service constructor:

```python
def __init__(
    self,
    segment_loader: _ResearchSegmentLoader,
    *,
    products: tuple[str, ...],
    jdj_policy: JdjPolicy,
    n_policy: NStructurePolicy,
    contract_multiplier_for_contract: _ContractMultiplierResolver,
    terminal_bar_ends_for_segment: _SessionTerminalResolver,
    config: JdjV1Config | None = None,
) -> None:
```

Constructor validation must require:

```python
resolved_config.profile.product_scope_source == "active_products"
resolved_config.profile.series_kind == SeriesKind.ACTUAL_DOMINANT.value
resolved_config.profile.execution_frequency is BarFrequency.M1
resolved_config.profile.trend_context_frequency is BarFrequency.M5
isinstance(products, tuple)
products
all(isinstance(item, str) and item and item == item.strip().lower() for item in products)
len(set(products)) == len(products)
```

Store `self._products = products`.

At the first line of `history()` after type-checking the request:

```python
if request.symbol not in self._products:
    raise JdjStrategyProfileUnavailableError()
```

This check must precede `self._segment_loader.load(...)`.

- [ ] **Step 7: Keep tests generic across symbols**

Generalize the test reader/service fixture so it can be constructed for a supplied symbol/contract pair rather than asserting JM inside every callback. Do not change candidate formulas; only test fixture identity data changes.

For a minimal active service test, use `rb` with `RB2701/RB2705` fixture identity and the same synthetic bar values. Candidate event identity must use `symbol="rb"` through the existing reducers/service rather than string replacement after generation.

- [ ] **Step 8: Run contract/service/parity tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
```

Expected: PASS; golden unchanged.

- [ ] **Step 9: Commit profile/admission**

```bash
git add \
  data/strategy_profiles/jdj_v1.json \
  services/quant-api/app/research/jdj_strategy/contract.py \
  services/quant-api/app/research/jdj_strategy/service.py \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
git commit -m "feat(strategy): admit active products to JDJ replay"
```

---

### Task 4: Resolve Exchange, Multiplier, and Session Facts Per Symbol

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/tests/test_research_composition.py`
- Test: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Test: `services/quant-api/tests/research/test_jdj_strategy_jm_parity.py`

**Interfaces:**
- Consumes: `JdjStrategyReplayService(... products=...)` from Task 3.
- Produces: one service whose callbacks derive exchange/multiplier/session from each callback's `symbol`, not builder state.

- [ ] **Step 1: Write failing cross-exchange composition tests**

Parameterize at least:

```python
("jm", "DCE", "JM2701", 60)
("rb", "SHFE", "RB2701", 10)
("cf", "CZCE", "CF701", 5)
("sc", "INE", "SC2701", 1000)
```

The fake session must return exchange by the symbol encoded in the SQL statement fixture or by a controlled monkeypatched resolver; the important assertion is that each callback invocation uses its own symbol.

Capture service construction and assert:

```python
assert captured["products"] == ("jm", "rb", "cf", "sc")
multiplier = captured["contract_multiplier_for_contract"]
terminals = captured["terminal_bar_ends_for_segment"]

assert multiplier(symbol="jm", contract="JM2701") == Decimal("60")
assert multiplier(symbol="rb", contract="RB2701") == Decimal("10")
assert multiplier(symbol="cf", contract="CF701") == Decimal("5")
assert multiplier(symbol="sc", contract="SC2701") == Decimal("1000")
```

Also verify `resolved_session_windows_for_trading_day` receives each symbol's matching exchange.

- [ ] **Step 2: Add fail-closed tests for owner/exchange/multiplier/session facts**

Keep or extend cases for:

```text
missing Instrument
inactive Instrument
ambiguous/empty exchange
missing Contract
contract owner != symbol
contract exchange != resolved exchange
multiplier is None / bool / zero / negative / non-int
duplicate Contract rows
session resolver error
empty session windows
terminal not present in current segment bars
```

All Catalog/profile failures map to `JdjStrategyContextInvalidError`; session identity failures remain `JdjStrategySessionIdentityError`.

- [ ] **Step 3: Run composition tests and verify old JM-captured builder fails**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_composition.py
```

Expected: FAIL on non-JM callbacks.

- [ ] **Step 4: Implement a local `exchange_for_symbol` helper inside the builder**

Inside `build_jdj_strategy_replay_service(session)`:

```python
def exchange_for_symbol(symbol: str) -> str:
    rows = tuple(
        session.scalars(
            select(Instrument.exchange_code).where(
                Instrument.symbol == symbol,
                Instrument.is_active.is_(True),
            )
        )
    )
    if len(rows) != 1 or not isinstance(rows[0], str) or not rows[0]:
        raise JdjStrategyContextInvalidError()
    return rows[0]
```

Do not call this helper once at builder construction and cache the result globally.

- [ ] **Step 5: Make the multiplier callback validate current symbol ownership**

```python
def contract_multiplier_for_contract(*, symbol: str, contract: str) -> Decimal:
    exchange = exchange_for_symbol(symbol)
    rows = tuple(
        session.execute(
            select(
                Contract.instrument_symbol,
                Contract.exchange_code,
                Contract.contract_multiplier,
            ).where(Contract.contract_code == contract)
        )
    )
    if len(rows) != 1:
        raise JdjStrategyContextInvalidError()
    owner, contract_exchange, multiplier = rows[0]
    if (
        owner != symbol
        or contract_exchange != exchange
        or isinstance(multiplier, bool)
        or not isinstance(multiplier, int)
        or multiplier <= 0
    ):
        raise JdjStrategyContextInvalidError()
    return Decimal(multiplier)
```

- [ ] **Step 6: Make the session callback resolve exchange per invocation**

```python
def terminal_bar_ends_for_segment(
    *,
    symbol: str,
    bars_1m: Sequence[CanonicalBar],
) -> dict[date, datetime]:
    if not bars_1m:
        raise JdjStrategySessionIdentityError()
    exchange = exchange_for_symbol(symbol)
    terminals: dict[date, datetime] = {}
    for trading_day in sorted({bar.trading_day for bar in bars_1m}):
        try:
            windows = resolved_session_windows_for_trading_day(
                session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_day,
            )
        except SessionClockError:
            raise JdjStrategySessionIdentityError() from None
        if not windows:
            raise JdjStrategySessionIdentityError()
        terminal = max(item.window.end for item in windows)
        bar_ends = {
            bar.bar_end for bar in bars_1m if bar.trading_day == trading_day
        }
        if terminal.tzinfo is None or terminal.astimezone(UTC) not in bar_ends:
            raise JdjStrategySessionIdentityError()
        terminals[trading_day] = terminal
    return terminals
```

- [ ] **Step 7: Inject the one active universe into the service**

Builder final construction must include:

```python
return JdjStrategyReplayService(
    ActualDominantResearchSegmentLoader(market_data),
    products=load_active_products(),
    jdj_policy=jdj_policy,
    n_policy=n_policy,
    contract_multiplier_for_contract=contract_multiplier_for_contract,
    terminal_bar_ends_for_segment=terminal_bar_ends_for_segment,
)
```

Do not copy the product tuple into another constant.

- [ ] **Step 8: Run composition + replay + parity tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
```

Expected: PASS.

- [ ] **Step 9: Commit dynamic market facts**

```bash
git add \
  services/quant-api/app/research/composition.py \
  services/quant-api/tests/test_research_composition.py
git commit -m "feat(strategy): resolve JDJ product facts dynamically"
```

---

### Task 5: Stabilize HTTP Error Mapping and Prove Non-JM Web Identity

**Files:**
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Expected unchanged: `apps/quant-web/src/api/market.ts`
- Expected unchanged: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Expected unchanged: `apps/quant-web/src/utils/mainIndicators.ts`

**Interfaces:**
- Consumes: active-aware service and per-symbol composition.
- Produces: unchanged HTTP DTO shape with precise 422/409 mapping; existing Web path demonstrably sends/guards non-JM symbol identity.

- [ ] **Step 1: Write failing backend API tests for the complete error matrix**

Add tests for:

```text
rb active request -> 200 with request.symbol == "rb"
non-active symbol -> 422 / JDJ_STRATEGY_PROFILE_UNAVAILABLE
builder raises ActiveUniverseError -> 409 / ACTIVE_UNIVERSE_INVALID
service raises JdjStrategyContextInvalidError -> 409
service raises JdjStrategySegmentIdentityError -> 409
service raises JdjStrategySessionIdentityError -> 409
```

The non-active test must make the mocked service raise `JdjStrategyProfileUnavailableError` from `.history()`, not request construction, proving route coverage at the service boundary.

- [ ] **Step 2: Run the backend API test and verify service-stage 422 is currently uncaught**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: the new service-stage profile-unavailable/active-universe cases fail until route handling is changed.

- [ ] **Step 3: Keep request and history inside the typed error boundary**

The endpoint should follow this structure:

```python
try:
    request = JdjStrategyReplayRequest(
        series_kind=series_kind,
        symbol=symbol,
        frequency=frequency,
        since=since,
        through=through,
    )
    result = build_jdj_strategy_replay_service(session).history(request)
except JdjStrategyProfileUnavailableError as exc:
    raise HTTPException(status_code=422, detail={"code": exc.code}) from None
except ActiveUniverseError as exc:
    raise HTTPException(status_code=409, detail={"code": exc.code}) from None
except (
    JdjStrategyContextInvalidError,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
) as exc:
    raise HTTPException(status_code=409, detail={"code": exc.code}) from None
```

Response projection remains unchanged.

- [ ] **Step 4: Add a Web unit test proving identity uses the current non-JM symbol**

In `historicalResearchMarkers.test.ts`, use a strategy identity such as:

```ts
{
  overlay: 'jdj_strategy',
  seriesKind: 'actual_dominant',
  symbol: 'rb',
  frequency: '1m',
}
```

Capture `fetchJdjStrategy` request and assert:

```ts
assert.equal(request.symbol, 'rb')
assert.equal(request.series_kind, 'actual_dominant')
assert.equal(request.frequency, '1m')
```

Also keep the existing full-response request identity mismatch rejection test; add `rb -> jm` mismatch if not already explicit.

- [ ] **Step 5: Add/adjust Playwright coverage without changing production Web source**

In `market-research.spec.mjs`, make the mocked current workspace select a non-JM product (use an existing active fixture such as `rb`) and assert the intercepted `/research/jdj-strategy/history` request carries `symbol=rb` and `frequency=1m`.

Return one valid RB action:

```js
{
  event_id: 'jdj-strategy-rb-entry-1',
  episode_id: 'jdj-rb-episode-1',
  kind: 'entry',
  source_event_ids: ['jdj-rb-follow-long-1'],
  primary_setup: 'trend_follow',
  supporting_setups: [],
  direction: 'long',
  contract: 'RB2701',
  trading_day: '2026-08-20',
  segment_start_trading_day: '2026-08-20',
  decision_at: '2026-08-20T01:01:00Z',
  effective_bar_end: '2026-08-20T01:02:00Z',
  reference_price: '3200',
  quantity: 1,
  position_quantity_after: 1,
  stop_price: '3180',
  target_price: '3240',
  reward_risk: '2',
  reason: 'ENTRY_AUTHORIZED',
  fill_basis: 'limit_touch',
}
```

Assert the corresponding marker renders. Do not add a new product selector or strategy UI.

- [ ] **Step 6: Run backend + Web unit + focused Playwright**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
```

Expected: PASS. If production Web source changes were needed, document the exact pre-existing JM-only bug in the commit; otherwise keep `apps/quant-web/src/**` untouched.

- [ ] **Step 7: Run parity again, then commit HTTP/Web tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py

git add \
  services/quant-api/app/research/historical_overlay_api.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(strategy): expose JDJ replay across active products"
```

---

### Task 6: Align Canonical Documentation and Run Full Automated Verification

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `TESTING.md`
- Do not modify yet: `STATUS.md`

**Interfaces:**
- Consumes: completed implementation from Tasks 1–5.
- Produces: canonical wording and reproducible verification commands matching actual code, with `STATUS.md` intentionally deferred.

- [ ] **Step 1: Update `PROJECT_SOURCE.md` only where the old JM-only replay boundary is now false**

Replace wording equivalent to:

```text
JM actual_dominant + 1m 日进斗金参考策略
```

with the precise current capability:

```text
当前 active universe 中单产品的 actual_dominant + 1m 日进斗金参考策略 replay
```

Keep all of these unchanged:

```text
research-only
deterministic reference replay
not formal backtest
not RQAlpha adapter
no DB/Redis/Alert/Execution Review/Runtime/order path
```

Do not describe active60 as OOS-validated.

- [ ] **Step 2: Update the corresponding `AGENTS.md` hard rule**

Change only the JM-specific product scope text in the JDJ reference replay rule. Preserve all no-order/no-write/RQAlpha isolation wording.

- [ ] **Step 3: Add an exact JDJ active60 verification section to `TESTING.md`**

The focused backend command must include:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_research_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py
```

And:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  ruff check services/quant-api/app/research/jdj_strategy \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/research/historical_overlay_api.py \
  services/quant-api/tests/research/test_jdj_strategy_*.py \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/test_market_research_overlays_api.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/research/jdj_strategy \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/research/historical_overlay_api.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py
```

Do not add a real RQAlpha command.

- [ ] **Step 4: Run the complete focused backend verification**

Run the exact pytest/Ruff/Mypy commands above.

Expected: all PASS.

- [ ] **Step 5: Run Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: all PASS.

- [ ] **Step 6: Run secret scan**

```bash
python3 scripts/engineering/secret_scan.py
```

Expected: `[secret-scan] status=passed findings=0`.

- [ ] **Step 7: Confirm no forbidden implementation paths changed**

```bash
git diff --name-only develop...HEAD
```

Review the list and fail the task if it contains unexpected changes under:

```text
services/quant-api/app/research/jdj/          # Candidate reducers
services/quant-api/app/research/n_structure/  # N formula
services/quant-api/app/alerts/
services/quant-api/app/execution_review/
services/quant-api/app/backtest/
services/quant-api/alembic/
```

Also fail if `STATUS.md` changed before the empirical smoke.

- [ ] **Step 8: Commit canonical docs**

```bash
git add PROJECT_SOURCE.md AGENTS.md TESTING.md
git commit -m "docs: align JDJ active60 replay contract"
```

---

### Task 7: Open the Develop PR and Stop for Independent Review

**Files:** none required unless Review finds defects.

**Interfaces:**
- Consumes: Tasks 1–6 and their green automated verification.
- Produces: a reviewable PR to `develop`; no merge yet.

- [ ] **Step 1: Push only the task branch**

```bash
git status --short
git log --oneline --decorate -6
git push -u origin feature/jdj-active60-1m-strategy
```

Expected: clean worktree after push.

- [ ] **Step 2: Open a PR targeting `develop`**

PR summary must state:

```text
- JM golden was frozen before production changes.
- Strategy Core/Candidate formulas are unchanged.
- Product admission is current active_products only.
- Replay remains research-only reference semantics.
- No OOS/Alert/Runtime/RQAlpha/DB/Canonical/Redis/order changes.
- Fixed-window real read-only active60 smoke has NOT been run yet; it is gated after independent code Review.
```

- [ ] **Step 3: STOP and dispatch a separate Sol/high Review session**

Reviewer must read Spec + Plan + PR diff and explicitly check:

```text
JM golden provenance and immutability
Candidate formula diff = zero
Core rule diff = zero
active universe single source
no builder-cached symbol/exchange state
contract owner/exchange/multiplier validation
session terminal per symbol
no fake JM0000/date.min identity
422/409 error matrix
reference price/quantity not overstated as executable
no prospective/OOS use
no Alert/Runtime/RQAlpha/DB/data writes
Web production code unchanged unless justified
```

Required review conclusion before proceeding:

```text
允许继续实现
```

If reviewer says `要求修正后再集成` or `阻塞`, fix on the same task branch, rerun affected verification, and repeat independent Review. Do not run the real active60 smoke until Review allows continuation.

---

### Task 8: Run the Fixed-Window Active60 Read-Only Capability Smoke

**Files:** no repository files are created by the smoke.

**Interfaces:**
- Consumes: independently reviewed task branch and current local read-only Catalog/Canonical facts.
- Produces: terminal-only per-symbol capability result for all current active60 products.

- [ ] **Step 1: Confirm branch/worktree identity and clean state**

```bash
git branch --show-current
git status --short
git rev-parse HEAD
```

Expected: task branch, clean worktree. Do not run from main/runtime worktrees.

- [ ] **Step 2: Run the repository-outer shell loop, one symbol per process**

Run from repository root:

```bash
jdj_project_env_file="/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env"

if ! test -f "$jdj_project_env_file" \
  || ! test "$(stat -f '%u' "$jdj_project_env_file")" -eq "$(id -u)" \
  || ! test "$(stat -f '%Lp' "$jdj_project_env_file")" = "600"; then
  printf '{"status":"command_failed","code":"JDJ_STRATEGY_SMOKE_ENV_INVALID"}\n' >&2
  exit 1
fi

set -a
if ! source "$jdj_project_env_file"; then
  set +a
  printf '{"status":"command_failed","code":"JDJ_STRATEGY_SMOKE_ENV_INVALID"}\n' >&2
  exit 1
fi
set +a

test -n "${DATABASE_URL:-}" || {
  printf '{"status":"command_failed","code":"JDJ_STRATEGY_SMOKE_ENV_INVALID"}\n' >&2
  exit 1
}

cd services/quant-api
active_products_file="../../data/universe/active_products.txt"
processed=0

while IFS= read -r symbol || test -n "$symbol"; do
  test -n "$symbol" || continue
  if UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
    uv run --offline python - "$symbol" <<'PY'
from __future__ import annotations

from datetime import date
import json
import sys

from app.db.session import SessionLocal
from app.market_data.operational_universe import ActiveUniverseError
from app.research.composition import build_jdj_strategy_replay_service
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyProfileUnavailableError,
    JdjStrategyReplayRequest,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
)

symbol = sys.argv[1]

try:
    with SessionLocal() as session:
        service = build_jdj_strategy_replay_service(session)
        request = JdjStrategyReplayRequest(
            series_kind="actual_dominant",
            symbol=symbol,
            frequency="1m",
            since=date(2026, 8, 18),
            through=date(2026, 8, 20),
        )
        result = service.history(request)
except (
    JdjStrategyProfileUnavailableError,
    JdjStrategyContextInvalidError,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
) as exc:
    payload = {
        "window": "2026-08-18..2026-08-20",
        "symbol": symbol,
        "status": "typed_unavailable",
        "code": exc.code,
    }
except ActiveUniverseError as exc:
    print(json.dumps({
        "window": "2026-08-18..2026-08-20",
        "symbol": symbol,
        "status": "command_failed",
        "code": exc.code,
    }, ensure_ascii=False))
    raise SystemExit(1) from None
except Exception:
    print(json.dumps({
        "window": "2026-08-18..2026-08-20",
        "symbol": symbol,
        "status": "command_failed",
        "code": "JDJ_STRATEGY_SMOKE_UNEXPECTED_FAILURE",
    }, ensure_ascii=False))
    raise SystemExit(1) from None
else:
    payload = {
        "window": "2026-08-18..2026-08-20",
        "symbol": symbol,
        "status": "ok",
        "action_count": len(result.actions),
    }

print(json.dumps(payload, ensure_ascii=False))
PY
  then
    processed=$((processed + 1))
  else
    exit_status=$?
    printf '{"symbol":"%s","status":"command_failed","exit_status":%s}\n' \
      "$symbol" "$exit_status" >&2
    exit "$exit_status"
  fi
done < "$active_products_file"

test "$processed" -eq 60 || {
  printf '{"status":"command_failed","code":"ACTIVE60_RESULT_COUNT_INVALID","count":%s}\n' \
    "$processed" >&2
  exit 1
}

cd ../..
```

Expected:

- the secure external project env exists, is owned by the invoking user, and has
  exact mode `0600`;
- the secure external project env is sourced before any Python process imports
  `app.db.session`;
- `DATABASE_URL` is present after sourcing;
- any environment validation failure emits only
  `JDJ_STRATEGY_SMOKE_ENV_INVALID`, does not print config values, and aborts
  before processing a symbol;
- exactly 60 result entries in active-universe order;
- each entry is `ok` or a known typed Strategy unavailable code;
- the shell reads `data/universe/active_products.txt` directly and starts one
  existing single-product replay process per non-empty line;
- any active-universe or unexpected failure prints the current symbol and a
  non-zero status, then aborts rather than being swallowed;
- no repository file changes.

Attempt 1 failed closed at symbol `a` because the original plan omitted
environment propagation. No repository change occurred. The user approved this
amendment plus exactly one retry after independent Review.

- [ ] **Step 3: Verify the smoke wrote nothing to the repository**

```bash
git status --short
```

Expected: empty.

- [ ] **Step 4: Interpret the smoke narrowly**

Allowed conclusion:

```text
All current active60 products were processed by the same JDJ replay contract or failed closed with an explicit typed reason for the fixed retrospective window.
```

Forbidden conclusions:

```text
profitable
effective
generalizes
OOS passed
tradeable
promotion-ready
Runtime-ready
```

If a code defect is exposed, return to the same task branch, fix it, rerun automated verification, and repeat independent Review before repeating this smoke.

---

### Task 9: Record Completion State, Re-Verify Docs, and Integrate Only After Review Approval

**Files:**
- Modify: `STATUS.md`
- Test/read: `PROJECT_SOURCE.md`, `AGENTS.md`, `TESTING.md`

**Interfaces:**
- Consumes: green automated verification, independent Review approval, fixed-window active60 smoke.
- Produces: accurate `develop`-candidate status and a PR eligible for merge to `develop` only.

- [ ] **Step 1: Update `STATUS.md` with facts only**

Add a concise develop section that records:

```text
- exact task-branch implementation commit under review/merge
- JDJ reference replay now supports current active60 + actual_dominant + 1m
- JM golden exact parity passed
- fixed smoke window 2026-08-18..2026-08-20
- count of ok vs typed_unavailable from the observed smoke output
- Strategy remains research-only; no OOS/Alert/Runtime/RQAlpha/data/DB/order change
```

Do not claim main/release/Runtime status changed. Do not paste raw paths, secrets, full smoke JSON, PnL, rankings, or strategy-validity conclusions.

- [ ] **Step 2: Run documentation/secret checks and parity one last time**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py

python3 scripts/engineering/secret_scan.py

git diff --check
```

Expected: PASS / no whitespace errors.

- [ ] **Step 3: Commit status closeout**

```bash
git add STATUS.md
git commit -m "docs: record JDJ active60 replay completion"
git push
```

- [ ] **Step 4: Re-read the PR diff and obtain the final independent integration conclusion**

The reviewer must explicitly return:

```text
允许集成 develop
```

If not, do not merge.

- [ ] **Step 5: Merge task branch to `develop` only**

After the independent Review says `允许集成 develop`, merge through the repository's normal PR/integration flow. Do not publish `main`, tag, release, or Runtime.

- [ ] **Step 6: Verify develop ancestry/readback**

```bash
git fetch origin develop
git merge-base --is-ancestor <TASK_FINAL_SHA> origin/develop
git show origin/develop:docs/superpowers/specs/2026-08-24-jdj-active60-1m-strategy-design.md >/dev/null
git show origin/develop:docs/superpowers/plans/2026-08-24-jdj-active60-1m-strategy.md >/dev/null
```

Expected: ancestor check returns zero and both documents are present.

- [ ] **Step 7: Clean the temporary task worktree/branch only after confirmed integration**

Resolve and record the exact task worktree path, then fail closed unless all
preconditions hold:

```bash
set -euo pipefail

task_worktree_path="<EXACT_TASK_WORKTREE_PATH>"
cleanup_controller_path="<EXACT_DEVELOP_WORKTREE_PATH>"
task_branch=feature/jdj-active60-1m-strategy
launch_agents_dir="/Users/zhangzhao/Library/LaunchAgents"

test -d "$task_worktree_path"
test ! -L "$task_worktree_path"
test "$(git -C "$task_worktree_path" branch --show-current)" = "$task_branch"
test -z "$(git -C "$task_worktree_path" status --porcelain)"
test "$(git -C "$cleanup_controller_path" branch --show-current)" = develop
test -z "$(git -C "$cleanup_controller_path" status --porcelain --untracked-files=no)"
test "$(cd "$task_worktree_path" && pwd -P)" != \
  "$(cd "$cleanup_controller_path" && pwd -P)"
git -C "$cleanup_controller_path" worktree list --porcelain

for label in \
  com.guiyi.quant-api \
  com.guiyi.quant-web \
  com.guiyi.quant-live \
  com.guiyi.quant-after-market \
  com.guiyi.quant-alert
do
  installed_plist="$launch_agents_dir/$label.plist"
  test -f "$installed_plist" || {
    printf 'TASK_WORKTREE_PLIST_IDENTITY_UNRESOLVED label=%s reason=missing\n' \
      "$label" >&2
    exit 1
  }
  plist_root="$(
    plutil -extract EnvironmentVariables.GUIYI_PROJECT_ROOT raw -o - \
      "$installed_plist" 2>/dev/null
  )" || {
    printf 'TASK_WORKTREE_PLIST_IDENTITY_UNRESOLVED label=%s reason=unreadable\n' \
      "$label" >&2
    exit 1
  }
  test -n "$plist_root" || {
    printf 'TASK_WORKTREE_PLIST_IDENTITY_UNRESOLVED label=%s reason=empty\n' \
      "$label" >&2
    exit 1
  }
  if test "$plist_root" = "$task_worktree_path"
  then
    printf 'TASK_WORKTREE_INSTALLED_PLIST_REFERENCE_PRESENT label=%s\n' \
      "$label" >&2
    exit 1
  fi

  if ! launch_output="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null)"
  then
    printf 'TASK_WORKTREE_LAUNCH_IDENTITY_UNRESOLVED label=%s\n' "$label" >&2
    exit 1
  fi
  if printf '%s\n' "$launch_output" | rg -F -q -- "$task_worktree_path"
  then
    printf 'TASK_WORKTREE_LOADED_RUNTIME_REFERENCE_PRESENT label=%s\n' \
      "$label" >&2
    exit 1
  fi
done

git -C "$cleanup_controller_path" merge --ff-only origin/develop
git -C "$cleanup_controller_path" worktree remove "$task_worktree_path"
git -C "$cleanup_controller_path" branch -d "$task_branch"

if git ls-remote --exit-code --heads origin "$task_branch" >/dev/null 2>&1
then
  remote_branch_status=0
else
  remote_branch_status=$?
fi
case "$remote_branch_status" in
  0) printf 'REMOTE_TASK_BRANCH_REMAINS branch=%s\n' "$task_branch" ;;
  2) printf 'REMOTE_TASK_BRANCH_ABSENT branch=%s\n' "$task_branch" ;;
  *) printf 'REMOTE_TASK_BRANCH_STATUS_UNRESOLVED branch=%s\n' "$task_branch" ;;
esac
```

Do not use `--force`, broad paths, unresolved variables, direct directory
deletion, or any command that touches `main`, tags, release refs, or Runtime
worktrees. If an installed plist or loaded launchd label cannot be read, or
either references the task worktree, stop without removing anything. A remote
task branch is status-only here: deleting a remote ref requires a new,
single-use explicit intent and is not authorized by this plan.

---

## Plan Self-Review Checklist

Before implementation begins, the executor must confirm this plan covers every Spec hard requirement:

- [ ] pre-change JM golden is committed before production edits;
- [ ] no Candidate/Core semantic changes;
- [ ] V2 one-profile contract with `product_scope_source=active_products`;
- [ ] request shape and service membership are separate;
- [ ] current active universe is the only admission source;
- [ ] `ResolvedContractSegment` is explicit replay identity; no `JM0000/date.min` fallback;
- [ ] exchange/multiplier/session are resolved per callback symbol;
- [ ] HTTP 422/409 matrix is stable;
- [ ] Web sends current non-JM symbol without new UI;
- [ ] reference price/quantity remain non-executable research semantics;
- [ ] OOS/Alert/Runtime/RQAlpha/DB/Canonical/Redis/order paths remain untouched;
- [ ] independent Review occurs before the real read-only capability smoke;
- [ ] fixed smoke does not cross `2026-08-20`;
- [ ] `STATUS.md` is updated only after tests + Review + smoke;
- [ ] merge target is `develop` only;
- [ ] task worktree/branch cleanup happens only after integration readback.

Any unchecked item is a blocker; do not reinterpret it away during implementation.
