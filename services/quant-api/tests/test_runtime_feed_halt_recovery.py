"""Only the exact verified-stage Feed failure can be closed, never retried."""

from copy import deepcopy
import json

import pytest

from app import runtime_cohort_recovery as m
from app.runtime_handover import _write
from tests.test_runtime_cohort_forward_recovery import intake_halt_case, native


def feed_halt_case(tmp_path):
    host, path, b_path, a_attempt, b_attempt, original, audit = intake_halt_case(
        tmp_path
    )
    c = m.freeze_forward_recovery(host, path, predecessor_recovery_plan=b_path)
    c_path = tmp_path / "feed-halt.json"
    _write(c_path, c)
    c_attempt = host.directory / "cohort-forward-recoveries" / c["plan_sha256"]
    c_attempt.mkdir(mode=0o700)
    _write(c_attempt / "plan.json", c)
    _write(
        c_attempt / "state.json",
        {
            "schema_version": 1,
            "kind": m.KIND,
            "plan_sha256": c["plan_sha256"],
            "source": c["source"],
            "phase": "outcome_unknown",
            "failed_stage": "verified",
            "effects": {
                "consumers": {
                    "resumed_generation": m.registry(c["new"])
                    .services["live"]
                    .generation
                },
                "intake": {
                    "schema_version": 2,
                    "kind": "reference_receiving_liveness_v1",
                    "mode": "durable_receiving_caught_up_idle",
                    "calculation_ready": False,
                    "before_sha256": "1" * 64,
                    "after_sha256": "2" * 64,
                    "advanced_count": 0,
                    "remaining_count": 0,
                    "old_tail_reached": True,
                },
                "feed": {
                    "bootstrapped": True,
                    "label": m.registry(c["new"]).services["market-feed"].label,
                },
            },
        },
    )
    audit.pop("confirmed_live_stop", None)
    audit["owners"]["market-feed"] = {"pid": 40577, "phase": "parked", "generation": 29}
    audit["controls"]["market-feed"] = {"request_id": "a" * 32}
    intent = {
        "kind": "parked_feed_close_intent_v1",
        "observed_pids": [40577],
        "binding_sha256": "b" * 64,
        "frontiers_sha256": "c" * 64,
    }
    audit["feed_close"] = intent

    def current_audit(
        source, budget, *, predecessor=None, feed_close_plan=None, **kwargs
    ):
        value = deepcopy(audit)
        if feed_close_plan is not None:
            identity, receipt = m._feed_close_attempt(
                host, feed_close_plan, predecessor
            )
            value["owners"]["market-feed"] = {"phase": "absent", "generation": 29}
            value["feed_close"] = {
                "kind": "feed_close_readback_v1",
                "attempt": identity,
                "proof": receipt["feed_close"],
            }
        value["confirmed_feed_halt"] = {
            "predecessor_plan_sha256": predecessor["plan_sha256"],
            "owners_sha256": m.digest(value["owners"]),
            "controls_sha256": m.digest(value["controls"]),
            "receiving_context": value["receiving_context"],
            "feed_close_sha256": m.digest(value["feed_close"]),
            "all_consumers_parked": True,
            "current_tail_reached": True,
        }
        p = value["confirmed_feed_halt"]
        p["proof_sha256"] = m.digest(p)
        return value

    host.audit_forward = current_audit

    def stop(source, frozen, budget, record):
        host.calls.append("feed_stop")
        effect = {
            "phase": "bootout_requested",
            "intent": frozen["feed_close"],
            "observed_pids": frozen["feed_close"]["observed_pids"],
        }
        record(effect)
        return {
            "kind": "feed_closed_v1",
            "intent_sha256": m.digest(effect["intent"]),
            "observed_pids": effect["observed_pids"],
            "label_absent": True,
            "observed_pids_exited": True,
            "owner_lock_available": True,
            "frontiers_sha256": effect["intent"]["frontiers_sha256"],
            "observed_at": host.now().isoformat(),
        }

    host.stop_parked_feed = stop
    host.halt_unknown = lambda *args: host.calls.append("halt")
    return host, path, c_path, (a_attempt, b_attempt, c_attempt, original)


def close_plan(host, path, c_path, tmp_path):
    frozen = m.freeze_forward_recovery(
        host, path, predecessor_recovery_plan=c_path, close_feed_only=True
    )
    target = tmp_path / "close-only.json"
    _write(target, frozen)
    return frozen, target


def test_close_only_never_resumes_or_updates_global_success_and_preserves_all_failures(
    tmp_path,
):
    host, path, c_path, attempts = feed_halt_case(tmp_path)
    before = {p: (p / "state.json").read_bytes() for p in attempts}
    pointer = (host.directory / "cohort-release.json").read_bytes()
    frozen, target = close_plan(host, path, c_path, tmp_path)
    result = m.apply_forward_recovery(host, target)
    assert result["status"] == "feed_closed"
    assert host.calls == ["feed_stop"]
    assert (host.directory / "cohort-release.json").read_bytes() == pointer
    assert all((p / "state.json").read_bytes() == value for p, value in before.items())
    assert frozen["stop_after"] == "feed_close"
    with pytest.raises(ValueError, match="ATTEMPT_ALREADY_EXISTS"):
        m.apply_forward_recovery(host, target)
    with pytest.raises(ValueError, match="READBACK_REQUIRED"):
        m._no_unresolved_recovery(host)  # Closing Feed does not resolve A/B/C.


@pytest.mark.parametrize(
    "wrong", ["stage", "feed", "calendar", "intake", "fourth_unknown", "ancestor"]
)
def test_only_exact_c_prefix_can_plan_feed_close(tmp_path, wrong):
    host, path, c_path, attempts = feed_halt_case(tmp_path)
    a, _, c, _ = attempts
    state = json.loads((c / "state.json").read_text())
    if wrong == "stage":
        state["failed_stage"] = "calendars"
    elif wrong == "feed":
        state["effects"]["feed"]["label"] = "other"
    elif wrong == "calendar":
        state["effects"]["calendars"] = {}
    elif wrong == "intake":
        state["effects"]["intake"]["calculation_ready"] = True
    elif wrong == "fourth_unknown":
        other = c.parent / ("e" * 64)
        other.mkdir(mode=0o700)
        _write(other / "state.json", {"phase": "outcome_unknown"})
    else:
        old = json.loads((a / "state.json").read_text())
        old["error_code"] = "CHANGED"
        _write(a / "state.json", old)
    _write(c / "state.json", state)
    with pytest.raises(ValueError):
        close_plan(host, path, c_path, tmp_path)
    assert host.calls == []


def test_uncertain_feed_stop_is_not_reissued_or_selected_as_a_new_predecessor(tmp_path):
    host, path, c_path, _ = feed_halt_case(tmp_path)
    frozen, target = close_plan(host, path, c_path, tmp_path)

    def uncertain(source, audit, budget, record):
        record(
            {
                "phase": "bootout_requested",
                "intent": audit["feed_close"],
                "observed_pids": [40577],
            }
        )
        host.calls.append("feed_stop")
        raise OSError("private native result")

    host.stop_parked_feed = uncertain
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        m.apply_forward_recovery(host, target)
    assert host.calls == ["feed_stop"]
    with pytest.raises(ValueError):
        m.apply_forward_recovery(host, target)
    with pytest.raises(ValueError):
        close_plan(host, path, c_path, tmp_path)
    with pytest.raises(ValueError):
        m.freeze_forward_recovery(host, path, predecessor_recovery_plan=target)
    assert host.calls == ["feed_stop"]


def test_normal_recovery_requires_exact_successful_closure_and_only_then_resolves_c_chain(
    tmp_path,
):
    host, path, c_path, attempts = feed_halt_case(tmp_path)
    _, close = close_plan(host, path, c_path, tmp_path)
    m.apply_forward_recovery(host, close)
    host.calls.clear()
    frozen = m.freeze_forward_recovery(
        host, path, predecessor_recovery_plan=c_path, feed_close_plan=close
    )
    target = tmp_path / "resume.json"
    _write(target, frozen)
    assert "stop_after" not in frozen
    assert m.apply_forward_recovery(host, target)["status"] == "recovered"
    assert host.calls == ["consumers", "intake", "feed", "verified", "calendars"]
    m._no_unresolved_recovery(host)


def test_close_receipt_state_or_private_plan_drift_blocks_before_resume(tmp_path):
    host, path, c_path, _ = feed_halt_case(tmp_path)
    frozen, close = close_plan(host, path, c_path, tmp_path)
    m.apply_forward_recovery(host, close)
    target = tmp_path / "resume.json"
    _write(
        target,
        m.freeze_forward_recovery(
            host, path, predecessor_recovery_plan=c_path, feed_close_plan=close
        ),
    )
    host.calls.clear()
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    receipt = json.loads((attempt / "receipt.json").read_text())
    receipt["feed_close"]["observed_pids_exited"] = False
    _write(attempt / "receipt.json", receipt)
    with pytest.raises(ValueError):
        m.apply_forward_recovery(host, target)
    assert host.calls == []


def test_close_receipt_drift_between_stages_blocks_the_next_resume(tmp_path):
    host, path, c_path, _ = feed_halt_case(tmp_path)
    frozen, close = close_plan(host, path, c_path, tmp_path)
    m.apply_forward_recovery(host, close)
    target = tmp_path / "resume.json"
    _write(
        target,
        m.freeze_forward_recovery(
            host, path, predecessor_recovery_plan=c_path, feed_close_plan=close
        ),
    )
    receipt = (
        host.directory
        / "cohort-forward-recoveries"
        / frozen["plan_sha256"]
        / "receipt.json"
    )

    def drift(*args):
        host.calls.append("consumers")
        data = json.loads(receipt.read_text())
        data["feed_close"]["observed_pids_exited"] = False
        _write(receipt, data)
        return {"resumed": True}

    host.calls.clear()
    host.resume_consumers = drift
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        m.apply_forward_recovery(host, target)
    assert host.calls == ["consumers", "halt"]


@pytest.mark.parametrize(
    "mode,old_tail,remaining",
    [
        ("durable_receiving", False, 1),
        ("durable_receiving_backlog_liveness", True, 0),
    ],
)
def test_impossible_historical_intake_modes_cannot_be_selected(
    tmp_path, mode, old_tail, remaining
):
    host, path, c_path, attempts = feed_halt_case(tmp_path)
    c = attempts[2]
    state = json.loads((c / "state.json").read_text())
    state["effects"]["intake"].update(
        mode=mode,
        advanced_count=1,
        old_tail_reached=old_tail,
        remaining_count=remaining,
    )
    _write(c / "state.json", state)
    with pytest.raises(ValueError):
        close_plan(host, path, c_path, tmp_path)


def native_stop_case(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from tests.test_runtime_cohort_forward_recovery import fixture

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    clock = [0.0]
    calls = []
    recorded = []
    current.monotonic = lambda: clock[0]
    current.now = host.now
    current.forward_guards = lambda *args: nullcontext()
    current._resume_owner_guards = lambda: nullcontext()
    owners = {"market-feed": {"pid": 101, "phase": "parked", "generation": 29}}
    controls = {"market-feed": {"request_id": "a" * 32}}
    frontiers = {"source": "verified", "completed": "verified"}
    intent = {
        "kind": "parked_feed_close_intent_v1",
        "observed_pids": [101],
        "binding_sha256": "b" * 64,
        "frontiers_sha256": m.digest(frontiers),
    }
    audit = {
        "controller": {"tag": "v1.16.19"},
        "owners": owners,
        "controls": controls,
        "installed_sha256": m.digest({}),
        "feed_close": intent,
    }
    current._controller = lambda: audit["controller"]
    current._fixed = lambda *args: {}
    current.feed_close_intent = lambda *args: intent
    current._parked_owners = lambda *args, **kwargs: owners
    current._controls = lambda *args: controls
    current._feed_pids = lambda *args: [101]
    current._observed_feed_pids = lambda source, previous: previous
    current._feed_frontiers = lambda *args: frontiers
    current._calculation_boundary = lambda: True
    current.check_protected_forward = lambda *args: None
    current.definition_absent = lambda binding: bool(calls)
    current.loaded = lambda *args, **kwargs: None if calls else "101"

    def launch(*args):
        assert recorded and recorded[0]["phase"] == "bootout_requested"
        calls.append(args)

    def exited(pid, signal):
        raise ProcessLookupError

    current.launch = launch
    monkeypatch.setattr(m.os, "kill", exited)
    monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: True)
    monkeypatch.setattr(m, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + 10))
    return current, source, audit, calls, recorded


def test_native_close_records_before_one_bootout_and_proves_actual_exit(
    tmp_path, monkeypatch
):
    current, source, audit, calls, recorded = native_stop_case(tmp_path, monkeypatch)
    proof = current.stop_parked_feed(source, audit, lambda: None, recorded.append)
    assert len(calls) == 1 and calls[0][0] == "bootout"
    assert proof["label_absent"] is True and proof["observed_pids_exited"] is True
    assert m._valid_feed_close(proof, audit["feed_close"])


def test_native_newly_observed_pid_must_also_exit(tmp_path, monkeypatch):
    current, source, audit, calls, recorded = native_stop_case(tmp_path, monkeypatch)
    current._observed_feed_pids = lambda *args: [101, 202]

    def alive(pid, signal):
        if pid == 202:
            return None
        raise ProcessLookupError

    monkeypatch.setattr(m.os, "kill", alive)
    with pytest.raises(ValueError, match="FEED_EXIT_UNPROVEN"):
        current.stop_parked_feed(source, audit, lambda: None, recorded.append)
    assert len(calls) == 1
    assert recorded[-1]["observed_pids"] == [101, 202]


@pytest.mark.parametrize("wrong", ["busy_lock", "source_drift", "record_failure"])
def test_native_close_proof_is_not_manufactured_after_incomplete_readback(
    tmp_path, monkeypatch, wrong
):
    current, source, audit, calls, recorded = native_stop_case(tmp_path, monkeypatch)
    record = recorded.append
    if wrong == "busy_lock":
        monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: False)
    elif wrong == "source_drift":
        current._feed_frontiers = lambda *args: {"changed": True}
    else:

        def record(value):
            raise OSError("private write failure")

    with pytest.raises((ValueError, OSError)):
        current.stop_parked_feed(source, audit, lambda: None, record)
    assert len(calls) == (0 if wrong == "record_failure" else 1)


@pytest.mark.parametrize(
    "wrong", [None, "middle_original", "content_index", "missing_index", "unacked"]
)
def test_source_closure_frontier_verifies_every_original_and_identity_entry(
    tmp_path, monkeypatch, wrong
):
    import app.redis_connections as connections
    from app.market_data.observation_stream import (
        ObservationStream,
        ObservationEnvelope,
    )
    from tests.reference_trading.test_receiving_handover import Redis, DAY
    from tests.reference_trading.test_receiving_liveness import _setup

    data = tmp_path / "receiving"
    data.mkdir(mode=0o700)
    _, _, completed, _, _, capture, sample = _setup(data)
    capture("11-0")
    capture("12-0")
    redis = Redis()
    redis.close = lambda: None
    source = ObservationStream(redis, kind="source")
    redis.values[source.registration_key("live")] = DAY.isoformat()
    redis.values[source.cursor_key("live", DAY)] = "12-0"
    redis.rows[source.key(DAY)] = deepcopy(completed.redis.rows[completed.key(DAY)])
    records = {}
    for identifier, fields in redis.rows[source.key(DAY)]:
        event = ObservationEnvelope.from_json(fields["envelope"], stream_id=identifier)
        raw = event.to_json()
        content = json.loads(raw)
        content.pop("source_observed_at")
        content.pop("raw_received_at")
        records[event.observation_id] = json.dumps(
            {
                "id": identifier,
                "payload": raw,
                "content": json.dumps(content, sort_keys=True, separators=(",", ":")),
            }
        )
    redis.hashes[source.identity_key(DAY)] = records
    if wrong == "middle_original":
        row = redis.rows[source.key(DAY)][1][1]
        value = json.loads(row["envelope"])
        value["data"]["close"] = "999"
        row["envelope"] = json.dumps(value)
    elif wrong == "content_index":
        key = next(iter(records))
        value = json.loads(records[key])
        value["content"] = "changed"
        records[key] = json.dumps(value)
    elif wrong == "missing_index":
        records.pop(next(iter(records)))
    elif wrong == "unacked":
        redis.values[source.cursor_key("live", DAY)] = "11-0"
    current = native(tmp_path)
    current._snapshot = lambda *args: sample(live=False)
    monkeypatch.setattr(connections, "get_redis_connection", lambda: redis)
    if wrong is not None:
        with pytest.raises(ValueError):
            current._feed_frontiers({}, lambda: None)
    else:
        first = current._feed_frontiers({}, lambda: None)
        assert first["source"][DAY.isoformat()]["count"] == 3
        assert first == current._feed_frontiers({}, lambda: None)


@pytest.mark.parametrize("changed", ["stop_after", "invalid_end", "full_receipt"])
def test_closure_end_and_terminal_receipt_cannot_be_relabelled_as_recovery(
    tmp_path, changed
):
    host, path, c_path, _ = feed_halt_case(tmp_path)
    frozen, close = close_plan(host, path, c_path, tmp_path)
    if changed in {"stop_after", "invalid_end"}:
        bad = deepcopy(frozen)
        if changed == "stop_after":
            bad.pop("stop_after")
        else:
            bad["stop_after"] = "calendars"
        bad["plan_sha256"] = m.digest(
            {k: v for k, v in bad.items() if k != "plan_sha256"}
        )
        _write(close, bad)
        with pytest.raises(ValueError):
            m.apply_forward_recovery(host, close)
        assert host.calls == []
    else:
        m.apply_forward_recovery(host, close)
        attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
        receipt = json.loads((attempt / "receipt.json").read_text())
        receipt["recovery_started"] = True
        _write(attempt / "receipt.json", receipt)
        with pytest.raises(ValueError):
            m.freeze_forward_recovery(
                host, path, predecessor_recovery_plan=c_path, feed_close_plan=close
            )


def unknown_close_case(tmp_path):
    from app.runtime_identity import RuntimeIdentityError

    host, path, c_path, attempts = feed_halt_case(tmp_path)
    frozen, close = close_plan(host, path, c_path, tmp_path)
    original_stop = host.stop_parked_feed
    proofs = []

    def failed(source, audit, budget, record):
        proofs.append(original_stop(source, audit, budget, record))
        raise RuntimeIdentityError("SERVICE_IDENTITY_INVALID")

    host.stop_parked_feed = failed
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        m.apply_forward_recovery(host, close)
    host.confirm_feed_close_unknown = lambda *args: deepcopy(proofs[0])
    host.calls.clear()
    return host, path, c_path, frozen, close, attempts


def test_readonly_confirmation_preserves_unknown_and_unblocks_only_its_exact_closure(
    tmp_path,
):
    host, path, c_path, frozen, close, attempts = unknown_close_case(tmp_path)
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    state = (attempt / "state.json").read_bytes()
    originals = {p: (p / "state.json").read_bytes() for p in attempts}
    result = m.confirm_unknown_feed_close(host, close)
    assert result["status"] == "feed_closed_confirmed"
    assert host.calls == []
    assert (attempt / "state.json").read_bytes() == state
    assert not (attempt / "receipt.json").exists()
    assert all((p / "state.json").read_bytes() == raw for p, raw in originals.items())
    confirmation = (attempt / "feed-close-confirmation.json").read_bytes()
    assert (
        m.confirm_unknown_feed_close(host, close)["status"] == "feed_closed_confirmed"
    )
    assert (attempt / "feed-close-confirmation.json").read_bytes() == confirmation
    resume = m.freeze_forward_recovery(
        host, path, predecessor_recovery_plan=c_path, feed_close_plan=close
    )
    assert "confirmation_bytes_sha256" in resume["audit"]["feed_close"]["attempt"]


@pytest.mark.parametrize(
    "wrong", ["extra_unknown", "extra_effect", "false_exit", "confirmation_drift"]
)
def test_readonly_confirmation_never_grants_a_generic_unknown_exception(
    tmp_path, wrong
):
    host, path, c_path, frozen, close, _ = unknown_close_case(tmp_path)
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    if wrong == "extra_unknown":
        p = attempt.parent / ("e" * 64)
        p.mkdir(mode=0o700)
        _write(p / "state.json", {"phase": "outcome_unknown"})
    elif wrong == "extra_effect":
        state = json.loads((attempt / "state.json").read_text())
        state["effects"]["consumers"] = {}
        _write(attempt / "state.json", state)
    elif wrong == "false_exit":
        actual = host.confirm_feed_close_unknown
        host.confirm_feed_close_unknown = lambda *args: {
            **actual(*args),
            "observed_pids_exited": False,
        }
    else:
        m.confirm_unknown_feed_close(host, close)
        p = attempt / "feed-close-confirmation.json"
        value = json.loads(p.read_text())
        value["source_close_attempt"]["state_bytes_sha256"] = "0" * 64
        _write(p, value)
    with pytest.raises(ValueError):
        m.confirm_unknown_feed_close(host, close)
    assert host.calls == []


def test_shutdown_observation_collects_pid_without_treating_exiting_as_ready(
    tmp_path, monkeypatch
):
    import app.runtime_identity as identities
    from app.runtime_bindings import authorized_program_arguments
    from tests.test_runtime_cohort_forward_recovery import fixture

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    binding = m.registry(source["new"]).services["market-feed"]
    arguments = "\n".join(authorized_program_arguments(binding, current.home))
    text = f"""gui/501/{binding.label} = {{
state = exiting
pid = 101
working directory = {binding.root}
arguments = {{
{arguments}
}}
environment = {{
GUIYI_PROJECT_ROOT => {binding.root}
GUIYI_RUNTIME_COMMIT => {binding.commit}
GUIYI_RUNTIME_TAG => {binding.tag}
GUIYI_RUNTIME_GENERATION => {binding.generation}
}}
}}"""
    monkeypatch.setattr(
        identities, "read_launchd_service", lambda *args, **kwargs: text
    )
    monkeypatch.setattr(
        identities, "read_command", lambda *args, **kwargs: "101 1\n202 101"
    )
    assert current._observed_feed_pids(source, [101]) == [101, 202]


@pytest.mark.parametrize(
    "wrong", [None, "label_present", "busy_lock", "frontier_drift", "owner_drift"]
)
def test_native_unknown_confirmation_is_fresh_readback_without_any_launch(
    tmp_path, monkeypatch, wrong
):
    current, source, audit, calls, recorded = native_stop_case(tmp_path, monkeypatch)
    audit["new_protected"] = {}
    current._old_exited = lambda *args: "f" * 64
    current.definition_absent = lambda binding: wrong != "label_present"
    expected = {"market-feed": {"phase": "absent", "generation": 29}}
    current._parked_owners = lambda *args, **kwargs: (
        {} if wrong == "owner_drift" else expected
    )
    if wrong == "busy_lock":
        monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: False)
    if wrong == "frontier_drift":
        current._feed_frontiers = lambda *args: {"changed": True}
    plan = {"audit": audit}
    state = {"effects": {"feed_stop": {"observed_pids": [101]}}}
    if wrong:
        with pytest.raises(ValueError):
            current.confirm_feed_close_unknown(source, plan, state, lambda: None)
    else:
        proof = current.confirm_feed_close_unknown(source, plan, state, lambda: None)
        assert m._valid_feed_close(proof, audit["feed_close"])
    assert calls == [] and recorded == []
