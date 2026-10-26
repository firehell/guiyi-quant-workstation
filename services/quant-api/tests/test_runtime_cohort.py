from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
import pytest
from app.runtime_bindings import BindingRegistry, ServiceBinding, CONTRACTS
from app.runtime_cohort import freeze_cohort, apply_cohort, CohortError


class Host:
    def __init__(self, tmp):
        self.directory = tmp / "control"
        self.directory.mkdir(mode=0o700)
        a = tmp / "release-v1.16.4"
        b = tmp / "release-v1.16.5"
        a.mkdir()
        b.mkdir()
        self.root = b
        self.old = BindingRegistry(
            1,
            {
                s: ServiceBinding(
                    s,
                    str(a),
                    "v1.16.4",
                    "a" * 40,
                    28,
                    True,
                    {k: "b" * 64 for k in CONTRACTS},
                )
                for s in (
                    "api",
                    "web",
                    "live",
                    "market-feed",
                    "alert",
                    "reference-worker",
                    "after-market",
                    "late-provider-recovery",
                    "weekly-audit",
                    "log-rotate",
                )
            },
        )
        self.registry = self.old
        self.calls = []
        self.failure = None
        self.in_guard = False

    def now(self):
        return datetime(2026, 10, 25, tzinfo=UTC)

    def bindings(self):
        return self.registry

    def binding_hash(self):
        return "c" * 64

    def verify_release(self, *a):
        pass

    def contracts(self, root):
        return {
            k: ("d" * 64 if k in ("launcher", "formula", "reference") else "b" * 64)
            for k in CONTRACTS
        }

    def protected(self, old):
        return {"scope": "stable"}

    def installed(self, old):
        return {"all": "exact"}

    def check_plan(self, p):
        assert self.registry == self.old

    def session_proof(self):
        return {"mode": "closed_idle", "products": 60}

    def prewarm(self, p):
        self.calls.append("prewarm")

    def preserve(self, p, attempt):
        self.calls.append("preserve")

    def suspend_calendars(self, p):
        self.calls.append("calendars_off")

    def drain(self, p):
        self.calls.append("drain")
        if self.failure == "drain":
            raise RuntimeError("DRAIN_TIMEOUT")
        return {"owners": "parked", "progress": "frozen"}

    @contextmanager
    def guards(self, p):
        self.calls.append("guard")
        self.in_guard = True
        try:
            yield
        finally:
            self.in_guard = False

    def stop_old(self, p, proof):
        assert self.in_guard
        self.calls.append("old_exited")

    def install(self, p, attempt):
        assert self.in_guard
        self.calls.append("install")
        if self.failure == "install":
            raise RuntimeError("INSTALL_FAILED")

    def commit(self, p):
        assert self.in_guard and "old_exited" in self.calls
        self.calls.append("commit")
        self.registry = BindingRegistry(
            1, {k: ServiceBinding(**v) for k, v in p["new"]["services"].items()}
        )
        if self.failure == "cas_unknown":
            raise RuntimeError("CAS_UNKNOWN")

    def start_consumers(self, p):
        self.calls.append("consumers")

    def consumers_ready(self, p, proof):
        self.calls.append("consumers_ready")

    def start_feed(self, p):
        self.calls.append("feed")

    def verify(self, p, proof):
        self.calls.append("verify")
        if self.failure == "verify":
            raise RuntimeError("VERIFY_FAILED")
        return {"identity": "matched", "mode": "closed_idle"}

    def restore_calendars(self, p):
        self.calls.append("calendars_on")

    def restore_old(self, p):
        assert self.registry == self.old
        self.calls.append("restore_old")

    def halt_unknown(self, p):
        self.calls.append("halt_unknown")

    def assert_protected(self, p):
        self.calls.append("protected")


def plan(h):
    return freeze_cohort(h, candidate_root=h.root, tag="v1.16.5", commit="e" * 40)


def test_all_ten_commit_once_after_old_exit_and_consume_before_feed(tmp_path):
    h = Host(tmp_path)
    p = plan(h)
    r = apply_cohort(h, p)
    assert r["status"] == "switched"
    assert h.calls.count("commit") == 1
    assert (
        h.calls.index("old_exited")
        < h.calls.index("commit")
        < h.calls.index("consumers")
        < h.calls.index("consumers_ready")
        < h.calls.index("feed")
        < h.calls.index("calendars_on")
    )
    assert {b.generation for b in h.registry.services.values()} == {29}
    assert {b.commit for b in h.registry.services.values()} == {"e" * 40}


@pytest.mark.parametrize("failure", ["drain", "install"])
def test_before_cas_failure_restores_only_old_without_registry_write(tmp_path, failure):
    h = Host(tmp_path)
    p = plan(h)
    h.failure = failure
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert h.registry == h.old and "restore_old" in h.calls and "commit" not in h.calls


@pytest.mark.parametrize("failure", ["cas_unknown", "verify"])
def test_after_cas_unknown_never_rolls_back_or_retries(tmp_path, failure):
    h = Host(tmp_path)
    p = plan(h)
    h.failure = failure
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert "halt_unknown" in h.calls and "restore_old" not in h.calls
    before = list(h.calls)
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert h.calls == before


def test_unknown_previous_attempt_and_tampering_fail_before_mutation(tmp_path):
    h = Host(tmp_path)
    p = plan(h)
    p["new"]["services"]["alert"]["enabled"] = False
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert not h.calls


def test_disabled_calendar_is_preserved_and_migrations_forbidden(tmp_path):
    h = Host(tmp_path)
    h.old = BindingRegistry(
        1,
        {
            **h.old.services,
            "weekly-audit": replace(h.old.services["weekly-audit"], enabled=False),
        },
    )
    h.registry = h.old
    p = plan(h)
    assert p["new"]["services"]["weekly-audit"]["enabled"] is False
    h.contracts = lambda root: {k: "e" * 64 for k in CONTRACTS}
    with pytest.raises(CohortError, match="SCHEMA"):
        plan(h)


def test_expired_plan_has_no_effects(tmp_path):
    from datetime import timedelta

    h = Host(tmp_path)
    p = plan(h)
    h.now = lambda: datetime(2026, 10, 25, tzinfo=UTC) + timedelta(minutes=16)
    with pytest.raises(CohortError, match="EXPIRED"):
        apply_cohort(h, p)
    assert not h.calls


def test_private_attempt_directory_cannot_be_redirected(tmp_path):
    h = Host(tmp_path)
    p = plan(h)
    outside = tmp_path / "outside"
    outside.mkdir()
    (h.directory / "cohort-attempts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CohortError, match="DIRECTORY_UNSAFE"):
        apply_cohort(h, p)
    assert not list(outside.iterdir()) and not h.calls


def test_hash_recomputed_still_cannot_expand_enabled_scope_or_mix_contracts(tmp_path):
    from app.reference_trading.recovery_campaign import digest

    h = Host(tmp_path)
    h.old = BindingRegistry(
        1,
        {
            **h.old.services,
            "weekly-audit": replace(h.old.services["weekly-audit"], enabled=False),
        },
    )
    h.registry = h.old
    p = plan(h)
    p["new"]["services"]["weekly-audit"]["enabled"] = True
    p["plan_sha256"] = digest({k: v for k, v in p.items() if k != "plan_sha256"})
    with pytest.raises(CohortError, match="TARGET_INVALID"):
        apply_cohort(h, p)
    p = plan(h)
    p["new"]["services"]["live"]["contracts"]["formula"] = "a" * 64
    p["plan_sha256"] = digest({k: v for k, v in p.items() if k != "plan_sha256"})
    with pytest.raises(CohortError, match="TARGET_CONTRACTS_INVALID"):
        apply_cohort(h, p)
    assert not h.calls


def test_prewarm_expiry_cancels_before_stopping_any_service(tmp_path):
    from datetime import timedelta

    h = Host(tmp_path)
    p = plan(h)

    def warmup(_plan):
        h.calls.append("prewarm")
        h.now = lambda: datetime(2026, 10, 25, tzinfo=UTC) + timedelta(minutes=16)

    h.prewarm = warmup
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert h.calls == ["prewarm"]
    assert h.registry == h.old


def test_install_over_budget_restores_without_cas(tmp_path, monkeypatch):
    import app.runtime_cohort as module

    h = Host(tmp_path)
    p = plan(h)
    clock = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    original = h.install

    def install(_plan, attempt):
        original(_plan, attempt)
        clock[0] = 601.0

    h.install = install
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert "restore_old" in h.calls and "commit" not in h.calls


def test_disabled_continuous_rejected_before_side_effects(tmp_path):
    h = Host(tmp_path)
    h.old = BindingRegistry(
        1, {**h.old.services, "live": replace(h.old.services["live"], enabled=False)}
    )
    h.registry = h.old
    p = plan(h)
    with pytest.raises(CohortError, match="CONTINUOUS_DISABLED"):
        apply_cohort(h, p)
    assert h.calls == []


def test_post_cas_journal_io_failure_still_halts_new_work(tmp_path, monkeypatch):
    import app.runtime_cohort as module

    h = Host(tmp_path)
    p = plan(h)
    original = module._write

    def write(path, value):
        if "consumers" in h.calls:
            raise OSError("DISK_FULL")
        return original(path, value)

    monkeypatch.setattr(module, "_write", write)
    with pytest.raises((CohortError, OSError)):
        apply_cohort(h, p)
    assert "halt_unknown" in h.calls
    assert "restore_old" not in h.calls


@pytest.mark.parametrize("mutation", ["ttl", "root"])
def test_rehashed_plan_cannot_expand_ttl_or_release_storage(tmp_path, mutation):
    from app.reference_trading.recovery_campaign import digest
    from datetime import timedelta

    h = Host(tmp_path)
    p = plan(h)
    if mutation == "ttl":
        p["expires_at"] = (h.now() + timedelta(hours=1)).isoformat()
    else:
        (tmp_path / "other" / "release-v1.16.5").mkdir(parents=True)
        for value in p["new"]["services"].values():
            value["root"] = str(tmp_path / "other" / "release-v1.16.5")
    p["plan_sha256"] = digest({k: v for k, v in p.items() if k != "plan_sha256"})
    with pytest.raises(CohortError):
        apply_cohort(h, p)
    assert h.calls == []


def test_warmup_reports_real_app_file_for_namespace_package(monkeypatch, capsys):
    import app
    import json
    from pathlib import Path
    from app import runtime_cohort, runtime_deployment

    assert app.__file__ is None  # Production app is a namespace package.
    calls = []
    monkeypatch.setattr(
        runtime_deployment,
        "warmup_service",
        lambda service: calls.append(service) or {},
    )
    assert runtime_cohort.main(["warmup", "web"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready" and calls == ["web"]
    assert (
        Path(result["source_roots"]["app"]) == Path(runtime_cohort.__file__).resolve()
    )
    assert Path(result["source_roots"]["app"]).is_file()
    assert Path(result["source_roots"]["core"]).is_file()


def test_internal_alert_warmup_explicitly_allows_only_closed_warming(
    monkeypatch, capsys
):
    import json
    from app import runtime_cohort, runtime_deployment
    from app.alerts import composition

    calls = []
    proof = {
        "calculated": 53,
        "total": 54,
        "warming": [{"symbol": "bz", "frequency": "1w", "bar_count": 26}],
        "natural_signals_verified": False,
    }
    monkeypatch.setattr(
        composition,
        "warmup_alert_runtime",
        lambda **kwargs: calls.append(kwargs) or proof,
    )
    monkeypatch.setattr(
        runtime_deployment,
        "warmup_service",
        lambda _: pytest.fail("native warmup must stay strict"),
    )
    assert runtime_cohort.main(["warmup", "alert"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["proof"] == proof
    assert calls == [{"allow_closed_warming": True}]


def test_cohort_retains_per_stream_warming_in_attempt_before_any_stop(tmp_path):
    import json

    h = Host(tmp_path)
    p = plan(h)
    proof = {
        "alert": {
            "calculated": 53,
            "total": 54,
            "warming": [
                {
                    "rule_code": "subing_ths_alert_15m_v1",
                    "symbol": "bz",
                    "frequency": "1w",
                    "contract": "BZ2611",
                    "bar_count": 26,
                }
            ],
            "natural_signals_verified": False,
        }
    }
    h.prewarm = lambda _: proof
    check = h.check_plan

    def check_with_evidence(plan):
        check(plan)
        if (h.directory / "cohort-release.json").exists():
            state = json.loads((h.directory / "cohort-release.json").read_text())
            if state["phase"] == "prewarmed":
                assert state["effects"]["prewarm"] == proof
                assert "calendars_off" not in h.calls

    h.check_plan = check_with_evidence
    assert apply_cohort(h, p)["status"] == "switched"
    state = json.loads((h.directory / "cohort-release.json").read_text())
    attempt = h.directory / "cohort-attempts" / p["plan_sha256"] / "state.json"
    assert state["effects"]["prewarm"] == proof
    assert json.loads(attempt.read_text())["effects"]["prewarm"] == proof

@pytest.mark.parametrize('error,expected', [
    (CohortError('COHORT_FEED_CLOSE_UNPROVEN'), 'COHORT_FEED_CLOSE_UNPROVEN'),
    (RuntimeError('PRIVATE_CONNECTION_VALUE'), None),
    (CohortError('private value with credentials'), None),
])
def test_cancelled_attempt_retains_phase_and_only_bounded_cohort_code(tmp_path, error, expected):
    import json
    host = Host(tmp_path)
    plan = freeze_cohort(host, candidate_root=host.root, tag='v1.16.5', commit='e' * 40)
    def fail(_plan):
        raise error
    host.drain = fail
    with pytest.raises(CohortError, match='COHORT_PRECONDITION_CANCELLED'):
        apply_cohort(host, plan)
    state = json.loads((host.directory / 'cohort-release.json').read_text())
    assert state['phase'] == 'cancelled'
    assert state['failed_phase'] == 'drain'
    assert state.get('error_code') == expected
    assert host.registry == host.old and 'commit' not in host.calls
    assert 'PRIVATE_CONNECTION_VALUE' not in json.dumps(state)
    assert 'private value with credentials' not in json.dumps(state)

@pytest.mark.parametrize('service,expected', [('web', 'web'), ('private service value', None)])
def test_cancelled_drain_retains_only_known_service(tmp_path, service, expected):
    import json
    host = Host(tmp_path)
    plan = freeze_cohort(host, candidate_root=host.root, tag='v1.16.5', commit='e' * 40)
    error = CohortError('COHORT_OLD_DRAIN_TIMEOUT')
    error.service = service
    def fail(_plan):
        raise error
    host.drain = fail
    with pytest.raises(CohortError):
        apply_cohort(host, plan)
    state = json.loads((host.directory / 'cohort-release.json').read_text())
    assert state.get('failed_service') == expected
    assert 'private service value' not in json.dumps(state)
