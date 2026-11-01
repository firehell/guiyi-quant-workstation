"""Known planning failures recover without inventing a prior plan or repository write."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.contracts import (
    CheckpointToken, CommitResult, StoredRevisionState, StoredStream,
)
from app.reference_trading.historical_refresh import (
    BUDGET, HistoricalRefresh, RefreshStateError, RefreshStateStore,
)
from app.reference_trading.plan_bundle import read_plan
from app.reference_trading.planning import HistoricalReferenceRequest, canonical_sha256
from app.reference_trading.refresh_recovery import recover_blocked_planning
from app.reference_trading.service import HistoricalReferenceService
from tests.reference_trading.test_historical_refresh import Planner, Service, route, END


def prepared(tmp_path):
    item = route()
    planner = Planner()
    manifest = {"query_since": item.since.isoformat(), "proof": "old-source"}
    token = CheckpointToken(item.identity.stream_id, "old-active", 1, 2, "c" * 64)
    stream = StoredStream(item.identity.stream_id, False, "old-active", 1, 2, "STALE")
    active = StoredRevisionState(
        stream, "old-active", "active", manifest, canonical_sha256(manifest),
        token, "old-batch", {"end_input_index": 1},
    )
    receipt = CommitResult("committed", "old-batch", 1, "c" * 64)
    repository = SimpleNamespace(
        active=active,
        maximum=1,
        committed_through=item.computed_through,
        revisions=[(
            "old-active", "active", 1, "old-batch", canonical_sha256(manifest),
        )],
    )

    class ReadSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _query):
            return repository.maximum

        def execute(self, _query):
            return SimpleNamespace(
                all=lambda: repository.revisions,
                scalar_one_or_none=lambda: repository.committed_through,
            )

    repository._session_factory = ReadSession
    repository.read_state = lambda _stream_id: repository.active
    repository.read_batch = lambda _stream_id, _revision_id, key: (
        receipt if key == "old-batch" else None
    )
    guarded = []

    @contextmanager
    def guard(*_args, **_kwargs):
        guarded.append(True)
        try:
            yield
        finally:
            guarded.pop()

    def load(request, *, expected_source_token):
        assert guarded
        new = planner.plan(HistoricalReferenceRequest("rebuild", (request,), BUDGET)).streams[0]
        return SimpleNamespace(
            stream=item.identity, source_token=expected_source_token,
            completed_through=new.target_completed_through,
            bars=(None,) * new.input_count, input_bytes=new.input_bytes,
            dependency_manifest=new.input_manifest,
        )

    service = Service([("completed", None, False)])
    service._repository = repository
    service._reader = SimpleNamespace(source_guard=guard, load_stream=load)
    service._snapshot_matches = HistoricalReferenceService._snapshot_matches

    @contextmanager
    def components(**_kwargs):
        yield planner, service

    store = RefreshStateStore(tmp_path / "refresh.json")
    prior = {"status": "blocked", "reason": "REFERENCE_BUDGET_EXCEEDED"}
    unrelated = {"status": "pending", "reason": "SOURCE_BUSY"}
    store.write({
        "version": "newow_historical_refresh_v1", "cursor": "other-route",
        "routes": {item.identity.stream_id: prior, "other-route": unrelated},
    })
    runner = HistoricalRefresh(
        routes=lambda: (item,), endpoint=lambda *_args: (END, END.date()),
        components=components, state=store,
    )
    return runner, item, planner, service, repository


def test_dryrun_archives_only_on_hash_bound_apply_and_native_worker_executes(tmp_path):
    runner, item, _, service, repository = prepared(tmp_path)
    original = runner.state.path.read_bytes()
    original_active = repository.active
    dry = recover_blocked_planning(runner, item.identity.stream_id, now=END)
    assert dry["status"] == "ready"
    assert dry["recovery"]["prior"] == {
        "status": "blocked", "reason": "REFERENCE_BUDGET_EXCEEDED",
    }
    assert runner.state.path.read_bytes() == original
    assert not service.calls and not list(tmp_path.glob("*.recovery-*.json"))
    with pytest.raises(ValueError, match="HASH_CONFLICT"):
        recover_blocked_planning(
            runner, item.identity.stream_id, now=END, apply=True,
            expected_recovery_sha256="a" * 64,
        )
    assert runner.state.path.read_bytes() == original
    applied = recover_blocked_planning(
        runner, item.identity.stream_id, now=END, apply=True,
        expected_recovery_sha256=dry["recovery_sha256"],
    )
    assert applied["status"] == "installed" and repository.active == original_active
    current = runner.state.read()
    assert current["cursor"] == "other-route"
    assert current["routes"]["other-route"] == {
        "status": "pending", "reason": "SOURCE_BUSY",
    }
    pending = current["routes"][item.identity.stream_id]
    assert pending["status"] == "pending" and pending["reason"] is None
    assert runner.state.read_plan(pending["plan"])["operation"] == "rebuild"
    archive = next(tmp_path.glob("refresh.json.recovery-*.json"))
    assert read_plan(archive, trusted_root=tmp_path) == dry["recovery"]
    assert not service.calls
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        recover_blocked_planning(runner, item.identity.stream_id, now=END, apply=True,
                                 expected_recovery_sha256=dry["recovery_sha256"])
    runner.tick(now=END)
    assert service.calls and service.calls[0][0] == "rebuild"


def test_original_blocked_entry_must_have_no_plan_or_unknown_fields(tmp_path):
    runner, item, _, _, _ = prepared(tmp_path)
    state = runner.state.read()
    state["routes"][item.identity.stream_id]["plan"] = {"unexpected": True}
    runner.state.write(state)
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        recover_blocked_planning(runner, item.identity.stream_id, now=END)


@pytest.mark.parametrize("kind", ("ahead", "candidate", "active_drift"))
def test_checkpoint_candidate_or_active_drift_rejects_without_archive(tmp_path, kind):
    runner, item, _, _, repository = prepared(tmp_path)
    original = runner.state.path.read_bytes()
    if kind == "ahead":
        repository.maximum = 2
    elif kind == "candidate":
        repository.revisions.append(("candidate", "candidate", 1, "seed", "d" * 64))
    else:
        repository.active = replace(repository.active, revision_status="superseded")
    with pytest.raises(ValueError, match="READBACK_REQUIRED"):
        recover_blocked_planning(runner, item.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob("*.recovery-*.json"))


def test_source_pin_drift_rejects_before_archive_or_state_write(tmp_path):
    runner, item, _, service, _ = prepared(tmp_path)
    original = runner.state.path.read_bytes()
    source_load = service._reader.load_stream

    def changed(*args, **kwargs):
        snapshot = source_load(*args, **kwargs)
        snapshot.source_token = "changed"
        return snapshot

    service._reader.load_stream = changed
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        recover_blocked_planning(runner, item.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob("*.recovery-*.json"))


def test_source_or_checkpoint_change_between_dryrun_and_apply_rejects(tmp_path):
    runner, item, planner, _, repository = prepared(tmp_path)
    dry = recover_blocked_planning(runner, item.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    planner.source = "new-source"
    with pytest.raises(ValueError, match="HASH_CONFLICT"):
        recover_blocked_planning(
            runner, item.identity.stream_id, now=END, apply=True,
            expected_recovery_sha256=dry["recovery_sha256"],
        )
    assert runner.state.path.read_bytes() == original
    planner.source = "same-source"
    repository.maximum = 2
    with pytest.raises(ValueError, match="READBACK_REQUIRED"):
        recover_blocked_planning(
            runner, item.identity.stream_id, now=END, apply=True,
            expected_recovery_sha256=dry["recovery_sha256"],
        )
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob("*.recovery-*.json"))


@pytest.mark.parametrize("kind", ("since", "watermark", "endpoint_behind", "route"))
def test_stale_route_or_current_checkpoint_cannot_be_recovered(tmp_path, kind):
    runner, item, _, _, repository = prepared(tmp_path)
    original = runner.state.path.read_bytes()
    if kind == "since":
        repository.active = replace(repository.active, dependency_manifest={
            "query_since": "2023-01-02", "proof": "old-source",
        })
    elif kind == "watermark":
        repository.committed_through = END
    elif kind == "endpoint_behind":
        newer = replace(item, computed_through=END + timedelta(days=1))
        repository.committed_through = newer.computed_through
        runner._routes = lambda: (newer,)
    else:
        calls = 0

        def changed_route():
            nonlocal calls
            calls += 1
            return (item,) if calls == 1 else (replace(item, reason="HISTORY_NOT_PUBLISHED"),)

        runner._routes = changed_route
    with pytest.raises(ValueError, match="READBACK_REQUIRED|ROUTE_CHANGED"):
        recover_blocked_planning(runner, item.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob("*.recovery-*.json"))


def test_unrelated_state_change_after_dryrun_is_preserved_on_apply(tmp_path):
    runner, item, _, _, _ = prepared(tmp_path)
    dry = recover_blocked_planning(runner, item.identity.stream_id, now=END)
    updated = runner.state.read()
    updated["cursor"] = "moved"
    updated["routes"]["other-route"] = {"status": "blocked", "reason": "INDEPENDENT"}
    runner.state.write(updated)
    applied = recover_blocked_planning(
        runner, item.identity.stream_id, now=END, apply=True,
        expected_recovery_sha256=dry["recovery_sha256"],
    )
    assert applied["recovery_sha256"] == dry["recovery_sha256"]
    current = runner.state.read()
    assert current["cursor"] == "moved"
    assert current["routes"]["other-route"] == {
        "status": "blocked", "reason": "INDEPENDENT",
    }
    assert current["routes"][item.identity.stream_id]["status"] == "pending"


def test_noncooperating_state_write_during_archive_is_not_overwritten(tmp_path):
    from app.reference_trading import refresh_recovery

    runner, item, _, _, _ = prepared(tmp_path)
    dry = recover_blocked_planning(runner, item.identity.stream_id, now=END)
    archive = refresh_recovery._archive_recovery

    def changed_during_archive(store, recovery):
        digest = archive(store, recovery)
        other = store.read()
        other["cursor"] = "noncooperating-writer"
        store.write(other)
        return digest

    refresh_recovery._archive_recovery = changed_during_archive
    try:
        with pytest.raises(ValueError, match="STATE_CHANGED"):
            recover_blocked_planning(
                runner, item.identity.stream_id, now=END, apply=True,
                expected_recovery_sha256=dry["recovery_sha256"],
            )
    finally:
        refresh_recovery._archive_recovery = archive
    current = runner.state.read()
    assert current["cursor"] == "noncooperating-writer"
    assert current["routes"][item.identity.stream_id]["status"] == "blocked"


def test_archive_completed_then_state_write_unknown_preserves_readback(tmp_path):
    runner, item, _, _, _ = prepared(tmp_path)
    dry = recover_blocked_planning(runner, item.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    write = runner.state.write

    def fail_write(_state):
        raise RefreshStateError("REFRESH_STATE_WRITE_UNKNOWN")

    runner.state.write = fail_write
    with pytest.raises(RefreshStateError, match="WRITE_UNKNOWN"):
        recover_blocked_planning(
            runner, item.identity.stream_id, now=END, apply=True,
            expected_recovery_sha256=dry["recovery_sha256"],
        )
    assert runner.state.path.read_bytes() == original
    assert len(list(tmp_path.glob("refresh.json.recovery-*.json"))) == 1
    runner.state.write = write


def test_non_newow_or_missing_source_stays_blocked(tmp_path):
    runner, item, _, _, _ = prepared(tmp_path)
    missing = replace(item, reason="HISTORY_SOURCE_MISSING")
    runner._routes = lambda: (missing,)
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        recover_blocked_planning(runner, item.identity.stream_id, now=END)
    assert runner.state.read()["routes"][item.identity.stream_id]["status"] == "blocked"
