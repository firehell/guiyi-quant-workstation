from __future__ import annotations

from app.reference_trading.health import ForwardReferenceHealth
from app.reference_trading.repository import ReferenceRepository
from test_forward_capture import _active, _capture


def test_health_distinguishes_enabled_and_pending_from_success():
    factory, identity, revision, activation = _active()
    before = ForwardReferenceHealth(factory).read()
    assert before["enabled_count"] == 1
    assert before["streams"][0]["pending_capture_count"] == 0
    ReferenceRepository(factory).capture_forward(_capture(identity, revision))
    pending = ForwardReferenceHealth(factory).read()["streams"][0]
    assert pending["pending_capture_count"] == 1
    assert pending["latest_reconciliation_status"] == "pending"
    assert pending["computed_through"] is None
    assert pending["last_success"] is None


def test_health_reports_all_720_streams_without_per_stream_queries():
    from sqlalchemy import event
    from app.reference_trading.models import ReferenceStream
    factory, identity, _revision, _activation = _active()
    with factory() as session:
        template = session.get(ReferenceStream, identity.stream_id)
        fields = {
            column.name: getattr(template, column.name)
            for column in ReferenceStream.__table__.columns
            if column.name not in {"stream_id", "identity_hash", "active_revision_id"}
        }
        for index in range(719):
            session.add(ReferenceStream(
                stream_id=f"health-stream-{index:04}", identity_hash=f"{index:064x}",
                active_revision_id=None, **fields,
            ))
        session.commit()
    engine = factory.kw["bind"]
    statements = []
    def counted(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", counted)
    try:
        result = ForwardReferenceHealth(factory).read()
    finally:
        event.remove(engine, "before_cursor_execute", counted)
    assert result["enabled_count"] == 720
    assert len(result["streams"]) == 720
    assert sum(statement.lstrip().upper().startswith("SELECT") for statement in statements) <= 7


def test_health_reads_endpoint_keys_once_and_exposes_seed_without_observation():
    from test_activation import NOW
    from app.reference_trading.models import ReferenceBatch
    factory, identity, revision, _ = _active()
    with factory() as session:
        seed = session.query(ReferenceBatch).filter_by(revision_id=revision, kind='seed_seal').one()
        seed.computed_through = NOW
        session.commit()
    calls = []
    def endpoints(session, keys, at):
        calls.append(keys)
        return {key: {'expected_through': NOW.isoformat(), 'expected_source': 'canonical_completed', 'endpoint_status': 'READY'} for key in keys}
    health = ForwardReferenceHealth(factory, endpoint_reader=endpoints, now=lambda: NOW).read(products=('rb',))
    assert len(calls) == 1
    assert set(calls[0]) == {('rb', '1d'), ('rb', '1w'), ('rb', '60m')}
    item = health['streams'][0]
    assert item['expected_through'] == NOW.isoformat()
    assert item['historical_computed_through'] == NOW.isoformat()
    assert item['observed_through'] is None
    assert item['last_success'] is None


def test_canonical_endpoint_reader_requires_completed_mds_bar(monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace
    from test_activation import NOW
    from app.market_data.market_data_service import MarketDataError
    from app.reference_trading.health import read_completed_canonical_endpoints

    seen = []
    class Market:
        def query_page(self, request):
            seen.append(request)
            if request.frequency.value == '1w':
                raise MarketDataError('MAIN_CONTRACT_MAP_MISSING')
            delta = timedelta(seconds=1) if request.frequency.value == '60m' else -timedelta(seconds=1)
            return SimpleNamespace(bars=(SimpleNamespace(bar_end=NOW + delta),))

    monkeypatch.setattr('app.market_data.composition.build_market_data_service', lambda _: Market())
    values = read_completed_canonical_endpoints(None, [('rb', '1d'), ('rb', '1w'), ('rb', '60m')], NOW)
    assert len(seen) == 3 and all(request.limit == 1 for request in seen)
    assert values[('rb', '1d')]['expected_through'] == (NOW - timedelta(seconds=1)).isoformat()
    assert values[('rb', '1w')]['endpoint_reason'] == 'AUTHORITATIVE_ENDPOINT_UNAVAILABLE'
    assert values[('rb', '60m')]['expected_through'] is None
    assert values[('rb', '60m')]['endpoint_reason'] == 'COMPLETE_PERIOD_MISSING'
