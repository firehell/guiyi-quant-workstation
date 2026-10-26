"""Fault injection against the real Mac cohort adapter, without host mutations."""

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from types import SimpleNamespace

import pytest

from app.runtime_bindings import BindingRegistry, CONTRACTS, ServiceBinding
from app.runtime_cohort import CohortError
from app.runtime_cohort_host import CohortHost

NOW = datetime(2026, 10, 26, 1, tzinfo=UTC)


def binding(tmp_path, service="market-feed", **kwargs):
    return ServiceBinding(
        service,
        str(tmp_path),
        "v1.16.5",
        "a" * 40,
        29,
        True,
        {key: "b" * 64 for key in CONTRACTS},
        **kwargs,
    )


def closed_proof():
    return {
        "status": "CLOSED_CLEANED",
        "trading_day": "2026-10-23",
        "cleanup_verified": True,
        "cleanup_checked_at": (NOW - timedelta(days=2)).isoformat(),
        "source_commit": "c" * 40,
        "evidence_kind": "retained",
        "after_market_generation": 28,
        "remaining_bar_keys": 0,
        "subscription_present": False,
        "consumer_count": 3,
        "source_cursor": "100-0",
        "pending_count": 0,
        "natural_bar_verified": False,
    }


def heartbeat(b):
    return {
        "generated_at": NOW.isoformat(),
        "runtime_root": b.root,
        "runtime_commit": b.commit,
        "runtime_tag": b.tag,
        "runtime_generation": b.generation,
        "available": True,
        "operational_count": 1,
        "subscribed_count": 0,
        "input_pending_count": 0,
        "input_failure": None,
        "phase_by_product": {"jm": "CLOSED"},
        "closed_cleaned": closed_proof(),
    }


def awaiting_host(tmp_path, monkeypatch, *, ready=True, hb=None, owner_proof=None):
    from app import runtime_cohort_host as module
    from app import redis_connections

    b = binding(tmp_path)
    host = object.__new__(CohortHost)
    host.deadline = 10
    host.now = lambda: NOW
    host.session_proof = lambda: {
        "mode": "closed_idle",
        "products": 1,
        "phases": {"jm": {"phase": "CLOSED"}},
    }
    state = {
        "phase": "active",
        "generation": b.generation,
        "pid": 123,
        "at": NOW.isoformat(),
        "ready": ready,
        "proof": {"closed_cleaned": closed_proof()}
        if owner_proof is None
        else owner_proof,
    }
    monkeypatch.setattr(module, "read_service_state", lambda _: state)
    monkeypatch.setattr(module, "owner_process_matches", lambda *_: True)
    ticks = iter((0, 0, 2))
    monkeypatch.setattr(module, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module, "sleep", lambda _: None)
    calls = []
    raw = json.dumps(heartbeat(b) if hb is None else hb).encode()

    class Redis:
        def get(self, key):
            calls.append(key)
            return raw

        def close(self):
            calls.append("close")

    monkeypatch.setattr(redis_connections, "get_redis_connection", Redis)
    plan = {"new": asdict(BindingRegistry(1, {"market-feed": b}))}
    return host, plan, state, calls


def test_feed_ready_requires_independent_heartbeat_and_preserves_closed_idle_semantics(
    tmp_path, monkeypatch
):
    host, plan, _, calls = awaiting_host(tmp_path, monkeypatch)
    assert host._await_names(plan, ("market-feed",), {"progress": {}}, 1) == {
        "market-feed": "closed_idle"
    }
    assert calls == ["live:feed:heartbeat", "close"]


def test_feed_not_ready_cannot_use_an_older_successful_heartbeat(tmp_path, monkeypatch):
    host, plan, _, calls = awaiting_host(tmp_path, monkeypatch, ready=False)
    with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
        host._await_names(plan, ("market-feed",), {"progress": {}}, 1)
    assert calls == ["live:feed:heartbeat", "close"]


@pytest.mark.parametrize("ready", (True, False))
@pytest.mark.parametrize(
    "field,value",
    [
        ("available", False),
        ("input_failure", "OBSERVATION_COMMIT_UNKNOWN"),
        ("metadata_preparation_error", "RQDATA_NOT_READY"),
        ("input_pending_count", 1),
        ("subscribed_count", 1),
        ("runtime_commit", "d" * 40),
        ("runtime_generation", 28),
        ("runtime_root", "/another/root"),
        ("runtime_tag", "v1.16.4"),
        ("generated_at", (NOW - timedelta(seconds=31)).isoformat()),
        ("generated_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("generated_at", "invalid"),
        ("generated_at", NOW.replace(tzinfo=None).isoformat()),
        ("phase_by_product", {"jm": "UNKNOWN"}),
        ("closed_cleaned", {"status": "CLOSED_CLEANED"}),
        ("input_pending_count", False),
        ("subscribed_count", False),
    ],
)
def test_feed_poll_failure_or_wrong_identity_never_passes_even_with_ready_owner(
    tmp_path, monkeypatch, ready, field, value
):
    hb = heartbeat(binding(tmp_path))
    hb[field] = value
    host, plan, _, _ = awaiting_host(tmp_path, monkeypatch, ready=ready, hb=hb)
    with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
        host._await_names(plan, ("market-feed",), {"progress": {}}, 1)


def test_feed_closed_cleaned_proof_must_match_the_successful_owner_poll(
    tmp_path, monkeypatch
):
    host, plan, state, _ = awaiting_host(tmp_path, monkeypatch)
    state["proof"]["closed_cleaned"]["source_cursor"] = "99-0"
    with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
        host._await_names(plan, ("market-feed",), {"progress": {}}, 1)


def test_feed_healthy_normal_closed_day_does_not_require_cleanup_of_a_live_snapshot(
    tmp_path, monkeypatch
):
    hb = heartbeat(binding(tmp_path))
    hb["closed_cleaned"] = None
    host, plan, _, _ = awaiting_host(
        tmp_path, monkeypatch, hb=hb, owner_proof={"cycle_ok": True}
    )
    assert host._await_names(plan, ("market-feed",), {"progress": {}}, 1) == {
        "market-feed": "closed_idle"
    }


def test_installed_distinguishes_loaded_idle_from_absent_definition(
    tmp_path, monkeypatch
):
    from app.runtime_fault_recovery_host import FaultRecoveryHost
    from app import runtime_identity

    b = binding(tmp_path, "after-market")
    reg = BindingRegistry(1, {"after-market": b})
    monkeypatch.setattr(
        FaultRecoveryHost,
        "installed",
        lambda *_: {"after-market": {"loaded_pid": None}},
    )
    host = object.__new__(CohortHost)
    host.loaded = lambda *_args, **_kwargs: None
    monkeypatch.setattr(
        runtime_identity,
        "read_launchd_service",
        lambda *_args, **_kwargs: "state = waiting",
    )
    assert host.installed(reg)["after-market"]["loaded"] is True
    monkeypatch.setattr(
        runtime_identity, "read_launchd_service", lambda *_args, **_kwargs: None
    )
    assert host.installed(reg)["after-market"]["loaded"] is False


def test_restore_old_does_not_bootstrap_previously_absent_enabled_calendar(
    tmp_path, monkeypatch
):
    from app import runtime_cohort_host as module

    b = binding(tmp_path, "after-market")
    reg = BindingRegistry(1, {"after-market": b})
    plan = {
        "old": asdict(reg),
        "new": asdict(reg),
        "installed": {
            "after-market": {"plist_hex": b"original".hex(), "loaded": False}
        },
    }
    host = object.__new__(CohortHost)
    host.bindings = lambda: reg
    host._replace_plist = lambda *_: None
    host.path = lambda _: tmp_path / "after-market.plist"
    host.definition_absent = lambda _: True
    host.assert_installed = lambda *_: None
    calls = []
    host.launch = lambda *args, **_: calls.append(args)
    host.start = lambda _: pytest.fail("previously absent must stay absent")
    monkeypatch.setattr(module, "monotonic", lambda: 0)
    monkeypatch.setattr(module, "CONTINUOUS", ())
    host.restore_old(plan)
    assert not any(args[0] == "bootstrap" for args in calls)


@pytest.mark.parametrize("day_known", (True, False))
@pytest.mark.parametrize("registered_offset", (-1, 0))
def test_session_proof_requires_matching_registered_day_before_consumers_start(
    tmp_path, monkeypatch, day_known, registered_offset
):
    from contextlib import nullcontext
    from app import redis_connections
    from app.db import session as database, readonly
    from app.market_data import (
        composition,
        market_phase,
        operational_universe,
        observation_stream,
    )
    from app.market_data.aggregation import SessionWindow
    from app.market_data.market_phase import MarketPhase, ProductMarketPhase

    products = tuple(f"p{i}" for i in range(60))
    next_start = NOW + timedelta(hours=2)

    class Resolver:
        def __init__(self, _):
            pass

        def resolve(self, symbol, at):
            if at == next_start:
                return ProductMarketPhase(
                    symbol,
                    MarketPhase.TRADING,
                    NOW.date(),
                    SessionWindow(next_start, next_start + timedelta(hours=1)),
                    None,
                )
            return ProductMarketPhase(
                symbol,
                MarketPhase.CLOSED,
                NOW.date() if day_known else None,
                None,
                next_start,
            )

    monkeypatch.setattr(database, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(
        readonly, "readonly_transaction", lambda *_args, **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        composition,
        "build_market_feed_service",
        lambda _: SimpleNamespace(quiescent=lambda _: True),
    )
    monkeypatch.setattr(market_phase, "MarketPhaseResolver", Resolver)
    monkeypatch.setattr(
        operational_universe, "load_operational_products", lambda: products
    )

    class Redis:
        def close(self):
            pass

    monkeypatch.setattr(redis_connections, "get_redis_connection", Redis)
    calls = []

    def source(_redis, *, kind):
        assert kind == "source"
        return SimpleNamespace(
            registered_day=lambda consumer: (
                calls.append(consumer) or NOW.date() + timedelta(days=registered_offset)
            )
        )

    monkeypatch.setattr(observation_stream, "ObservationStream", source)
    host = object.__new__(CohortHost)
    host.now = lambda: NOW
    if registered_offset:
        with pytest.raises(CohortError, match="DAY_INITIALIZATION_REQUIRED"):
            host.session_proof()
    else:
        assert host.session_proof()["registered_trading_day"] == NOW.date().isoformat()
    assert calls == ["live"]


def test_live_not_ready_empty_proof_never_becomes_closed_idle(tmp_path, monkeypatch):
    from app import runtime_cohort_host as module

    b = binding(tmp_path, "live")
    host = object.__new__(CohortHost)
    host.deadline = 10
    host.now = lambda: NOW
    host.session_proof = lambda: {"mode": "closed_idle"}
    monkeypatch.setattr(
        module,
        "read_service_state",
        lambda _: {
            "phase": "active",
            "generation": b.generation,
            "pid": 123,
            "at": NOW.isoformat(),
            "ready": False,
            "proof": {},
        },
    )
    monkeypatch.setattr(module, "owner_process_matches", lambda *_: True)
    ticks = iter((0, 0, 2))
    monkeypatch.setattr(module, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module, "sleep", lambda _: None)
    with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
        host._await_names(
            {"new": asdict(BindingRegistry(1, {"live": b}))},
            ("live",),
            {"progress": {}},
            1,
        )


def preserve_host(tmp_path, monkeypatch):
    from app.runtime_contracts import SERVICES
    from app.market_data import operational_universe, late_provider_recovery

    old_root, new_root = tmp_path / "release-v1.16.4", tmp_path / "release-v1.16.5"
    for root in (old_root, new_root):
        (root / ".run").mkdir(parents=True)
    old = BindingRegistry(1, {name: binding(old_root, name) for name in SERVICES})
    new = BindingRegistry(1, {name: binding(new_root, name) for name in SERVICES})
    directory = tmp_path / "control"
    directory.mkdir(mode=0o700)
    host = object.__new__(CohortHost)
    host.directory = directory
    host.now = lambda: NOW
    marker = old_root / ".run/market-runtime-enabled"
    marker.write_bytes(b"enabled\n")
    protected = {"files": {str(marker): sha256(marker.read_bytes()).hexdigest()}}
    host.protected = lambda _: protected
    plan = {"old": asdict(old), "new": asdict(new), "protected": protected}
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    monkeypatch.setattr(
        operational_universe, "load_operational_products", lambda: ("jm",)
    )
    # The recovery reader binds this authority at module import. Patch its local
    # alias too, so the isolated one-product fixture does not depend on whether
    # another suite imported that module before this test.
    monkeypatch.setattr(late_provider_recovery, "load_operational_products", lambda: ("jm",))
    return host, plan, attempt, old_root, new_root


def test_preserve_indexes_private_originals_without_promoting_weekly_or_moving_stable_state(
    tmp_path, monkeypatch
):
    import stat

    host, plan, attempt, old, new = preserve_host(tmp_path, monkeypatch)
    weekly = old / ".run/weekly-audit-status.json"
    weekly.write_bytes(b'{"original_natural_status":true}')
    stable = host.directory / "market-day-metadata-preparation.json"
    stable.write_bytes(b'{"old_control":"inflight"}')
    refresh = host.directory / "newow-historical-refresh-state.json"
    refresh.write_bytes(b'{"old_control":"blocked"}')
    payload = {
        "schema_version": 1,
        "runs": {
            "2026-10-23": {
                "products": ["jm"],
                "due_at": "2026-10-25T19:05:00+08:00",
                "state": "claimed",
                "error_code": "RQDATA_NOT_READY",
                "checks": 1,
            }
        },
    }
    late = old / ".run/late-provider-recovery-status.json"
    late.write_text(json.dumps(payload))
    result = host.preserve(plan, attempt)
    assert not (new / ".run/weekly-audit-status.json").exists()
    assert (
        new / ".run/late-provider-recovery-status.json"
    ).read_bytes() == late.read_bytes()
    assert stable.read_bytes() == b'{"old_control":"inflight"}'
    assert refresh.read_bytes() == b'{"old_control":"blocked"}'
    assert result["stable_state_migrated"] is False
    raw_index = (attempt / "originals/index.json").read_bytes()
    assert sha256(raw_index).hexdigest() == result["original_index_sha256"]
    rows = {row["source"]: row for row in json.loads(raw_index)["files"]}
    for path in (weekly, stable, refresh, late):
        row = rows[str(path)]
        copy = attempt / "originals" / row["file"]
        assert copy.read_bytes() == path.read_bytes()
        assert sha256(copy.read_bytes()).hexdigest() == row["sha256"]
        assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert stat.S_IMODE((attempt / "originals").stat().st_mode) == 0o700


def test_preserve_stable_state_busy_fails_without_copying_or_resetting_it(
    tmp_path, monkeypatch
):
    import fcntl

    host, plan, attempt, _, _ = preserve_host(tmp_path, monkeypatch)
    path = host.directory / "market-day-metadata-preparation.json"
    path.write_bytes(b"original")
    with path.with_suffix(".lock").open("w") as stream:
        os.chmod(stream.name, 0o600)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(CohortError, match="STABLE_STATE_BUSY"):
            host.preserve(plan, attempt)
    assert path.read_bytes() == b"original"


def test_candidate_source_roots_reject_cross_checkout_imports(tmp_path):
    app = tmp_path / "services/quant-api/app/__init__.py"
    core = tmp_path / "packages/quant-core/guiyi_quant/__init__.py"
    for path in (app, core):
        path.parent.mkdir(parents=True)
        path.write_text("")
    value = {
        "source_roots": {
            "app": str(app),
            "core": str(core),
            "project_root": str(tmp_path),
            "version": "1.16.5",
        }
    }
    assert CohortHost._candidate_sources(value, tmp_path, "v1.16.5")
    for field in ("app", "core", "project_root", "version"):
        wrong = deepcopy(value)
        wrong["source_roots"][field] = (
            "/other/checkout" if field != "version" else "1.16.4"
        )
        assert not CohortHost._candidate_sources(wrong, tmp_path, "v1.16.5")


def test_web_prewarm_missing_vite_blocks_before_any_node_execution(
    tmp_path, monkeypatch
):
    from app import runtime_cohort_host as module

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("missing Vite must be detected first"),
    )
    with pytest.raises(CohortError, match="WEB_DEPENDENCY_MISSING"):
        CohortHost._verify_web_dependencies(tmp_path)


def test_preserve_fsyncs_originals_and_its_index_directory(tmp_path, monkeypatch):
    import stat

    host, plan, attempt, _, _ = preserve_host(tmp_path, monkeypatch)
    flushed = []
    fsync = os.fsync

    def record(fd):
        item = os.fstat(fd)
        flushed.append((item.st_ino, stat.S_ISDIR(item.st_mode)))
        fsync(fd)

    monkeypatch.setattr(os, "fsync", record)
    host.preserve(plan, attempt)
    assert ((attempt / "originals").stat().st_ino, True) in flushed
    assert (attempt.stat().st_ino, True) in flushed
    assert ((attempt / "originals/index.json").stat().st_ino, False) in flushed


def test_preserve_incompatible_late_state_blocks_without_installing_it(
    tmp_path, monkeypatch
):
    host, plan, attempt, old, new = preserve_host(tmp_path, monkeypatch)
    late = old / ".run/late-provider-recovery-status.json"
    late.write_text('{"schema_version":99,"runs":{}}')
    with pytest.raises(ValueError, match="LATE_RECOVERY_STATE_INVALID"):
        host.preserve(plan, attempt)
    assert not (new / ".run/late-provider-recovery-status.json").exists()
    assert (attempt / "originals/index.json").exists()


def test_web_prewarm_executes_fixed_vite_version_check_and_rejects_failure(
    tmp_path, monkeypatch
):
    from app import runtime_cohort_host as module

    vite = tmp_path / "apps/quant-web/node_modules/vite/bin/vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text("")
    calls = []

    def execute(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(module.subprocess, "run", execute)
    with pytest.raises(CohortError, match="WEB_DEPENDENCY_INVALID"):
        CohortHost._verify_web_dependencies(tmp_path)
    assert calls[0][0] == ["/opt/homebrew/bin/node", str(vite), "--version"]
    assert calls[0][1]["timeout"] == 15


@pytest.mark.parametrize("enabled", (True, False))
def test_restore_old_restores_loaded_calendar_registration_without_enabling_disabled_business(
    tmp_path, monkeypatch, enabled
):
    from dataclasses import replace
    from app import runtime_cohort_host as module

    b = replace(binding(tmp_path, "after-market"), enabled=enabled)
    reg = BindingRegistry(1, {"after-market": b})
    plan = {
        "old": asdict(reg),
        "new": asdict(reg),
        "installed": {"after-market": {"plist_hex": b"original".hex(), "loaded": True}},
    }
    host = object.__new__(CohortHost)
    host.bindings = lambda: reg
    host._replace_plist = lambda *_: None
    host.path = lambda _: tmp_path / "after-market.plist"
    loaded = False
    host.definition_absent = lambda _: not loaded
    host.assert_installed = lambda *_: None
    calls = []

    def launch(*args, **_kwargs):
        nonlocal loaded
        calls.append(args)
        if args[0] == "bootstrap":
            loaded = True

    def start(_binding):
        nonlocal loaded
        calls.append(("start-enabled",))
        loaded = True

    host.launch = launch
    host.start = start
    monkeypatch.setattr(module, "monotonic", lambda: 0)
    monkeypatch.setattr(module, "CONTINUOUS", ())
    host.restore_old(plan)
    if enabled:
        assert ("start-enabled",) in calls
    else:
        assert ("start-enabled",) not in calls
        assert not any(args[0] == "enable" for args in calls)
        assert any(args[0] == "bootstrap" for args in calls)
        assert any(args[0] == "disable" for args in calls)


@pytest.mark.parametrize("wrong_core", (True, False))
def test_prewarm_rejects_wrong_import_identity_even_when_candidate_reports_ready(
    tmp_path, monkeypatch, wrong_core
):
    import plistlib
    from dataclasses import replace
    from app.runtime_contracts import SERVICES
    from app import runtime_cohort_host as module

    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    marker = old_root / ".run/alert-runtime-enabled"
    marker.parent.mkdir(mode=0o700)
    marker.write_text("enabled\n")
    marker.chmod(0o600)
    old = BindingRegistry(
        1,
        {
            name: replace(
                binding(old_root, name), enabled=name in {"api", "web", "alert"}
            )
            for name in SERVICES
        },
    )
    new = BindingRegistry(
        1,
        {
            name: replace(
                binding(new_root, name), enabled=name in {"api", "web", "alert"}
            )
            for name in SERVICES
        },
    )
    plan = {
        "old": asdict(old),
        "new": asdict(new),
        "installed": {
            name: {"plist_hex": plistlib.dumps({"EnvironmentVariables": {}}).hex()}
            for name in ("api", "web", "alert")
        },
    }
    app, core = (
        new_root / "services/quant-api/app/__init__.py",
        new_root / "packages/quant-core/guiyi_quant/__init__.py",
    )
    for path in (app, core):
        path.parent.mkdir(parents=True)
        path.write_text("")
    source_roots = {
        "app": str(app),
        "core": str(core) if not wrong_core else str(old_root / "core.py"),
        "project_root": str(new_root),
        "version": "1.16.5",
    }
    host = object.__new__(CohortHost)
    host.directory = tmp_path / "control"
    events = []
    host._verify_web_dependencies = lambda root: events.append(
        ("web-dependencies", root)
    )

    def warmup(arguments, **kwargs):
        events.append(("warmup", arguments[-1]))
        assert kwargs["env"]["GUIYI_PROJECT_ROOT"] == str(new_root)
        assert kwargs["timeout"] == (600 if arguments[-1] == "alert" else 120)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "ready",
                    "service": arguments[-1],
                    "proof": {"calculated": 1},
                    "source_roots": source_roots,
                }
            ),
        )

    monkeypatch.setattr(module.subprocess, "run", warmup)
    if wrong_core:
        with pytest.raises(CohortError, match="CANDIDATE_WARMUP_FAILED"):
            host.prewarm(plan)
    else:
        assert set(host.prewarm(plan)) == {"api", "web", "alert"}
    assert events[0] == ("web-dependencies", new_root)


@pytest.mark.parametrize("was_loaded", (True, False))
def test_restore_old_rejects_calendar_loaded_readback_mismatch(
    tmp_path, monkeypatch, was_loaded
):
    from app import runtime_cohort_host as module

    b = binding(tmp_path, "after-market")
    reg = BindingRegistry(1, {"after-market": b})
    plan = {
        "old": asdict(reg),
        "new": asdict(reg),
        "installed": {
            "after-market": {"plist_hex": b"original".hex(), "loaded": was_loaded}
        },
    }
    host = object.__new__(CohortHost)
    host.bindings = lambda: reg
    host._replace_plist = lambda *_: None
    host.path = lambda _: tmp_path / "after-market.plist"
    absent = iter((True, True if was_loaded else False))
    host.definition_absent = lambda _: next(absent)
    host.assert_installed = lambda *_: None
    host.launch = lambda *_args, **_kwargs: None
    host.start = lambda _: None
    monkeypatch.setattr(module, "monotonic", lambda: 0)
    monkeypatch.setattr(module, "CONTINUOUS", ())
    with pytest.raises(CohortError, match="OLD_RESTORE_CALENDAR_UNPROVEN"):
        host.restore_old(plan)


@pytest.mark.parametrize(
    "name",
    [
        "reference-continuity-generation8.json",
        "deployment-outcome.json",
        "weekly-audit.scheduled-update.json",
    ],
)
def test_preserved_journals_accept_existing_evidence_above_config_limit(tmp_path, name):
    host = object.__new__(CohortHost)
    host.directory = tmp_path
    path = tmp_path / name
    payload = b"x" * (1475785)
    path.write_bytes(payload)
    path.chmod(0o600)
    assert host.bytes(path) == payload


def test_preserved_journal_limit_does_not_weaken_path_or_file_security(tmp_path):
    host = object.__new__(CohortHost)
    host.directory = tmp_path
    large = tmp_path / "reference-generation8.json"
    large.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    large.chmod(0o600)
    with pytest.raises(ValueError):
        host.bytes(large)
    config = tmp_path / "project.env"
    config.write_bytes(b"x" * 1475785)
    config.chmod(0o600)
    with pytest.raises(ValueError):
        host.bytes(config)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    outside = other / "reference-generation8.json"
    outside.write_bytes(b"x" * 1475785)
    outside.chmod(0o600)
    with pytest.raises(ValueError):
        host.bytes(outside)
    large.unlink()
    large.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        host.bytes(large)

def test_preserve_refresh_control_uses_its_existing_bounded_reader_limit(tmp_path):
    host = object.__new__(CohortHost)
    host.directory = tmp_path
    path = tmp_path / 'newow-historical-refresh-state.json'
    payload = b'x' * 2_274_736
    path.write_bytes(payload)
    path.chmod(0o600)
    assert host.bytes(path) == payload


def test_refresh_control_larger_limit_is_exact_path_only_and_still_secure(tmp_path, monkeypatch):
    from app.reference_trading import historical_refresh
    monkeypatch.setattr(historical_refresh, 'MAX_REFRESH_STATE_BYTES', 2_000_000)
    host = object.__new__(CohortHost)
    host.directory = tmp_path
    path = tmp_path / 'newow-historical-refresh-state.json'
    path.write_bytes(b'x' * 2_000_001)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        host.bytes(path)
    outside = tmp_path / 'other'
    outside.mkdir(mode=0o700)
    other = outside / path.name
    other.write_bytes(b'x' * 1_100_000)
    other.chmod(0o600)
    with pytest.raises(ValueError):
        host.bytes(other)
    path.unlink()
    path.symlink_to(other)
    with pytest.raises((ValueError, OSError)):
        host.bytes(path)


def test_native_commit_checks_deadline_after_all_schema_and_session_readbacks(tmp_path, monkeypatch):
    from app import runtime_cohort_host as module
    b = binding(tmp_path)
    old = BindingRegistry(1, {"market-feed": b})
    plan = {"old": asdict(old), "new": asdict(old), "registry_sha256": "c" * 64,
            "created_at": NOW.isoformat(), "expires_at": (NOW + timedelta(minutes=15)).isoformat()}
    host = object.__new__(CohortHost)
    host.now = lambda: NOW
    host.deadline = 600
    clock = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    host.check_schema_compatibility = lambda plan: None
    host.bindings = lambda: old
    host.binding_hash = lambda: "c" * 64
    host.definition_absent = lambda binding: True
    host.verify_release = lambda *args: None
    def slow_session():
        clock[0] = 601.0
    host.session_proof = slow_session
    writes = []
    monkeypatch.setattr(module, "write_bindings", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(CohortError, match="COHORT_DOWNTIME_EXCEEDED"):
        host.commit(plan)
    assert writes == []
