from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.market_data.contract_preparation_runtime import discover_demands, ContractPreparationWorker
from app.market_data.market_phase import MarketPhase

NOW = datetime(2026, 10, 26, 12, 45, tzinfo=UTC)
DAY = date(2026, 10, 27)


def fake_catalog_authority(monkeypatch, selected, state=None):
    from app.market_data import catalog, composition, market_phase
    state = state if state is not None else {}
    class Catalog:
        def __init__(self, session, root):
            self.session = session
        def contract_fact(self, product, contract):
            return SimpleNamespace(listed_date=state.get("listed_date", selected.listed_date), expired_date=selected.expired_date)
    monkeypatch.setattr(catalog, "MarketCatalog", Catalog)
    monkeypatch.setattr(composition, "build_database_coverage_source", lambda session: SimpleNamespace(
        latest_complete_day_with_refresh_at=lambda products, now: (state.get("through", selected.through), now)))
    monkeypatch.setattr(market_phase, "MarketPhaseResolver", lambda session: SimpleNamespace(
        resolve=lambda product, instant: SimpleNamespace(phase=state.get("phase", MarketPhase.TRADING),
                                                         trading_day=state.get("day", selected.trading_day))))


def test_discovery_uses_current_or_thirty_minute_session_and_rank1_only():
    calls = []
    class Resolver:
        def resolve(self, symbol, instant):
            calls.append((symbol, instant))
            active = symbol == "rb" and instant > NOW
            return SimpleNamespace(phase=MarketPhase.TRADING if active else MarketPhase.CLOSED,
                                   trading_day=DAY if active else None)
    demands = discover_demands(now=NOW, products=("rb", "cu"), resolver=Resolver(),
                               scopes={"rb": (("5m", "1w"), "rb-scope"), "cu": (("1d",), "cu-scope")},
                               dominant=lambda product, day: "RB2701",
                               contract_fact=lambda product, contract: SimpleNamespace(listed_date=date(2026, 1, 1), expired_date=date(2027, 1, 16)),
                               completed_day=lambda product: date(2026, 10, 26))
    assert len(demands) == 1
    assert demands[0].trading_day == DAY
    assert demands[0].frequencies == ("5m", "1w")
    assert len(calls) == 4


def test_unknown_authority_fails_closed_without_guessing_next_contract():
    calls = []
    class Resolver:
        def resolve(self, symbol, instant):
            return SimpleNamespace(phase=MarketPhase.UNKNOWN, trading_day=None)
    import pytest
    with pytest.raises(ValueError, match="AUTHORITY_UNAVAILABLE"):
        discover_demands(now=NOW, products=("rb",), resolver=Resolver(), scopes={"rb": (("5m",), "scope")},
                         dominant=lambda *args: calls.append(args), contract_fact=None, completed_day=None)
    assert calls == []


def test_disabled_product_never_resolves_or_creates_demand():
    class Resolver:
        def resolve(self, *args):
            raise AssertionError("disabled")
    assert discover_demands(now=NOW, products=("rb",), resolver=Resolver(), scopes={},
                            dominant=None, contract_fact=None, completed_day=None) == ()


def test_worker_lifecycle_calls_coordinator_in_own_thread_and_joins():
    import threading
    done = threading.Event()
    calls = []
    class Preparation:
        def tick(self, now):
            calls.append(threading.current_thread().name)
            done.set()
        def snapshot(self):
            return {"requests": {}}
    worker = ContractPreparationWorker(Preparation(), interval=60)
    worker.start()
    assert done.wait(2)
    worker.stop()
    assert calls == ["market-contract-preparation"]
    assert worker.snapshot()["running"] is False


def test_real_composition_keeps_apply_lease_reservation_and_fresh_readback_sessions(tmp_path, monkeypatch):
    from app.market_data import contract_preparation_runtime as module
    from app.market_data import market_data_service as service_module
    from app.market_data.contract_preparation import PreparationDemand
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite+pysqlite:///:memory:")
    opened = []
    def session_factory():
        session = Session(engine)
        opened.append(session)
        return session
    calls = []
    selected = PreparationDemand("rb", "RB2701", DAY, date(2026, 1, 1), date(2027, 1, 16), date(2026, 10, 26), ("5m",), "scope")
    class Manager:
        def __init__(self, session):
            self.session = session
        def contract_warmup(self, request, **kwargs):
            calls.append(("apply" if request.apply else "plan", self.session))
            if request.apply:
                kwargs["before_apply"]()
                # Durable state and budget must precede the source boundary.
                state = preparation.snapshot()
                unit = next(iter(state["requests"].values()))["units"]["5m"]
                assert unit["status"] == "INFLIGHT"
                assert state["budgets"][DAY.isoformat()]["requests"] == 1
            return SimpleNamespace(plan=SimpleNamespace(listed_date=selected.listed_date, expired_date=selected.expired_date,
                requested_through=selected.through, plan_sha256="a" * 64, provider_request_count=1,
                expected_bar_count=100, target_windows=()), status="passed", applied=1, failures=())
    class Data:
        def __init__(self, catalog, store):
            self.session = catalog.session
        def dominant_segment_for_day(self, product, day):
            return SimpleNamespace(contract=selected.contract)
        def query_contract_trading_days(self, request):
            calls.append(("MDS", self.session))
            assert request.contract == selected.contract
    monkeypatch.setattr(service_module, "MarketDataService", Data)
    fake_catalog_authority(monkeypatch, selected)
    monkeypatch.setattr(module, "enabled_consumer_scopes", lambda session, products: {"rb": (selected.frequencies, "scope")})
    preparation = module.build_contract_preparation(session_factory, canonical_root=tmp_path / "canonical", products=("rb",),
                                                   state_path=tmp_path / "state.json", manager_factory=lambda session, **kwargs: Manager(session), clock=lambda: NOW)
    preparation.discover = lambda now: (selected,)
    assert preparation.tick(NOW) is None
    assert [kind for kind, session in calls] == ["plan", "apply", "plan", "MDS"]
    assert calls[0][1] is not calls[1][1]
    assert calls[1][1] is not calls[2][1]
    assert calls[2][1] is calls[3][1]
    engine.dispose()


def test_requester_never_constructs_manager_or_provider(tmp_path, monkeypatch):
    from app.market_data import composition
    from app.market_data.contract_preparation_runtime import build_contract_preparation_requester
    def forbidden(*args, **kwargs):
        raise AssertionError("consumer must not construct provider")
    monkeypatch.setattr(composition, "build_historical_data_manager", forbidden)
    request = build_contract_preparation_requester(state_path=tmp_path / "state.json")
    assert request("rb", "RB2701", DAY, ("5m",)) is True
    assert request("rb", "RB2701", DAY, ("5m",)) is False


def test_live_foreground_loop_starts_and_drains_history_worker():
    from app.market_data.live_market import LiveMarketService
    calls = []
    class Worker:
        def start(self):
            calls.append("start")
        def stop(self):
            calls.append("stop")
    service = LiveMarketService.__new__(LiveMarketService)
    service._sleep = lambda seconds: None
    service._history_preparation = Worker()
    service._discard_provider = lambda: calls.append("close quote")
    service.run_forever(should_stop=lambda: True)
    assert calls == ["start", "stop", "close quote"]


def test_enabled_scope_union_excludes_disabled_and_nonoperational_consumers():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.reference_trading.models import ReferenceStream
    from app.alerts.models import AlertRule
    from app.market_data.contract_preparation_runtime import enabled_consumer_scopes
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for identity, product, frequency, enabled in (("a", "rb", "5m", True), ("b", "rb", "1w", False), ("c", "cu", "60m", True)):
            session.add(ReferenceStream(stream_id=identity, identity_hash=identity * 64, strategy_code="subing_ths",
                formula_versions=["test"], profile_id="test", reference_model_version="test", futures_adaptation_version="test",
                product=product, frequency=frequency, series_kind="actual_dominant", recording_mode="forward_observation",
                observation_policy_version="test", enabled=enabled))
        session.add(AlertRule(rule_code="subing_ths_alert_15m_v1", enabled=True, scope_product_frequencies={"rb": ["15m"]}))
        session.add(AlertRule(rule_code="htdy_original_15m", enabled=False, scope_product_frequencies={"rb": ["1w"]}))
        session.commit()
        scopes = enabled_consumer_scopes(session, ("rb",))
        assert set(scopes) == {"rb"}
        assert scopes["rb"][0] == ("5m", "15m")
    engine.dispose()


def test_worker_snapshot_is_cached_and_never_reads_durable_state_on_quote_thread():
    import threading
    calls = []
    class Preparation:
        def tick(self, now):
            return None
        def snapshot(self):
            calls.append(threading.current_thread().name)
            return {"requests": {}, "budgets": {}}
    worker = ContractPreparationWorker(Preparation())
    assert worker.snapshot()["counts"] == {}
    assert calls == []
    worker._stop.wait = lambda interval: worker._stop.set()
    worker._run()
    assert len(calls) == 1
    before = list(calls)
    assert worker.snapshot()["active"] == []
    assert worker.snapshot()["budgets"] == {}
    assert calls == before


def test_background_health_cache_bounds_active_requests_and_budget_days():
    class Preparation:
        def tick(self, now):
            return None
        def snapshot(self):
            return {"requests": {str(i): {"identity": {"product": "rb", "contract": "RB2701", "trading_day": DAY.isoformat()},
                    "units": {"5m": {"status": "WAITING_LEASE", "reason": "CONTRACT_PREPARATION_SOURCE_BUSY"}}}
                    for i in range(20)}, "budgets": {f"2026-10-{day:02}": {"requests": day, "bars": 100, "contracts": {"private": {}}}
                    for day in range(20, 27)}}
    worker = ContractPreparationWorker(Preparation())
    worker._stop.wait = lambda interval: worker._stop.set()
    worker._run()
    health = worker.snapshot()
    assert len(health["active"]) == 16
    assert health["active_truncated"] is True
    assert list(health["budgets"]) == ["2026-10-24", "2026-10-25", "2026-10-26"]
    assert all(set(budget) == {"requests", "bars"} for budget in health["budgets"].values())


import pytest  # noqa: E402


@pytest.mark.parametrize("drift", ("phase", "day", "lifecycle", "cutoff", "rank1"))
def test_apply_rechecks_fresh_admission_under_native_lease_before_reserving_or_provider(tmp_path, monkeypatch, drift):
    from app.market_data import contract_preparation_runtime as module
    from app.market_data import market_data_service as service_module
    from app.market_data.contract_preparation import PreparationDemand
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from datetime import timedelta
    engine = create_engine("sqlite+pysqlite:///:memory:")
    selected = PreparationDemand("rb", "RB2701", DAY, date(2026, 1, 1), date(2027, 1, 16),
                                  date(2026, 10, 26), ("5m",), "scope")
    state, provider_calls, clocks = {}, [], []
    fake_catalog_authority(monkeypatch, selected, state)
    monkeypatch.setattr(module, "enabled_consumer_scopes", lambda session, products: {"rb": (selected.frequencies, "scope")})
    class Data:
        def __init__(self, catalog, store):
            pass
        def dominant_segment_for_day(self, product, day):
            return SimpleNamespace(contract=state.get("contract", selected.contract))
    monkeypatch.setattr(service_module, "MarketDataService", Data)
    def clock():
        clocks.append("fresh")
        return NOW + timedelta(minutes=15)
    class Manager:
        def contract_warmup(self, request, **kwargs):
            if request.apply:
                changes = {"phase": {"phase": MarketPhase.CLOSED}, "day": {"day": DAY + timedelta(days=1)},
                           "lifecycle": {"listed_date": date(2026, 1, 2)}, "cutoff": {"through": date(2026, 10, 23)},
                           "rank1": {"contract": "RB2705"}}
                state.update(changes[drift])
                kwargs["before_apply"]()  # Native HDM invokes this while its global lease is held.
                provider_calls.append("provider")
            return SimpleNamespace(plan=SimpleNamespace(listed_date=selected.listed_date, expired_date=selected.expired_date,
                requested_through=selected.through, plan_sha256="a" * 64, provider_request_count=1,
                expected_bar_count=100, target_windows=()), status="passed", applied=1, failures=())
    preparation = module.build_contract_preparation(lambda: Session(engine), canonical_root=tmp_path / "canonical", products=("rb",),
        state_path=tmp_path / "state.json", manager_factory=lambda *args, **kwargs: Manager(), clock=clock)
    preparation.discover = lambda now: (selected,)
    preparation.tick(NOW)
    unit = next(iter(preparation.snapshot()["requests"].values()))["units"]["5m"]
    assert unit["reason"] == "CONTRACT_PREPARATION_AUTHORITY_DRIFT"
    assert unit["attempts"] == 0
    assert preparation.snapshot()["budgets"] == {}
    assert provider_calls == []
    assert clocks == ["fresh"]
    engine.dispose()


def test_durable_unit_publication_refreshes_cached_health_while_source_is_inflight(tmp_path):
    import threading
    from app.market_data.contract_preparation import ContractPreparation, PreparationDemand, PreparationPlan
    selected = PreparationDemand("rb", "RB2701", DAY, date(2026, 1, 1), date(2027, 1, 16),
                                  date(2026, 10, 26), ("5m",), "scope")
    entered, release = threading.Event(), threading.Event()
    def apply(item, frequency, plan, reserve, check):
        reserve()
        entered.set()
        assert release.wait(3)
        return {"status": "passed", "applied": 1}
    preparation = ContractPreparation(state_path=tmp_path / "state.json", binding_id="test",
        discover=lambda now: (selected,), plan=lambda *args: PreparationPlan("a" * 64, 1, 100),
        apply=apply, readback=lambda *args: True)
    worker = ContractPreparationWorker(preparation, clock=lambda: NOW)
    worker.start()
    try:
        assert entered.wait(3)
        # Mid-call cache comes from the fsynced INFLIGHT state publication, not
        # the next coordinator tick or any foreground disk read.
        health = worker.snapshot()
        assert health["counts"] == {"INFLIGHT": 1}
        assert health["active"][0]["contract"] == "RB2701"
        assert health["budgets"][DAY.isoformat()] == {"requests": 1, "bars": 100}
        health["active"][0]["status"] = "tampered copy"
        assert worker.snapshot()["active"][0]["status"] == "INFLIGHT"
    finally:
        release.set()
        worker.stop()


@pytest.mark.parametrize("missing", ("rank1", "phase", "contract"))
def test_normal_discovery_waits_only_for_product_missing_authority_and_prepares_others(tmp_path, monkeypatch, missing):
    from app.market_data import contract_preparation_runtime as module
    from app.market_data import market_data_service as service_module, market_phase, catalog
    from app.market_data.contract_preparation import PreparationDemand
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    selected = PreparationDemand("rb", "RB2701", DAY, date(2026, 1, 1), date(2027, 1, 16),
                                  date(2026, 10, 26), ("5m",), "scope")
    available = {"ready": False}
    fake_catalog_authority(monkeypatch, selected)
    monkeypatch.setattr(module, "enabled_consumer_scopes", lambda session, products:
                        {product: (("5m",), "scope") for product in products})
    if missing == "phase":
        monkeypatch.setattr(market_phase, "MarketPhaseResolver", lambda session: SimpleNamespace(
            resolve=lambda product, instant: SimpleNamespace(
                phase=MarketPhase.UNKNOWN if product == "cu" and not available["ready"] else MarketPhase.TRADING, trading_day=DAY)))
    elif missing == "contract":
        original = catalog.MarketCatalog.contract_fact
        def fact(self, product, contract):
            if product == "cu" and not available["ready"]:
                raise catalog.CatalogError("CONTRACT_NOT_FOUND")
            return original(self, product, contract)
        monkeypatch.setattr(catalog.MarketCatalog, "contract_fact", fact)
    calls = []
    class Data:
        def __init__(self, catalog, store):
            pass
        def dominant_segment_for_day(self, product, day):
            if product == "cu" and missing == "rank1" and not available["ready"]:
                raise MarketDataError("DOMINANT_CONTEXT_MISSING")
            return SimpleNamespace(contract="CU2701" if product == "cu" else "RB2701")
        def query_contract_trading_days(self, request):
            assert request.symbol in {"rb", "cu"}
            calls.append("readback " + request.symbol)
    monkeypatch.setattr(service_module, "MarketDataService", Data)
    class Manager:
        def contract_warmup(self, request, **kwargs):
            assert request.symbol in {"rb", "cu"}
            if request.apply:
                kwargs["before_apply"]()
                calls.append("apply " + request.symbol)
            return SimpleNamespace(plan=SimpleNamespace(listed_date=selected.listed_date, expired_date=selected.expired_date,
                requested_through=selected.through, plan_sha256="a" * 64, provider_request_count=0,
                expected_bar_count=0, target_windows=()), status="noop", applied=0, failures=())
    engine = create_engine("sqlite+pysqlite:///:memory:")
    preparation = module.build_contract_preparation(lambda: Session(engine), canonical_root=tmp_path / "canonical",
        products=("cu", "rb"), state_path=tmp_path / "state.json", manager_factory=lambda *args, **kwargs: Manager(), clock=lambda: NOW)
    worker = ContractPreparationWorker(preparation, clock=lambda: NOW)
    worker._stop.wait = lambda interval: worker._stop.set()
    worker._run()
    assert calls == ["apply rb", "readback rb"]
    health = worker.snapshot()
    assert health["counts"] == {"READY": 1, "WAITING_AUTHORITY": 1}
    assert health["authority_waiting"] == [{"product": "cu", "status": "WAITING_AUTHORITY", "reason": {
        "rank1": "DOMINANT_CONTEXT_MISSING", "phase": "CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE",
        "contract": "CONTRACT_NOT_FOUND"}[missing]}]
    assert health["authority_waiting_truncated"] is False
    assert len(preparation.snapshot()["requests"]) == 1
    assert next(iter(preparation.snapshot()["requests"].values()))["identity"]["product"] == "rb"
    assert preparation.snapshot()["budgets"][DAY.isoformat()]["requests"] == 0
    available["ready"] = True
    worker._stop.clear()
    worker._run()
    recovered = worker.snapshot()
    assert recovered["authority_waiting"] == []
    assert recovered["authority_waiting_truncated"] is False
    assert recovered["counts"] == {"READY": 2}
    assert calls == ["apply rb", "readback rb", "apply cu", "readback cu"]
    engine.dispose()


def test_waiting_authority_health_is_bounded_cached_and_defaults_empty():
    class Preparation:
        def tick(self, now):
            return None
        def snapshot(self):
            return {"requests": {}, "budgets": {}}
        def authority_waiting(self):
            return tuple({"product": "rb", "status": "WAITING_AUTHORITY", "reason": "DOMINANT_CONTEXT_MISSING"}
                         for _ in range(20))
    worker = ContractPreparationWorker(Preparation())
    assert worker.snapshot()["authority_waiting"] == []
    assert worker.snapshot()["authority_waiting_truncated"] is False
    worker._stop.wait = lambda interval: worker._stop.set()
    worker._run()
    health = worker.snapshot()
    assert len(health["authority_waiting"]) == 16
    assert health["authority_waiting_truncated"] is True
    assert health["counts"] == {"WAITING_AUTHORITY": 20}
    health["authority_waiting"][0]["reason"] = "tampered copy"
    assert worker.snapshot()["authority_waiting"][0]["reason"] == "DOMINANT_CONTEXT_MISSING"


def test_unknown_discovery_error_never_exposes_exception_text_or_claims_attempt(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.market_data import contract_preparation_runtime as module
    engine = create_engine("sqlite+pysqlite:///:memory:")
    def unavailable(*args, **kwargs):
        raise RuntimeError("credential-bearing-provider-url")
    monkeypatch.setattr(module, "enabled_consumer_scopes", unavailable)
    preparation = module.build_contract_preparation(lambda: Session(engine), canonical_root=tmp_path / "canonical",
        products=("rb",), state_path=tmp_path / "state.json", clock=lambda: NOW)
    assert preparation.discover(NOW) == ()
    assert preparation.authority_waiting() == ({"product": "rb", "status": "WAITING_AUTHORITY",
                                               "reason": "CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE"},)
    assert preparation.snapshot()["requests"] == {}
    assert preparation.snapshot()["budgets"] == {}
    engine.dispose()
