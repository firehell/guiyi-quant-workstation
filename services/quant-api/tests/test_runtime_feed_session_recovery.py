from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, date, datetime
import json

import pytest

from app.runtime_feed_session_recovery import Coordinator, RecoveryError, safe_proof


def proof():
    return dict(
        status="READ_ONLY_INSPECTED",
        pid=17,
        detached=True,
        runtime_frame_bound=True,
        target_calls=0,
        target_writes=0,
        input_failure="LIVE_PROVIDER_CLOSE_UNKNOWN",
        retirement_failed=True,
        provider_type="RQDataLiveProvider",
        close_succeeded=True,
        close_failed=False,
        closed=True,
        raw_buffer_count=0,
        pending_count=0,
        isolation_provider_matches=True,
        isolation_snapshot_matches=True,
        isolation_day="2026-11-02",
        object_identity="objects",
        process_identity="birth",
        proof_at=datetime.fromtimestamp(1000, UTC).isoformat(),
        listeners={
            "_listener": {"present": False},
            "_retired_listener": {"present": True, "native_thread_alive": False},
        },
    )


class Backend:
    old_day = date(2026, 11, 2)
    def __init__(self, folder):
        self.folder = folder
        self.now = 1000
        self.drains = 0
        self.resumes = 0
        self.pending = proof()
        self.frozen = True
        self.is_parked = True
        self.is_ready = True
        self.baseline = {
            "pid": 17,
            "process_identity": "birth",
            "protected": {"account": "unchanged"},
            "journals": {"old": "prefix"},
        }
        self.failure_stage = None

    def snapshot(self):
        return deepcopy(self.baseline)

    def probe(self, pid, label):
        return deepcopy(self.pending)

    def guard(self):
        return nullcontext()

    def drain(self):
        assert (
            json.loads((self.folder / "state.json").read_text())["stage"]
            == "DRAIN_INTENT"
        )
        self.drains += 1
        if self.failure_stage == "drain":
            raise OSError("unknown result")
        return "exact-request"

    def parked(self, original, request):
        assert request == "exact-request"
        return self.is_parked

    def verify_frozen(self, original):
        if not self.frozen:
            raise RecoveryError("SOURCE_DRIFT")

    def resume(self, original, request):
        assert (
            json.loads((self.folder / "state.json").read_text())["stage"]
            == "RESUME_INTENT"
        )
        self.resumes += 1
        if self.failure_stage == "resume":
            raise OSError("unknown cancel")

    def ready(self, original, request):
        return {"pid": 18, "unique": True} if self.is_ready else None

    def sleep(self, seconds):
        self.now += seconds


def setup(tmp_path):
    b = Backend(tmp_path)
    c = Coordinator(b, tmp_path, clock=lambda: b.now, sleep=b.sleep)
    return b, c, c.plan()


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_buffer_count", 1),
        ("pending_count", 1),
        ("close_succeeded", False),
        ("close_failed", True),
        ("detached", False),
        ("runtime_frame_bound", False),
        ("isolation_provider_matches", False),
        ("isolation_snapshot_matches", False),
        ("isolation_day", "2026-11-03"),
        ("target_calls", 1),
        ("target_writes", 1),
        ("pid", 18),
        ("input_failure", "unknown private value"),
        ("pending_count", False),
    ],
)
def test_unproven_closure_never_creates_drain_intent(tmp_path, field, value):
    b, c, p = setup(tmp_path)
    b.pending[field] = value
    with pytest.raises(RecoveryError):
        c.apply(p)
    assert b.drains == b.resumes == 0
    assert not (tmp_path / "state.json").exists()


def test_live_retired_listener_cannot_be_closed_by_pid_exit(tmp_path):
    b, c, p = setup(tmp_path)
    b.pending["listeners"]["_retired_listener"]["native_thread_alive"] = True
    with pytest.raises(RecoveryError):
        c.apply(p)
    assert b.drains == b.resumes == 0


def test_expired_or_future_proof_is_not_fresh():
    p = proof()
    assert not safe_proof(p, pid=17, now=1091, old_day=Backend.old_day)
    assert not safe_proof(p, pid=17, now=999, old_day=Backend.old_day)


def test_same_version_success_preserves_old_failure_and_consumes_once(tmp_path):
    b, c, p = setup(tmp_path)
    result = c.apply(p)
    assert (
        result["stage"] == "COMPLETE" and result["original_failure_preserved"] is True
    )
    assert result["old_run_result"] == "EXITED_AFTER_PREVIOUS_RETIREMENT_FAILURE"
    assert b.drains == b.resumes == 1
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(RecoveryError, match="ATTEMPT_CONSUMED"):
        c.apply(p)
    with pytest.raises(RecoveryError, match="ATTEMPT_CONSUMED"):
        c.plan()
    assert b.drains == b.resumes == 1


@pytest.mark.parametrize("stage", ["drain", "resume"])
def test_unknown_control_write_never_retries(tmp_path, stage):
    b, c, p = setup(tmp_path)
    b.failure_stage = stage
    with pytest.raises(OSError):
        c.apply(p)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["result"] == "UNKNOWN"
    with pytest.raises(RecoveryError, match="ATTEMPT_CONSUMED"):
        c.apply(p)
    assert b.drains == 1 and b.resumes == (stage == "resume")


def test_changed_source_after_drain_never_cancels(tmp_path):
    b, c, p = setup(tmp_path)
    b.frozen = False
    with pytest.raises(RecoveryError, match="SOURCE_DRIFT"):
        c.apply(p)
    assert b.drains == 1 and b.resumes == 0


def test_no_actual_parked_owner_stays_drained(tmp_path):
    b, c, p = setup(tmp_path)
    b.is_parked = False
    with pytest.raises(RecoveryError, match="FEED_STOP_UNKNOWN"):
        c.apply(p)
    assert b.drains == 1 and b.resumes == 0


def test_resume_without_fresh_ready_is_unknown_not_complete(tmp_path):
    b, c, p = setup(tmp_path)
    b.is_ready = False
    with pytest.raises(RecoveryError, match="FEED_READY_UNKNOWN"):
        c.apply(p)
    assert (
        json.loads((tmp_path / "state.json").read_text())["stage"] == "RESUME_REQUESTED"
    )
    assert b.drains == b.resumes == 1


def test_object_change_and_modified_plan_never_drain(tmp_path):
    b, c, p = setup(tmp_path)
    b.pending["object_identity"] = "new-object"
    with pytest.raises(RecoveryError):
        c.apply(p)
    b.pending = proof()
    p["baseline"]["pid"] = 18
    with pytest.raises(RecoveryError, match="PLAN_INVALID"):
        c.apply(p)
    assert b.drains == 0


def test_mismatched_pid_birth_proof_never_drains(tmp_path):
    b, c, p = setup(tmp_path)
    b.pending["process_identity"] = "reused-pid"
    with pytest.raises(RecoveryError):
        c.apply(p)
    assert b.drains == b.resumes == 0


def test_wrong_old_day_rejected_before_drain(tmp_path):
    b, c, p = setup(tmp_path)
    b.old_day = date(2026, 11, 3)
    with pytest.raises(RecoveryError, match='READER_CLOSURE_UNPROVEN'):
        c.apply(p)
    assert b.drains == b.resumes == 0


@pytest.mark.parametrize('field', ['binding', 'day'])
def test_frozen_context_drift_rejected_before_drain(tmp_path, field):
    b, c, p = setup(tmp_path)
    b.baseline[field] = 'changed'
    with pytest.raises(RecoveryError, match='SOURCE_DRIFT'):
        c.apply(p)
    assert b.drains == b.resumes == 0


def test_native_protection_refuses_running_tq_worker_before_reading(tmp_path):
    from app.runtime_feed_session_recovery import Native
    from guiyi_quant.tq_simulation.runtime import owner_lock
    native = object.__new__(Native)
    native.runtime = tmp_path
    base = tmp_path / 'tqkq-simulation'
    base.mkdir(mode=0o700)
    with owner_lock(base / 'owner.lock'):
        with pytest.raises(BlockingIOError):
            native.protected()


@pytest.mark.parametrize('generation,phase,accepted', [
    (63, 'drain', True), (63, 'cancelled', True), (64, 'cancelled', True),
    (64, 'drain', False), (65, 'cancelled', False), (65, 'drain', False),
    (0, 'cancelled', False), (True, 'cancelled', False), (63, 'unknown', False),
])
def test_native_control_retains_inert_prior_generation_bytes(tmp_path, generation, phase, accepted):
    import base64
    import hashlib
    from app.runtime_feed_session_recovery import Native
    native = object.__new__(Native)
    native.runtime, native.generation = tmp_path, 64
    value = dict(schema_version=1, service='market-feed', generation=generation,
                 request_id='a' * 32, phase=phase)
    raw = (json.dumps(value, indent=2) + '\n').encode()
    path = tmp_path / 'market-feed.handover.json'
    path.write_bytes(raw)
    path.chmod(0o600)
    if accepted:
        frozen = native.control()
        assert frozen['value'] == value
        assert base64.b64decode(frozen['raw_base64']) == raw
        assert frozen['sha256'] == hashlib.sha256(raw).hexdigest()
    else:
        with pytest.raises(RecoveryError, match='EXISTING_DRAIN_UNRESOLVED'):
            native.control()
    assert path.read_bytes() == raw


def test_native_drain_supersedes_only_frozen_control_and_keeps_original(tmp_path, monkeypatch):
    import base64
    from app import runtime_handover
    from app.runtime_feed_session_recovery import Native
    monkeypatch.setattr(runtime_handover, 'runtime_directory', lambda: tmp_path)
    native = object.__new__(Native)
    native.runtime, native.generation = tmp_path, 64
    path = tmp_path / 'market-feed.handover.json'
    old = dict(schema_version=1, service='market-feed', generation=63,
               request_id='b' * 32, phase='drain')
    raw = (json.dumps(old, indent=2) + '\n').encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    native.frozen_control = native.control()
    path.write_bytes(raw + b' ')
    with pytest.raises(RecoveryError, match='CONTROL_DRIFT'):
        native.drain()
    assert path.read_bytes() == raw + b' '
    path.write_bytes(raw)
    request = native.drain()
    current = json.loads(path.read_bytes())
    assert current['generation'] == 64 and current['phase'] == 'drain'
    assert current['request_id'] == request != old['request_id']
    assert base64.b64decode(native.frozen_control['raw_base64']) == raw
