from contextlib import contextmanager, nullcontext
from datetime import date, datetime
from types import SimpleNamespace
import json
import pytest

from app.market_data.after_market import AfterMarketResult, AfterMarketUpdater
from app.market_data.late_provider_recovery import (
    schedule_failure,
    run_scheduled,
    recovery_health,
)
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import SHANGHAI

DAY = date(2026, 9, 30)
PRODUCTS = load_operational_products()


def clock(day, hour=19, minute=5):
    return datetime(2026, 10, day, hour, minute, tzinfo=SHANGHAI)


def scheduled(tmp_path, *, archive_scope=None):
    path = tmp_path / "late.json"
    schedule_failure(
        path,
        AfterMarketResult("failed", DAY, 2, "RQDATA_NOT_READY"),
        PRODUCTS,
        datetime(2026, 9, 30, 18, 5, tzinfo=SHANGHAI),
        archive_scope=archive_scope,
    )
    return path


def runner(path, current, ready=lambda day: False, manager=None, **kw):
    return run_scheduled(
        manager,
        path=path,
        now=lambda: current,
        ready=ready,
        invalidate=lambda: None,
        verify_identity=lambda: None,
        live_store=SimpleNamespace(
            publish_state=lambda data: None, cleanup_trading_day=lambda day: None
        ),
        **kw,
    )


@pytest.fixture
def formal_late(tmp_path, monkeypatch):
    from app.market_data import late_provider_recovery as late

    path = tmp_path / "late-provider-recovery-status.json"
    old_day = DAY.isoformat()
    mapping = {product: product.upper() + "2612" for product in PRODUCTS}
    live = {DAY: mapping, date(2026, 10, 8): mapping}
    events = []
    manager = SimpleNamespace(
        catalog=SimpleNamespace(main_map=lambda symbol, *_: [SimpleNamespace(contract=mapping[symbol])]),
        publication_evidence=[],
    )

    def daily_recovery(request, **options):
        assert request.products == PRODUCTS and request.through == DAY
        events.append("apply" if request.apply else "plan")
        if request.apply:
            assert options["expected_plan_sha256"] == "a" * 64
            options["before_daily_apply"](0, 2)
            options["before_apply"]()
        return SimpleNamespace(plan_sha256="a" * 64, maintenance=SimpleNamespace(status="noop", applied=0))

    def cleanup(day):
        state = json.loads(path.read_bytes())["runs"][old_day]
        assert state["state"] == "claimed" and state["checks"] == 1
        assert state["stage"] == "live_cleanup" and state["live_evidence"]["cleanup_verified"] is False
        events.append(("cleanup", day))
        live.pop(day, None)

    @contextmanager
    def archive_readback(products, day, publications):
        assert products == PRODUCTS and day == DAY and publications == []
        events.append("independent_readback")
        yield {product: "b" * 64 for product in products}
        events.append("readback_released")

    manager.daily_recovery = daily_recovery
    monkeypatch.setattr(late, "_sync_archive_metadata", lambda *_: events.append("metadata"))
    updater = AfterMarketUpdater(
        manager=manager, rqdata=None, status_path=tmp_path / "after-market-status.json",
        sleep=lambda _: pytest.fail("late recovery must not sleep"), notification_transport=None,
        now=lambda: clock(2), archive_root=tmp_path / "archive", archive_readback=archive_readback,
        archive_binding=lambda: "formal-bound-fixture",
        live_store=SimpleNamespace(
            subscriptions=live.get, publish_state=lambda _: events.append("invalidation"),
            cleanup_trading_day=cleanup,
            cleanup_readback=lambda day: {"remaining_bar_keys": 0, "subscription_present": day in live},
        ),
    )
    updater.status_path.write_text(json.dumps({
        "schema_version": 3, "current_run": None,
        "last_run": {
            "status": "failed", "trading_day": old_day, "products": list(PRODUCTS),
            "error_code": "RQDATA_NOT_READY", "attempts": 2,
            "started_at": "2026-09-30T18:05:00+08:00", "finished_at": "2026-09-30T19:06:00+08:00",
        },
    }))
    schedule_failure(path, AfterMarketResult("failed", DAY, 2, "RQDATA_NOT_READY"), PRODUCTS,
                     datetime(2026, 9, 30, 18, 5, tzinfo=SHANGHAI),
                     archive_scope=lambda: updater.archive_scope_proof(PRODUCTS, DAY))
    return path, updater, events, live


def test_formal_late_retains_same_receipt_contract_and_preserves_natural_status(formal_late, monkeypatch):
    from app import runtime_bindings
    from app.market_data import market_archive
    from app.market_data.composition import build_closed_cleanup_evidence

    path, updater, events, live = formal_late
    natural = updater.status_path.read_bytes()
    result = runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                    ready=lambda day: events.append(("ready", day)) or True)
    assert result["status"] == "passed"
    assert events == [
        ("ready", DAY), "metadata", "plan", "apply", "independent_readback",
        "invalidation", ("cleanup", DAY), "readback_released",
    ]
    assert updater.status_path.read_bytes() == natural
    assert tuple(live) == (date(2026, 10, 8),)
    receipt = market_archive.current_retained_receipt(updater.archive_root, now=clock(2))
    assert receipt.trading_day == DAY and set(receipt.revisions) == set(PRODUCTS)
    evidence = market_archive.retained_cleanup_receipt(updater.archive_root, day=DAY, products=PRODUCTS, now=clock(2))
    assert evidence["cleanup_verified"]
    row = json.loads(path.read_bytes())["runs"][DAY.isoformat()]
    assert row["market_archive_receipt_sha256"] == receipt.identity
    binding = SimpleNamespace(enabled=True, generation=7)
    monkeypatch.setattr(runtime_bindings, "resolve_service_binding", lambda _: binding)
    monkeypatch.setattr(market_archive, "formal_archive_root", lambda: updater.archive_root)
    closed = build_closed_cleanup_evidence(updater.live_store, PRODUCTS, formal_tick=True)
    assert closed(DAY, clock(2))["after_market_generation"] == 7
    assert closed(date(2026, 10, 8), clock(2)) is None
    assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                  ready=lambda _: pytest.fail("duplicate recovery"))["status"] == "not_due"


@pytest.mark.parametrize("reason", ["scope", "readback", "count"])
def test_formal_late_preserves_live_when_archive_cannot_be_verified(formal_late, reason):
    path, updater, events, live = formal_late
    if reason == "scope":
        live[DAY] = {}
    elif reason == "readback":
        # An incomplete or changed committed scope must fail before cleanup.
        @contextmanager
        def bad_readback(*_):
            yield {}
        updater.archive_readback = bad_readback
    else:
        updater.manager.publication_evidence = [{
            "dataset": ["contract", PRODUCTS[0], PRODUCTS[0].upper() + "2612", "1m"],
            "year": 2026, "month": 9, "file_name": "part." + "a" * 64 + ".parquet",
            "provenance": {"version": 1, "input_source": "historical_provider", "input_sha256": "b" * 64},
        }]

    assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                  ready=lambda day: events.append(("ready", day)) or True)["status"] == "failed"
    assert DAY in live and "invalidation" not in events and not updater.archive_root.exists()
    if reason == "scope":
        assert events == []
    else:
        row = json.loads(path.read_bytes())["runs"][DAY.isoformat()]
        assert row["state"] == "claimed" and row["stage"] == "readback" and row["checks"] == 1
    assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                  ready=lambda _: pytest.fail("claim consumed"))["status"] == {
                      "scope": "not_due", "readback": "failed", "count": "commit_outcome_unknown",
                  }[reason]


@pytest.mark.parametrize("edge", ["metadata_commit", "apply_commit", "process_exit"])
def test_formal_late_unknown_commit_parks_both_routes(formal_late, edge, monkeypatch):
    from app.market_data import late_provider_recovery as late
    from app.market_data.current_day_metadata_recovery import CurrentDayMetadataRecoveryError
    from app.market_data.storage import StorageError

    path, updater, events, live = formal_late
    original = updater.manager.daily_recovery

    def fail_apply(request, **options):
        if request.apply:
            if edge == "process_exit":
                raise KeyboardInterrupt
            raise StorageError("COMMIT_OUTCOME_UNKNOWN")
        return original(request, **options)

    def fail_metadata(_manager, _products, _day, _verify, checkpoint):
        checkpoint("metadata_apply")
        raise CurrentDayMetadataRecoveryError("COMMIT_OUTCOME_UNKNOWN")

    if edge == "metadata_commit":
        monkeypatch.setattr(late, "_sync_archive_metadata", fail_metadata)
    else:
        updater.manager.daily_recovery = fail_apply
    if edge == "process_exit":
        with pytest.raises(KeyboardInterrupt):
            runner(path, clock(2), manager=updater.manager, formal_archive=updater, ready=lambda _: True)
    else:
        assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                      ready=lambda _: True)["status"] == "commit_outcome_unknown"
    original_status = updater.status_path.read_bytes()
    assert updater.run().error_code == "COMMIT_OUTCOME_UNKNOWN"
    assert updater.status_path.read_bytes() == original_status
    assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                  ready=lambda _: pytest.fail("unresolved commit"))["status"] == "commit_outcome_unknown"
    assert DAY in live and "independent_readback" not in events and not updater.archive_root.exists()


@pytest.mark.parametrize("binding_drift", [False, True])
def test_expired_formal_subscription_requires_original_scope_proof(formal_late, binding_drift):
    path, updater, events, live = formal_late
    del live[DAY]
    if binding_drift:
        updater.archive_binding = lambda: "changed-formal-binding"
    result = runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                    ready=lambda day: events.append(("ready", day)) or True)
    assert result["status"] == ("failed" if binding_drift else "passed")
    assert (("cleanup", DAY) in events) is not binding_drift
    assert date(2026, 10, 8) in live
    if binding_drift:
        assert events == []


def test_formal_does_not_consume_legacy_pending_claim(formal_late, tmp_path):
    _, updater, events, _ = formal_late
    path = scheduled(tmp_path)
    initial = path.read_bytes()
    assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                  ready=lambda _: pytest.fail("legacy source"))["status"] == "archive_source_changed"
    assert path.read_bytes() == initial and events == []


@pytest.mark.parametrize("next_entry", ["late", "natural"])
def test_formal_late_resumes_only_proved_cleanup_after_process_exit(formal_late, next_entry, monkeypatch):
    from app.market_data.market_archive import current_retained_receipt

    path, updater, events, live = formal_late
    cleanup = updater.live_store.cleanup_trading_day

    def interrupted_cleanup(day):
        cleanup(day)
        raise KeyboardInterrupt

    updater.live_store.cleanup_trading_day = interrupted_cleanup
    with pytest.raises(KeyboardInterrupt):
        runner(path, clock(2), manager=updater.manager, formal_archive=updater, ready=lambda _: True)
    assert DAY not in live and not updater.archive_root.exists()
    updater.live_store.cleanup_trading_day = lambda _: pytest.fail("repeated delete")
    previous_natural = updater.status_path.read_bytes()
    if next_entry == "late":
        assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                      ready=lambda _: pytest.fail("repeat provider"))["status"] == "passed"
    else:
        def next_natural():
            assert current_retained_receipt(updater.archive_root, now=clock(2)).trading_day == DAY
            assert updater._live_evidence is None and updater._historical_publications is None
            return AfterMarketResult("skipped", clock(2).date(), 0, "NON_TRADING_DAY")

        monkeypatch.setattr(updater, "_run_guarded", next_natural)
        assert updater.run().status == "skipped"
    assert updater.status_path.read_bytes() == previous_natural
    assert events.count("independent_readback") == 2 and events.count("apply") == 1
    row = json.loads(path.read_bytes())["runs"][DAY.isoformat()]
    assert row["state"] == "passed" and row["checks"] == 1 and "historical_publications" not in row


@pytest.mark.parametrize("formal_tick", [False, True])
def test_scheduled_runtime_keeps_source_and_status_owner_bound(tmp_path, monkeypatch, formal_tick):
    from app import redis_connections, runtime_bindings, runtime_identity
    from app.core import env
    from app.market_data import after_market, captured_recovery_runtime, late_provider_recovery as late
    from app.market_data import live_recovery_guard, market_foundation_scope

    monkeypatch.delenv("GUIYI_MARKET_SOURCE", raising=False)
    if formal_tick:
        monkeypatch.setenv("GUIYI_MARKET_SOURCE", "rqdata_tick")
    tags = {"GUIYI_RUNTIME_COMMIT": "a" * 40, "GUIYI_RUNTIME_TAG": "fixture", "GUIYI_RUNTIME_GENERATION": "1"}
    for key, value in tags.items():
        monkeypatch.setenv(key, value)
    root = tmp_path / "late-worker-release"
    archive_owner = tmp_path / "archive-release"
    monkeypatch.setattr(env, "PROJECT_ROOT", root)
    bindings = {
        service: SimpleNamespace(
            root=str(archive_owner if service == "after-market" else root), label=service, enabled=True,
            generation=1, commit=tags["GUIYI_RUNTIME_COMMIT"], tag=tags["GUIYI_RUNTIME_TAG"],
        )
        for service in ("api", "live", "after-market", "late-provider-recovery", "market-feed")
    }
    registry = SimpleNamespace(services=bindings)
    monkeypatch.setattr(runtime_bindings, "read_bindings", lambda: registry)
    monkeypatch.setattr(runtime_bindings, "verify_release", lambda *_: None)
    monkeypatch.setattr(runtime_bindings, "authorized_program_arguments", lambda *_: ["/bin/bash"])
    monkeypatch.setattr(runtime_identity, "read_launchd_service", lambda *_, **__: "\tprogram = /bin/bash\n")
    monkeypatch.setattr(runtime_identity, "launchd_arguments", lambda *_: ["/bin/bash"])
    monkeypatch.setattr(runtime_identity, "launchd_environments", lambda *_: [tags])
    monkeypatch.setattr(captured_recovery_runtime, "_verify_loaded_service", lambda *_, **__: None)
    monkeypatch.setattr(live_recovery_guard, "after_market_recovery_guard", lambda **_: nullcontext())
    connection = SimpleNamespace(mget=lambda *_: [b"formal-tick-marker", None])
    monkeypatch.setattr(redis_connections, "get_redis_connection", lambda: nullcontext(connection))
    monkeypatch.setattr(market_foundation_scope, "require_formal_tick_binding", lambda redis, *_: (
        None if redis is connection else pytest.fail("binding Redis changed")
    ))
    status_path = archive_owner / ".run" / "after-market-status.json"
    manager = SimpleNamespace(catalog=SimpleNamespace(
        canonical_root=tmp_path, session=SimpleNamespace(get_bind=lambda: SimpleNamespace(url="fixture")),
    ))
    updater = SimpleNamespace(
        status_path=status_path, research_update=None, live_store=object(),
        _invalidate_market_home_projection=lambda: None,
    )

    def build(_manager, *, failure_notification, late_recovery):
        assert not failure_notification and late_recovery is formal_tick
        return updater

    def run(_manager, *, path, formal_archive, **_):
        assert formal_tick and path.parent == status_path.parent and formal_archive is updater
        return {"status": "not_due"}

    monkeypatch.setattr(after_market, "build_after_market_updater", build)
    monkeypatch.setattr(late, "run_scheduled", run)
    if formal_tick:
        assert late.run_runtime_scheduled(manager)["status"] == "not_due"
    else:
        with pytest.raises(ValueError, match="MARKET_BAR_WRITER_NAMESPACE_CONFLICT"):
            late.run_runtime_scheduled(manager)


def test_due_two_calendar_days_in_holiday_and_only_once(tmp_path):
    path = scheduled(tmp_path)
    calls = []
    assert runner(path, clock(2, 19, 4))["status"] == "not_due"
    assert (
        runner(path, clock(2), ready=lambda day: calls.append(day) or False)["status"]
        == "failed"
    )
    runner(path, clock(2), ready=lambda day: calls.append(day) or True)
    assert calls == [DAY]
    assert json.loads(path.read_text())["runs"][DAY.isoformat()]["checks"] == 1


def test_same_original_failure_does_not_reschedule(tmp_path):
    path = scheduled(tmp_path)
    runner(path, clock(2))
    original = path.read_bytes()
    schedule_failure(
        path,
        AfterMarketResult("failed", DAY, 2, "RQDATA_NOT_READY"),
        PRODUCTS,
        clock(2),
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "error",
    ["UPDATE_FAILED", "COMMIT_OUTCOME_UNKNOWN", "HISTORICAL_MAINTENANCE_REQUIRED"],
)
def test_unknown_or_partial_failures_are_never_eligible(tmp_path, error):
    path = tmp_path / "late.json"
    schedule_failure(
        path, AfterMarketResult("failed", DAY, 2, error), PRODUCTS, clock(2)
    )
    assert not path.exists()


def test_expired_trigger_never_calls_provider(tmp_path):
    path = scheduled(tmp_path)
    assert (
        runner(path, clock(3), ready=lambda day: pytest.fail("late trigger"))["status"]
        == "expired"
    )
    assert recovery_health(path, clock(3))["status"] == "degraded"


def test_identity_check_cannot_extend_claim_window(tmp_path):
    path = scheduled(tmp_path)
    times = iter((clock(2, 20, 4), clock(2, 20, 5)))
    result = run_scheduled(
        None, path=path, now=lambda: next(times), ready=lambda _: pytest.fail("expired claim"),
        invalidate=lambda: None, verify_identity=lambda: None, live_store=None,
    )
    assert result["status"] == "expired"
    assert json.loads(path.read_bytes())["runs"][DAY.isoformat()]["checks"] == 0


def test_crash_after_claim_never_retries(tmp_path):
    path = scheduled(tmp_path)

    def crash(day):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        runner(path, clock(2), ready=crash)
    assert (
        runner(path, clock(2), ready=lambda day: pytest.fail("repeated"))["status"]
        == "not_due"
    )
    assert recovery_health(path, clock(2))["status"] == "degraded"


def test_exact_recovery_hash_and_fresh_readback(tmp_path):
    path = scheduled(tmp_path)
    calls = []

    class Manager:
        catalog = SimpleNamespace(
            acquire_maintenance_lock=lambda: SimpleNamespace(
                release=lambda: calls.append("release")
            )
        )
        metadata = SimpleNamespace(
            synchronize_current_day=lambda products, day: calls.append((products, day))
        )

        def daily_recovery(self, request, **kw):
            calls.append((request, kw))
            return SimpleNamespace(
                plan_sha256="a" * 64,
                target_windows=(),
                maintenance=SimpleNamespace(status="passed"),
            )

    assert (
        runner(path, clock(2), ready=lambda day: True, manager=Manager())["status"]
        == "passed"
    )
    requests = [
        item for item in calls if isinstance(item, tuple) and hasattr(item[0], "apply")
    ]
    assert [item[0].apply for item in requests] == [False, True, False]
    assert all(
        item[0].through == DAY and item[0].products == PRODUCTS for item in requests
    )
    assert requests[1][1]["expected_plan_sha256"] == "a" * 64


def test_scope_drift_fails_before_provider(tmp_path):
    path = scheduled(tmp_path)
    payload = json.loads(path.read_text())
    payload["runs"][DAY.isoformat()]["products"] = ["rs"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="STATE_INVALID"):
        runner(path, clock(2), ready=lambda day: pytest.fail("scope drift"))


@pytest.mark.parametrize("stage", ["metadata", "apply", "readback"])
def test_failure_after_claim_never_repeats_recovery(tmp_path, stage):
    path = scheduled(tmp_path)
    calls = []

    def sync(*args):
        if stage == "metadata":
            raise RuntimeError("private provider details")

    class Manager:
        catalog = SimpleNamespace(
            acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None)
        )
        metadata = SimpleNamespace(synchronize_current_day=sync)

        def daily_recovery(self, request, **kw):
            calls.append(request.apply)
            if request.apply and stage == "apply":
                raise RuntimeError("COMMIT_OUTCOME_UNKNOWN")
            remaining = ("missing",) if len(calls) == 3 and stage == "readback" else ()
            return SimpleNamespace(
                plan_sha256="a" * 64,
                target_windows=remaining,
                maintenance=SimpleNamespace(status="passed"),
            )

    assert (
        runner(path, clock(2), ready=lambda day: True, manager=Manager())["status"]
        == "failed"
    )
    before = list(calls)
    runner(path, clock(2), ready=lambda day: pytest.fail("retry"), manager=Manager())
    assert calls == before
    assert "private" not in path.read_text()


@pytest.mark.parametrize(
    "kind", ["symlink", "dangling", "hardlink", "directory", "writable"]
)
def test_unsafe_owned_state_rejected_without_provider_or_replacement(tmp_path, kind):
    import os

    path = tmp_path / "late.json"
    other = tmp_path / "other.json"
    other.write_text('{"schema_version":1,"runs":{}}')
    if kind == "symlink":
        path.symlink_to(other)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "missing")
    elif kind == "hardlink":
        os.link(other, path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_text(other.read_text())
        path.chmod(0o666)
    before = other.read_bytes()
    with pytest.raises((ValueError, OSError)):
        runner(path, clock(2), ready=lambda day: pytest.fail("unsafe state"))
    assert other.read_bytes() == before


def test_claim_directory_fsync_failure_blocks_provider(tmp_path, monkeypatch):
    import os
    import stat

    path = scheduled(tmp_path)
    real = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("fixture failure")
        real(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(OSError):
        runner(path, clock(2), ready=lambda day: pytest.fail("non durable claim"))


@pytest.mark.parametrize("has_proof", [True, False])
def test_formal_late_readback_claim_survives_interruption(formal_late, has_proof):
    from app.market_data.late_provider_recovery import prepare_natural_archive

    path, updater, events, live = formal_late
    finish = updater.finish_late_archive

    def stop_before_readback(*_args, **_options):
        raise KeyboardInterrupt

    updater.finish_late_archive = stop_before_readback
    with pytest.raises(KeyboardInterrupt):
        runner(path, clock(2), manager=updater.manager, formal_archive=updater, ready=lambda _: True)

    payload = json.loads(path.read_text())
    row = payload["runs"][DAY.isoformat()]
    assert row["stage"] == "readback" and row["historical_publications"] == []
    updater.finish_late_archive = finish
    updater.manager.daily_recovery = lambda *_args, **_options: pytest.fail("repeated provider or Catalog write")
    if not has_proof:
        del row["historical_publications"]
        path.write_text(json.dumps(payload))
        assert prepare_natural_archive(updater) == "COMMIT_OUTCOME_UNKNOWN"
        assert runner(path, clock(2), manager=updater.manager, formal_archive=updater,
                      ready=lambda _: pytest.fail("repeated provider"))["status"] == "commit_outcome_unknown"
        assert DAY in live
    else:
        assert prepare_natural_archive(updater) is None
        verified = json.loads(path.read_text())["runs"][DAY.isoformat()]
        assert verified["state"] == "passed" and verified["checks"] == 1
        assert verified["market_archive_receipt_sha256"]
        assert DAY not in live
    assert events.count("apply") == 1
