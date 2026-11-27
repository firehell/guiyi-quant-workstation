from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from app.compute_runtime import ComputeBusy, ComputeRuntime
from app.compute_runtime.owned_live import OwnedLiveCommit, OwnedLiveScope
from guiyi_quant.compute import REGISTRY


START = datetime(2026, 11, 26, 1, tzinfo=UTC)
M30 = OwnedLiveScope("subing_simulation", "jm", "JM2701", "30m", START.date())
H1 = replace(M30, frequency="60m")


def _commit(scope, index=1, previous=None):
    bar_end = START + timedelta(minutes=index)
    return OwnedLiveCommit(scope, f"{index}-0", bar_end, bar_end + timedelta(seconds=2),
                           previous, "a" * 64, "b" * 64)


def test_owned_live_validates_replay_and_scope_before_running_consumer():
    original = _commit(M30)
    owner = object()
    calls = []
    with ComputeRuntime(REGISTRY, owned_live_scopes=(M30,)) as runtime:
        def run():
            calls.append("called")
            return "calculated"

        jumped = _commit(M30, 2, original.bar_end)
        with pytest.raises(ValueError, match="COMPUTE_OWNED_LIVE_PREFIX_REQUIRED"):
            runtime.submit_owned_live(jumped, owner=owner, run=run).result()
        assert runtime.submit_owned_live(original, owner=owner, run=run).result().duplicate is False
        assert runtime.submit_owned_live(original, owner=owner, run=run).result().duplicate is True
        with pytest.raises(ValueError, match="COMPUTE_OWNED_LIVE_COMMIT_CONFLICT"):
            runtime.submit_owned_live(replace(original, input_digest="c" * 64), owner=owner, run=run).result()
        with pytest.raises(ValueError, match="COMPUTE_OWNED_LIVE_OWNER_CONFLICT"):
            runtime.submit_owned_live(original, owner=object(), run=run).result()
        with pytest.raises(ValueError, match="COMPUTE_SCOPE_NOT_ENABLED"):
            runtime.submit_owned_live(_commit(H1), owner=owner, run=run)
        assert runtime.submit_owned_live(jumped, owner=owner, run=run).result().duplicate is False
        assert calls == ["called", "called"]


def test_failed_paper_step_fences_both_periods_until_owner_rebuilds():
    owner = object()

    def fail():
        raise RuntimeError("PARTIAL_FACTOR_FAILURE")

    with ComputeRuntime(REGISTRY, owned_live_scopes=(M30, H1)) as runtime:
        with pytest.raises(RuntimeError, match="PARTIAL_FACTOR_FAILURE"):
            runtime.submit_owned_live(_commit(M30), owner=owner, run=fail).result()
        with pytest.raises(ValueError, match="COMPUTE_OWNED_LIVE_RESTORE_REQUIRED"):
            runtime.submit_owned_live(_commit(H1), owner=owner, run=lambda: pytest.fail()).result()
    with ComputeRuntime(REGISTRY, owned_live_scopes=(M30, H1)) as restarted:
        assert restarted.submit_owned_live(_commit(H1), owner=object(), run=lambda: 1).result().result == 1


def test_owned_live_queue_budget_applies_while_first_job_is_running():
    started, release = Event(), Event()

    def wait():
        started.set()
        assert release.wait(3)
        return True

    with ComputeRuntime(REGISTRY, live_pending=1, owned_live_scopes=(M30, H1)) as runtime:
        first = runtime.submit_owned_live(_commit(M30), owner=object(), run=wait)
        try:
            assert started.wait(3)
            with pytest.raises(ComputeBusy, match="live"):
                runtime.submit_owned_live(_commit(H1), owner=object(), run=lambda: pytest.fail())
        finally:
            release.set()
        assert first.result(timeout=3).result is True
