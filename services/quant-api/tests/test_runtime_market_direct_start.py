from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import plistlib
from types import SimpleNamespace
from time import monotonic
import pytest

from app import runtime_market_direct_start as direct
from app.runtime_bindings import BindingRegistry, ServiceBinding, read_bindings, write_bindings
from app.runtime_cohort_errors import CohortError

_DAY = date(2026, 11, 30)
_CONTRACTS = {key: "b" * 64 for key in ("db", "live", "input", "formula", "reference", "launcher")}


class StartHost:
    def __init__(self, home):
        self.home = home
        self.directory = home / "Library/Application Support/GuiyiQuant"
        self.release_root = home / "release"
        self.release_root.mkdir()
        self.calls = []
        self.staged = False
        self.fail_install = False
        self.fail_start = False
        self.modify_config = False
        self.redis_writes = 0
        self.clock = datetime(2026, 11, 27, 11, tzinfo=UTC)

    def release(self, root, tag, commit, previous):
        assert (root, tag, commit) == (self.release_root, "v1.16.151", "c" * 40)
        return _CONTRACTS, ("market-foundation/v0.1.2", "d" * 40)

    def now(self):
        return self.clock

    def settings(self):
        return {}, "changed" if self.modify_config else "config"

    def authority(self, settings, root, day):
        assert root == self.release_root and day == _DAY
        return {"subscriptions": {"rb": "RB2701"}, "prior_day": "2026-11-27",
                "first_session": "2026-11-27T13:00:00+00:00"}

    def target_instance(self, settings, authority):
        return "target"

    def installation_preimage(self, new):
        return {}

    guards_for_direct_start = staticmethod(lambda *args: nullcontext())
    _private_original = staticmethod(lambda path, raw: path.write_bytes(raw))
    _sync_directory = staticmethod(lambda path: None)

    def park(self, old, new):
        assert old is None or not Path(old.services["live"].root).exists()
        self.calls.append("park")

    def stage(self, plan, settings, *, may_exist):
        self.calls.append("stage_read" if may_exist else "stage")
        if may_exist:
            assert self.staged
        else:
            assert not self.staged
            self.redis_writes += 1
            self.staged = True

    def install_new(self, new, attempt, expected):
        self.calls.append("install")
        if self.fail_install:
            raise OSError

    def assert_ready_to_bind(self, plan, new, settings):
        self.calls.append("precommit")

    def bindings(self):
        return read_bindings(home=self.home)

    def start_new(self, plan, *, verify_running_only):
        self.calls.append("verify_running" if verify_running_only else "start")
        if self.fail_start:
            raise OSError

    def verify_installed(self, new):
        self.calls.append("verify_installed")

    def read_target(self, plan, *, bound):
        return "bound" if bound else "staged" if self.staged else "empty"


@pytest.fixture
def start(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    host = StartHost(tmp_path)
    old_root = tmp_path / "missing-old-root"
    old_root.mkdir()
    previous = BindingRegistry(1, {
        name: ServiceBinding(name, str(old_root), "v1.16.141", "a" * 40, 94, True, _CONTRACTS)
        for name in ("live", "alert", "weekly-audit")
    })
    write_bindings(previous, home=tmp_path, expected_sha256=None)
    old_bytes = (host.directory / "service-bindings.json").read_bytes()
    old_root.rmdir()
    plan = direct.freeze_market_direct_start(
        host, root=host.release_root, tag="v1.16.151", commit="c" * 40, day=_DAY,
    )
    return host, plan, old_bytes


def test_direct_start_accepts_missing_old_root_and_is_idempotent(start):
    host, plan, original = start
    assert host.calls == []
    assert direct.apply_market_direct_start(host, plan) == {"status": "switched", "generation": 95}
    assert host.calls == ["park", "stage", "install", "precommit", "start"]
    assert host.bindings().services["live"].root == str(host.release_root)
    assert host.bindings().services["alert"].enabled is False
    assert host.bindings().services["weekly-audit"].enabled is True
    attempt = direct._attempt_path(host, plan)
    assert (attempt / "previous-registry.json").read_bytes() == original
    assert direct.apply_market_direct_start(host, plan)["status"] == "already_started"
    assert host.calls[-1] == "verify_installed" and host.redis_writes == 1


def test_active_session_is_explicit_and_rechecked_before_effects(start):
    host, _, _ = start
    authority = {"mode": "active_session", "subscriptions": {"rb": "RB2701"},
                 "window_end": "2026-11-27T13:00:00+00:00"}
    host.active_authority = lambda *_: authority
    plan = direct.freeze_market_direct_start(
        host, root=host.release_root, tag="v1.16.151", commit="c" * 40, day=_DAY,
        active_session=True,
    )
    assert plan["authority"]["mode"] == "active_session"
    host.active_authority = lambda *_: {**authority, "subscriptions": {"rb": "RB2705"}}
    with pytest.raises(CohortError, match="MARKET_DIRECT_START_AUTHORITY_DRIFT"):
        direct.apply_market_direct_start(host, plan)
    assert host.calls == []
    host.active_authority = lambda *_: authority
    assert direct.apply_market_direct_start(host, plan) == {"status": "switched", "generation": 95}
    assert host.calls == ["park", "stage", "install", "precommit", "start"]


def test_journal_preserving_cutover_drains_before_guard_and_does_not_reseed(start):
    host, _, _ = start
    previous_authority = host.authority({}, host.release_root, _DAY)
    host.authority = lambda *_: {**previous_authority, "retained_tick": {"archive": "confirmed"}}
    host.prepare_retained_scope = lambda *_: host.calls.append("drain-confirmed")
    host.stage = lambda *_, **kw: host.calls.append("retain-existing")
    plan = direct.freeze_market_direct_start(
        host, root=host.release_root, tag="v1.16.151", commit="c" * 40, day=_DAY,
    )
    assert direct.apply_market_direct_start(host, plan) == {"status": "switched", "generation": 95}
    assert host.calls == ["drain-confirmed", "park", "retain-existing", "install", "precommit", "start"]
    assert host.redis_writes == 0


@pytest.mark.parametrize("failure, registry, expected_phase", [
    ("fail_install", "previous", "installing"), ("fail_start", "new", "starting"),
])
def test_interrupted_direct_start_reads_back_and_resumes_without_reseeding(start, failure, registry, expected_phase):
    host, plan, _ = start
    setattr(host, failure, True)
    with pytest.raises(OSError):
        direct.apply_market_direct_start(host, plan)
    assert direct.read_market_direct_start(host, plan) == {
        "status": "readback", "phase": expected_phase, "registry": registry,
        "redis": "staged" if registry == "previous" else "bound",
    }
    with pytest.raises(CohortError, match="EXPLICIT_RESUME"):
        direct.apply_market_direct_start(host, plan)
    setattr(host, failure, False)
    assert direct.apply_market_direct_start(host, plan, resume=True)["status"] == "switched"
    assert host.redis_writes == 1


def test_config_drift_stops_before_effects(start):
    host, plan, _ = start
    host.modify_config = True
    with pytest.raises(CohortError, match="AUTHORITY_DRIFT"):
        direct.apply_market_direct_start(host, plan)
    assert host.calls == []
    assert not direct._attempt_path(host, plan).exists()


def test_post_commit_recovery_after_preopen_only_verifies_running_writers(start):
    host, plan, _ = start
    host.fail_start = True
    with pytest.raises(OSError):
        direct.apply_market_direct_start(host, plan)
    host.fail_start = False
    host.clock = datetime(2026, 11, 27, 13, 1, tzinfo=UTC)
    assert direct.apply_market_direct_start(host, plan, resume=True)["status"] == "switched"
    assert host.calls[-1] == "verify_running" and host.redis_writes == 1


def test_proven_empty_attempt_can_be_cancelled(start, monkeypatch):
    host, plan, original = start
    stage = host.stage
    def lost_before_redis(*args, **kwargs):
        raise OSError
    monkeypatch.setattr(host, "stage", lost_before_redis)
    with pytest.raises(OSError):
        direct.apply_market_direct_start(host, plan)
    assert direct.read_market_direct_start(host, plan)["redis"] == "empty"
    assert direct.cancel_uncommitted_market_direct_start(host, plan) == {"status": "cancelled", "target_retained": False}
    assert (host.directory / "service-bindings.json").read_bytes() == original
    monkeypatch.setattr(host, "stage", stage)
    host.clock = host.clock.replace(minute=1)
    fresh = direct.freeze_market_direct_start(
        host, root=host.release_root, tag="v1.16.151", commit="c" * 40, day=_DAY,
    )
    assert fresh["plan_sha256"] != plan["plan_sha256"]
    assert direct.apply_market_direct_start(host, fresh)["status"] == "switched"
    assert host.redis_writes == 1


def test_cancelled_attempt_preserves_staged_redis_and_previous_registry(start):
    host, plan, original = start
    host.fail_install = True
    with pytest.raises(OSError):
        direct.apply_market_direct_start(host, plan)
    assert direct.cancel_uncommitted_market_direct_start(host, plan) == {"status": "cancelled", "target_retained": True}
    assert host.staged and host.redis_writes == 1
    assert (host.directory / "service-bindings.json").read_bytes() == original


def test_native_plist_uses_dedicated_market_config(tmp_path):
    host = direct.MarketDirectStartHost()
    host.home = tmp_path
    host.directory = tmp_path / "Library/Application Support/GuiyiQuant"
    root = Path(direct.__file__).resolve().parents[3]
    app = ServiceBinding("api", str(root), "v1.16.151", "c" * 40, 95, True, _CONTRACTS)
    payload = plistlib.loads(host._plist(app))
    assert payload["EnvironmentVariables"]["GUIYI_RUNTIME_ENV"] == str(host.target_config)
    assert "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH" not in payload["EnvironmentVariables"]
    assert payload["WorkingDirectory"] == str(host.home)
    for name in direct.CALENDARS:
        scheduled = ServiceBinding(name, str(root), app.tag, app.commit, app.generation, True, app.contracts)
        plist = plistlib.loads(host._plist(scheduled))
        assert plist["KeepAlive"] is False and plist["RunAtLoad"] is False
        assert plist["StartCalendarInterval"]


def test_direct_warmup_uses_installed_core_and_explicit_runtime_flags(tmp_path, monkeypatch):
    from app import runtime_market_cohort_host
    from app.compute_runtime import artifact

    api = tmp_path / "services/quant-api"
    worker = api / "app/runtime_cohort.py"
    worker.parent.mkdir(parents=True)
    worker.touch()
    core = api / ".venv/lib/python3.13/site-packages/guiyi_quant"
    core.mkdir(parents=True)
    core_entry = core / "__init__.py"
    core_entry.touch()
    monkeypatch.setattr(artifact, "locked_core", lambda lock: ({}, core))
    monkeypatch.delenv("GUIYI_OBSERVATION_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("GUIYI_RUNTIME_HANDOVER_ENABLED", raising=False)
    def run(argv, *, env, **kwargs):
        assert argv[-1] == "market-direct-staged"
        assert env["GUIYI_OBSERVATION_STREAM_ENABLED"] == env["GUIYI_RUNTIME_HANDOVER_ENABLED"] == "1"
        assert env["GUIYI_MARKET_SOURCE"] == "rqdata_tick"
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "ready", "service": argv[-1], "proof": {"receipt_only": True, "binding": "verified"},
            "source_roots": {"app": str(worker), "core": str(core_entry),
                             "project_root": str(tmp_path), "version": "1.16.151"},
        }).encode())
    monkeypatch.setattr(runtime_market_cohort_host.subprocess, "run", run)
    binding = ServiceBinding("market-feed", str(tmp_path), "v1.16.151", "c" * 40, 95, True, _CONTRACTS)
    host = direct.MarketDirectStartHost()
    host.deadline = monotonic() + 60
    assert host._prove_staged_warmup(binding, {}, "verified", direct=True)["receipt_only"]


def test_native_park_rejects_unregistered_writer_or_active_owner(start, monkeypatch):
    fixture, plan, _ = start
    host = direct.MarketDirectStartHost()
    host.home = fixture.home
    old, _, _ = direct.market_start_preimage(home=host.home)
    new = direct.registry(plan["new"])
    monkeypatch.setattr(host, "_loaded_inventory", lambda root: {"com.guiyi.quant-live-candidate-" + "d" * 32})
    with pytest.raises(CohortError, match="UNOWNED_JOB"):
        host.park(old, new)
    monkeypatch.setattr(host, "_loaded_inventory", lambda root: {"com.guiyi.quant-live"})
    monkeypatch.setattr(direct, "read_launchd_service", lambda label, **kw:
                        "job = {\n\tstate = running\n\tpid = 33\n}" if label.endswith("-live") else None)
    monkeypatch.setattr(direct, "launchd_arguments", lambda output: direct.authorized_program_arguments(old.services["live"], host.home))
    monkeypatch.setattr(host, "launch", lambda *args: pytest.fail("busy job must stay untouched"))
    with pytest.raises(CohortError, match="OLD_JOB_BUSY"):
        host.park(old, new)


def test_direct_baseline_stages_and_reads_only_a_dedicated_redis(tmp_path, monkeypatch):
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.observation_stream import ObservationStream

    port = os.environ.get("GUIYI_MARKET_TARGET_REDIS_PORT")
    if port is None:
        pytest.skip("requires a dedicated empty Redis instance")
    assert 1024 <= int(port) <= 65535 and int(port) != 6379
    host = direct.MarketDirectStartHost()
    settings = {"REDIS_URL": f"redis://127.0.0.1:{port}/0",
                "DATABASE_URL": "postgresql+psycopg://operator@127.0.0.1:5432/guiyi_quant",
                "GUIYI_CANONICAL_DATA_ROOT": str(tmp_path)}
    root = Path(direct.__file__).resolve().parents[3]
    new = direct._target_bindings(None, root, "v1.16.151", "c" * 40, _CONTRACTS)
    plan = {"new": asdict(new), "day": _DAY.isoformat(),
            "authority": {"subscriptions": {product: f"{product.upper()}2701" for product in load_operational_products()}},
            "target_instance": host.empty_target(settings), "config_sha256": "config"}
    monkeypatch.setattr(host, "settings", lambda: (settings, "config"))
    observed = []
    monkeypatch.setattr(host, "_prove_staged_warmup",
                        lambda binding, settings, fingerprint, *, direct, active_day=None:
                        observed.append((binding.service, fingerprint, direct, active_day)))
    host.stage(plan, settings, may_exist=False)
    try:
        assert host.read_target(plan, bound=False) == "staged"
        host.stage(plan, settings, may_exist=True)
        assert observed[0] == observed[1] and observed[0][0] == "market-feed" and observed[0][2] is True
        with direct._redis(settings["REDIS_URL"]) as redis:
            assert ObservationStream(redis, kind="source").cursor("live", _DAY) == "0-0"
            assert not redis.exists("live:observations:registered:completed:alert",
                                    "live:observations:registered:completed:reference")
        assert host.read_target(plan, bound=True) == "bound"
        with pytest.raises(CohortError, match="TARGET_DAY_DRIFT"):
            host.read_target({**plan, "day": "2026-12-01"}, bound=True)
    finally:
        with direct._redis(settings["REDIS_URL"]) as redis:
            for key in redis.scan_iter():
                redis.delete(key)
