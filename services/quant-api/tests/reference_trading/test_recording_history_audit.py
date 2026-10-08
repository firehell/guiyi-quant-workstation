from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import event

from tests.reference_trading.test_newow_bootstrap import setup_source
from app.reference_trading.models import ReferenceStream
from scripts.newow_recording_audit import audit_history

NOW = datetime(2026, 10, 8, 10, tzinfo=UTC)


def test_audit_reads_formal_identity_and_only_checkpoint_scalars():
    factory, repo, identity, revision, checkpoint = setup_source()
    statements = []
    engine = factory.kw['bind']
    def record(connection, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with factory() as session:
            result = audit_history(session, ('rb',), at=NOW)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert result['expected_count'] == 12
    assert result['registered_count'] == result['active_count'] == result['ready_count'] == 1
    item = next(item for item in result['items'] if item['stream_id'] == identity.stream_id)
    assert item['status'] == 'READY'
    assert item['active_revision_id'] == revision
    assert item['computed_through'] == checkpoint.computed_through.isoformat()
    assert all('checkpoint_text' not in sql and 'dependency_manifest' not in sql for sql in statements)


def test_legacy_daily_identity_does_not_fill_formal_slot():
    factory, repo, identity, revision, checkpoint = setup_source()
    legacy = replace(identity, futures_adaptation_version='newow_futures_v1', profile_id='legacy_profile')
    repo.ensure_stream(legacy)
    with factory.begin() as session:
        session.delete(session.get(ReferenceStream, identity.stream_id))
    with factory() as session:
        result = audit_history(session, ('rb',), at=NOW)
    assert result['registered_count'] == result['active_count'] == result['ready_count'] == 0
    assert all(item['status'] == 'NOT_REGISTERED' for item in result['items'])


def test_registered_but_not_active_is_reported_without_fake_watermark():
    factory, repo, identity, revision, checkpoint = setup_source()
    with factory.begin() as session:
        stream = session.get(ReferenceStream, identity.stream_id)
        stream.active_revision_id = None
    with factory() as session:
        result = audit_history(session, ('rb',), at=NOW)
    assert result['registered_count'] == 1
    assert result['active_count'] == result['ready_count'] == 0
    item = next(item for item in result['items'] if item['stream_id'] == identity.stream_id)
    assert item['status'] == 'NO_ACTIVE_REVISION' and item['computed_through'] is None


def test_incompatible_checkpoint_schema_is_not_ready():
    from app.reference_trading.models import ReferenceRevision, ReferenceBatch
    factory, repo, identity, revision, checkpoint = setup_source()
    with factory.begin() as session:
        rev = session.get(ReferenceRevision, (identity.stream_id, revision))
        session.get(ReferenceBatch, rev.checkpoint_batch_id).strategy_schema = 'legacy_checkpoint'
    with factory() as session:
        result = audit_history(session, ('rb',), at=NOW)
    assert result['registered_count'] == result['active_count'] == 1
    assert result['ready_count'] == 0
    assert result['status_counts']['CHECKPOINT_SCHEMA_CONFLICT'] == 1


def test_stored_identity_metadata_conflict_cannot_count_as_active_formal_asset():
    factory, repo, identity, revision, checkpoint = setup_source()
    with factory.begin() as session:
        session.get(ReferenceStream, identity.stream_id).profile_id = 'legacy_profile'
    with factory() as session:
        result = audit_history(session, ('rb',), at=NOW)
    assert result['registered_count'] == 1
    assert result['active_count'] == result['ready_count'] == 0
    assert result['status_counts']['IDENTITY_CONFLICT'] == 1
