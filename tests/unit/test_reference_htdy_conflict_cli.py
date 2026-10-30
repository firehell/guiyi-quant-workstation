"""No network or production mutation: exact recovery CLI orchestration contracts."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/reference_htdy_conflict_recovery.py"


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location("htdy_conflict_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A separately frozen 48-route fixture scope; production digest stays fixed.
    module.FROZEN_SCOPE_SHA256 = module.digest(sorted(scope()))
    module.FROZEN_OPEN_SCOPE_SHA256 = module.digest(sorted(scope()[:20]))
    return module


class Backend:
    def __init__(self):
        self.now = datetime(2026, 10, 30, 4, tzinfo=UTC)
        self.calls = []
        self.window = True
        self.parked = True
        self.result = None
        self.failure = False

    def identity(self):
        return dict(
            root="/fixed/code", commit="a" * 40, tag="v1.16.39", config_sha256="b" * 64
        )

    def check_window(self):
        self.calls.append("window")
        if not self.window:
            raise ValueError("REST_WINDOW_REQUIRED")

    @contextmanager
    def fenced(self):
        self.calls.append("fence")
        if not self.parked:
            raise ValueError("PARKED_OWNER_REQUIRED")
        yield self

    def plan(self, ids, *, recording_start, expires_at, now):
        self.calls.append("plan")
        return dict(
            version="domain-v1",
            plan_hash="c" * 64,
            items=[
                dict(
                    binding=dict(
                        stream_id=i,
                        revision_id="old",
                        checkpoint_sha256="d" * 64,
                        checkpoint=dict(
                            reference_state=dict(
                                open_trade=(
                                    dict(reference_trade_id="trade-" + i)
                                    if i in scope()[:20]
                                    else None
                                )
                            )
                        ),
                    )
                )
                for i in ids
            ],
            recording_start=recording_start.isoformat(),
            expires_at=expires_at.isoformat(),
        )

    def apply(self, plan, *, expected_plan_hash, now):
        self.calls.append("apply")
        assert expected_plan_hash == plan["plan_hash"]
        if self.failure:
            raise RuntimeError("private-password SQL")
        self.result = {i["binding"]["stream_id"]: "new" for i in plan["items"]}
        return self.result

    def readback(self, plan):
        self.calls.append("readback")
        return self.result


def scope():
    return tuple("reference-stream:" + str(i) for i in range(48))


def plan(cli, tmp_path, backend):
    runner = cli.Coordinator(backend, tmp_path / "attempt", clock=lambda: backend.now)
    path = tmp_path / "plan.json"
    value = runner.plan(
        path,
        scope(),
        inventory_sha256=cli.FROZEN_INVENTORY_SHA256,
        recording_start=backend.now + timedelta(minutes=30),
        expires_at=backend.now + timedelta(minutes=5),
    )
    return runner, path, value


def test_default_is_readonly_without_loading_dependencies(cli, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "load_dependencies", lambda *_: pytest.fail("private loader called")
    )
    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["readonly"] is True


def test_plan_is_exact_private_and_never_applies(cli, tmp_path):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    assert "apply" not in b.calls and b.calls[:2] == ["window", "fence"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert runner.directory.stat().st_mode & 0o777 == 0o700
    assert p["identity"] == b.identity() and len(p["stream_ids"]) == 48


def test_apply_once_claims_before_domain_and_keeps_parked(cli, tmp_path):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    original = b.apply

    def applied(*args, **kwargs):
        assert (runner.directory / "apply-claim.json").exists()
        return original(*args, **kwargs)

    b.apply = applied
    result = runner.apply(path, expected_plan_hash=p["plan_hash"])
    assert result["status"] == "COMMITTED" and result["reference_must_remain_parked"]
    assert b.parked and "resume" not in b.calls
    with pytest.raises(Exception):
        runner.apply(path, expected_plan_hash=p["plan_hash"])
    assert b.calls.count("apply") == 1


@pytest.mark.parametrize(
    "change", ["expiry", "identity", "hash", "scope", "window", "fence"]
)
def test_precheck_failure_never_claims_or_applies(cli, tmp_path, change):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    expected = p["plan_hash"]
    if change == "expiry":
        b.now += timedelta(minutes=6)
    elif change == "identity":
        b.identity = lambda: dict(
            root="/other", commit="d" * 40, tag="v1.16.40", config_sha256="e" * 64
        )
    elif change == "hash":
        expected = "f" * 64
    elif change == "scope":
        p["stream_ids"].append("outside")
        path.write_text(json.dumps(p))
    elif change == "window":
        b.window = False
    elif change == "fence":
        b.parked = False
    with pytest.raises(Exception):
        runner.apply(path, expected_plan_hash=expected)
    assert (
        "apply" not in b.calls and not (runner.directory / "apply-claim.json").exists()
    )


def test_unknown_is_consumed_status_reads_only_even_after_window(cli, tmp_path):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    b.failure = True
    with pytest.raises(Exception):
        runner.apply(path, expected_plan_hash=p["plan_hash"])
    claim = (runner.directory / "apply-claim.json").read_bytes()
    b.window = False
    b.now += timedelta(hours=2)
    result = runner.status(path, expected_plan_hash=p["plan_hash"])
    assert result["status"] == "UNKNOWN_NO_COMMIT_PROVEN"
    assert (runner.directory / "apply-claim.json").read_bytes() == claim
    assert "private" not in json.dumps(result) and "SQL" not in json.dumps(result)


def test_frozen_inventory_rejects_changed_bytes_and_non48(cli, tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"items": []}))
    path.chmod(0o600)
    with pytest.raises(Exception):
        cli.frozen_scope(path)


def test_plan_refuses_existing_or_symlink_targets(cli, tmp_path):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    with pytest.raises(Exception):
        runner.plan(
            path,
            scope(),
            inventory_sha256=cli.FROZEN_INVENTORY_SHA256,
            recording_start=b.now + timedelta(minutes=30),
            expires_at=b.now + timedelta(minutes=5),
        )
    linked = tmp_path / "linked"
    linked.symlink_to(path)
    with pytest.raises(Exception):
        runner.status(linked, expected_plan_hash=p["plan_hash"])


def test_slow_window_expiry_never_claims(cli, tmp_path):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    original = b.check_window

    def slow():
        original()
        b.now += timedelta(minutes=6)

    b.check_window = slow
    with pytest.raises(ValueError):
        runner.apply(path, expected_plan_hash=p["plan_hash"])
    assert not (runner.directory / "apply-claim.json").exists()
    assert "apply" not in b.calls


def test_attempt_cannot_bind_a_second_plan(cli, tmp_path):
    b = Backend()
    runner, _, _ = plan(cli, tmp_path, b)
    second = tmp_path / "second.json"
    with pytest.raises(Exception):
        runner.plan(
            second,
            scope(),
            inventory_sha256=cli.FROZEN_INVENTORY_SHA256,
            recording_start=b.now + timedelta(minutes=40),
            expires_at=b.now + timedelta(minutes=5),
        )
    assert not second.exists()


def test_status_rejects_foreign_claim(cli, tmp_path):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    cli.put(
        runner.directory / "apply-claim.json",
        dict(schema=cli.VERSION, plan_hash="f" * 64, identity=b.identity()),
    )
    with pytest.raises(ValueError):
        runner.status(path, expected_plan_hash=p["plan_hash"])
    assert "readback" not in b.calls


@pytest.mark.parametrize("kind", ["extra", "missing", "source_mismatch"])
def test_plan_rejects_open_scope_drift(cli, tmp_path, kind):
    b = Backend()
    original = b.plan

    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        rows = {r["binding"]["stream_id"]: r["binding"] for r in value["items"]}
        if kind in {"missing", "source_mismatch"}:
            rows[scope()[0]]["checkpoint"]["reference_state"]["open_trade"] = None
        if kind in {"extra", "source_mismatch"}:
            rows[scope()[25]]["checkpoint"]["reference_state"]["open_trade"] = {
                "reference_trade_id": "unexpected"
            }
        return value

    b.plan = changed
    with pytest.raises(ValueError):
        plan(cli, tmp_path, b)
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize("action", ["apply", "status"])
def test_frozen_open_identity_is_verified_on_readback_and_apply(cli, tmp_path, action):
    b = Backend()
    runner, path, p = plan(cli, tmp_path, b)
    assert len(p["open_trades"]) == 20
    p["open_trades"][0]["reference_trade_id"] = "foreign-trade"
    p["plan_hash"] = cli.digest({k: v for k, v in p.items() if k != "plan_hash"})
    path.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="RECOVERY_OPEN_SCOPE_DRIFT"):
        getattr(runner, action)(path, expected_plan_hash=p["plan_hash"])
    assert "apply" not in b.calls and "readback" not in b.calls


def test_native_slow_session_proof_rejects_remaining_less_than_660(
    cli, tmp_path, monkeypatch
):
    import sys
    from dataclasses import dataclass
    from types import ModuleType, SimpleNamespace
    from hashlib import sha256

    @dataclass
    class Binding:
        generation: int = 41

    binding = Binding()
    now = datetime(2026, 10, 30, 4, tzinfo=UTC)
    calls = []
    clock = {"now": now}

    class Clock:
        fromisoformat = staticmethod(datetime.fromisoformat)

        @staticmethod
        def now(_):
            return clock["now"]

    def slow_proof():
        calls.append("session")
        clock["now"] = now + timedelta(seconds=30)
        return dict(
            mode="closed_idle",
            phases={
                str(i): dict(
                    phase="CLOSED",
                    next_session_start=(now + timedelta(seconds=680)).isoformat(),
                )
                for i in range(60)
            },
        )

    for name, attrs in {
        "app.runtime_cohort_host": dict(
            CohortHost=lambda: SimpleNamespace(session_proof=slow_proof)
        ),
        "app.private_settings": dict(
            read_private_settings_content=lambda _: b"safe-fixture"
        ),
        "app.runtime_bindings": dict(
            resolve_service_binding=lambda _: binding,
            bindings_sha256=lambda: "registry",
        ),
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli, "verify_code", lambda *_: None)
    b = object.__new__(cli.MacBackend)
    b.args = SimpleNamespace(exact_commit="a" * 40, tag="v1.16.39")
    b._identity = dict(
        root="/fixed",
        commit="a" * 40,
        tag="v1.16.39",
        config_sha256=sha256(b"safe-fixture").hexdigest(),
        reference_binding=dict(generation=41),
        registry_sha256="registry",
    )
    b.park = lambda *_: calls.append("park")
    runner = cli.Coordinator(b, tmp_path / "attempt", clock=lambda: clock["now"])
    with pytest.raises(ValueError, match="RECOVERY_REST_WINDOW_REQUIRED"):
        runner.park(now + timedelta(minutes=5))
    assert calls == ["session"]
    assert not runner.directory.exists()


@pytest.mark.parametrize(
    "values,expected",
    [
        (
            {
                "REDIS_URL": "redis://127.0.0.1:6379/0",
                "POSTGRES_PASSWORD": "fixture-p@ss",
            },
            "redis://:fixture-p%40ss@127.0.0.1:6379/0",
        ),
        (
            {"POSTGRES_PASSWORD": "fallback", "REDIS_PASSWORD": "fixture-primary"},
            "redis://:fixture-primary@127.0.0.1:6379/0",
        ),
        (
            {
                "REDIS_URL": "redis://:fixture-explicit@127.0.0.1:6379/0",
                "POSTGRES_PASSWORD": "fallback",
            },
            "redis://:fixture-explicit@127.0.0.1:6379/0",
        ),
    ],
)
def test_dependencies_derive_wrapper_redis_idempotently_before_reexec(
    cli, monkeypatch, capsys, values, expected
):
    import os
    import sys
    from types import ModuleType

    private = ModuleType("app.private_settings")
    private.private_dependency_settings = lambda _: (
        dict(values),
        {"config_sha256": "b" * 64},
    )
    monkeypatch.setitem(sys.modules, "app.private_settings", private)
    for key in (
        "GUIYI_HTDY_CONFLICT_CLI_READY",
        "REDIS_URL",
        "REDIS_PASSWORD",
        "POSTGRES_PASSWORD",
        "PGOPTIONS",
        "GUIYI_OBSERVATION_STREAM_ENABLED",
        "GUIYI_RUNTIME_HANDOVER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    observed = []

    def execv(*args):
        observed.append(
            dict(url=os.environ["REDIS_URL"], readonly=os.environ.get("PGOPTIONS"))
        )

    monkeypatch.setattr(cli.os, "execv", execv)
    assert cli.load_dependencies() == "b" * 64
    assert observed == [dict(url=expected, readonly=None)]
    assert cli.load_dependencies() == "b" * 64
    assert os.environ["REDIS_URL"] == expected and len(observed) == 1
    assert os.environ["GUIYI_OBSERVATION_STREAM_ENABLED"] == "1"
    assert os.environ["GUIYI_RUNTIME_HANDOVER_ENABLED"] == "1"
    assert capsys.readouterr().out == ""


def test_dependencies_missing_default_password_fails_without_reexec_or_secret_output(
    cli, monkeypatch, capsys
):
    import sys
    from types import ModuleType

    private = ModuleType("app.private_settings")
    private.private_dependency_settings = lambda _: (
        {"REDIS_URL": "redis://127.0.0.1:6379/0"},
        {"config_sha256": "b" * 64},
    )
    monkeypatch.setitem(sys.modules, "app.private_settings", private)
    monkeypatch.setattr(cli.os, "execv", lambda *_: pytest.fail("must not reexec"))
    with pytest.raises(ValueError, match="^RECOVERY_DEPENDENCIES_INVALID$"):
        cli.load_dependencies()
    assert capsys.readouterr().out == ""
