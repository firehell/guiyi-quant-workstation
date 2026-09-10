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
        env = {"GUIYI_PROJECT_ROOT": str(root), "GUIYI_RUNTIME_COMMIT": "a" * 40}
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
