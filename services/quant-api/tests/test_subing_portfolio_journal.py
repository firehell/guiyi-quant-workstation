"""Portfolio batches, retries, continuity and isolated PostgreSQL replay."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
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
    segments = [segment(p, [100, 101, 102]) for p in products]
    batch = []
    contexts = {}
    for i in range(3):
        prepared = {}
        for n, s in enumerate(segments):
            x = s.executions[i]
            b, f = x.bar, x.facts
            c, day = b.physical_contract, b.trading_day.isoformat()
            at = b.bar_end
            confirmed = at + timedelta(seconds=2)
            ctx = contexts.setdefault(
                s.product,
                dict(
                    contract=c,
                    **dict(
                        s.schedule[day],
                        day_end=s.executions[-1].bar.bar_end.isoformat(),
                    ),
                    sessions=[
                        [
                            b.session_open_at.isoformat(),
                            s.executions[-1].bar.bar_end.isoformat(),
                        ]
                    ],
                    expected_1m=[row.bar.bar_end.isoformat() for row in s.executions],
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
