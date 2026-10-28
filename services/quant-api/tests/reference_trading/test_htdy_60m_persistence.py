"""Real Alert/kernel/repository pipeline; synthetic bars, isolated databases only."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import math
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.notification import NotificationTransportError
from app.alerts.registry import HTDY_ALERT_RULE_CODE
from app.alerts.runtime import AlertRuntime
from app.db.base import Base
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.htdy_activation import apply_htdy_activation, htdy_identity, plan_htdy_activation
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.live_wake import InboxForwardLiveWake
from app.reference_trading.models import ReferenceActionRow, ReferenceBatch, ReferenceInboxDelivery, ReferenceTradeRow
from app.reference_trading.query import HistoricalReferenceQuery
from app.reference_trading.repository import ReferenceRepository
from tests.reference_trading.test_htdy_60m_forward import Read, original
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=pytest.mark.isolated_postgresql)])
def factory(request):
    engine = (request.getfixturevalue("reference_postgresql") if request.param == "postgresql"
              else create_engine("sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


class RollingRead(Read):
    def __init__(self):
        super().__init__()
        start = self.bars[0].bar_end
        values = [Decimal(3500 + int(300*math.sin(i*2*math.pi/12))) for i in range(50)]
        self.all_bars = tuple(CanonicalBar(start+timedelta(hours=i), start.date(),
            close-10, close+5, close-15, close, Decimal(100), None, None)
            for i, close in enumerate(values))
        self.select(31)

    def select(self, index):
        self.bars = self.all_bars[index-31:index+1]

    def bars_until(self, query, *, trading_day, end, limit=32):
        assert query.frequency.value == "60m" and limit in {32, 64}
        assert end == self.bars[-1].bar_end
        return MarketReadWindow("rb", "actual_dominant", "60m", trading_day, "RB2610",
            end, self.bars, ("RB2610",)*32)


def setup(factory, read):
    first = read.bars[-1].bar_end
    now = first-timedelta(minutes=2)
    plan = plan_htdy_activation(operational=("rb",), recording_start=first-timedelta(seconds=1),
        expires_at=now+timedelta(minutes=1), now=now, host="isolated", environment="isolated")
    apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"], operational=("rb",), now=now)
    repo = ReferenceRepository(factory)
    repo.inbox_enabled = True
    inbox = ReferenceInboxRepository(factory)
    worker = build_forward_reference_worker(repository=repo, market_read=read, newow_reader=None,
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *args: (args[-1],), newow_capability_ready=lambda *_: False,
        enabled=True)
    wake = object.__new__(InboxForwardLiveWake)
    wake._inbox, wake._worker = inbox, worker
    wake._after_stream_id = None
    wake._retry_after_by_stream = {}
    wake.stop_requested = lambda: False
    wake.request_history = lambda *_: None
    return repo, inbox, worker, wake


def test_events_and_reference_survive_failed_transport_duplicates_and_restart(factory):
    read = RollingRead()
    repo, inbox, worker, wake = setup(factory, read)
    with factory() as db, db.begin():
        db.add(AlertRule(rule_code=HTDY_ALERT_RULE_CODE, enabled=True,
            scope_product_frequencies={"rb": ["60m"]}))
    class Sender:
        calls = 0
        def send(self, message):
            self.calls += 1
            raise NotificationTransportError("fixture transport failure")
    sender = Sender()
    runtime = AlertRuntime(session_factory=factory, market_read_factory=lambda _: read,
        htdy_evaluator=HtdyOriginalEvaluator(), sender=sender, operational_products=("rb",),
        taxonomy={"rb": SimpleNamespace(name="螺纹钢")},
        clock=lambda: original(read).confirmed_at+timedelta(milliseconds=1))
    for index in range(31, 46):
        read.select(index)
        event = replace(original(read), observation_id=f"htdy60m-{index}", stream_id=f"{index}-0")
        runtime._source_observed_at = event.source_observed_at
        runtime._source_observation_id = event.observation_id
        assert runtime.process_message(event.channel, json.dumps(event.data)) is True
        receipt = inbox.ingest(event)
        if index == 34:
            # A fresh worker resumes from the committed checkpoint, with no new seed.
            worker = build_forward_reference_worker(repository=repo, market_read=read, newow_reader=None,
                owner_segments=lambda *_: ("owner", "calc"), expected_endpoints=lambda *a: (a[-1],),
                newow_capability_ready=lambda *_: False, enabled=True)
            wake._worker = worker
        wake._calculate_heads()
        assert inbox.pending_head(htdy_identity("rb").stream_id) is None
        assert inbox.ingest(event).duplicate
        runtime.process_message(event.channel, json.dumps(event.data))
        with factory() as db:
            assert db.get(ReferenceInboxDelivery, receipt.delivery_ids[0]).status == "COMPLETED"
    with factory() as db:
        events = db.scalars(select(AlertEvent).order_by(AlertEvent.bar_end)).all()
        assert [item.result_codes for item in events] == [["buy"], ["sell"], ["buy"]]
        assert [item.source_observation_id for item in events] == ["htdy60m-33", "htdy60m-39", "htdy60m-45"]
        assert db.scalar(select(func.count()).select_from(ReferenceActionRow)) == 5
        trades = db.scalars(select(ReferenceTradeRow).where(ReferenceTradeRow.valid_to_seq.is_(None))).all()
        assert len(trades) == 3
        assert sorted(item.status for item in trades) == ["CLOSED", "CLOSED", "OPEN"]
    assert sender.calls == 3
    status = runtime._current_runtime_status()
    assert status["processing_error_type"] is None
    assert status["notification_error_type"] == "notification_transport_failed"
    query = HistoricalReferenceQuery(factory)
    stream = htdy_identity("rb").stream_id
    page = query.trades(stream, since=read.all_bars[0].trading_day,
        through=read.all_bars[-1].trading_day, limit=50)
    assert len(page["items"]) == 3
    assert {item["status"] for item in page["items"]} == {"CLOSED", "OPEN"}


def test_capture_survives_cancel_and_resumes_without_reading_new_input(factory):
    read = RollingRead()
    repo, inbox, worker, wake = setup(factory, read)
    event = original(read)
    receipt = inbox.ingest(event)
    from app.reference_trading.forward_inputs import capture_htdy_live
    capture = capture_htdy_live(read, htdy_identity("rb"),
        revision_id=inbox.pending_head(htdy_identity("rb").stream_id).revision_id,
        generation=1, after=None, now=event.confirmed_at, wake_kind="live_event",
        observation=event, event_bar_end=read.bars[-1].bar_end,
        expected_endpoints=lambda *a: (a[-1],), owner_segments=lambda *_: ("owner", "calc"))
    from hashlib import sha256
    proof = {**capture.source_proof, "inbox_delivery_id": receipt.delivery_ids[0],
        "journal_envelope_sha256": sha256(event.to_json().encode()).hexdigest(),
        "journal_stream_id": event.stream_id}
    repo.capture_forward(replace(capture, source_proof=proof))
    def forbidden(*_a, **_kw):
        raise AssertionError("persisted capture must resume without reading mutable inputs")
    read.bars_until = forbidden
    wake._calculate_heads()
    with factory() as db:
        delivery = db.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
        assert delivery.status == "COMPLETED", (delivery.code, worker._blocked)
        assert db.get(ReferenceBatch, delivery.calculation_batch_id).kind == "calculation"
        assert db.scalar(select(func.count()).select_from(ReferenceActionRow)) == 0


@pytest.mark.parametrize("committed", [True, False])
def test_commit_connection_loss_requires_exact_readback_or_stays_unknown(factory, monkeypatch, committed):
    from sqlalchemy.exc import OperationalError
    read = RollingRead()
    read.select(33)  # The real frozen formula produces a buy on this window.
    repo, inbox, worker, wake = setup(factory, read)
    receipt = inbox.ingest(original(read))
    commit = repo.commit_batch
    def lost(*args, **kwargs):
        if committed:
            commit(*args, **kwargs)
        raise OperationalError("fixture lost commit acknowledgement", {}, Exception())
    monkeypatch.setattr(repo, "commit_batch", lost)
    wake._calculate_heads()
    with factory() as db:
        delivery = db.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
        assert delivery.status == ("COMPLETED" if committed else "UNKNOWN")
        assert db.scalar(select(func.count()).select_from(ReferenceActionRow)) == int(committed)
    if not committed:
        assert repo.read_pending_capture(htdy_identity("rb").stream_id) is not None
        wake._calculate_heads()  # UNKNOWN is retained; it cannot be retried by polling.
        with factory() as db:
            assert db.get(ReferenceInboxDelivery, receipt.delivery_ids[0]).status == "UNKNOWN"


def test_blocked_eligible_original_recovers_with_native_atomic_closure(factory, tmp_path):
    from hashlib import sha256
    from app.reference_trading.inbox_recovery import InboxRecovery, digest
    from app.reference_trading.models import ReferenceInboxRecoveryResult
    read = RollingRead()
    repo, inbox, worker, _ = setup(factory, read)
    event = original(read)
    receipt = inbox.ingest(event)
    identifier = receipt.delivery_ids[0]
    inbox.mark_blocked(identifier, 'HTDY_WINDOW_UNAVAILABLE')
    stream = htdy_identity('rb').stream_id
    worker.source_envelope = event
    worker.source_observed_at = event.confirmed_at
    worker.raw_received_at = event.raw_received_at
    capture = worker._read_input(stream, 'live_event', read.bars[-1].bar_end)
    capture = replace(capture, source_proof={**capture.source_proof,
        'inbox_delivery_id': identifier, 'journal_stream_id': event.stream_id,
        'journal_envelope_sha256': sha256(event.to_json().encode()).hexdigest(),
        'raw_received_at': event.raw_received_at.isoformat(),
        'confirmed_at': event.confirmed_at.isoformat()})
    attempts = tmp_path.resolve() / 'single-account-attempt'
    recovery = InboxRecovery(factory, attempt_dir=attempts,
        verify_fence=lambda: {'owner': 'parked', 'attempt_namespace_sha256': digest(str(attempts))},
        verify_source=lambda plan: None,
        now=lambda: event.confirmed_at + timedelta(seconds=30))
    plan = recovery.plan(identifier, capture=capture,
        expires_at=event.confirmed_at + timedelta(minutes=1))
    result = recovery.apply(plan, expected_plan_hash=plan.plan_hash,
        evaluator=worker._service_for(stream)._evaluator)
    assert recovery.readback(plan) == result
    with factory() as db:
        original_row = db.get(ReferenceInboxDelivery, identifier)
        assert original_row.status == 'BLOCKED' and original_row.code == 'HTDY_WINDOW_UNAVAILABLE'
        closure = db.get(ReferenceInboxRecoveryResult, identifier)
        assert closure.outcome == 'CALCULATED'
        assert db.scalar(select(func.count()).select_from(AlertEvent)) == 0
    assert inbox.pending_head(stream) is None
    assert inbox.health()['blocked_count'] == 0
