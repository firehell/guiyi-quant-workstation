from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from app.runtime_cohort import CohortError, apply_cohort
from app.runtime_cohort_host import CohortHost
from app.reference_trading.receiving_handover import (
    freeze_receiving_intent,
    seal_receiving_backlog,
    verify_receiving_backlog,
)
from tests.test_runtime_cohort import Host, plan as cohort_plan
from tests.reference_trading.test_receiving_handover import setup, SCHEMA, CAPACITY, DAY

NOW = datetime.now(UTC)


def native_drain(
    tmp_path, monkeypatch, *, other_backlog=None, capture_count=0, intent=True
):
    from app import runtime_cohort_host as module
    from app import redis_connections
    from app.db import session as database

    fixture = Host(tmp_path)
    plan = cohort_plan(fixture)
    protocol, journal, _ = setup(tmp_path)
    target = asdict(fixture.old.services["reference-worker"])
    # Drain binds the exact candidate target from the native plan.
    target = plan["new"]["services"]["reference-worker"]
    frozen = freeze_receiving_intent(
        protocol, journal, target=target, schema_proof=SCHEMA
    )
    if intent:
        plan["reference_receiving_handover"] = frozen
    host = object.__new__(CohortHost)
    host.deadline = 100
    host.now = lambda: fixture.now()
    host.loaded = lambda *args, **kwargs: 123
    host.request_drain = lambda name, generation: "drain-" + name
    host.session_proof = lambda: {}
    monkeypatch.setattr(module, "monotonic", lambda: 0)
    monkeypatch.setattr(
        module,
        "read_service_state",
        lambda name: {"phase": "parked", "generation": 28, "pid": 123},
    )
    monkeypatch.setattr(module, "owner_lock_available", lambda name: True)
    progress = {
        name: {DAY.isoformat(): {"cursor": "12-0", "tail": "12-0"}}
        for name in ("market-feed", "live", "alert", "reference-worker")
    }
    progress["reference-worker"] = frozen["baseline"]
    if other_backlog:
        progress[other_backlog] = {DAY.isoformat(): {"cursor": "10-0", "tail": "12-0"}}
    monkeypatch.setattr(module, "observation_progress", lambda name: progress[name])
    feed = fixture.old.services["market-feed"]
    import json

    class Redis:
        def get(self, key):
            return json.dumps(
                {
                    "runtime_commit": feed.commit,
                    "runtime_generation": feed.generation,
                    "input_pending_count": 0,
                    "input_failure": None,
                    "subscribed_count": 0,
                    "generated_at": fixture.now().isoformat(),
                }
            )

        def close(self):
            pass

    monkeypatch.setattr(redis_connections, "get_redis_connection", Redis)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def scalar(self, statement):
            return capture_count

    monkeypatch.setattr(database, "SessionLocal", Session)

    @contextmanager
    def context(target):
        yield protocol, journal, SCHEMA, CAPACITY

    host._reference_receiving_context = context
    return host, plan, protocol, journal


def test_native_drain_accepts_only_reference_with_sealed_readonly_proof(
    tmp_path, monkeypatch
):
    host, plan, protocol, journal = native_drain(tmp_path, monkeypatch)
    raw = protocol.path.read_bytes()
    proof = host.drain(plan)
    assert proof["reference_receiving_handover"]["count"] == 2
    host.check_reference_receiving_handover(plan, proof)
    assert journal.cursor("reference", DAY) == "10-0"
    assert protocol.path.read_bytes() == raw


@pytest.mark.parametrize("other", ("market-feed", "live", "alert"))
def test_other_consumers_backlog_still_refuses_native_drain(
    tmp_path, monkeypatch, other
):
    host, plan, _, _ = native_drain(tmp_path, monkeypatch, other_backlog=other)
    with pytest.raises(CohortError, match="COHORT_OBSERVATION_BACKLOG"):
        host.drain(plan)


@pytest.mark.parametrize(
    "intent,captures,code",
    ((False, 0, "COHORT_OBSERVATION_BACKLOG"), (True, 1, "COHORT_PENDING_CAPTURE")),
)
def test_missing_intent_and_pending_capture_keep_original_gates(
    tmp_path, monkeypatch, intent, captures, code
):
    host, plan, _, _ = native_drain(
        tmp_path, monkeypatch, intent=intent, capture_count=captures
    )
    with pytest.raises(CohortError, match=code):
        host.drain(plan)


def test_target_must_explicitly_support_tracked_handover_kind(tmp_path, monkeypatch):
    from app.reference_trading import receiving_handover as module
    from app import runtime_bindings

    host = object.__new__(CohortHost)
    fixture = Host(tmp_path)
    host._reference_receiving_context = lambda target: pytest.fail(
        "legacy target must never open database"
    )
    monkeypatch.setattr(runtime_bindings, "_tracked", lambda root: {})
    assert host.freeze_reference_receiving_handover(fixture.old) is None
    monkeypatch.setattr(
        runtime_bindings, "_tracked", lambda root: {module.PATH: "a" * 40}
    )
    monkeypatch.setattr(runtime_bindings, "_git", lambda *args: "KIND='unknown'")
    assert module.target_supports_receiving_handover(tmp_path) is False
    monkeypatch.setattr(
        runtime_bindings, "_git", lambda *args: "KIND=" + repr(module.KIND)
    )
    assert module.target_supports_receiving_handover(tmp_path) is True


@pytest.mark.parametrize("fail_checkpoint", (None, 1, 2))
def test_cohort_rechecks_same_full_suffix_before_stop_and_cas(
    tmp_path, fail_checkpoint
):
    fixture = Host(tmp_path)
    protocol, journal, _ = setup(tmp_path)
    checks = []

    def freeze(new):
        fixture.target = asdict(new.services["reference-worker"])
        return freeze_receiving_intent(
            protocol, journal, target=fixture.target, schema_proof=SCHEMA
        )

    fixture.freeze_reference_receiving_handover = freeze
    frozen = cohort_plan(fixture)
    original_drain = fixture.drain

    def drain(plan):
        proof = original_drain(plan)
        proof["reference_receiving_handover"] = seal_receiving_backlog(
            protocol,
            journal,
            plan["reference_receiving_handover"],
            target=fixture.target,
            schema_proof=SCHEMA,
            progress=plan["reference_receiving_handover"]["baseline"],
            capacity=CAPACITY,
        )
        return proof

    fixture.drain = drain

    def check(plan, proof):
        checks.append(len(checks) + 1)
        assert fixture.in_guard
        if len(checks) == fail_checkpoint:
            journal.redis.rows[journal.key(DAY)][1][1]["envelope"] = journal.redis.rows[
                journal.key(DAY)
            ][1][1]["envelope"].replace("100", "101")
        try:
            verify_receiving_backlog(
                protocol,
                journal,
                plan["reference_receiving_handover"],
                proof["reference_receiving_handover"],
                target=fixture.target,
                schema_proof=SCHEMA,
                capacity=CAPACITY,
            )
        except ValueError:
            raise CohortError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None

    fixture.check_reference_receiving_handover = check
    if fail_checkpoint:
        with pytest.raises(CohortError):
            apply_cohort(fixture, frozen)
        assert "commit" not in fixture.calls and "restore_old" in fixture.calls
        if fail_checkpoint == 1:
            assert "old_exited" not in fixture.calls
    else:
        assert apply_cohort(fixture, frozen)["status"] == "switched"
        assert checks == [1, 2]
