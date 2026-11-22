"""Regression checks for the Nov-19 retirement's production entry points."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app import runtime_bindings, runtime_handover
from app.db.base import Base
from app.models import Exchange, Instrument, TradingCalendar
from app.reference_trading import interval_retirement as retirement
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.models import (
    ReferenceActionRow, ReferenceActivationReceipt, ReferenceBatch, ReferenceMarkRow,
    ReferenceStream, ReferenceTradeRow,
)
from app.reference_trading.query import HistoricalReferenceQuery
from app.reference_trading.recovery_campaign import write_once
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from guiyi_quant.reference_trading import CompletedReferenceBar, reduce_reference
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
from tests.reference_trading import test_interval_retirement as samples
from tests.reference_trading.test_formula_transition import BAR
from tests.reference_trading.test_interval_retirement import NOW, plan_for, scenario


@pytest.fixture
def cli(monkeypatch):
    root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    return import_module("reference_interval_retirement")


def test_first_h1_requires_each_calendar_date_through_target(tmp_path):
    cut = datetime(2026, 11, 19, 12, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Exchange(code="SHFE", name="SHFE"))
            session.add(Instrument(symbol="rb", name="RB", exchange_code="SHFE"))
            for offset, opened in ((0, False), (2, True)):
                session.add(TradingCalendar(
                    exchange_code="SHFE", trade_date=cut.date() + timedelta(days=offset),
                    is_trading_day=opened, has_night_session=False,
                ))
            session.flush()
            with pytest.raises(RepositoryConflict, match="INTERVAL_RETIREMENT_CALENDAR_INCOMPLETE"):
                retirement.first_session_endpoint(session, "rb", cut, data_root=tmp_path)
    finally:
        engine.dispose()


def test_private_plan_larger_than_settings_budget_roundtrips(cli, tmp_path):
    path = tmp_path / "plan.json"
    plan = {"originals": ["a" * 64] * 17000}
    write_once(path, plan)
    assert path.stat().st_size > 1024 * 1024
    assert cli.read_plan(path) == plan


@pytest.mark.parametrize("mode, code", [
    ("old_registration", "INTERVAL_RETIREMENT_ORIGINAL_INPUT_UNPROVEN"),
    ("found", "INTERVAL_RETIREMENT_ORIGINAL_FOUND"),
    ("append_before_commit", "INTERVAL_RETIREMENT_ORIGINAL_INPUT_UNPROVEN"),
])
def test_jd_operator_requires_stable_advanced_journal(cli, monkeypatch, mode, code):
    from app import redis_connections
    from app.market_data import observation_stream

    day = retirement.JD_MISSING_H1.date()
    fake = SimpleNamespace(close=lambda: None, journal_tail="1-0")
    row = SimpleNamespace(stream_id="1-0", channel="live:bar:jd:60m",
        data={"bar_end": (retirement.JD_MISSING_H1 + timedelta(minutes=mode != "found")).isoformat()})
    journal = SimpleNamespace(
        tail=lambda _: fake.journal_tail, cursor=lambda *_: "1-0",
        registered_day=lambda _: day + timedelta(days=mode != "old_registration"),
        read=lambda *a, **kw: (row,),
    )
    monkeypatch.setattr(redis_connections, "get_redis_connection", lambda: fake)
    monkeypatch.setattr(observation_stream, "ObservationStream", lambda *a, **kw: journal)
    with pytest.raises(RuntimeError, match=code):
        proof = cli.check_jd_original_absent()
        fake.journal_tail = "2-0"
        cli.check_jd_journal_witness(*proof)


def test_existing_drain_remains_owned_by_original_caller(cli, tmp_path, monkeypatch):
    binding = SimpleNamespace(root=str(cli.ROOT), commit="c" * 40, generation=7, enabled=True)
    monkeypatch.setattr(runtime_bindings, "resolve_service_binding", lambda service: binding)
    monkeypatch.setattr(runtime_handover, "runtime_directory", lambda: tmp_path)
    runtime_handover._write(tmp_path / "reference-worker.owner.json", {
        "schema_version": 1, "service": "reference-worker", "generation": 7, "phase": "active",
    })
    old_request = runtime_handover.request_drain("reference-worker", generation=7, runtime_dir=tmp_path)
    handover = tmp_path / "reference-worker.handover.json"
    original = handover.read_bytes()
    monkeypatch.setattr(cli, "verify_code", lambda *args: None)
    monkeypatch.setattr(cli, "load_dependencies", lambda path: "a" * 64)
    monkeypatch.setattr(cli, "business_claim_path", lambda: tmp_path / "claim.json")
    monkeypatch.setattr(cli.signal, "signal", lambda *_: None)
    from app.db import session as database
    monkeypatch.setattr(database, "SessionLocal", SimpleNamespace(kw={
        "bind": SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    }))
    inventory = tmp_path / "inventory.json"
    write_once(inventory, {})
    monkeypatch.setattr(retirement, "INVENTORY_SHA256", sha256(inventory.read_bytes()).hexdigest())
    monkeypatch.setattr(sys, "argv", [
        "retire", "--phase", "execute", "--exact-root", str(cli.ROOT),
        "--exact-commit", binding.commit, "--inventory", str(inventory),
        "--plan", str(tmp_path / "plan.json"), "--attempt", str(tmp_path / "attempt"),
    ])
    with pytest.raises(RuntimeError, match="INTERVAL_RETIREMENT_OWNER_BUSY"):
        cli.main()
    cli.cancel_owned(tmp_path, binding, "different-request")
    assert runtime_handover._read(handover)["request_id"] == old_request
    assert handover.read_bytes() == original


def test_idle_scheduling_cost_and_terminal_receipt_binding(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        factory, service, streams = scenario(engine, monkeypatch)
        inbox = ReferenceInboxRepository(factory)
        plan = plan_for(service, streams)

        def poll():
            statements = []

            def counted(*args):
                statements.append(args[2])

            event.listen(engine, "before_cursor_execute", counted)
            try:
                heads = inbox.next_heads()
                pending = inbox.has_unfinished()
            finally:
                event.remove(engine, "before_cursor_execute", counted)
            return len(statements), heads, pending

        baseline, _, pending = poll()
        assert pending
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
        after, heads, pending = poll()
        assert heads == ()
        assert not pending
        assert after <= baseline

        target = plan["items"][0]["bootstrap"]["target_stream_id"]
        with factory.begin() as session:
            receipt = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == target,
            ))
            receipt.recovery_policy = "interrupt_and_restart"
        with factory() as session, pytest.raises(RepositoryConflict, match="SEED_DRIFT"):
            retirement.retired_interval_delivery_ids(
                session, stream_ids=[plan["items"][0]["old"]["stream"]["stream_id"]]
            )
    finally:
        engine.dispose()


def test_retired_snapshot_and_cutoff_survive_successor_disable(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        factory, service, streams = scenario(engine, monkeypatch)
        with factory.begin() as session:
            opening = session.scalar(select(ReferenceTradeRow).where(ReferenceTradeRow.status == "OPEN"))
            old = opening.stream_id
            action = session.get(ReferenceActionRow, opening.entry_action_pk)
            action.observed_at = BAR
            opening.observed_at = BAR
            session.get(ReferenceBatch, action.batch_id).observed_at = BAR
        reader = HistoricalReferenceQuery(factory)
        window = {"since": BAR.date(), "through": NOW.date()}
        previous = reader.trades(old, **window)
        assert [item["status"] for item in previous["items"]] == ["OPEN"]
        plan = plan_for(service, streams)
        committed = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
        item = next(i for i in plan["items"] if i["old"]["stream"]["stream_id"] == old)
        ForwardActivation(factory).disable(
            item["bootstrap"]["target_stream_id"], expected_generation=1, now=NOW + timedelta(days=1),
        )
        assert service.status(plan) == committed
        preserved = reader.trades(old, **window, snapshot_token=previous["snapshot"])
        assert preserved["items"] == previous["items"]
        before = reader.trades(old, **window, cutoff=NOW - timedelta(microseconds=1))
        at = reader.trades(old, **window, cutoff=NOW)
        assert before["items"][0]["status"] == "OPEN"
        assert before["coverage"]["observation_boundary_at"] is None
        terminal = at["items"][0]
        assert terminal["status"] == "OBSERVATION_INTERRUPTED"
        assert terminal["entry_reference_price"] == previous["items"][0]["entry_reference_price"]
        assert terminal["exit_reference_price"] is None and terminal["reference_return"] is None
        assert at["coverage"]["observation_boundary_at"] == NOW.isoformat()
    finally:
        engine.dispose()


def test_interruption_keeps_holding_bars_from_last_completed_mark(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    source_fixture = samples.source_fixture
    marked_stream = None

    def marked_source(engine, *, current, product, opened_codes):
        nonlocal marked_stream
        factory, pairs = source_fixture(engine, current=current, product=product, opened_codes=opened_codes)
        if marked_stream is not None or "trend" not in opened_codes:
            return factory, pairs
        with factory.begin() as session:
            opening = session.scalar(select(ReferenceTradeRow).join(
                ReferenceStream, ReferenceStream.stream_id == ReferenceTradeRow.stream_id,
            ).where(ReferenceStream.product == product, ReferenceStream.strategy_code == "newow_trend",
                    ReferenceTradeRow.status == "OPEN"))
            marked_stream = opening.stream_id
            action = session.get(ReferenceActionRow, opening.entry_action_pk)
            batch = session.get(ReferenceBatch, action.batch_id)
            _, checkpoint = ReferenceRepository(factory).load_checkpoint(marked_stream)
            trade = checkpoint.reference_state.open_trade
            end = trade.entry_bar_end + timedelta(hours=1)
            completed_bar = CompletedReferenceBar(
                trade.physical_contract, trade.owner_segment_id, trade.calculation_segment_id,
                end, end.date(), Decimal("101"),
            )
            transition = reduce_reference(checkpoint.reference_state, completed_bar=completed_bar)
            (mark,) = transition.marks
            assert opening.holding_bars == 0 and mark.holding_bars == 1
            raw = adapter_checkpoint_to_json(
                replace(checkpoint, computed_through=end, reference_state=transition.state),
                strategy_schema=batch.strategy_schema,
            )
            batch.checkpoint_text = raw
            batch.post_state_hash = sha256(raw.encode()).hexdigest()
            batch.computed_through = end
            session.add(ReferenceMarkRow(
                stream_id=opening.stream_id, revision_id=opening.revision_id, trade_id=opening.trade_id,
                trade_valid_from_seq=opening.valid_from_seq, batch_seq=batch.seq,
                entry_action_pk=opening.entry_action_pk, bar_end=end, trading_day=mark.trading_day,
                reference_price=mark.reference_price, holding_bars=mark.holding_bars,
                reference_return=mark.reference_return, observed_at=end,
            ))
        return factory, pairs

    monkeypatch.setattr(samples, "source_fixture", marked_source)
    try:
        factory, service, streams = scenario(engine, monkeypatch)
        plan = plan_for(service, streams)
        result = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
        assert result == service.status(plan)
        with factory() as session:
            opening, interrupted = session.scalars(select(ReferenceTradeRow).where(
                ReferenceTradeRow.stream_id == marked_stream,
            ).order_by(ReferenceTradeRow.valid_from_seq)).all()
            mark = session.scalar(select(ReferenceMarkRow).where(ReferenceMarkRow.stream_id == marked_stream))
            assert opening.status == "OPEN" and opening.holding_bars == 0
            assert mark.holding_bars == interrupted.holding_bars == 1
            assert interrupted.status == "OBSERVATION_INTERRUPTED"
            assert opening.trade_id == interrupted.trade_id == mark.trade_id
            assert opening.entry_reference_price == interrupted.entry_reference_price == Decimal("100")
            assert mark.reference_price == Decimal("101")
            assert interrupted.exit_action_pk is None and interrupted.exit_bar_end is None
            assert interrupted.exit_reference_price is None and interrupted.reference_return is None
    finally:
        engine.dispose()
