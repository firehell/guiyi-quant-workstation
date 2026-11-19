"""Retiring reference calculations must not delete old journals or route alerts."""
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.models import ReferenceInboxDelivery, ReferenceStream
from app.reference_trading.repository import ReferenceRepository
from tests.reference_trading.test_forward_capture import _active
from tests.reference_trading.test_inbox import event
from tests.reference_trading.test_activation import NOW


@pytest.mark.parametrize("strategy", ["htdy", "subing_reference", "subing-reference"])
def test_enabled_legacy_streams_never_schedule_or_receive_new_deliveries(strategy):
    factory, identity, _, _ = _active()
    repo = ReferenceRepository(factory)
    retired = replace(identity, strategy_code=strategy)
    repo.ensure_stream(retired)
    with factory.begin() as session:
        # Deliberately no activation receipt: retired streams must be excluded
        # before any activation or market input is accessed.
        session.execute(update(ReferenceStream).where(
            ReferenceStream.stream_id == retired.stream_id).values(enabled=True))
    assert repo.enabled_forward_stream_ids() == (identity.stream_id,)
    assert repo.enabled_forward_routes("rb", "1d") == (identity.stream_id,)
    assert repo.forward_work_key(retired.stream_id) is None
    assert repo.enabled_forward_work_routes(f"stream:{retired.stream_id}") == ()
    assert all(not key.startswith("stream:") for key in repo.enabled_forward_scan_work_keys())
    inbox = ReferenceInboxRepository(factory)
    receipt = inbox.ingest(event())
    assert len(receipt.delivery_ids) == 1
    assert inbox.next_heads()[0].stream_id == identity.stream_id


@pytest.mark.parametrize("strategy", ["htdy", "subing_reference"])
def test_old_pending_and_blocked_journals_are_preserved_but_no_longer_operational(strategy):
    factory, identity, _, _ = _active()
    inbox = ReferenceInboxRepository(factory)
    original = event()
    receipt = inbox.ingest(original)
    inbox.mark_blocked(receipt.delivery_ids[0], "OBSERVATION_GAP")
    with factory.begin() as session:
        # Model an existing activation belonging to the retired strategy.
        session.execute(update(ReferenceStream).where(
            ReferenceStream.stream_id == identity.stream_id).values(strategy_code=strategy))
        before = session.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
        original_fields = {c.name: getattr(before, c.name) for c in before.__table__.columns}
    assert not inbox.has_unfinished()
    assert inbox.next_heads() == ()
    health = inbox.health()
    assert health["unfinished_current_generation_deliveries"] == 0
    assert health["blocked_count"] == 0
    assert health["unfinished_retired_strategy_deliveries"] == 1
    assert inbox.ingest(original).duplicate
    assert inbox.ingest(event("20-0", end=NOW + timedelta(seconds=3))).delivery_ids == ()
    with factory() as session:
        after = session.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
        assert {c.name: getattr(after, c.name) for c in after.__table__.columns} == original_fields
        assert len(session.scalars(select(ReferenceInboxDelivery)).all()) == 1


def test_public_history_composition_rejects_new_and_saved_legacy_work_before_input_reads():
    from types import SimpleNamespace
    from app.reference_trading.composition import (
        ActiveHistoricalReferencePlanner, ActiveHistoricalReferenceService,
    )
    from tests.reference_trading.test_bootstrap import Reader, _plan

    legacy = _plan(Reader())  # Retained legacy identity and plan remain verifiable.
    request = SimpleNamespace(streams=(legacy.streams[0].request,))
    with pytest.raises(ValueError, match="REFERENCE_STRATEGY_RETIRED"):
        ActiveHistoricalReferencePlanner(None).plan(request)
    service = ActiveHistoricalReferenceService(None, None)
    for method, operation in ((service.execute, "build"), (service.advance, "advance"),
                              (service.rebuild, "rebuild")):
        from app.reference_trading.planning import canonical_sha256
        plan = replace(legacy, operation=operation, plan_hash="")
        plan = replace(plan, plan_hash=canonical_sha256(plan))
        with pytest.raises(ValueError, match="REFERENCE_STRATEGY_RETIRED"):
            method(plan, plan.plan_hash)


def test_retired_http_calculations_never_open_history_readers(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.api import market_subing_reference as api

    def unexpected(*args, **kwargs):
        pytest.fail("retired reference computation must not read market input")
    monkeypatch.setattr(api, "_build_service", unexpected)
    request = Request({"type": "http", "query_string": b""})
    calls = (
        lambda: api.htdy_historical_reference(request, "jm", session=object()),
        lambda: api.historical_reference_signals(request, "jm", "htdy", NOW.date(),
            NOW.date(), NOW, NOW, session=object()),
    )
    for call in calls:
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 410
        assert caught.value.detail == {"code": "REFERENCE_STRATEGY_RETIRED"}


@pytest.mark.parametrize("batch", [False, True])
def test_retired_snapshot_commands_fail_before_configuration_or_storage(batch, monkeypatch, capsys):
    import json
    from app.reference_trading import htdy_snapshot, htdy_snapshot_batch
    from app import private_settings

    def unexpected(*args, **kwargs):
        pytest.fail("retired command must not load private configuration")
    monkeypatch.setattr(private_settings, "load_private_readonly_settings", unexpected)
    argv = ["snapshot", "run", "--through", "2026-11-18"] if batch else ["snapshot", "build", "--symbol", "jm"]
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as caught:
        (htdy_snapshot_batch if batch else htdy_snapshot).main()
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out)["code"] == "REFERENCE_STRATEGY_RETIRED"
