from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import event
import pytest

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
    assert result['expected_count'] == 21
    assert result['registered_count'] == result['active_count'] == result['ready_count'] == 1
    item = next(item for item in result['items'] if item['stream_id'] == identity.stream_id)
    assert item['status'] == 'READY'
    assert item['active_revision_id'] == revision
    assert item['computed_through'] == checkpoint.computed_through.isoformat()
    assert all('checkpoint_text' not in sql for sql in statements)
    selected = [sql for sql in statements if 'reference_batches.dependency_manifest' in sql]
    assert len(selected) == 1
    assert 'JSON_EXTRACT(reference_batches.dependency_manifest, ?)' in selected[0]
    assert selected[0].count('reference_batches.dependency_manifest') == 1


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


@pytest.mark.parametrize('strategy', ['trend', 'dual_fusion'])
@pytest.mark.parametrize('old_policy', [None, 'legacy_boundary_v0'])
def test_old_hash_bound_daily_policy_is_stale_not_ready(strategy, old_policy):
    from app.reference_trading.models import ReferenceRevision, ReferenceBatch
    from app.reference_trading.contracts import manifest_sha256
    from tests.reference_trading.test_newow_bootstrap import setup_fusion_source
    factory, repo, identity, revision, checkpoint = (setup_fusion_source() if strategy == 'dual_fusion' else setup_source())
    with factory.begin() as session:
        rev = session.get(ReferenceRevision, (identity.stream_id, revision))
        batch = session.get(ReferenceBatch, rev.checkpoint_batch_id)
        manifest = dict(batch.dependency_manifest)
        if old_policy is None:
            manifest.pop('reference_boundary_policy_version', None)
        else:
            manifest['reference_boundary_policy_version'] = old_policy
        batch.dependency_manifest = manifest
        rev.dependency_digest = manifest_sha256(manifest)
    with factory() as session:
        result = audit_history(session, ('rb',), at=NOW)
    expected_count = 2 if strategy == 'dual_fusion' else 1
    assert result['registered_count'] == result['active_count'] == expected_count
    assert result['ready_count'] == expected_count - 1
    assert result['status_counts']['BOUNDARY_POLICY_STALE'] == 1
    item = next(item for item in result['items'] if item['stream_id'] == identity.stream_id)
    assert item['reference_boundary_policy_version'] == old_policy


def test_weekly_and_hourly_do_not_require_daily_boundary_policy():
    for frequency in ('1w', '60m'):
        factory, repo, identity, revision, checkpoint = setup_source(frequency=frequency)
        with factory() as session:
            result = audit_history(session, ('rb',), at=NOW)
        assert result['ready_count'] == 1
        item = next(item for item in result['items'] if item['stream_id'] == identity.stream_id)
        assert item['reference_boundary_policy_version'] is None
