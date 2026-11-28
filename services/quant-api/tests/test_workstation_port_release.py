from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sqlite3

import pytest

from app.api import workstation_settings as config
from app.backtest_center.store import RunStore
from app.runtime_bindings import CONTRACTS, BindingRegistry, ServiceBinding, market_start_preimage, registry_path
from app.workstation_port_release import WorkstationPortBackend, commit_port, quiet_backtest


def write(path, value):
    path.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def plus():
    return {**{k: "/configured/" + k for k in config.PLUS_PATHS}, "RQSDK_LICENSE": "private-placeholder"}


def test_api_profile_only_composes_for_exact_supervised_owner(tmp_path, monkeypatch):
    tmp_path = tmp_path.resolve()
    home = tmp_path / "private"
    source = write(home / "plus", plus())
    key = config.install(source, home)
    assert config.install(source, home) == key
    monkeypatch.setattr(config, "runtime_directory", lambda: home)
    monkeypatch.delenv("GUIYI_RUNTIME_HANDOVER_ENABLED", raising=False)
    assert config.configured_environment() == {}
    binding = service("api", tmp_path)
    monkeypatch.setattr(config, "resolve_service_binding", lambda _: binding)
    monkeypatch.setenv("GUIYI_RUNTIME_HANDOVER_ENABLED", "1")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    for k, v in {"GUIYI_PROJECT_ROOT": str(tmp_path), "GUIYI_RUNTIME_GENERATION": "1",
                 "GUIYI_RUNTIME_TAG": binding.tag, "GUIYI_RUNTIME_COMMIT": binding.commit}.items():
        monkeypatch.setenv(k, v)
    for k in config.PLUS:
        monkeypatch.delenv(k, raising=False)
    assert config.configured_environment() == plus()
    monkeypatch.setenv("RQSDK_LICENSE", "conflict")
    with pytest.raises(ValueError, match="ENV_CONFLICT"):
        config.configured_environment()
    monkeypatch.setenv("GUIYI_RUNTIME_GENERATION", "2")
    with pytest.raises(ValueError, match="OWNER_MISMATCH"):
        config.configured_environment()
    reader = {config.READER: "reader-placeholder"}
    assert config.install(write(home / "reader", reader), home) != key
    assert config.profile(home / config.PROFILE)[0] == plus() | reader
    with pytest.raises(ValueError, match="PROFILE_CONFLICT"):
        config.install(write(home / "reader", {config.READER: "changed"}), home)
    assert config.profile(home / config.PROFILE)[0] == plus() | reader


def test_profile_rejects_untrusted_or_extra_settings(tmp_path):
    tmp_path = tmp_path.resolve()
    p = write(tmp_path / "input", {"PATH": "/tmp"})
    for value in ({"PATH": "/tmp"}, {"RQSDK_LICENSE": "a"}, plus() | {"GUIYI_BACKTEST_PLUS_PYTHON": "relative"}):
        write(p, value)
        with pytest.raises(ValueError, match="PROFILE_INVALID"):
            config.profile(p)
    write(p, plus()).chmod(0o644)
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        config.profile(p)
    link = p.with_name("link")
    link.symlink_to(p)
    p.chmod(0o600)
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        config.profile(link)
    link.unlink()
    os.link(p, link)
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        config.profile(p)


def service(name, root):
    return ServiceBinding(name, str(root), "v1.0.0", "a" * 40, 1, True, dict.fromkeys(CONTRACTS, "0" * 64))


def test_cas_preserves_live_and_absent_peers_and_checks_old_registry(tmp_path):
    home = tmp_path.resolve()
    old = {k: service(k, home) for k in ("api", "web", "live", "weekly-audit")}
    content = {k: asdict(v) for k,v in old.items()}
    content["weekly-audit"]["root"] = str(home / "retired")
    write(registry_path(home), {"schema_version": 1, "services": content})
    previous, before, _ = market_start_preimage(home=home)
    target = home / "release"
    target.mkdir()
    def candidate(name):
        return replace(old[name], root=str(target), generation=2, tag="v1.0.1", commit="b" * 40,
                       launchd_label=f"com.guiyi.quant-{name}-candidate-" + "1" * 32)
    with pytest.raises(ValueError, match="SCOPE"):
        commit_port(previous, before, candidate("live"), home=home)
    api = candidate("api")
    commit_port(previous, before, api, home=home)
    current, digest, _ = market_start_preimage(home=home)
    assert current.services == {**previous.services, "api": api}
    with pytest.raises(ValueError, match="DRIFT"):
        commit_port(previous, before, candidate("web"), home=home)
    web = candidate("web")
    commit_port(current, digest, web, home=home)
    assert market_start_preimage(home=home)[0] == BindingRegistry(1, {**current.services, "web": web})


def test_quiet_checks_runs_and_first_experiment_writer(tmp_path):
    path = tmp_path.resolve() / "runs.db"
    RunStore(path)
    with quiet_backtest(path, reserve=True):
        with sqlite3.connect(path, timeout=0) as other, pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")
    experiments = path.with_name(path.name + ".experiments.sqlite3")
    with pytest.raises(ValueError, match="STORE_DRIFT"), quiet_backtest(path, reserve=True):
        with sqlite3.connect(experiments) as db:
            db.execute("CREATE TABLE experiments (status text)")
            db.execute("INSERT INTO experiments VALUES ('RUNNING')")
    with pytest.raises(ValueError, match="BUSY"), quiet_backtest(path, reserve=False):
        pass
    with sqlite3.connect(experiments) as db:
        db.execute("UPDATE experiments SET status='SUCCEEDED'")
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE bt_runs RENAME TO old")
        db.execute("CREATE TABLE bt_runs(status text)")
        db.execute("INSERT INTO bt_runs VALUES ('CANCELING')")
    with pytest.raises(ValueError, match="BUSY"), quiet_backtest(path, reserve=True):
        pass


def test_failed_preflight_never_drains_old_owner(tmp_path, monkeypatch):
    from app.runtime_deployment import LaunchdBackend
    seen = []
    def fail(_):
        raise ValueError("PEER_DRIFT")
    backend = WorkstationPortBackend(tmp_path, fail, lambda _: None)
    backend.candidates["web"] = object()
    monkeypatch.setattr(LaunchdBackend, "drain_owner", lambda *args: seen.append(args))
    with pytest.raises(ValueError, match="PEER_DRIFT"):
        backend.drain_owner("web", object(), "request")
    assert seen == []


def test_candidate_definition_comes_from_canonical_service_template(tmp_path):
    import plistlib
    from app.workstation_port_release import expected_definition

    class Host:
        home = tmp_path
        def _plist(self, item):
            assert item.label == "com.guiyi.quant-api"
            return plistlib.dumps({"Label": item.label, "ProgramArguments": [], "EnvironmentVariables": {"PATH": "/bin"}})

    item = replace(service("api", tmp_path.resolve()), launchd_label="com.guiyi.quant-api-candidate-" + "a"*32)
    value = expected_definition(Host(), item)
    assert value["Label"] == item.label
    assert value["ProgramArguments"][2:] == ["handover-candidate", "api", "a"*32, "1"]
    assert value["EnvironmentVariables"] == {"PATH": "/bin"}


def test_completed_api_can_finish_web_without_restarting_api(tmp_path, monkeypatch):
    from app import workstation_port_release as release

    home = tmp_path.resolve()
    target = home / "release"
    target.mkdir()
    web = service("web", home)
    api = replace(service("api", target), generation=2, tag="v1.0.1", commit="b" * 40,
                  launchd_label="com.guiyi.quant-api-candidate-" + "1"*32)
    current = BindingRegistry(1, {"api": api, "web": web, "live": service("live", home)})
    write(registry_path(home), asdict(current))
    calls = []

    class Host:
        def __init__(self):
            self.home = home
        def inventory(self):
            return market_start_preimage(home=home)
        def ready(self, items):
            calls.extend(items)

    host = Host()
    def validate(*args):
        registry, _, _ = host.inventory()
        done = {n for n in release.PAIR if registry.services[n].root == str(target)}
        return registry, done, 2, "market", "profile", {"running": {}}, home / "unused"

    def handover(name, previous, new, *, backend, commit_binding):
        assert name == "web" and previous == web
        backend.candidates[name] = replace(new, launchd_label="com.guiyi.quant-web-candidate-" + "2"*32)
        commit_binding()
        return "switched"

    monkeypatch.setattr(release, "validate", validate)
    monkeypatch.setattr(release, "protected", lambda *args: {"running": {}})
    monkeypatch.setattr(release, "execute_handover", handover)
    assert release.run(host, "apply", target, api.tag, api.commit)["status"] == "switched"
    assert host.inventory()[0].services["api"] == api
    assert release.run(host, "apply", target, api.tag, api.commit)["status"] == "switched"
    assert calls == ["web"]
