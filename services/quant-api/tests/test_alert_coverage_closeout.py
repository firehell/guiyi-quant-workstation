from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.alerts.coverage_closeout import propose_closeout, merge_closeout, digest
from app.alerts.registry import SUBING_THS_ALERT_RULE_CODE
from app.market_data.market_read_service import (
    MarketReadWindowNotDue,
    MarketReadWindowError,
)

NOW = datetime(2026, 11, 1, 14, tzinfo=UTC)
IDENTITY = {
    "runtime_root": "/tested/release",
    "runtime_commit": "a" * 40,
    "runtime_generation": 54,
}
ROUTE = SUBING_THS_ALERT_RULE_CODE + ":jm:1w"


def original():
    return dict(
        state="evaluation_failed",
        contract=None,
        trading_day="2026-10-29",
        last_evaluated_bar_at=None,
        last_success_at=None,
        error_type="evaluation_failed",
        input_error_code=None,
        previous_unresolved=None,
        last_warming_bar_at=None,
        warming_observation_id=None,
        warming_runtime_generation=None,
        warming_attempts=[],
    )


def evidence(symbol="jm"):
    return dict(
        symbol=symbol,
        trading_day="2026-10-29",
        owner_contract="JM2701",
        calendar=[[f"2026-10-{i}", i < 31] for i in range(26, 32)]
        + [["2026-11-01", False]],
        sessions=[["2026-10-29T01:00:00+00:00", "2026-10-29T07:00:00+00:00"]],
        cutoff="2026-10-29T07:00:00+00:00",
    )


def reader(error="not_due"):
    def latest(query, **kwargs):
        if error == "not_due":
            raise MarketReadWindowNotDue(
                "MARKET_READ_WEEK_NOT_COMPLETED", evidence=evidence(query.symbol)
            )
        if error == "missing":
            raise MarketReadWindowError("TRADING_CALENDAR_MISSING")
        if error == "unknown":
            raise RuntimeError("UNKNOWN")
        return object()

    return SimpleNamespace(latest_subing_quality_window=latest)


def proposal():
    expected = {ROUTE: original()}
    return expected, propose_closeout(expected, reader(), now=NOW, identity=IDENTITY)


def test_archive_preserves_original_and_is_idempotent():
    expected, resolutions = proposal()
    before = deepcopy(expected)
    remaining, archive = merge_closeout(
        expected, resolutions, {"schema_version": 1, "resolutions": {}}
    )
    assert remaining == {} and expected == before
    assert len(archive["resolutions"]) == 1
    assert next(iter(archive["resolutions"].values()))["original"] == before[ROUTE]
    assert merge_closeout(expected, resolutions, archive) == (remaining, archive)


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract", "JM2701"),
        ("last_success_at", "2026-10-29T07:00:00+00:00"),
        ("input_error_code", "TRADING_CALENDAR_MISSING"),
        ("previous_unresolved", "2026-10-28"),
        ("error_type", "evaluation_input_invalid"),
        ("trading_day", "2026-11-01"),
    ],
)
def test_never_closes_actual_or_ambiguous_errors(field, value):
    row = original()
    row[field] = value
    assert propose_closeout({ROUTE: row}, reader(), now=NOW, identity=IDENTITY) == {}


@pytest.mark.parametrize("outcome", ["missing", "completed"])
def test_missing_authority_or_due_week_is_not_closable(outcome):
    assert (
        propose_closeout(
            {ROUTE: original()}, reader(outcome), now=NOW, identity=IDENTITY
        )
        == {}
    )


def test_unknown_error_is_not_swallowed():
    with pytest.raises(RuntimeError, match="UNKNOWN"):
        propose_closeout(
            {ROUTE: original()}, reader("unknown"), now=NOW, identity=IDENTITY
        )


def test_other_rule_or_frequency_is_not_closed():
    assert (
        propose_closeout(
            {ROUTE.replace(":1w", ":1d"): original()},
            reader(),
            now=NOW,
            identity=IDENTITY,
        )
        == {}
    )


@pytest.mark.parametrize(
    "corruption", ["calendar", "hash", "sessions", "identity", "old_archive", "stale"]
)
def test_corrupt_or_stale_proof_fails_closed(corruption):
    expected, resolutions = proposal()
    item = resolutions[ROUTE]
    archive = {"schema_version": 1, "resolutions": {}}
    if corruption == "calendar":
        item["input_evidence"]["calendar"][3][1] = False
        item["input_evidence_sha256"] = digest(item["input_evidence"])
    elif corruption == "hash":
        item["input_evidence_sha256"] = "b" * 64
    elif corruption == "sessions":
        item["input_evidence"]["sessions"] = []
        item["input_evidence_sha256"] = digest(item["input_evidence"])
    elif corruption == "identity":
        item["runtime_identity"]["runtime_generation"] = 0
    elif corruption == "old_archive":
        archive["resolutions"] = {"bad": {}}
    elif corruption == "stale":
        expected[ROUTE] = {**original(), "contract": "JM2701"}
    with pytest.raises(RuntimeError, match="ALERT_COVERAGE_CLOSEOUT_"):
        merge_closeout(expected, resolutions, archive)


def test_real_redis_cas_archive_and_owner_fence():
    import os
    import json
    from uuid import uuid4
    from redis import Redis, WatchError
    from app.alerts.composition import RedisAlertHeartbeatStore

    if os.environ.get("GUIYI_TEST_REDIS_PORT") != "16389":
        pytest.skip("dedicated ephemeral Redis required")
    client = Redis(host="127.0.0.1", port=16389, db=15)
    prefix = "test:closeout:" + uuid4().hex

    class Store(RedisAlertHeartbeatStore):
        _UNRESOLVED_KEY = prefix + ":unresolved"
        _CLOSEOUT_KEY = prefix + ":archive"

    store = Store(client)
    expected, resolutions = proposal()
    try:
        store.write_unresolved(expected)

        def lost_owner():
            raise RuntimeError("OWNER_LOST")

        with pytest.raises(RuntimeError, match="OWNER_LOST"):
            store.close_not_due(expected, resolutions, assert_owned=lost_owner)
        assert store.read_unresolved() == expected
        assert client.get(store._CLOSEOUT_KEY) is None

        def concurrent_write():
            client.set(
                store._UNRESOLVED_KEY,
                json.dumps({"schema_version": 2, "unresolved": {}}),
            )

        with pytest.raises(WatchError):
            store.close_not_due(expected, resolutions, assert_owned=concurrent_write)
        assert client.get(store._CLOSEOUT_KEY) is None
        with pytest.raises(RuntimeError, match="STALE"):
            store.close_not_due(expected, resolutions, assert_owned=lambda: None)
        store.write_unresolved(expected)
        assert (
            store.close_not_due(expected, resolutions, assert_owned=lambda: None) == {}
        )
        assert store.read_unresolved() == {}
        archive = json.loads(client.get(store._CLOSEOUT_KEY))
        assert len(archive["resolutions"]) == 1
        assert (
            next(iter(archive["resolutions"].values()))["original"] == expected[ROUTE]
        )
        store.write_unresolved(expected)
        assert (
            store.close_not_due(expected, resolutions, assert_owned=lambda: None) == {}
        )
        assert json.loads(client.get(store._CLOSEOUT_KEY)) == archive
    finally:
        client.delete(store._UNRESOLVED_KEY, store._CLOSEOUT_KEY)
        client.close()


@pytest.mark.parametrize(
    "held,write_fails", [(True, False), (False, False), (True, True)]
)
def test_owner_startup_updates_cache_only_after_confirmed_atomic_write(
    monkeypatch, held, write_fails
):
    from contextlib import nullcontext
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.alerts.runtime import AlertRuntime
    import app.alerts.runtime as module

    expected, resolutions = proposal()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(module, "runtime_heartbeat_identity", lambda: dict(IDENTITY))

    def write(actual, proposed, *, assert_owned, replacements=None):
        assert actual == expected and set(proposed) == set(resolutions)
        assert_owned()
        if write_fails:
            raise RuntimeError("UNKNOWN_COMMIT")
        return {}

    source = reader()
    source.coverage_closeout_guard = lambda: nullcontext(held)
    runtime = AlertRuntime(
        session_factory=lambda: Session(engine),
        market_read_factory=lambda session: source,
        sender=object(),
        operational_products=("jm",),
        taxonomy={},
        heartbeat_store=SimpleNamespace(close_not_due=write),
        clock=lambda: NOW,
    )
    runtime._unresolved_coverage = deepcopy(expected)
    runtime._coverage_progress = {
        (SUBING_THS_ALERT_RULE_CODE, "jm", "1w"): deepcopy(expected[ROUTE])
    }
    if write_fails:
        with pytest.raises(RuntimeError, match="UNKNOWN_COMMIT"):
            runtime._close_not_due_coverage()
    else:
        runtime._close_not_due_coverage()
    assert runtime._coverage_closeout_pending is (not held)
    assert bool(runtime._unresolved_coverage) == (not held or write_fails)
    assert bool(runtime._coverage_progress) == (not held or write_fails)
    engine.dispose()


@pytest.mark.parametrize("kind", ["contract_symbol", "session_day", "warming_record"])
def test_independent_proof_validation_rejects_cross_identity(kind):
    expected, resolutions = proposal()
    item = resolutions[ROUTE]
    if kind == "contract_symbol":
        item["input_evidence"]["owner_contract"] = "RB2701"
    elif kind == "session_day":
        item["input_evidence"]["sessions"] = [
            ["2026-10-28T01:00:00+00:00", "2026-10-28T07:00:00+00:00"]
        ]
        item["input_evidence"]["cutoff"] = "2026-10-28T07:00:00+00:00"
    else:
        item["original"]["warming_attempts"] = [{"unknown": True}]
    item["input_evidence_sha256"] = digest(item["input_evidence"])
    with pytest.raises(RuntimeError, match="ALERT_COVERAGE_CLOSEOUT_INVALID"):
        merge_closeout(expected, resolutions, {"schema_version": 1, "resolutions": {}})


def test_busy_deployment_defers_until_owner_heartbeat_can_obtain_guard(monkeypatch):
    from contextlib import nullcontext
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.alerts.runtime import AlertRuntime
    import app.alerts.runtime as module

    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(module, "runtime_heartbeat_identity", lambda: dict(IDENTITY))
    source = reader()
    held = iter([False, True])
    source.coverage_closeout_guard = lambda: nullcontext(next(held))
    writes = []

    def write(expected, resolutions, *, assert_owned, replacements=None):
        assert_owned()
        writes.append(resolutions)
        return {}

    runtime = AlertRuntime(
        session_factory=lambda: Session(engine),
        market_read_factory=lambda session: source,
        sender=object(),
        operational_products=("jm",),
        taxonomy={},
        heartbeat_store=SimpleNamespace(close_not_due=write),
        clock=lambda: NOW,
    )
    runtime._unresolved_coverage = {ROUTE: original()}
    runtime._close_not_due_coverage()
    assert runtime._coverage_closeout_pending and not writes
    runtime._close_not_due_coverage()
    assert not runtime._coverage_closeout_pending and len(writes) == 1
    assert runtime._unresolved_coverage == {}
    engine.dispose()


@pytest.mark.parametrize(
    "error_type",
    [None, "evaluation_warming_up", "evaluation_input_invalid", "evaluation_failed"],
)
def test_legacy_busy_progress_is_preserved_and_real_failure_survives_restart(
    monkeypatch, error_type
):
    from contextlib import nullcontext
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.alerts.runtime import AlertRuntime
    import app.alerts.runtime as module

    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(module, "runtime_heartbeat_identity", lambda: dict(IDENTITY))
    source = reader()
    held = iter([False, True])
    source.coverage_closeout_guard = lambda: nullcontext(next(held))
    persisted = {ROUTE: original()}
    archives = {"schema_version": 1, "resolutions": {}}

    def write(expected, resolutions, *, assert_owned, replacements=None):
        nonlocal persisted, archives
        assert_owned()
        persisted, archives = merge_closeout(
            expected, resolutions, archives, replacements=replacements
        )
        return persisted

    def factory():
        return Session(engine)

    runtime = AlertRuntime(
        session_factory=factory,
        market_read_factory=lambda s: source,
        sender=object(),
        operational_products=("jm",),
        taxonomy={},
        heartbeat_store=SimpleNamespace(close_not_due=write),
        clock=lambda: NOW,
    )
    runtime._unresolved_coverage = deepcopy(persisted)
    runtime._coverage_progress = {(SUBING_THS_ALERT_RULE_CODE, "jm", "1w"): original()}
    runtime._close_not_due_coverage()
    assert runtime._coverage_closeout_pending
    runtime._record_rule_result(
        SUBING_THS_ALERT_RULE_CODE,
        evaluated_bar_at=datetime(2026, 10, 30, 7, tzinfo=UTC)
        if error_type is None
        else None,
        at=NOW,
        event_created=False,
        error_type=error_type,
        input_error_code="TRADING_SESSION_MISSING"
        if error_type == "evaluation_input_invalid"
        else None,
        coverage_identity=("jm", "1w", "JM2701", date(2026, 10, 30)),
    )
    # Explicit legacy snapshot: the v64 producer persisted only the first failure.
    # The new producer has separate real-Redis crash/restart coverage below.
    runtime._unresolved_coverage = deepcopy(persisted)
    runtime._close_not_due_coverage()
    current = runtime._coverage_progress[(SUBING_THS_ALERT_RULE_CODE, "jm", "1w")]
    assert current["trading_day"] == "2026-10-30"
    assert current["previous_unresolved"] is None
    assert current["error_type"] == error_type
    assert next(iter(archives["resolutions"].values()))["original"] == original()
    is_failure = error_type in {"evaluation_input_invalid", "evaluation_failed"}
    assert bool(persisted) is is_failure
    restored = AlertRuntime(
        session_factory=factory,
        market_read_factory=lambda s: source,
        sender=object(),
        operational_products=("jm",),
        taxonomy={},
        heartbeat_store=SimpleNamespace(read_unresolved=lambda: persisted),
    )
    restored._restore_unresolved_coverage()
    assert bool(restored._unresolved_coverage) is is_failure
    if is_failure:
        assert restored._unresolved_coverage[ROUTE]["trading_day"] == "2026-10-30"
        assert restored._unresolved_coverage[ROUTE]["error_type"] == error_type
    engine.dispose()


@pytest.mark.parametrize("later_error", [None, "evaluation_warming_up"])
@pytest.mark.parametrize("unknown_commit", [False, True])
def test_legacy_intervening_failure_remains_durable_after_later_success_or_warming(
    monkeypatch, later_error, unknown_commit
):
    from contextlib import nullcontext
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.alerts.runtime import AlertRuntime
    import app.alerts.runtime as module

    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(module, "runtime_heartbeat_identity", lambda: dict(IDENTITY))
    source = reader()
    held = iter([False, True])
    source.coverage_closeout_guard = lambda: nullcontext(next(held))
    persisted = {ROUTE: original()}
    archive = {"schema_version": 1, "resolutions": {}}

    def write(expected, resolutions, *, assert_owned, replacements=None):
        nonlocal persisted, archive
        assert_owned()
        remaining, saved = merge_closeout(
            expected, resolutions, archive, replacements=replacements
        )
        if unknown_commit:
            raise RuntimeError("UNKNOWN_COMMIT")
        persisted, archive = remaining, saved
        return persisted

    def factory():
        return Session(engine)

    runtime = AlertRuntime(
        session_factory=factory,
        market_read_factory=lambda s: source,
        sender=object(),
        operational_products=("jm",),
        taxonomy={},
        heartbeat_store=SimpleNamespace(close_not_due=write),
        clock=lambda: NOW,
    )
    runtime._unresolved_coverage = deepcopy(persisted)
    runtime._coverage_progress = {(SUBING_THS_ALERT_RULE_CODE, "jm", "1w"): original()}
    runtime._close_not_due_coverage()
    runtime._record_rule_result(
        SUBING_THS_ALERT_RULE_CODE,
        evaluated_bar_at=None,
        at=NOW,
        event_created=False,
        error_type="evaluation_input_invalid",
        input_error_code="TRADING_SESSION_MISSING",
        coverage_identity=("jm", "1w", "JM2701", date(2026, 10, 30)),
    )
    runtime._record_rule_result(
        SUBING_THS_ALERT_RULE_CODE,
        evaluated_bar_at=datetime(2026, 10, 31, 7, tzinfo=UTC)
        if later_error is None
        else None,
        at=NOW,
        event_created=False,
        error_type=later_error,
        coverage_identity=("jm", "1w", "JM2701", date(2026, 10, 31)),
    )
    # Exercise old-v64 cache/projection divergence independently of the new writer.
    runtime._unresolved_coverage = deepcopy(persisted)
    before_progress = deepcopy(runtime._coverage_progress)
    before_status = deepcopy(runtime._current_runtime_status())
    if unknown_commit:
        with pytest.raises(RuntimeError, match="UNKNOWN_COMMIT"):
            runtime._close_not_due_coverage()
        assert runtime._unresolved_coverage == {ROUTE: original()}
    else:
        runtime._close_not_due_coverage()
        assert persisted[ROUTE]["input_error_code"] == "ALERT_PREVIOUS_UNRESOLVED"
        assert persisted[ROUTE]["previous_unresolved"] == "2026-10-30"
        restored = AlertRuntime(
            session_factory=factory,
            market_read_factory=lambda s: source,
            sender=object(),
            operational_products=("jm",),
            taxonomy={},
            heartbeat_store=SimpleNamespace(read_unresolved=lambda: persisted),
        )
        restored._restore_unresolved_coverage()
        assert restored._unresolved_coverage == persisted
        assert propose_closeout(persisted, source, now=NOW, identity=IDENTITY) == {}
    assert runtime._coverage_progress == before_progress
    assert runtime._current_runtime_status() == before_status
    engine.dispose()


@pytest.mark.parametrize("unknown_after_commit", [False, True])
def test_real_failure_before_closeout_is_durable_across_restart(
    monkeypatch, unknown_after_commit
):
    import os
    import json
    from uuid import uuid4
    from datetime import date
    from redis import Redis
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from contextlib import nullcontext
    from app.alerts.runtime import AlertRuntime
    from app.alerts.composition import RedisAlertHeartbeatStore
    import app.alerts.runtime as module

    if os.environ.get("GUIYI_TEST_REDIS_PORT") != "16389":
        pytest.skip("dedicated ephemeral Redis required")
    c = Redis(host="127.0.0.1", port=16389, db=15)
    prefix = "test:closeout-restart:" + uuid4().hex

    class Store(RedisAlertHeartbeatStore):
        _UNRESOLVED_KEY = prefix + ":unresolved"
        _CLOSEOUT_KEY = prefix + ":closed"
        _HISTORY_KEY = prefix + ":history"

    store = Store(c)
    store.write_unresolved({ROUTE: original()})
    engine = create_engine("sqlite+pysqlite:///:memory:")
    source = reader()
    source.coverage_closeout_guard = lambda: nullcontext(True)
    monkeypatch.setattr(module, "runtime_heartbeat_identity", lambda: dict(IDENTITY))

    def runtime():
        result = AlertRuntime(
            session_factory=lambda: Session(engine),
            market_read_factory=lambda s: source,
            sender=object(),
            operational_products=("jm",),
            taxonomy={},
            heartbeat_store=store,
            clock=lambda: NOW,
        )
        result._restore_unresolved_coverage()
        return result

    try:
        owner = runtime()
        original_write = store.replace_unresolved

        def replacement(value, **kwargs):
            original_write(value, **kwargs)
            if unknown_after_commit:
                raise RuntimeError("UNKNOWN_COMMIT")

        monkeypatch.setattr(store, "replace_unresolved", replacement)

        def fail():
            owner._record_rule_result(
                SUBING_THS_ALERT_RULE_CODE,
                evaluated_bar_at=None,
                at=NOW,
                event_created=False,
                error_type="evaluation_input_invalid",
                input_error_code="TRADING_SESSION_MISSING",
                coverage_identity=("jm", "1w", "JM2701", date(2026, 10, 30)),
            )

        if unknown_after_commit:
            with pytest.raises(RuntimeError, match="UNKNOWN_COMMIT"):
                fail()
            assert owner._unresolved_coverage[ROUTE] == original()
        else:
            fail()
        fresh = runtime()
        fresh._close_not_due_coverage()
        retained = fresh._unresolved_coverage[ROUTE]
        assert retained["input_error_code"] == "TRADING_SESSION_MISSING"
        assert retained["trading_day"] == "2026-10-30"
        assert retained["previous_unresolved"] == "2026-10-29"
        history = json.loads(c.get(store._HISTORY_KEY))
        assert next(iter(history["originals"].values())) == {
            "route": ROUTE,
            "original": original(),
        }
        assert c.get(store._CLOSEOUT_KEY) is None
    finally:
        c.delete(store._UNRESOLVED_KEY, store._CLOSEOUT_KEY, store._HISTORY_KEY)
        c.close()
        engine.dispose()


def test_unacknowledged_observations_defer_closeout_without_touching_projection():
    from app.alerts.runtime import AlertRuntime

    runtime = AlertRuntime(
        session_factory=lambda: pytest.fail("must wait for pending input"),
        market_read_factory=lambda s: None,
        sender=object(),
        operational_products=("jm",),
        taxonomy={},
        heartbeat_store=SimpleNamespace(
            close_not_due=lambda *a, **k: pytest.fail("must not write")
        ),
        message_source=SimpleNamespace(
            coverage_snapshot=lambda **kwargs: {"cursor": "0-0", "tail": "1-0"}
        ),
    )
    runtime._unresolved_coverage = {ROUTE: original()}
    runtime._close_not_due_coverage()
    assert runtime._coverage_closeout_pending
    assert runtime._unresolved_coverage == {ROUTE: original()}
