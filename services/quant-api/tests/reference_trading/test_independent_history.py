from dataclasses import replace
from datetime import UTC, datetime

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.independent_history import read_independent_history
from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.repository import ReferenceRepository, _identity_from_row
from guiyi_quant.reference_trading import RecordingMode
from test_source_revisions import stored_case


def test_live_results_never_stand_in_for_a_missing_stale_or_current_independent_history():
    factory, _, sid, _, _ = stored_case()
    end = datetime(2026, 10, 23, 7, tzinfo=UTC)
    endpoints = {('rb', '60m'): {'canonical_expected_through': end.isoformat(),
                               'expected_source': 'completed_live',
                               'expected_through': '2026-10-23T14:00:00+00:00'}}
    with factory() as session:
        forward = session.get(ReferenceStream, sid)
        identity = replace(_identity_from_row(forward), recording_mode=RecordingMode.HISTORICAL_REPLAY,
                           observation_policy_version=None)
        assert read_independent_history(session, (forward,), endpoints)[sid]['status'] == 'NOT_BUILT'
    repo = ReferenceRepository(factory)
    stored = repo.ensure_stream(identity)
    revision = repo.create_revision(identity.stream_id, stored.row_version, manifest_sha256({'source':'canonical'}))
    with factory() as session, session.begin():
        historical = session.get(ReferenceStream, identity.stream_id)
        historical.active_revision_id = revision
        historical.health = 'READY'
        record = session.get(ReferenceRevision, (identity.stream_id, revision))
        record.status = 'active'
        record.checkpoint_batch_id = 'historical-seal'
        session.add(ReferenceBatch(batch_id='historical-seal', stream_id=identity.stream_id,
            revision_id=revision, batch_key='seal', payload_hash='a'*64, kind='seed_seal',
            outcome='committed', seq=1, expected_seq=0, computed_through=end,
            dependency_manifest={}, source_evidence={}, projected_action_pks=[], diagnostics=[], processed_at=end))
    with factory() as session:
        result = read_independent_history(session, (session.get(ReferenceStream, sid),), endpoints)[sid]
        assert result['status'] == 'CURRENT'
        assert result['expected_through'] == end.isoformat()
        assert result['stream_id'] != sid
        assert result['recording_mode'] == 'historical_replay'
    with factory() as session, session.begin():
        session.get(ReferenceRevision, (identity.stream_id, revision)).status = 'invalid'
    with factory() as session:
        assert read_independent_history(session, (session.get(ReferenceStream, sid),), endpoints)[sid]['status'] == 'REBUILD_REQUIRED'
