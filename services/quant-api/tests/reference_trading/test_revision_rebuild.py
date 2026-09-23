from __future__ import annotations

from dataclasses import replace

import pytest

from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict

from app.reference_trading.planning import HistoricalReferencePlanner, HistoricalReferenceRequest
from app.reference_trading.service import HistoricalReferenceService
from app.reference_trading.service import ServiceInterrupted
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401


def test_rebuild_invalidates_changed_active_and_publishes_complete_new_revision() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=9)
    first = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    old_revision = first.streams[0].active_revision_id
    assert old_revision is not None
    reader.token = "source-revised"
    original = reader._snapshot

    def revised(req):
        result = original(req)
        manifest = {**result.dependency_manifest}
        manifest["partitions"] = [{"key": "RB2605", "sha256": "e" * 64}]
        return replace(result, dependency_manifest=manifest)

    reader._snapshot = revised
    requested = HistoricalReferenceRequest(
        "rebuild", (initial.streams[0].request,), initial.budget, initial.batch_size,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)

    result = HistoricalReferenceService(repository, reader).rebuild(plan, plan.plan_hash)

    assert result.status == "completed"
    assert result.streams[0].active_revision_id != old_revision
    assert repository.read_state(
        initial.streams[0].request.identity.stream_id, old_revision,
    ).revision_status == "invalid"
    assert repository.read_state(
        initial.streams[0].request.identity.stream_id,
    ).revision_status == "active"


def test_interrupted_rebuild_resumes_its_existing_candidate() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=9)
    HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    requested = HistoricalReferenceRequest(
        "rebuild", (initial.streams[0].request,), initial.budget, 10,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)

    def stop(_stage, _context):
        raise ServiceInterrupted("stop")

    partial = HistoricalReferenceService(
        repository, reader, after_batch=stop,
    ).rebuild(plan, plan.plan_hash)
    token = partial.streams[0].resume_token
    assert partial.status == "partial"
    assert token is not None

    resumed = HistoricalReferenceService(repository, reader).resume(
        plan, token, plan.plan_hash,
    )

    assert resumed.status == "completed"
    assert resumed.streams[0].candidate_revision_id == token.revision_id


@pytest.mark.isolated_postgresql
def test_postgresql_rebuild_rejects_old_snapshot_and_reads_new_revision(
    reference_postgresql,  # noqa: F811
) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.reference_trading.repository import ReferenceRepository

    reader = Reader()
    factory = sessionmaker(reference_postgresql, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    initial = _plan(reader, batch_size=9)
    first = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    assert first.status == "completed"
    stream_id = initial.streams[0].request.identity.stream_id
    params = {
        "since": reader.bars[0].trading_day,
        "through": reader.bars[-1].trading_day,
    }
    query = HistoricalReferenceQuery(factory)
    old = query.trades(stream_id, **params)

    reader.token = "source-revised"
    original = reader._snapshot

    def revised(request):
        result = original(request)
        return replace(result, dependency_manifest={
            **result.dependency_manifest,
            "partitions": [{"key": "RB2605", "sha256": "e" * 64}],
        })

    reader._snapshot = revised
    requested = HistoricalReferenceRequest(
        "rebuild", (initial.streams[0].request,), initial.budget, initial.batch_size,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)
    rebuilt = HistoricalReferenceService(repository, reader).rebuild(plan, plan.plan_hash)
    assert rebuilt.status == "completed"
    current = query.trades(stream_id, **params)
    assert current["revision_id"] != old["revision_id"]
    assert current["items"] == old["items"]
    with pytest.raises(QueryConflict, match="SNAPSHOT_INVALIDATED"):
        query.trades(stream_id, snapshot_token=old["snapshot"], **params)
