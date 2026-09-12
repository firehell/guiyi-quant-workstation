from contextlib import contextmanager
from datetime import UTC, date, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_literal_config_does_not_execute_or_accept_shell(tmp_path):
    from app.market_data.closeout_binding import literal_settings
    assert literal_settings(b'A=plain\nB="${A}-value"\n') == {"A": "plain", "B": "plain-value"}
    for content in (b'A=$(touch /tmp/no)\n', b'A=`id`\n', b'source other\n', b'A=one\nA=two\n', b'A=${UNKNOWN}\n'):
        with pytest.raises(ValueError):
            literal_settings(content)


def test_actual_dependency_mismatch_rejected_without_queries(tmp_path):
    from app.market_data.closeout_binding import assert_dependencies
    settings = {"DATABASE_URL": "postgresql+psycopg://fixture@127.0.0.1:15448/test",
        "REDIS_URL": "redis://127.0.0.1:15449/0", "POSTGRES_PASSWORD": "fixture-only",
        "GUIYI_CANONICAL_DATA_ROOT": str(tmp_path), "GUIYI_LIVE_RECOVERY_ENABLED": "1"}
    with Session(create_engine("sqlite://")) as db:
        manager = SimpleNamespace(catalog=SimpleNamespace(session=db, canonical_root=tmp_path), store=SimpleNamespace(root=tmp_path))
        with pytest.raises(ValueError):
            assert_dependencies(settings, root=Path("/fixture"), manager=manager, session=db,
                redis=Redis.from_url(settings["REDIS_URL"]), products=("au",))
        assert not db.in_transaction()


@pytest.fixture
def target(tmp_path, monkeypatch):
    from app.market_data import closeout_binding as module
    from app.core.env import PROJECT_ROOT
    home, root = tmp_path / "home", tmp_path / "runtime"
    home.mkdir()
    root.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        module, "verify_closeout_identity", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module, "verify_runtime_release_identity", lambda *args: None, raising=False
    )
    run = root / ".run"
    run.mkdir(mode=0o700)
    raw = json.dumps({"current_run": {"started_at": "2028-01-01T00:00:00Z"}}).encode()
    (run / "after-market-status.json").write_bytes(raw)
    runtime_dir = home / "Library/Application Support/GuiyiQuant"
    runtime_dir.mkdir(parents=True, mode=0o700)
    script = root / "scripts/ops/macos/run-local-service.sh"
    script.parent.mkdir(parents=True)
    script.write_text("fixture script, never executed")
    (runtime_dir / "run-local-service.sh").write_bytes(script.read_bytes())
    config = runtime_dir / "project.env"
    config.write_text('DATABASE_URL=postgresql+psycopg://fixture@127.0.0.1:15448/test\n'
        'REDIS_URL=redis://127.0.0.1:15449/0\nPOSTGRES_PASSWORD=fixture-only\n'
        'RQDATA_LICENSE_KEY=fixture-rqdata-license\n'
        f'GUIYI_CANONICAL_DATA_ROOT="{tmp_path.resolve()}/canonical"\nGUIYI_LIVE_RECOVERY_ENABLED=1\n')
    config.chmod(0o600)
    universe = root / "data/universe"
    universe.mkdir(parents=True)
    for name in ("active_products.txt", "retired_products.txt", "product_window_starts.csv", "active_history_floor.txt"):
        (universe / name).write_bytes((PROJECT_ROOT / "data/universe" / name).read_bytes())
    (universe / "operational_products.txt").write_text("au\n")
    plists = home / "Library/LaunchAgents"
    plists.mkdir(parents=True)
    outputs = {}
    for index, name in enumerate(("api", "web", "live", "alert", "after-market")):
        label = f"com.guiyi.quant-{name}"
        args = ["/bin/bash", str(runtime_dir / "run-local-service.sh"), name]
        cwd = home if name in {"api", "web"} else root
        env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_PROJECT_ROOT": str(root), "GUIYI_RUNTIME_COMMIT": "a" * 40}
        (plists / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label, "WorkingDirectory": str(cwd),
            "ProgramArguments": args, "EnvironmentVariables": env}))
        fields = 'state = not running\n' if name == "after-market" else f'state = running\npid = {100 + index}\n'
        outputs[label] = 'service = {\n' + fields + f'working directory = {cwd}\narguments = {{\n' + '\n'.join(args) + '\n}\nenvironment = {\n' + '\n'.join(f'{k} => {v}' for k, v in env.items()) + '\n}\n}\n'
    def read(arguments, **kwargs):
        if arguments[0] == "/bin/launchctl":
            return outputs[arguments[-1].split('/')[-1]]
        assert arguments[:4] == ["/usr/bin/env", "TZ=UTC", "/bin/ps", "-p"]
        return "Mon Jan 01 00:00:00 2029"
    monkeypatch.setattr(module, "_read_command", read)
    monkeypatch.setattr(
        module,
        "_read_launchd_service",
        lambda label, **kwargs: outputs[label],
        raising=False,
    )
    return SimpleNamespace(root=root, home=home, config=config, module=module, outputs=outputs,
        status=run / "after-market-status.json",
        create=lambda: module.RuntimeDataBinding(
            root, "a" * 40, hashlib.sha256(raw).hexdigest(), home=home
        ))


def _terminal_status(*, schema_version=5):
    interruption = {
        "trading_day": "2028-01-01", "started_at": "2028-01-01T00:00:00Z",
        "closed_at": "2029-01-01T00:00:00Z",
        "snapshot_checked_at": "2029-01-01T00:00:00Z",
        "snapshot_classification": "not_verified_missing", "reconciliation_verified": False,
    }
    return {
        "schema_version": schema_version, "last_interruption": interruption, "current_run": None,
        "last_run": {"trading_day": "2028-01-01", "status": "interrupted", "attempts": None,
            "started_at": "2028-01-01T00:00:00Z", "finished_at": "2029-01-01T00:00:00Z",
            "products": ["au"], "error_code": "AFTER_MARKET_INTERRUPTED",
            "failure_notification": None},
        "last_successful_trading_day": "2027-12-31",
        "last_failure": {"trading_day": "2028-01-01", "error_code": "AFTER_MARKET_INTERRUPTED"},
    }


def _write_status(path, payload):
    content = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _stop_writer(target) -> None:
    target.outputs["com.guiyi.quant-after-market"] = None


def _clean_candidate_reader(arguments, *, root):
    from app.market_data.captured_recovery_runtime import _read_command

    if "status" in arguments:
        return ""
    return _read_command(arguments, root=root)


def _stopped_binding_with_heartbeats(target, *, checks=None):
    terminal_sha256 = _write_status(target.status, _terminal_status())
    _stop_writer(target)
    binding = target.module.RuntimeDataBinding(
        target.root, "a" * 40, terminal_sha256, home=target.home
    )
    heartbeat = {
        "runtime_root": str(target.root),
        "runtime_commit": "a" * 40,
        "recovery_guard_enabled": True,
        "generated_at": "2029-01-01T00:00:00Z",
    }
    redis = SimpleNamespace(get=lambda key: json.dumps(heartbeat))
    store = SimpleNamespace(heartbeat=lambda: heartbeat)

    def check_runtime_heartbeats():
        binding.recheck_identity()
        binding._check_heartbeats(
            redis, store, lambda: datetime(2029, 1, 1, tzinfo=UTC)
        )
        binding.recheck_identity()
        if checks is not None:
            checks.append("checked")

    binding.check_runtime_heartbeats = check_runtime_heartbeats
    return binding, terminal_sha256


def test_stopped_authority_uses_real_schema_v5_binding_and_rechecks_every_fact(
    target, monkeypatch
):
    from app.market_data import runtime_status_authority as authority_module

    attacker_home = target.home.parent / "runtime-env-home"
    monkeypatch.setenv("HOME", str(attacker_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: attacker_home))
    checks = []
    binding, terminal_sha256 = _stopped_binding_with_heartbeats(
        target, checks=checks
    )
    monkeypatch.setattr(authority_module, "_account_home", lambda: target.home)
    monkeypatch.setattr(
        authority_module, "verify_runtime_release_identity", lambda *args: None
    )

    authority = authority_module.resolve_market_runtime_status_authority(
        candidate_root=target.root,
        expected_stopped_status_sha256=terminal_sha256,
        service_reader=lambda label, **kwargs: target.outputs[label],
        binding_factory=lambda *args, **kwargs: binding,
    )

    assert authority.mode == "stopped_terminal"
    assert authority.path == target.status
    authority.recheck()
    assert checks == ["checked", "checked"]

    target.config.write_text(target.config.read_text() + "# drift\n")
    with pytest.raises(ValueError):
        authority.recheck()


def test_partial_install_restore_reaches_real_stopped_authority_and_preflight(
    target, tmp_path, monkeypatch
):
    from contextlib import nullcontext

    from app.core.env import PROJECT_ROOT
    from app.market_data import runtime_status_authority as authority_module
    from app.market_data.market_phase import MarketPhase, ProductMarketPhase
    from app.market_data.runtime_promotion import (
        run_market_runtime_promotion_preflight,
    )

    terminal_sha256 = _write_status(target.status, _terminal_status())
    _stop_writer(target)
    candidate = tmp_path / "candidate"
    for relative in (
        "deploy/launchd",
        "scripts/ops/macos/install-local-services.sh",
        "scripts/ops/macos/run-local-service.sh",
        "scripts/ops/macos/rotate-local-service-logs.sh",
    ):
        source = PROJECT_ROOT / relative
        destination = candidate / relative
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text(
        "#!/bin/sh\nprintf '%s\\n' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'\n",
        encoding="utf-8",
    )
    (fake_bin / "git").chmod(0o755)
    (fake_bin / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_bin / "sleep").chmod(0o755)
    state_dir = target.home / "launchd-state"
    state_dir.mkdir()
    (state_dir / "com.guiyi.quant-live").touch()
    (target.home / "fail-live-once").touch()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'command="${1:-}"; target="${2:-}"; label="${target##*/}"\n'
        'if [ "$command" = print ] && [ "$target" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$command" = print ]; then\n'
        '  [ -f "$HOME/launchd-state/$label" ] && exit 0\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "$label" "$UID" >&2; exit 113\n'
        "fi\n"
        'if [ "$command" = bootout ]; then rm -f "$HOME/launchd-state/$label"; exit 0; fi\n'
        'if [ "$command" = bootstrap ]; then\n'
        '  label="${3##*/}"; label="${label%.plist}"; touch "$HOME/launchd-state/$label"; exit 0\n'
        "fi\n"
        'if [ "$command" = enable ]; then\n'
        '  case "$target" in *com.guiyi.quant-live)\n'
        '    if [ -f "$HOME/fail-live-once" ]; then rm -f "$HOME/fail-live-once"; exit 81; fi ;;\n'
        "  esac\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    python = candidate / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = -m ] && [ "$2" = app.market_data.runtime_status_authority ] '
        '&& [ "$3" = launchd-service-state ]; then\n'
        '  label="$4"\n'
        '  launchctl print "gui/$UID" >/dev/null 2>&1 || exit 1\n'
        '  if output="$(launchctl print "gui/$UID/$label" 2>&1)"; then\n'
        "    printf 'loaded\\n'; exit 0\n"
        "  else\n"
        '    result="$?"\n'
        "  fi\n"
        '  exact="Could not find service \\"$label\\" in domain for user gui: $UID"\n'
        '  [ "$result" = 113 ] || exit 1\n'
        '  [ "$output" = "$exact" ] || [ "$output" = "Bad request.\n$exact" ] || exit 1\n'
        "  printf 'absent\\n'; exit 0\n"
        "fi\n"
        'case "$*" in\n'
        '  "-m app.market_data.runtime_status_authority verify-restored-loaded-service "*) exit 0 ;;\n'
        "esac\n"
        "printf '%s\\n' "
        "'{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\","
        "\"status\":\"passed\",\"reason\":\"non_trading_interval\","
        "\"trading_day\":null,\"operational_count\":1,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        [
            str(candidate / "scripts/ops/macos/install-local-services.sh"),
            "--confirm-market-runtime",
        ],
        cwd=candidate,
        env={
            **os.environ,
            "HOME": str(target.home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "POSTGRES_PASSWORD": "fixture-only",
            "GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256": terminal_sha256,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "previous market authority restored" in result.stderr
    monkeypatch.setattr(authority_module, "_account_home", lambda: target.home)
    checks = []

    def binding_factory(root, commit, status_sha256, *, home):
        binding = target.module.RuntimeDataBinding(
            root, commit, status_sha256, home=home
        )
        heartbeat = {
            "runtime_root": str(target.root),
            "runtime_commit": "a" * 40,
            "recovery_guard_enabled": True,
            "generated_at": "2029-01-01T00:00:00Z",
        }

        def check():
            binding.recheck_identity()
            binding._check_heartbeats(
                SimpleNamespace(get=lambda key: json.dumps(heartbeat)),
                SimpleNamespace(heartbeat=lambda: heartbeat),
                lambda: datetime(2029, 1, 1, tzinfo=UTC),
            )
            binding.recheck_identity()
            checks.append("checked")

        binding.check_runtime_heartbeats = check
        return binding

    authority = authority_module.resolve_market_runtime_status_authority(
        candidate_root=candidate,
        expected_stopped_status_sha256=terminal_sha256,
        service_reader=lambda label, **kwargs: target.outputs[label],
        binding_factory=binding_factory,
    )

    class Resolver:
        def resolve(self, symbol, now):
            return ProductMarketPhase(
                symbol=symbol,
                phase=MarketPhase.CLOSED,
                trading_day=None,
                current_session=None,
                next_session_start=None,
            )

    decision = run_market_runtime_promotion_preflight(
        session_factory=lambda: nullcontext(object()),
        phase_resolver_factory=lambda session: Resolver(),
        live_store_factory=lambda: object(),
        products_loader=lambda: ("au",),
        status_authority_factory=lambda: authority,
        now=lambda: datetime(2029, 1, 1, tzinfo=UTC),
    )

    assert authority.mode == "stopped_terminal"
    assert decision.status == "passed"
    assert decision.reason == "non_trading_interval"
    assert checks == ["checked", "checked"]


def test_public_daily_recovery_accepts_real_stopped_runtime_binding(target):
    from app.guiyi_cli.daily_recovery import run_daily_recovery
    from app.market_data.historical_data_manager import (
        DailyRecoveryResult,
        MaintenanceResult,
    )

    binding, terminal_sha256 = _stopped_binding_with_heartbeats(target)
    calls = []

    class Manager:
        def daily_recovery(
            self,
            request,
            *,
            expected_plan_sha256,
            before_apply,
            verify_identity,
            observer,
        ):
            verify_identity()
            calls.append((request.products, expected_plan_sha256))
            return DailyRecoveryResult(
                maintenance=MaintenanceResult(
                    "update", "planned", request.through, 0, 0, 0, 0, 0
                ),
                plan_sha256="c" * 64,
                target_windows=(),
                readonly=True,
            )

    @contextmanager
    def context(root, commit, status_sha256):
        assert (root, commit, status_sha256) == (
            target.root,
            "a" * 40,
            terminal_sha256,
        )
        yield SimpleNamespace(
            products=binding.products,
            manager=Manager(),
            invalidate_projection=lambda: None,
            verify_identity=binding.check_runtime_heartbeats,
        )

    args = SimpleNamespace(
        runtime_root=str(target.root),
        runtime_commit="a" * 40,
        expected_status_sha256=terminal_sha256,
        through=date(2029, 1, 1),
        apply=False,
        expected_plan_sha256=None,
    )

    result = run_daily_recovery(
        args, progress_stream=io.StringIO(), runtime_context_factory=context
    )

    assert result["status"] == "planned"
    assert calls == [(binding.products, None)]


def test_public_current_day_capture_accepts_real_stopped_runtime_binding(target):
    from app.guiyi_cli.current_day_metadata_recovery import (
        run_current_day_metadata_recovery,
    )
    from app.market_data.metadata import MetadataSnapshot

    binding, terminal_sha256 = _stopped_binding_with_heartbeats(target)
    calls = []
    snapshot = MetadataSnapshot((), (), (), (), (), (), {})

    @contextmanager
    def context(root, commit, status_sha256, *, phase):
        assert (root, commit, status_sha256, phase) == (
            target.root,
            "a" * 40,
            terminal_sha256,
            "capture",
        )
        yield SimpleNamespace(
            products=binding.products,
            synchronizer=SimpleNamespace(
                capture_current_day=lambda products, trading_day: (
                    calls.append((products, trading_day)) or snapshot
                )
            ),
            verify_identity=binding.check_runtime_heartbeats,
        )

    args = SimpleNamespace(
        phase="capture",
        runtime_root=str(target.root),
        runtime_commit="a" * 40,
        expected_status_sha256=terminal_sha256,
        trading_day=date(2029, 1, 1),
        snapshot=None,
        expected_snapshot_sha256=None,
        expected_plan_sha256=None,
    )

    result = run_current_day_metadata_recovery(
        args, runtime_context_factory=context
    )

    assert result["status"] == "captured"
    assert calls == [(binding.products, date(2029, 1, 1))]


@pytest.mark.parametrize("entrypoint", ["daily", "current_day"])
@pytest.mark.parametrize("failure", ["writer_reappeared", "launchd_error"])
def test_public_maintenance_stopped_runtime_identity_failure_is_fail_closed(
    target, entrypoint, failure
):
    from app.market_data.captured_recovery_runtime import CapturedRecoveryRuntimeError

    binding, terminal_sha256 = _stopped_binding_with_heartbeats(target)
    provider_calls = []
    if failure == "writer_reappeared":
        target.outputs["com.guiyi.quant-after-market"] = "candidate writer reappeared"
    else:
        original = target.module._read_launchd_service

        def unavailable(label, **kwargs):
            if label == "com.guiyi.quant-live":
                raise CapturedRecoveryRuntimeError(
                    "CAPTURED_RECOVERY_RUNTIME_IDENTITY_UNAVAILABLE"
                )
            return original(label, **kwargs)

        target.module._read_launchd_service = unavailable

    if entrypoint == "daily":
        from app.guiyi_cli.daily_recovery import run_daily_recovery
        from app.market_data.historical_data_manager import DailyRecoveryResult

        class Manager:
            def daily_recovery(self, request, **kwargs):
                kwargs["verify_identity"]()
                provider_calls.append("daily")
                return DailyRecoveryResult

        @contextmanager
        def context(root, commit, status_sha256):
            yield SimpleNamespace(
                products=binding.products,
                manager=Manager(),
                invalidate_projection=lambda: None,
                verify_identity=binding.check_runtime_heartbeats,
            )

        args = SimpleNamespace(
            runtime_root=str(target.root),
            runtime_commit="a" * 40,
            expected_status_sha256=terminal_sha256,
            through=date(2029, 1, 1),
            apply=False,
            expected_plan_sha256=None,
        )
        with pytest.raises((ValueError, CapturedRecoveryRuntimeError)):
            run_daily_recovery(
                args, progress_stream=io.StringIO(), runtime_context_factory=context
            )
    else:
        from app.guiyi_cli.current_day_metadata_recovery import (
            run_current_day_metadata_recovery,
        )
        from app.market_data.current_day_metadata_recovery import (
            CurrentDayMetadataRecoveryError,
        )

        @contextmanager
        def context(root, commit, status_sha256, *, phase):
            yield SimpleNamespace(
                products=binding.products,
                synchronizer=SimpleNamespace(
                    capture_current_day=lambda *args: provider_calls.append("current")
                ),
                verify_identity=binding.check_runtime_heartbeats,
            )

        args = SimpleNamespace(
            phase="capture",
            runtime_root=str(target.root),
            runtime_commit="a" * 40,
            expected_status_sha256=terminal_sha256,
            trading_day=date(2029, 1, 1),
            snapshot=None,
            expected_snapshot_sha256=None,
            expected_plan_sha256=None,
        )
        with pytest.raises(
            CurrentDayMetadataRecoveryError,
            match="CURRENT_DAY_METADATA_RUNTIME_IDENTITY_DRIFT",
        ):
            run_current_day_metadata_recovery(
                args, runtime_context_factory=context
            )

    assert provider_calls == []


def test_binding_constructs_target_dependencies_not_executing_environment(target, monkeypatch):
    from app.market_data.composition import build_historical_data_manager
    binding = target.create()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///wrong-environment")
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", "/wrong-lake")
    with Session(create_engine(binding.settings["DATABASE_URL"])) as db:
        manager = build_historical_data_manager(
            db,
            data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]),
            config_root=binding.root,
            provider_settings=binding.settings,
        )
        client = Redis.from_url(binding.settings["REDIS_URL"])
        heartbeat = {"runtime_root": str(target.root), "runtime_commit": "a" * 40,
            "recovery_guard_enabled": True, "generated_at": "2029-01-01T00:00:00Z"}
        requested = []
        def get(key):
            requested.append(key)
            return json.dumps(heartbeat) if key == "alert:heartbeat" else None
        monkeypatch.setattr(client, "get", get)
        store = SimpleNamespace(heartbeat=lambda: heartbeat)
        binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        assert requested == ["alert:heartbeat"]
        assert not db.in_transaction()
        assert manager.store.root == Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"])
        assert manager.provider.matches_provider_settings(binding.settings)
        target.config.write_text(target.config.read_text() + "# later replacement\n")
        with pytest.raises(ValueError):
            binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        assert not db.in_transaction()
        client.close()


def test_runtime_binding_rejects_missing_provider_configuration(target) -> None:
    target.config.write_text(
        target.config.read_text().replace(
            "RQDATA_LICENSE_KEY=fixture-rqdata-license\n", ""
        )
    )

    with pytest.raises(ValueError):
        target.create()


def test_runtime_binding_rejects_manager_with_different_provider_configuration(
    target, monkeypatch
) -> None:
    from app.market_data.composition import build_historical_data_manager

    binding = target.create()
    with Session(create_engine(binding.settings["DATABASE_URL"])) as db:
        manager = build_historical_data_manager(
            db,
            data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]),
            config_root=binding.root,
            provider_settings={"RQDATA_LICENSE_KEY": "different-license"},
        )
        client = Redis.from_url(binding.settings["REDIS_URL"])
        heartbeat = {
            "runtime_root": str(target.root),
            "runtime_commit": "a" * 40,
            "recovery_guard_enabled": True,
            "generated_at": "2029-01-01T00:00:00Z",
        }
        monkeypatch.setattr(client, "get", lambda key: json.dumps(heartbeat))
        store = SimpleNamespace(heartbeat=lambda: heartbeat)

        with pytest.raises(ValueError):
            binding.check(
                manager,
                db,
                client,
                store,
                lambda: datetime(2029, 1, 1, tzinfo=UTC),
            )

        assert manager.provider._client is None
        client.close()


def test_closeout_cli_composes_lazy_provider_from_exact_runtime_settings(
    target, monkeypatch
) -> None:
    from app.guiyi_cli import after_market_closeout as cli_closeout
    from app.market_data import closeout_binding, composition

    binding = target.create()
    real_build = composition.build_historical_data_manager
    received = []

    def build_manager(*args, **kwargs):
        received.append(kwargs.get("provider_settings"))
        return real_build(*args, **kwargs)

    def closeout(manager, **kwargs):
        assert manager.provider._client is None
        return {"status": "ready", "readonly": True}

    monkeypatch.setattr(closeout_binding, "RuntimeDataBinding", lambda *args: binding)
    monkeypatch.setattr(composition, "build_historical_data_manager", build_manager)
    monkeypatch.setattr(cli_closeout, "close_interrupted_run", closeout)
    args = SimpleNamespace(runtime_root=str(target.root), runtime_commit="a" * 40,
        expected_status_sha256="b" * 64, apply=False)

    result = cli_closeout.run_closeout_command(
        args, session_factory=None, manager_factory=None
    )

    assert result == {"status": "ready", "readonly": True}
    assert received == [binding.settings]


def test_running_binding_requires_explicit_exact_terminal_rebind(target, monkeypatch):
    from app.market_data.composition import build_historical_data_manager

    binding = target.create()
    terminal = _terminal_status()
    terminal_sha256 = _write_status(target.status, terminal)
    with Session(create_engine(binding.settings["DATABASE_URL"])) as db:
        manager = build_historical_data_manager(db,
            data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]),
            config_root=binding.root, provider_settings=binding.settings)
        client = Redis.from_url(binding.settings["REDIS_URL"])
        heartbeat = {"runtime_root": str(target.root), "runtime_commit": "a" * 40,
            "recovery_guard_enabled": True, "generated_at": "2029-01-01T00:00:00Z"}
        monkeypatch.setattr(client, "get", lambda key: json.dumps(heartbeat))
        store = SimpleNamespace(heartbeat=lambda: heartbeat)

        with pytest.raises(ValueError):
            binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        with pytest.raises(ValueError):
            binding.rebind_terminal_status("b" * 64)

        binding.rebind_terminal_status(terminal_sha256)
        binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        assert binding.last_interruption == terminal["last_interruption"]

        target.status.write_bytes(target.status.read_bytes() + b" ")
        with pytest.raises(ValueError):
            binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        client.close()


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4, 5])
def test_fresh_binding_accepts_only_exact_schema_v5_terminal_authority(target, schema_version):
    terminal = _terminal_status(schema_version=schema_version)
    terminal_sha256 = _write_status(target.status, terminal)
    _stop_writer(target)

    if schema_version < 5:
        with pytest.raises(ValueError):
            target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)
        return

    binding = target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)
    assert binding.last_interruption == terminal["last_interruption"]


def test_terminal_binding_accepts_only_explicitly_absent_writer_and_rechecks_it(target):
    terminal_sha256 = _write_status(target.status, _terminal_status())
    writer = "com.guiyi.quant-after-market"
    target.outputs[writer] = None

    binding = target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)

    assert binding.after_market_state == "stopped"
    binding.recheck_identity()

    target.outputs[writer] = (
        "service = {\nstate = not running\n"
        f"working directory = {target.root}\narguments = {{\n/bin/bash\n"
        f"{Path.home() / 'Library/Application Support/GuiyiQuant/run-local-service.sh'}\n"
        "after-market\n}\nenvironment = {\n"
        f"GUIYI_PROJECT_ROOT => {target.root}\nGUIYI_RUNTIME_COMMIT => {'a' * 40}\n"
        "}\n}\n"
    )
    with pytest.raises(ValueError):
        binding.recheck_identity()


def test_terminal_binding_treats_launchd_error_as_unavailable_not_absent(target):
    from app.market_data.captured_recovery_runtime import CapturedRecoveryRuntimeError

    terminal_sha256 = _write_status(target.status, _terminal_status())

    def unavailable(label, **kwargs):
        if label == "com.guiyi.quant-after-market":
            raise CapturedRecoveryRuntimeError(
                "CAPTURED_RECOVERY_RUNTIME_IDENTITY_UNAVAILABLE"
            )
        return target.outputs[label]

    target.module._read_launchd_service = unavailable

    with pytest.raises(ValueError):
        target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)


def test_compatible_recovery_proof_is_bounded_redacted_and_not_ready(target):
    from app.core.env import PROJECT_ROOT
    from app.market_data.captured_recovery_runtime import _read_command

    terminal = _terminal_status()
    terminal_sha256 = _write_status(target.status, terminal)
    _stop_writer(target)
    binding = target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)
    products_path = target.root / "data/universe/operational_products.txt"
    products_sha256 = hashlib.sha256(products_path.read_bytes()).hexdigest()
    candidate_commit = _read_command(
        ["/usr/bin/git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
        root=PROJECT_ROOT,
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (target.status, target.config, products_path)
    }
    heartbeat_checks = []

    proof = binding.compatible_recovery_proof(
        candidate_root=PROJECT_ROOT,
        candidate_commit=candidate_commit,
        expected_operational_products_sha256=products_sha256,
        _identity_reader=_clean_candidate_reader,
        _heartbeat_checker=lambda: heartbeat_checks.append("checked"),
    )

    assert proof == {
        "schema_version": 1,
        "command": "data.compatible-recovery-proof",
        "status": "passed",
        "readonly": True,
        "candidate": {
            "root": str(PROJECT_ROOT),
            "commit": candidate_commit,
            "tree": _read_command(
                [
                    "/usr/bin/git",
                    "-c",
                    "core.fsmonitor=false",
                    "rev-parse",
                    "HEAD^{tree}",
                ],
                root=PROJECT_ROOT,
            ),
        },
        "source_runtime": {"root": str(target.root), "commit": "a" * 40},
        "status_schema_version": 5,
        "status_sha256": terminal_sha256,
        "operational_products_sha256": products_sha256,
        "operational_products_count": 1,
        "last_interruption": terminal["last_interruption"],
        "configuration_identity": {
            "database": "retained",
            "redis": "retained",
            "canonical": "retained",
            "rqdata": "retained",
        },
        "required_services": ["api", "web", "live", "alert", "after-market"],
        "provider_requests": 0,
        "database_writes": 0,
        "canonical_writes": 0,
        "runtime_mutations": 0,
        "recovery_ready": False,
        "recovery_blockers": [
            "PUBLISHED_EXACT_RECOVERY_TAG_REQUIRED",
            "IMMUTABLE_RECOVERY_ROOT_REQUIRED",
            "SEPARATE_RECOVERY_EXECUTION_INTENT_REQUIRED",
        ],
    }
    assert "fixture-only" not in json.dumps(proof)
    assert "fixture-rqdata-license" not in json.dumps(proof)
    assert heartbeat_checks == ["checked", "checked"]
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (target.status, target.config, products_path)
    }


@pytest.mark.parametrize(
    "drift", ["candidate_commit", "candidate_root", "candidate_status", "products"]
)
def test_compatible_recovery_proof_rejects_explicit_identity_drift(target, drift):
    from app.core.env import PROJECT_ROOT
    from app.market_data.captured_recovery_runtime import _read_command

    terminal_sha256 = _write_status(target.status, _terminal_status())
    _stop_writer(target)
    binding = target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)
    candidate_commit = _read_command(
        ["/usr/bin/git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
        root=PROJECT_ROOT,
    )
    arguments = {
        "candidate_root": PROJECT_ROOT,
        "candidate_commit": candidate_commit,
        "expected_operational_products_sha256": hashlib.sha256(
            (target.root / "data/universe/operational_products.txt").read_bytes()
        ).hexdigest(),
        "_identity_reader": _clean_candidate_reader,
        "_heartbeat_checker": lambda: None,
    }
    if drift == "candidate_commit":
        arguments["candidate_commit"] = "b" * 40
    elif drift == "candidate_root":
        arguments["candidate_root"] = target.root
    elif drift == "candidate_status":
        arguments["_identity_reader"] = (
            lambda arguments, *, root: (
                " M services/quant-api/app/market_data/closeout_binding.py"
                if "status" in arguments
                else _clean_candidate_reader(arguments, root=root)
            )
        )
    else:
        arguments["expected_operational_products_sha256"] = "b" * 64

    with pytest.raises(ValueError):
        binding.compatible_recovery_proof(**arguments)


@pytest.mark.parametrize("entrypoint", ["fresh", "rebind"])
def test_terminal_binding_requires_runtime_operational_product_scope(target, entrypoint):
    binding = target.create()
    terminal = _terminal_status()
    terminal["last_run"]["products"] = ["AG"]
    terminal_sha256 = _write_status(target.status, terminal)
    if entrypoint == "fresh":
        _stop_writer(target)

    with pytest.raises(ValueError):
        if entrypoint == "fresh":
            target.module.RuntimeDataBinding(target.root, "a" * 40, terminal_sha256)
        else:
            binding.rebind_terminal_status(terminal_sha256)


def test_closeout_writer_terminal_sha_rebinds_same_runtime_binding(target):
    from app.market_data.after_market_closeout import close_interrupted_run
    from app.market_data.historical_data_manager import MaintenanceResult

    running = {
        "schema_version": 2,
        "current_run": {"scheduled_date": "2028-01-01", "started_at": "2028-01-01T00:00:00Z",
            "products": ["au"]},
        "last_run": None, "last_successful_trading_day": "2027-12-31", "last_failure": None,
    }
    running_sha256 = _write_status(target.status, running)
    guard_dir = target.root / ".run/live-recovery-guards"
    guard_dir.mkdir(mode=0o700)
    (guard_dir / "after-market.lock").touch(mode=0o600)
    binding = target.module.RuntimeDataBinding(target.root, "a" * 40, running_sha256)
    events = []
    with Session(create_engine("sqlite://")) as db:
        manager = SimpleNamespace(
            catalog=SimpleNamespace(session=db, product_partitions=lambda symbol: (),
                main_map=lambda *args: [SimpleNamespace(contract="AU2901")],
                acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: events.append("release"))),
            audit=lambda request: MaintenanceResult("audit", "passed", request.through, 0, 0, 0, 0, 0),
        )
        result = close_interrupted_run(manager, root=target.root, expected_commit="a" * 40,
            expected_status_sha256=running_sha256, products=binding.products,
            live_store=SimpleNamespace(subscriptions=lambda day: {"au": "AU2901"}),
            now=lambda: datetime(2029, 1, 1, tzinfo=UTC), apply=True,
            verify_identity=lambda *args: None)

    assert result["status"] == "closed_interrupted"
    assert result["terminal_status_sha256"] == hashlib.sha256(target.status.read_bytes()).hexdigest()
    binding.rebind_terminal_status(result["terminal_status_sha256"])
    assert binding.last_interruption == json.loads(target.status.read_bytes())["last_interruption"]
    assert events == ["release"]


def test_binding_accepts_known_inert_legacy_settings_without_exposing_them(target):
    inert_names = (
        "APP_ENV", "APP_PORT", "APP_SECRET_KEY", "BACKTEST_DATA_PATH", "BACKTEST_MAX_WORKERS",
        "BACKTEST_RESULT_PATH", "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
        "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH", "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET",
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED", "GUIYI_DATA_CORE_V2_EOD_ENABLED",
        "GUIYI_DATA_CORE_V2_LIVE_DECISION_ENABLED", "GUIYI_DATA_CORE_V2_RETENTION_SCHEDULER_ENABLED",
        "GUIYI_DATA_CORE_V2_REVIEW_ENABLED", "GUIYI_DATA_SOURCE_FALLBACKS", "GUIYI_DATA_SOURCE_PRIMARY",
        "GUIYI_HTDY_S610_ACTIVATION_RECEIPT", "GUIYI_HTDY_S610_APPROVAL_C2_HASH",
        "GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT", "GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE",
        "GUIYI_HTDY_S610_APPROVAL_C_BUNDLE", "GUIYI_HTDY_S610_APPROVAL_C_HASH",
        "GUIYI_HTDY_S610_APPROVAL_C_RECEIPT", "GUIYI_HTDY_S610_APPROVAL_C_SIGNATURE",
        "GUIYI_HTDY_S610_APPROVED_SIGNERS", "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED",
        "GUIYI_HTDY_S610_OUTPUT_DIR", "GUIYI_HTDY_S610_PHASE", "GUIYI_HTDY_S610_REQUIRED",
        "GUIYI_LIVE_RUNTIME_ENABLED", "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH",
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET", "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
        "GUIYI_SUBING_OBSERVATION_ROOT", "GUIYI_WECHAT_AUTOSEND_ENABLED", "LOG_FILE", "LOG_LEVEL",
        "QYWX_WEBHOOK_URL", "RISK_MAX_DAILY_LOSS", "RISK_MAX_DRAWDOWN", "RISK_MAX_POSITION_RATIO",
        "VITE_WS_URL",
    )
    assert target.module._RETIRED_INERT_SETTINGS == set(inert_names)
    target.config.write_text(
        target.config.read_text() + "".join(f"{name}=fixture-only\n" for name in inert_names)
    )

    binding = target.create()

    assert not binding.settings.keys() & set(inert_names)


@pytest.mark.parametrize("setting", ["APP_ENV", "CORS_ORIGINS"])
def test_binding_discards_ignored_value_without_parsing_or_expanding_it(target, tmp_path, setting):
    marker = tmp_path / "must-not-exist"
    target.config.write_text(
        target.config.read_text()
        + f"{setting}=$(touch {marker}) # ignored value is opaque to closeout\n"
    )

    binding = target.create()

    assert setting not in binding.settings
    assert not marker.exists()


def test_binding_rejects_duplicate_ignored_setting(target):
    target.config.write_text(target.config.read_text() + "APP_ENV=one\nAPP_ENV=two\n")

    with pytest.raises(ValueError):
        target.create()


def test_binding_drops_active_settings_that_closeout_does_not_consume(target):
    ignored_names = (
        "CORS_ORIGINS", "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH", "GUIYI_MARKET_HOME_PROJECTION_ENABLED",
        "VITE_API_BASE_URL", "VITE_MARKET_WS_URL", "VITE_PROXY_API_TARGET",
        "VITE_PROXY_WS_TARGET",
    )
    assert target.module._CLOSEOUT_IGNORED_SETTINGS == set(ignored_names)
    target.config.write_text(
        target.config.read_text() + "".join(f"{name}=fixture-only\n" for name in ignored_names)
    )

    binding = target.create()

    assert not binding.settings.keys() & set(ignored_names)


@pytest.mark.parametrize(("dependency", "inert_value"), [
    ("DATABASE_URL", "postgresql+psycopg://fixture@127.0.0.1:15448/test"),
    ("REDIS_URL", "redis://127.0.0.1:15449/0"),
    ("POSTGRES_PASSWORD", "fixture-only"),
    ("GUIYI_CANONICAL_DATA_ROOT", "/fixture/canonical"),
    ("GUIYI_LIVE_RECOVERY_ENABLED", "1"),
])
def test_binding_rejects_dependency_value_expanded_from_inert_setting(target, dependency, inert_value):
    lines = target.config.read_text().splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(f"{dependency}="):
            lines[index] = f"{dependency}=$APP_SECRET_KEY"
            replaced = True
            break
    assert replaced
    target.config.write_text(f"APP_SECRET_KEY={inert_value}\n" + "\n".join(lines) + "\n")

    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize(("source", "intermediate", "dependency"), [
    ("APP_SECRET_KEY", "POSTGRES_USER", "DATABASE_URL"),
    ("CORS_ORIGINS", "POSTGRES_USER", "DATABASE_URL"),
])
def test_binding_rejects_ignored_value_indirectly_expanded_into_dependency(
        target, source, intermediate, dependency):
    lines = target.config.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"{dependency}="):
            lines[index] = (
                f"{dependency}=postgresql+psycopg://${{{intermediate}}}@127.0.0.1:15448/test"
            )
            break
    else:
        pytest.fail(f"missing fixture dependency {dependency}")
    target.config.write_text(
        f"{source}=fixture\n{intermediate}=${source}\n" + "\n".join(lines) + "\n"
    )

    with pytest.raises(ValueError):
        target.create()


def test_binding_rejects_optional_redis_password_expanded_from_inert_setting(target):
    target.config.write_text(
        "APP_SECRET_KEY=fixture-only\nREDIS_PASSWORD=$APP_SECRET_KEY\n"
        + target.config.read_text()
    )

    with pytest.raises(ValueError):
        target.create()


def test_binding_allows_dependency_sources_to_build_dependency_values(target):
    target.config.write_text(
        "POSTGRES_USER=fixture\nPOSTGRES_DB=test\nPOSTGRES_PORT=15448\n"
        "DATABASE_URL=postgresql+psycopg://$POSTGRES_USER@127.0.0.1:$POSTGRES_PORT/$POSTGRES_DB\n"
        "REDIS_URL=redis://127.0.0.1:15449/0\nPOSTGRES_PASSWORD=fixture-only\n"
        "RQDATA_LICENSE_KEY=fixture-rqdata-license\n"
        f"GUIYI_CANONICAL_DATA_ROOT={target.root}/canonical\nGUIYI_LIVE_RECOVERY_ENABLED=1\n"
    )

    binding = target.create()

    assert binding.settings["DATABASE_URL"] == "postgresql+psycopg://fixture@127.0.0.1:15448/test"
    assert not binding.settings.keys() & {"POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PORT"}


def test_binding_rejects_missing_explicit_configuration_and_loaded_override(target):
    target.config.write_text(target.config.read_text().replace("REDIS_URL=redis://127.0.0.1:15449/0\n", ""))
    with pytest.raises(ValueError):
        target.create()


def test_binding_rejects_data_override_in_loaded_service(target):
    target.outputs["com.guiyi.quant-live"] = target.outputs["com.guiyi.quant-live"].replace(
        "environment = {", "environment = {\nGUIYI_RUNTIME_ENV => /different/environment")
    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("field", ["root", "commit", "working_directory", "notification"])
def test_binding_rejects_installed_plist_identity_that_differs_from_loaded_service(target, field):
    path = Path.home() / "Library/LaunchAgents/com.guiyi.quant-live.plist"
    payload = plistlib.loads(path.read_bytes())
    if field == "root":
        payload["EnvironmentVariables"]["GUIYI_PROJECT_ROOT"] = "/different/runtime"
    elif field == "commit":
        payload["EnvironmentVariables"]["GUIYI_RUNTIME_COMMIT"] = "b" * 40
    elif field == "working_directory":
        payload["WorkingDirectory"] = "/different/runtime"
    else:
        path = Path.home() / "Library/LaunchAgents/com.guiyi.quant-api.plist"
        payload = plistlib.loads(path.read_bytes())
        payload["EnvironmentVariables"]["GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"] = "/different/notification.json"
    path.write_bytes(plistlib.dumps(payload))

    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("service", ["live", "after-market"])
@pytest.mark.parametrize("installed_label", [None, "com.guiyi.quant-other"])
def test_binding_rejects_missing_or_wrong_installed_plist_label(target, service, installed_label):
    path = Path.home() / "Library/LaunchAgents" / f"com.guiyi.quant-{service}.plist"
    payload = plistlib.loads(path.read_bytes())
    if installed_label is None:
        payload.pop("Label")
    else:
        payload["Label"] = installed_label
    path.write_bytes(plistlib.dumps(payload))

    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("loaded_only", ["path", "notification"])
def test_binding_rejects_behavior_environment_only_in_loaded_service(target, loaded_only):
    label = "com.guiyi.quant-api"
    path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    if loaded_only == "path":
        payload = plistlib.loads(path.read_bytes())
        payload["EnvironmentVariables"].pop("PATH")
        path.write_bytes(plistlib.dumps(payload))
    else:
        target.outputs[label] = target.outputs[label].replace(
            "environment = {", "environment = {\nGUIYI_ALERT_NOTIFICATION_CONFIG_PATH => /loaded/notification.json")

    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("key,value", [("HOME", "/other/home"), ("BASH_ENV", "/other/startup"), ("ENV", "/other/startup")])
def test_binding_rejects_shell_config_redirection(target, key, value):
    target.outputs["com.guiyi.quant-live"] = target.outputs["com.guiyi.quant-live"].replace(
        "environment = {", f"environment = {{\n{key} => {value}")
    with pytest.raises(ValueError):
        target.create()


def test_binding_rejects_non_private_config_parent(target):
    target.config.parent.chmod(0o755)
    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("key", ["PROJECT_ROOT", "GUIYI_HTDY_S610_UNREVIEWED"])
def test_binding_rejects_unknown_config_without_prefix_allowance(target, key):
    target.config.write_text(target.config.read_text() + f"{key}=fixture-only\n")
    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("key", ["PGOPTIONS", "PGSERVICE", "PGHOST", "PGDATABASE"])
def test_binding_rejects_executing_libpq_overrides(target, monkeypatch, key):
    monkeypatch.setenv(key, "fixture-override")
    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("symlink", [False, True])
def test_binding_rejects_target_dotenv_without_reading_it(target, symlink):
    path = target.root / ".env"
    if symlink:
        path.symlink_to(target.root / "absent-secret")
    else:
        path.write_text("PGOPTIONS=fixture-only\n")
    with pytest.raises(ValueError):
        target.create()


def test_real_launchd_sanitized_environment_and_schedule_shape(target):
    # 2026-09-10 local launchctl shape; all values below are synthetic.
    # API/Alert carry notification config; EOD has non-environment => descriptors.
    for name in ("api", "alert"):
        path = Path.home() / "Library/LaunchAgents" / f"com.guiyi.quant-{name}.plist"
        payload = plistlib.loads(path.read_bytes())
        payload["EnvironmentVariables"]["GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"] = "/fixture/notification.json"
        path.write_bytes(plistlib.dumps(payload))
        target.outputs[f"com.guiyi.quant-{name}"] = target.outputs[f"com.guiyi.quant-{name}"].replace(
            "environment = {", "environment = {\nGUIYI_ALERT_NOTIFICATION_CONFIG_PATH => /fixture/notification.json")
    tail = '''inherited environment = {
SSH_AUTH_SOCK => /fixture/socket
}
default environment = {
PATH => /usr/bin:/bin
}
event triggers = {
com.apple.launchd.calendarinterval => {
descriptor = {
Hour => 18
Minute => 5
}
}
}
'''
    output = target.outputs["com.guiyi.quant-after-market"]
    target.outputs["com.guiyi.quant-after-market"] = output.rsplit("}", 1)[0] + tail + "}\n"
    assert target.create().products == ("au",)


@pytest.mark.parametrize("scope", ["environment", "inherited environment", "default environment"])
@pytest.mark.parametrize("key", ["BASH_ENV", "PGOPTIONS", "DATABASE_URL"])
def test_overrides_in_every_environment_scope_still_block(target, scope, key):
    output = target.outputs["com.guiyi.quant-live"]
    if scope == "environment":
        output = output.replace("environment = {", f"environment = {{\n{key} => fixture-only")
    else:
        output = output.rsplit("}", 1)[0] + f"{scope} = {{\n{key} => fixture-only\n}}\n}}\n"
    target.outputs["com.guiyi.quant-live"] = output
    with pytest.raises(ValueError):
        target.create()


@pytest.mark.parametrize("fragment", [
    "environment = {\nHOME => /fixture\nHOME => /other\n}\n",
    "environment = {\nBASH_ENV => {\n}\n}\n",
    "environment = {\nmalformed\n}\n",
    "environment = {\n}\nenvironment = {\n}\n",
    "event triggers = {\nenvironment = {\nPGOPTIONS => bad\n}\n}\n",
])
def test_environment_parser_rejects_ambiguous_structure(fragment):
    from app.market_data.closeout_binding import _environments
    with pytest.raises(ValueError):
        _environments("service = {\n" + fragment + "}\n")


@pytest.mark.parametrize("service,value", [("api", "relative.json"), ("alert", "/fixture/../other"),
                                           ("live", "/fixture/notification.json")])
def test_notification_path_exception_is_narrow(target, service, value):
    target.outputs[f"com.guiyi.quant-{service}"] = target.outputs[f"com.guiyi.quant-{service}"].replace(
        "environment = {", f"environment = {{\nGUIYI_ALERT_NOTIFICATION_CONFIG_PATH => {value}")
    with pytest.raises(ValueError):
        target.create()


def test_binding_validates_target_active_not_current_active(target):
    (target.root / "data/universe/active_products.txt").write_text("au\n")
    with pytest.raises(ValueError):
        target.create()


def test_catalog_check_reuses_binding_and_rechecks_status_after_heartbeats(
    target, monkeypatch
):
    binding = target.create()
    calls = []
    catalog = SimpleNamespace()
    session = SimpleNamespace()
    redis = SimpleNamespace(get=lambda key: (calls.append(key) or b"{}"))
    store = SimpleNamespace(heartbeat=lambda: {})
    monkeypatch.setattr(
        target.module,
        "assert_catalog_dependencies",
        lambda settings, **kwargs: calls.append((settings, kwargs)),
    )
    monkeypatch.setattr(
        target.module, "_verify_heartbeat", lambda *args, **kwargs: None
    )

    binding.check_catalog(
        catalog,
        session,
        redis,
        store,
        lambda: datetime(2029, 1, 1, tzinfo=UTC),
    )

    assert calls[0][1]["catalog"] is catalog
    assert calls[0][1]["session"] is session
    assert calls[1] == "alert:heartbeat"

    store.heartbeat = lambda: (target.status.write_text("{}") or {})
    with pytest.raises(ValueError):
        binding.check_catalog(
            catalog,
            session,
            redis,
            store,
            lambda: datetime(2029, 1, 1, tzinfo=UTC),
        )


def test_binding_rejects_sources_newer_than_interrupted_run(target):
    status = target.root / ".run/after-market-status.json"
    raw = json.dumps({"current_run": {"started_at": "2020-01-01T00:00:00Z"}}).encode()
    status.write_bytes(raw)
    with pytest.raises(ValueError):
        target.module.RuntimeDataBinding(target.root, "a" * 40, hashlib.sha256(raw).hexdigest())


def _chronology_binding(tmp_path, *, stable_changed_at=100, install_changed_at=250):
    from app.market_data.closeout_binding import RuntimeDataBinding

    binding = object.__new__(RuntimeDataBinding)
    binding.root = tmp_path / "runtime"
    binding.runtime_dir = tmp_path / "home/Library/Application Support/GuiyiQuant"
    binding.agent_dir = tmp_path / "home/Library/LaunchAgents"
    binding.config_path = binding.runtime_dir / "project.env"
    binding.started_ns = 300
    binding._processes = {
        name: (str(100 + index), 200)
        for index, name in enumerate(("api", "web", "live", "alert"))
    }

    def snapshot(changed_at):
        return b"", (1, 1, 1, changed_at, changed_at)

    stable_paths = [
        binding.config_path,
        binding.root / "scripts/ops/macos/run-local-service.sh",
        binding.root / "data/universe/operational_products.txt",
        binding.root / "data/universe/active_products.txt",
        binding.root / "data/universe/retired_products.txt",
        binding.root / "data/universe/product_window_starts.csv",
        binding.root / "data/universe/active_history_floor.txt",
        binding.root,
    ]
    install_paths = [binding.runtime_dir / "run-local-service.sh"] + [
        binding.agent_dir / f"com.guiyi.quant-{name}.plist"
        for name in ("api", "web", "live", "alert", "after-market")
    ]
    binding._sources = {
        **{path: snapshot(stable_changed_at) for path in stable_paths},
        **{path: snapshot(install_changed_at) for path in install_paths},
    }
    return binding


def test_binding_accepts_same_release_staged_install_artifacts_after_earliest_consumer(tmp_path):
    binding = _chronology_binding(tmp_path)

    binding._validate_age()


def _set_changed_at(binding, path, changed_at):
    content, metadata = binding._sources[path]
    binding._sources[path] = content, (*metadata[:3], changed_at, changed_at)


@pytest.mark.parametrize("source", ["config", "exact_launcher", "universe", "runtime_root"])
def test_binding_rejects_stable_source_changed_after_earliest_consumer(tmp_path, source):
    binding = _chronology_binding(tmp_path)
    paths = {
        "config": binding.config_path,
        "exact_launcher": binding.root / "scripts/ops/macos/run-local-service.sh",
        "universe": binding.root / "data/universe/operational_products.txt",
        "runtime_root": binding.root,
    }
    _set_changed_at(binding, paths[source], 250)

    with pytest.raises(ValueError):
        binding._validate_age()


@pytest.mark.parametrize("source", ["shared_launcher", "after_market_plist"])
def test_binding_rejects_install_artifact_changed_at_interrupted_run(tmp_path, source):
    binding = _chronology_binding(tmp_path)
    path = (binding.runtime_dir / "run-local-service.sh" if source == "shared_launcher"
            else binding.agent_dir / "com.guiyi.quant-after-market.plist")
    _set_changed_at(binding, path, binding.started_ns)

    with pytest.raises(ValueError):
        binding._validate_age()


def test_binding_rejects_shared_launcher_content_that_differs_from_exact_release(target):
    path = Path.home() / "Library/Application Support/GuiyiQuant/run-local-service.sh"
    path.write_text("different launcher")

    with pytest.raises(ValueError):
        target.create()


def test_binding_rejects_source_replacement_even_with_same_mtime(target):
    import os
    binding = target.create()
    before = target.config.stat()
    replacement = target.config.with_suffix(".replacement")
    replacement.write_bytes(target.config.read_bytes())
    replacement.chmod(0o600)
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(target.config)
    with pytest.raises(ValueError):
        binding.check(None, None, None, None, lambda: datetime.now(UTC))


def test_binding_rejects_process_restart_before_remote_reads(target):
    binding = target.create()
    target.outputs["com.guiyi.quant-live"] = target.outputs["com.guiyi.quant-live"].replace("pid = 102", "pid = 202")
    with pytest.raises(ValueError):
        binding.check(None, None, None, None, lambda: datetime.now(UTC))


def test_binding_rejects_symlink_config(target):
    moved = target.config.with_suffix(".real")
    target.config.rename(moved)
    target.config.symlink_to(moved)
    with pytest.raises(OSError):
        target.create()


def test_binding_rejects_different_redis_endpoint_without_connecting(target):
    from app.market_data.composition import build_historical_data_manager
    binding = target.create()
    with Session(create_engine(binding.settings["DATABASE_URL"])) as db:
        manager = build_historical_data_manager(
            db, data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]),
            config_root=binding.root, provider_settings=binding.settings,
        )
        client = Redis.from_url("redis://127.0.0.1:15450/0")
        with pytest.raises(ValueError):
            target.module.assert_dependencies(binding.settings, root=binding.root, manager=manager,
                session=db, redis=client, products=binding.products)
        assert not db.in_transaction()
        client.close()


@pytest.mark.parametrize("mismatch", [None, "missing", "other_coverage", "scalar", "other_session", "root"])
def test_binding_requires_exact_partition_validator_and_dependency_identity(target, mismatch):
    from app.market_data.composition import build_historical_data_manager
    from app.market_data.coverage_source import DatabaseCoverageSource

    binding = target.create()
    engine = create_engine(binding.settings["DATABASE_URL"])
    with Session(engine) as db, Session(engine) as other_db:
        manager = build_historical_data_manager(db,
            data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]),
            config_root=binding.root, provider_settings=binding.settings)
        client = Redis.from_url(binding.settings["REDIS_URL"])
        if mismatch == "missing":
            manager.store.boundary_validator = None
        elif mismatch == "other_coverage":
            other = DatabaseCoverageSource(db, binding.root / "data/universe/product_window_starts.csv",
                history_floor_path=binding.root / "data/universe/active_history_floor.txt")
            manager.store.boundary_validator = other.valid_boundaries
        elif mismatch == "scalar":
            class OldCoverage:
                def valid_boundary(self, key, bar):
                    raise AssertionError("A scalar validator must never be invoked")
            manager.store.boundary_validator = OldCoverage().valid_boundary
        elif mismatch == "other_session":
            manager.coverage.session = other_db
        elif mismatch == "root":
            manager.store.root = target.root / "different-canonical"
        try:
            if mismatch is None:
                target.module.assert_dependencies(binding.settings, root=binding.root, manager=manager,
                    session=db, redis=client, products=binding.products)
            else:
                with pytest.raises(ValueError):
                    target.module.assert_dependencies(binding.settings, root=binding.root, manager=manager,
                        session=db, redis=client, products=binding.products)
            assert not db.in_transaction()
            assert not other_db.in_transaction()
        finally:
            client.close()
    engine.dispose()
