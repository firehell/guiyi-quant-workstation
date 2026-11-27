"""Portfolio batches, retries, continuity and isolated PostgreSQL replay."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import os
from pathlib import Path
import uuid

import pytest

from app.market_data.live_market import live_bar_channel
from app.market_data.observation_stream import ObservationEnvelope
from app.subing_portfolio_journal import PortfolioJournal, PreparedObservation
from app.subing_model.store import ModelStore
from guiyi_quant.subing_decision import _wire
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS
from tests.unit.subing_one_lot.test_portfolio import segment


def inputs(products=EXPANDED_PORTFOLIO_PRODUCTS):
    days, batch = input_days(products)
    return next(iter(days.values())), batch


def input_days(products=EXPANDED_PORTFOLIO_PRODUCTS, *, next_day_at=None, prices=(100, 101, 102)):
    segments = [segment(p, prices, next_day_at=next_day_at) for p in products]
    batch = []
    contexts = {}
    for i in range(len(prices)):
        prepared = {}
        for n, s in enumerate(segments):
            x = s.executions[i]
            b, f = x.bar, x.facts
            c, day = b.physical_contract, b.trading_day.isoformat()
            at = b.bar_end
            confirmed = at + timedelta(seconds=2)
            session = [row.bar for row in s.executions if row.bar.trading_day == b.trading_day]
            ctx = contexts.setdefault(b.trading_day, {}).setdefault(
                s.product,
                dict(
                    contract=c,
                    **dict(
                        s.schedule[day],
                        day_end=session[-1].bar_end.isoformat(),
                    ),
                    sessions=[
                        [
                            b.session_open_at.isoformat(),
                            session[-1].bar_end.isoformat(),
                        ]
                    ],
                    expected_1m=[row.bar_end.isoformat() for row in session],
                ),
            )
            assert ctx["contract"] == c
            data = _wire(asdict(b))
            data["contract"] = c
            data["turnover"] = None
            event = ObservationEnvelope(
                b.source_identity,
                b.trading_day,
                confirmed,
                live_bar_channel(s.product, "1m"),
                data,
                True,
                f"{int(confirmed.timestamp()) * 1000}-{n}",
                confirmed_at=confirmed,
            )
            facts = dict(
                schema_version=1,
                source="rqdata",
                plan_hash="a" * 64,
                captured_at=b.session_open_at.isoformat(),
                contracts={
                    c: dict(
                        instrument=dict(
                            order_book_id=c,
                            tick_size=str(f.tick_size),
                            contract_multiplier=str(f.multiplier),
                        ),
                        parameters=[
                            dict(
                                date=day,
                                commission_type="by_volume",
                                open_commission=str(f.fees.open_per_contract),
                                close_commission=str(f.fees.close_per_contract),
                                close_commission_today=str(
                                    f.fees.close_today_per_contract
                                ),
                                long_margin_ratio=str(f.long_margin_ratio),
                                short_margin_ratio=str(f.short_margin_ratio),
                            )
                        ],
                        daily=[
                            dict(
                                date=day,
                                prev_settlement=str(f.prev_settlement),
                                limit_up=str(f.limit_up),
                                limit_down=str(f.limit_down),
                            )
                        ],
                    )
                },
            )
            prepared[s.product] = PreparedObservation(
                event, facts, s.observations[at], s.structures[at.isoformat()]
            )
        batch.append((b.trading_day, at, at + timedelta(seconds=3), prepared))
    return contexts, batch


class MemoryStore:
    def __init__(self):
        self.rows = []
        self.record = None
        self.fail_append = False

    def create(self, run_id, identity, state):
        self.record = deepcopy(dict(identity=identity, state=state, sequence=0))

    def load(self, run_id):
        return deepcopy((self.record, self.rows))

    def append(self, run_id, payload, state, sequence):
        if self.fail_append:
            raise ValueError("MODEL_COMMIT_OUTCOME_UNKNOWN")
        if sequence != self.record["sequence"]:
            raise ValueError("MODEL_CONCURRENT_WRITER")
        self.rows.append(deepcopy(payload))
        self.record.update(sequence=sequence + 1, state=deepcopy(state))
        return True


@pytest.fixture
def model():
    contexts, batches = inputs()
    store = MemoryStore()
    journal = PortfolioJournal.create(
        store, "portfolio-test", batches[0][1] - timedelta(minutes=1)
    )
    return store, journal, contexts, batches


def test_restore_duplicate_and_actual_time(model):
    store, journal, contexts, batches = model
    assert journal.submit(*batches[0], contexts=contexts)
    restored = PortfolioJournal.restore(store, journal.run_id)
    assert not restored.submit(*batches[0], contexts=contexts)
    assert restored.submit(*batches[1])
    result = restored.projection()["result"]
    fills = [fill for row in result["accounts"].values() for fill in row["fills"]]
    assert len(fills) == len(EXPANDED_PORTFOLIO_PRODUCTS)
    assert all(f["decision_at"] == batches[0][2].isoformat() for f in fills)
    assert all(f["fill_at"] == batches[1][2].isoformat() for f in fills)
    assert (
        PortfolioJournal.restore(store, journal.run_id).projection()
        == restored.projection()
    )


def test_missing_product_does_not_commit(model):
    store, journal, contexts, (first, *_) = model
    day, at, observed, prepared = first
    prepared = dict(prepared)
    del prepared["rb"]
    with pytest.raises(ValueError, match="PORTFOLIO_BATCH_INCOMPLETE"):
        journal.submit(day, at, observed, prepared, contexts=contexts)
    assert store.record["sequence"] == 0


def test_commit_error_requires_store_readback(model):
    store, journal, contexts, batches = model
    assert journal.submit(*batches[0], contexts=contexts)
    store.fail_append = True
    with pytest.raises(ValueError, match="MODEL_COMMIT_OUTCOME_UNKNOWN"):
        journal.submit(*batches[1])
    with pytest.raises(ValueError, match="PORTFOLIO_RESTORE_REQUIRED"):
        journal.submit(*batches[1])
    with pytest.raises(ValueError, match="PORTFOLIO_RESTORE_REQUIRED"):
        journal.projection()
    restored = PortfolioJournal.restore(store, journal.run_id)
    assert restored.sequence == 1
    store.fail_append = False
    assert restored.submit(*batches[1])


def test_future_confirmation_is_rejected_before_commit(model):
    store, journal, contexts, (first, *_) = model
    day, at, observed, prepared = first
    prepared = dict(prepared)
    rb = prepared["rb"]
    prepared["rb"] = replace(
        rb, envelope=replace(rb.envelope, confirmed_at=observed + timedelta(seconds=1))
    )
    with pytest.raises(ValueError, match="PORTFOLIO_COMPLETED_OBSERVATION_INVALID"):
        journal.submit(day, at, observed, prepared, contexts=contexts)
    assert store.record["sequence"] == 0


@pytest.mark.skipif(
    os.getenv("GUIYI_SUBING_MODEL_PG_TEST") != "1",
    reason="explicit isolated PostgreSQL opt-in required",
)
def test_postgresql_atomic_restart_and_stale_writer():
    contexts, batches = inputs()
    store = ModelStore(
        Path(".run/subing-model-test-database.url").read_text(), test_only=True
    )
    run_id = "portfolio-test-" + uuid.uuid4().hex
    legacy_id = "legacy-jm-test-" + uuid.uuid4().hex
    store.create(legacy_id, dict(kind="ISOLATED_OLD_JM_IDENTITY"),
                 dict(cash="876543.21", open_position="PRESERVED", sequence=0))
    legacy_before = deepcopy(store.load(legacy_id))
    try:
        writer = PortfolioJournal.create(
            store, run_id, batches[0][1] - timedelta(minutes=1)
        )
        assert writer.products == EXPANDED_PORTFOLIO_PRODUCTS
        stale = PortfolioJournal.restore(store, run_id)
        assert writer.submit(*batches[0], contexts=contexts)
        with pytest.raises(ValueError, match="PORTFOLIO_CONCURRENT_WRITER"):
            stale.submit(*batches[0], contexts=contexts)
        restored = PortfolioJournal.restore(store, run_id)
        assert not restored.submit(*batches[0], contexts=contexts)
        assert restored.submit(*batches[1])
        assert (
            PortfolioJournal.restore(store, run_id).projection()
            == restored.projection()
        )
        assert store.load(legacy_id) == legacy_before
    finally:
        store.engine.dispose()


def test_delayed_knowledge_cannot_fill_at_an_already_completed_minute(model):
    _, journal, contexts, batches = model
    day, at, _, prepared = batches[0]
    late_read = batches[1][1] + timedelta(seconds=1)
    assert journal.submit(day, at, late_read, prepared, contexts=contexts)
    assert journal.submit(*batches[1])
    assert not any(
        row["fills"] for row in journal.projection()["result"]["accounts"].values()
    )
    assert journal.submit(*batches[2])
    assert all(
        row["fills"][0]["fill_at"] == batches[2][2].isoformat()
        for row in journal.projection()["result"]["accounts"].values()
    )


def test_skipping_an_expected_minute_cannot_advance_journal(model):
    store, journal, contexts, batches = model
    assert journal.submit(*batches[0], contexts=contexts)
    with pytest.raises(ValueError, match="PORTFOLIO_MINUTE_GAP"):
        journal.submit(*batches[2])
    assert store.record["sequence"] == 1


def test_expanded_scope_fills_both_new_products_and_restarts(model):
    _, original, _, _ = model
    store = MemoryStore()
    contexts, batches = inputs(EXPANDED_PORTFOLIO_PRODUCTS)
    expanded = PortfolioJournal.create(
        store, "expanded", original.started_at, products=EXPANDED_PORTFOLIO_PRODUCTS
    )
    assert expanded.submit(*batches[0], contexts=contexts)
    assert expanded.submit(*batches[1])
    state = PortfolioJournal.restore(store, "expanded").projection()["result"]
    assert state["policy"]["version"] == "subing_portfolio_one_lot_v2"
    assert state["accounts"]["OI2609"]["summary"]["fill_count"] == 1
    assert state["accounts"]["I2609"]["summary"]["fill_count"] == 1
    assert original.projection()["result"]["accounts"] == {}


def test_current_facts_learned_after_bar_cannot_fill_old_pending_until_next_minute(model):
    store, journal, contexts, batches = model
    assert journal.submit(*batches[0], contexts=contexts)
    day, at, _, prepared = batches[1]
    learned = at + timedelta(seconds=20)
    late = {product: replace(row, execution_facts={**row.execution_facts,
        'captured_at': learned.isoformat(), 'fee_assumption': {'source_day': str(day)}})
        for product, row in prepared.items()}
    assert journal.submit(day, at, learned+timedelta(seconds=1), late)
    assert all(not row['fills'] for row in journal.projection()['result']['accounts'].values())
    day3, at3, observed3, rows3 = batches[2]
    current = {product: replace(row, execution_facts={**row.execution_facts,
        'captured_at': learned.isoformat(), 'fee_assumption': {'source_day': str(day3)}})
        for product, row in rows3.items()}
    assert journal.submit(day3, at3, observed3, current)
    assert all(len(row['fills']) == 1 for row in journal.projection()['result']['accounts'].values())
    encoded = store.rows[1]['rows']['jm']['execution_facts']
    assert encoded['captured_at'] == learned.isoformat()
    assert encoded['fee_assumption']['source_day'] == str(day)
    assert len(encoded['payload_sha256']) == 64
    assert PortfolioJournal.restore(store, journal.run_id).projection() == journal.projection()


def test_same_night_accounts_replay_while_previous_day_research_fails_and_recovers(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from threading import Event, Thread
    from time import perf_counter

    from app.market_data.after_market import _atomic_write_status
    from app.services import newow_backtest_eod as eod
    from tests.unit.subing_account import test_account
    from tests.unit.tq_simulation import test_execution as tq

    night = datetime(2026, 11, 4, 13, 1, tzinfo=UTC)
    monkeypatch.setattr(test_account, "BASE", night)
    contexts, batches = inputs()

    def account_replay(folder):
        folder.mkdir(mode=0o700)
        started = perf_counter()
        controller = tq.Controller(folder, tq.A, ("RB",), tq.Transport())
        controller.clock = lambda: night
        controller.bind_symbol("SHFE.rb2701", "RB", "RB2701")
        opening_snapshot = night - timedelta(hours=2)
        controller.bootstrap(tq.snapshot(opening_snapshot), opening_snapshot)
        controller.owner("RB", "RB2701", night - timedelta(seconds=20), "owner")
        signal = tq.signal(night - timedelta(seconds=10))
        controller.signal(signal, processed_at=signal.observed_at)
        before = night - timedelta(seconds=2)
        controller.synchronize(tq.snapshot(before), before)
        native, _ = tq.full_fill(controller, night)
        gateway_calls = tuple(controller.gateway.calls)
        controller.close()
        restored = tq.Controller(folder, tq.A, ("RB",), tq.Transport())
        try:
            readback = restored.synchronize(native, night + timedelta(seconds=6))
            restored.recover(readback, (tq.m.RecoveryInput(
                "RB", "RB2701", 1, signal.bar_end, "fixture-recovery",
            ),))
            account = restored.store.current()
            assert len(gateway_calls) == 1 and restored.gateway.calls == []
            assert len(account.fills) == 1 and account.orders[0].reconciled
            tq_facts = account, gateway_calls
        finally:
            restored.close()
        tq_seconds = perf_counter() - started

        started = perf_counter()
        store = MemoryStore()
        journal = PortfolioJournal.create(store, "portfolio-night", night - timedelta(minutes=1))
        assert journal.submit(*batches[0], contexts=contexts)
        restored_journal = PortfolioJournal.restore(store, journal.run_id)
        assert not restored_journal.submit(*batches[0], contexts=contexts)
        for batch in batches[1:]:
            assert restored_journal.submit(*batch)
        paper_facts = restored_journal.run_id, store.record["sequence"], store.rows, restored_journal.projection()
        assert paper_facts[1] == 3
        assert sum(len(row["fills"]) for row in paper_facts[3]["result"]["accounts"].values()) == 16
        return (tq_facts, paper_facts), (tq_seconds, perf_counter() - started)

    baseline, baseline_seconds = account_replay(tmp_path / "baseline")
    path = tmp_path / "after-market-status.json"
    config = tmp_path / "research.json"
    config.write_text("fixture")
    day = night.date() - timedelta(days=1)
    _atomic_write_status(path, {
        "schema_version": 4, "last_successful_trading_day": str(day),
        "last_run": {
            "status": "passed", "trading_day": str(day), "attempts": 1, "products": ["rb"], "error_code": None,
            "started_at": f"{night.date()}T18:05:00+08:00", "finished_at": f"{night.date()}T18:10:00+08:00",
            "historical_publications": [{
                "dataset": ["contract", "rb", "RB2701", "1m"], "year": day.year, "month": day.month,
                "file_name": "part." + "b" * 64 + ".parquet",
                "provenance": {"version": 1, "input_source": "historical_provider", "input_sha256": "b" * 64},
            }],
        },
    })
    started = Event()
    release = Event()
    reports = []

    def slow_job(status, cutoff, config_path, **kwargs):
        assert cutoff == day and kwargs["latest_days"]["rb"] == day
        started.set()
        assert release.wait(10)
        return [{"status": "UNKNOWN", "code": "BACKTEST_JOB_BUSY"}]

    monkeypatch.setattr(eod, "consume_status", slow_job)
    worker = Thread(target=lambda: reports.extend(eod.reconcile_publications(path, config)))
    worker.start()
    try:
        assert started.wait(10)
        concurrent, concurrent_seconds = account_replay(tmp_path / "with-research")
        assert concurrent == baseline
        assert not release.is_set()
        assert eod.reconcile_publications(path, config) == []
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert reports[0]["deferred"] == 1
    monkeypatch.setattr(eod, "consume_status", lambda *_args, **_kwargs: [{"status": "SUCCEEDED"}])
    report, = eod.reconcile_publications(path, config)
    assert report["computed"] == 1
    assert eod.reconcile_publications(path, config) == []
    print("night replay, seconds, Tq then SuBing:", baseline_seconds, concurrent_seconds)


def test_market_handoff_reads_paper_watermark_from_postgres_and_completed_redis():
    from redis import Redis
    from app.market_data.observation_stream import ObservationStream
    from app.runtime_cohort_errors import CohortError
    from app.runtime_market_account_readback import paper_watermark

    url = os.getenv("GUIYI_MARKET_PAPER_TEST_DATABASE_URL")
    redis_port = int(os.getenv("GUIYI_TEST_REDIS_PORT", "0"))
    target_port = int(os.getenv("GUIYI_MARKET_TARGET_REDIS_PORT", "0"))
    if not url or not redis_port or not target_port:
        pytest.skip("requires disposable PostgreSQL and two isolated Redis instances")
    assert all(port > 1024 and port != 6379 for port in (redis_port, target_port))
    store = ModelStore(url, test_only=True)
    contexts, batches = inputs()
    run_id = "market-handoff-" + uuid.uuid4().hex
    day = batches[0][0]
    fixture_generation = "rqdata-tick:" + "a" * 32 + ":"
    with Redis(host="127.0.0.1", port=redis_port) as old, Redis(
        host="127.0.0.1", port=target_port,
    ) as target:
        assert old.dbsize() == target.dbsize() == 0
        stream = ObservationStream(target, kind="completed")
        old_stream = ObservationStream(old, kind="completed")
        try:
            store.initialize()
            writer = PortfolioJournal.create(store, run_id, batches[0][1] - timedelta(minutes=1))
            expected = {}
            for index, (day, at, observed, prepared) in enumerate(batches):
                inputs_at = {}
                for product, row in prepared.items():
                    old_stream.append(row.envelope)
                    event = replace(
                        row.envelope,
                        raw_received_at=row.envelope.source_observed_at,
                        source_generation=fixture_generation + "1",
                    )
                    stream_id = stream.append(event)
                    inputs_at[product] = replace(row, envelope=replace(event, stream_id=stream_id))
                    expected[product] = (event.data["contract"], at)
                assert writer.submit(day, at, observed, inputs_at, contexts=contexts if index == 0 else None)
            reader = ModelStore(url, test_only=True)
            reader.engine = reader.engine.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True,
            )
            try:
                result = paper_watermark(reader, run_id, stream, day, expected,
                                         generation_prefix=fixture_generation)
                assert result["status"] == "verified"
                assert result["sequence"] == len(batches)
                assert result["run_id"] == run_id
                assert set(result["watermarks"]) == set(EXPANDED_PORTFOLIO_PRODUCTS)
                with pytest.raises(CohortError, match="SUBING_HANDOFF_SOURCE_MISMATCH"):
                    paper_watermark(reader, run_id, stream, day, expected)
                with pytest.raises(CohortError, match="SUBING_HANDOFF_SOURCE_(MISSING|MISMATCH)"):
                    paper_watermark(reader, run_id, old_stream, day, expected,
                                    generation_prefix=fixture_generation)
            finally:
                reader.engine.dispose()
        finally:
            store.engine.dispose()
            for journal_stream in (old_stream, stream):
                journal_stream.redis.delete(journal_stream.key(day), journal_stream.identity_key(day))


@pytest.mark.isolated_postgresql
def test_market_handoff_resumes_paper_worker_on_the_same_postgres_run(monkeypatch, tmp_path):
    import json
    from hashlib import sha256

    from redis import Redis
    from sqlalchemy.engine import make_url

    from app import subing_portfolio_worker as worker
    from app.compute_runtime import ComputeRuntime
    from app.compute_runtime.isolated_simulation import bind_paper_live_factors, paper_live_scopes
    from app.market_data.live_market import _bar_payload
    from app.market_data.market_foundation_scope import bind_market_redis, bind_tick_source
    import sys
    from app.market_data.observation_stream import ObservationStream

    target_module = sys.modules.get("app.market_data.compute_target_observations")
    target_stream = target_module.ObservationStream if target_module is not None else ObservationStream
    target_envelope = target_module.ObservationEnvelope if target_module is not None else ObservationEnvelope
    formal_market = os.getenv("GUIYI_C6_FORMAL_PAPER_MARKET_URL")
    if target_module is not None:
        assert formal_market, "the frozen loader needs the formal fixture binding"
    from app.runtime_cohort_errors import CohortError
    from app.runtime_market_account_readback import paper_watermark
    from guiyi_quant.compute import REGISTRY
    from scripts.research.subing_model_facts import CAPTURE_VERSION, FEE_POLICY

    url = os.getenv("GUIYI_MARKET_PAPER_TEST_DATABASE_URL")
    market_url = os.getenv("GUIYI_MARKET_FOUNDATION_TEST_DATABASE_URL")
    ports = tuple(int(os.getenv(key, "0")) for key in (
        "GUIYI_TEST_REDIS_PORT", "GUIYI_MARKET_TARGET_REDIS_PORT",
    ))
    if not url or not market_url or not all(ports):
        pytest.skip("requires disposable PostgreSQL and two isolated Redis instances")
    assert (pg_port := make_url(url).port) and 1024 < pg_port <= 65535 and pg_port != 5432
    assert ports[0] != ports[1] and all(1024 < port <= 65535 and port != 6379 for port in ports)

    sessions, (first, last, upcoming, following) = input_days(next_day_at=2, prices=(100, 101, 102, 103))
    old_day, _, _, _ = last
    new_day, at, observed, prepared = upcoming
    contexts = sessions[new_day]
    generation = "rqdata-tick:" + "b" * 32 + ":"
    heartbeat = tmp_path / "heartbeat.json"
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    market_url = make_url(formal_market or market_url)
    run_id = "market-worker-handoff-" + uuid.uuid4().hex
    clock = [observed]
    factor_calls = []
    original_step = worker.Factors.step

    class ReplayClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)

    def record_step(self, frequency, candle):
        factor_calls.append((self.contract, frequency, candle.bar_end))
        return original_step(self, frequency, candle)

    monkeypatch.setattr(worker, "datetime", ReplayClock)
    monkeypatch.setattr(worker, "HEARTBEAT", heartbeat)
    monkeypatch.setattr(worker.Factors, "step", record_step)
    with Redis(host="127.0.0.1", port=ports[0], db=13) as old_redis, Redis(
        host="127.0.0.1", port=ports[1], db=0 if formal_market else 13,
    ) as target_redis:
        # Limit all writes to the isolated instances allocated for this test.
        assert old_redis.dbsize() == target_redis.dbsize() == 0
        old = target_stream(old_redis, kind="completed")
        target = target_stream(target_redis, kind="completed")
        if formal_market:
            from app.market_data.market_foundation_scope import formal_tick_fingerprint
            from app.private_settings import runtime_dependency_settings

            target_redis.set("live:market-foundation:formal-binding",
                             formal_tick_fingerprint(target_redis, market_url, canonical_root))
            config = tmp_path / "project.env"
            content = (
                f"DATABASE_URL={formal_market}\n"
                f"GUIYI_CANONICAL_DATA_ROOT={canonical_root}\n"
                f"REDIS_URL=redis://127.0.0.1:{ports[1]}/0\n"
                "# guiyi-market-source: rqdata_tick\n"
            ).encode()
            config.write_bytes(content)
            config.chmod(0o600)
            settings = runtime_dependency_settings(content)
        else:
            bind_market_redis(target_redis, tmp_path, market_url)
        bind_tick_source(target_redis)
        store = ModelStore(url, test_only=True)
        try:
            store.initialize()
            writer = PortfolioJournal.create(store, run_id, first[1] - timedelta(minutes=1))
            for day, endpoint, known, items in (first, last):
                recorded = {}
                for product, row in items.items():
                    contract = sessions[day][product]["contract"]
                    data = _bar_payload(worker.bar(row.envelope.data), contract=contract)
                    event = replace(row.envelope, data=data, observation_id=f"{day}:{contract}:1m:{data['bar_end']}")
                    recorded[product] = replace(row, envelope=replace(event, stream_id=old.append(event)))
                assert writer.submit(day, endpoint, known, recorded,
                                     contexts=sessions[day] if writer.day != day else None)
            old_expected = {product: (row["contract"], last[1]) for product, row in sessions[old_day].items()}
            before = paper_watermark(store, run_id, old, old_day, old_expected)
            old_head, old_events = store.load(run_id)
            assert before["status"] == "verified" and before["sequence"] == 2

            for product, row in prepared.items():
                context = contexts[product]
                contract = context["contract"]
                # Two one-minute fixture sessions each have an authoritative
                # shortened M30 and H1 close.
                endpoints = context["expected_1m"]
                context["sessions"] = [[context["first_open"], endpoints[0]], endpoints]
                context["expected_30m"] = context["expected_60m"] = endpoints
                facts = deepcopy(row.execution_facts)
                facts.update(capture_version=CAPTURE_VERSION, fee_policy_version=FEE_POLICY,
                             time_semantics="current_effective_execution_facts",
                             fee_assumption=dict(contract=contract, target_day=str(new_day),
                                                 source_day=str(new_day), assumed=False))
                facts["contracts"][contract].update(start=str(new_day), end=str(new_day),
                                                    field_sources={"snapshot_at": context["first_open"]})
                raw = json.dumps(facts).encode()
                payload = tmp_path / f"{product}-facts.json"
                payload.write_bytes(raw)
                (tmp_path / f"{product}.json").write_text(json.dumps({str(new_day): {
                    "path": str(payload), "sha256": sha256(raw).hexdigest(),
                }}))

            def append_batch(batch, *, legacy_period=None):
                _, end, _, rows = batch
                identifiers = []
                for product, row in rows.items():
                    contract = contexts[product]["contract"]
                    data = _bar_payload(worker.bar(row.envelope.data), contract=contract)
                    for frequency in ("60m", "30m", "1m"):
                        identifiers.append(target.append(replace(
                            target_envelope.from_json(row.envelope.to_json()),
                            stream_id="", channel=live_bar_channel(product, frequency), data=data,
                            observation_id=f"{new_day}:{contract}:{frequency}:{data['bar_end']}",
                            source_observed_at=end, raw_received_at=end + timedelta(milliseconds=10),
                            source_generation=None if frequency == legacy_period else generation + "1",
                        )))
                return identifiers

            def consume(stream, *, check_duplicate=False):
                restored = PortfolioJournal.restore(store, run_id)
                factors = {product: worker.Factors(row["contract"]) for product, row in contexts.items()}
                if formal_market:
                    from app.compute_runtime.paper_consumer import continue_frozen_paper

                    def run_native_day():
                        _, bound = worker.settings_and_redis()
                        native_stream = ObservationStream(bound, kind="completed")
                        worker.consume_day(restored, new_day, contexts, factors, native_stream, tmp_path, once=True)

                    with monkeypatch.context() as patch:
                        patch.setattr(worker, "settings_and_redis", lambda: (settings, stream.redis))
                        patch.setattr(worker, "main", run_native_day)
                        continue_frozen_paper(worker, stream_class=target_stream, private_config=config)
                    return
                with ComputeRuntime(REGISTRY, owned_live_scopes=paper_live_scopes(new_day, contexts)) as compute:
                    wrapped = bind_paper_live_factors(
                        compute, stream, restored, new_day, contexts, factors,
                        market_url=market_url, canonical_root=canonical_root,
                    )
                    worker.consume_day(restored, new_day, contexts, wrapped, stream, tmp_path, once=True)
                    if check_duplicate:
                        candle = worker.bar(prepared["rb"].envelope.data)
                        calls = len(factor_calls)
                        wrapped["rb"].step("30m", candle)
                        assert len(factor_calls) == calls
                        assert compute.queue_load()["live"]["peak_pending"] == 1

            wrong_source = "MARKET_FORMAL_BINDING_INVALID" if formal_market else "COMPUTE_LIVE_ISOLATION_REQUIRED"
            with pytest.raises(ValueError, match=wrong_source):
                consume(old)
            assert not factor_calls and store.load(run_id) == (old_head, old_events)
            for legacy_period in ("30m", "1m"):
                append_batch(upcoming, legacy_period=legacy_period)
                with pytest.raises(ValueError, match="COMPUTE_OWNED_LIVE_ORIGINAL_INVALID"):
                    consume(target)
                assert store.load(run_id) == (old_head, old_events)
                target_redis.delete(target.key(new_day), target.identity_key(new_day))
                factor_calls.clear()
            if barrier := os.environ.get("GUIYI_C6_PAPER_BARRIER"):
                from time import monotonic_ns, sleep

                commit_return = []
                native_submit = PortfolioJournal.submit

                def measured_submit(*args, **kwargs):
                    result = native_submit(*args, **kwargs)
                    if result:
                        commit_return.append(monotonic_ns())
                    return result

                monkeypatch.setattr(PortfolioJournal, "submit", measured_submit)
                barrier = Path(barrier)
                barrier.with_suffix(".ready").touch(exist_ok=False)
                deadline = monotonic_ns() + 80_000_000_000
                while not barrier.with_suffix(".go").exists():
                    assert monotonic_ns() < deadline
                    sleep(0.001)
            originals = append_batch(upcoming)
            if barrier:
                published_ns = monotonic_ns()
            consume(target, check_duplicate=True)
            assert len(factor_calls) == 2 * len(contexts)
            expected = {product: (row["contract"], at) for product, row in contexts.items()}
            prefix = [before["sequence"], before["tail_hash"]]
            after = paper_watermark(store, run_id, target, new_day, expected,
                                    generation_prefix=generation, prefix=prefix)
            assert after["status"] == "verified" and after["sequence"] == before["sequence"] + 1
            assert after["run_id"] == before["run_id"]
            assert after["tail_hash"] != before["tail_hash"]
            new_head, new_events = store.load(run_id)
            assert new_head["identity"] == old_head["identity"] and new_events[:-1] == old_events
            assert append_batch(upcoming) == originals
            consume(target)
            assert store.load(run_id) == (new_head, new_events)

            next_at = following[1]
            clock[0] = following[2]
            append_batch(following)
            consume(target)
            final_head, final_events = store.load(run_id)
            assert final_head["sequence"] == new_head["sequence"] + 1
            assert final_head["identity"] == old_head["identity"] and final_events[:-1] == new_events
            next_expected = {product: (row["contract"], next_at) for product, row in contexts.items()}
            assert paper_watermark(store, run_id, target, new_day, next_expected,
                                   generation_prefix=generation, prefix=prefix)["status"] == "verified"
            with pytest.raises(CohortError, match="SUBING_HANDOFF_LEDGER_PREFIX_CHANGED"):
                paper_watermark(store, run_id, target, new_day, next_expected, generation_prefix=generation,
                                prefix=[before["sequence"], "a" * 64])
            assert json.loads(heartbeat.read_text())["status"] == "SESSION_COMPLETE"
            if barrier:
                import resource

                usage = resource.getrusage(resource.RUSAGE_SELF)
                barrier.with_suffix(".json").write_text(json.dumps({
                    "observations": len(originals), "products": len(contexts),
                    "same_run_and_prefix": True, "duplicate_commands": 0,
                    "sequence": [old_head["sequence"], new_head["sequence"], final_head["sequence"]],
                    "completed_publish_return_to_postgres_commit_return_ms": (
                        commit_return[0] - published_ns
                    ) / 1_000_000,
                    "publish_return_ns": published_ns, "first_commit_return_ns": commit_return[0],
                    "user_cpu_s": usage.ru_utime, "system_cpu_s": usage.ru_stime,
                    "max_rss_macos_bytes": usage.ru_maxrss,
                }))
        finally:
            store.engine.dispose()
            for stream, day in ((old, old_day), (target, new_day)):
                stream.redis.delete(stream.key(day), stream.identity_key(day))
            target_redis.delete("live:market-foundation:binding", "live:market-foundation:source",
                                "live:market-foundation:formal-binding")
