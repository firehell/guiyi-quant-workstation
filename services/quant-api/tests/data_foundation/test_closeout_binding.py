from types import SimpleNamespace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from redis import Redis
from datetime import UTC, datetime
import hashlib
import json
import plistlib


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
    monkeypatch.setattr(module, "verify_closeout_identity", lambda *args: None)
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
    return SimpleNamespace(root=root, config=config, module=module, outputs=outputs,
        create=lambda: module.RuntimeDataBinding(root, "a" * 40, hashlib.sha256(raw).hexdigest()))


def test_binding_constructs_target_dependencies_not_executing_environment(target, monkeypatch):
    from app.market_data.composition import build_historical_data_manager
    binding = target.create()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///wrong-environment")
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", "/wrong-lake")
    with Session(create_engine(binding.settings["DATABASE_URL"])) as db:
        manager = build_historical_data_manager(db, data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]), config_root=binding.root)
        client = Redis.from_url(binding.settings["REDIS_URL"])
        heartbeat = {"runtime_root": str(target.root), "runtime_commit": "a" * 40,
            "recovery_guard_enabled": True, "generated_at": "2029-01-01T00:00:00Z"}
        monkeypatch.setattr(client, "get", lambda key: json.dumps(heartbeat))
        store = SimpleNamespace(heartbeat=lambda: heartbeat)
        binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        assert not db.in_transaction()
        assert manager.store.root == Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"])
        target.config.write_text(target.config.read_text() + "# later replacement\n")
        with pytest.raises(ValueError):
            binding.check(manager, db, client, store, lambda: datetime(2029, 1, 1, tzinfo=UTC))
        assert not db.in_transaction()
        client.close()


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


def test_binding_rejects_launcher_variable_in_config(target):
    target.config.write_text(target.config.read_text() + "PROJECT_ROOT=/different/runtime\n")
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
        manager = build_historical_data_manager(db, data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]), config_root=binding.root)
        client = Redis.from_url("redis://127.0.0.1:15450/0")
        with pytest.raises(ValueError):
            target.module.assert_dependencies(binding.settings, root=binding.root, manager=manager,
                session=db, redis=client, products=binding.products)
        assert not db.in_transaction()
        client.close()
