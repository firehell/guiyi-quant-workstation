from __future__ import annotations

import hashlib
from pathlib import Path
import plistlib

import pytest


@pytest.fixture(autouse=True)
def _use_test_account_home(monkeypatch):
    import app.market_data.runtime_status_authority as module

    monkeypatch.setattr(module, "_account_home", lambda: Path.home())


def _installed_writer(home: Path, root: Path, commit: str) -> Path:
    agent_dir = home / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True)
    path = agent_dir / "com.guiyi.quant-after-market.plist"
    path.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.guiyi.quant-after-market",
                "WorkingDirectory": str(root),
                "ProgramArguments": [
                    "/bin/bash",
                    str(
                        home
                        / "Library/Application Support/GuiyiQuant/run-local-service.sh"
                    ),
                    "after-market",
                ],
                "EnvironmentVariables": {
                    "GUIYI_PROJECT_ROOT": str(root),
                    "GUIYI_RUNTIME_COMMIT": commit,
                },
            }
        )
    )
    return path


def test_status_authority_pins_installed_stopped_terminal_and_rechecks(
    tmp_path: Path, monkeypatch
) -> None:
    from app.market_data.runtime_status_authority import (
        resolve_market_runtime_status_authority,
    )

    home = tmp_path / "home"
    root = tmp_path / "runtime"
    run = root / ".run"
    run.mkdir(parents=True)
    status = run / "after-market-status.json"
    status.write_bytes(b'{"schema_version":5,"current_run":null}\n')
    commit = "a" * 40
    _installed_writer(home, root, commit)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    checks: list[str] = []

    class Binding:
        after_market_state = "stopped"

        def __init__(
            self,
            observed_root: Path,
            observed_commit: str,
            status_sha: str,
            *,
            home: Path,
        ):
            assert observed_root == root
            assert observed_commit == commit
            assert status_sha == hashlib.sha256(status.read_bytes()).hexdigest()
            assert home == Path.home()

        def check_runtime_heartbeats(self) -> None:
            checks.append("checked")

    authority = resolve_market_runtime_status_authority(
        candidate_root=tmp_path / "candidate",
        expected_stopped_status_sha256=hashlib.sha256(status.read_bytes()).hexdigest(),
        service_reader=lambda label, **kwargs: None,
        binding_factory=Binding,
    )

    assert authority.path == status
    assert authority.mode == "stopped_terminal"
    assert checks == ["checked"]
    authority.recheck()
    assert checks == ["checked", "checked"]


def test_status_authority_uses_account_home_not_runtime_environment_home(
    tmp_path: Path, monkeypatch
) -> None:
    import app.market_data.runtime_status_authority as module

    trusted_home = tmp_path / "trusted-home"
    attacker_home = tmp_path / "runtime-env-home"
    root = tmp_path / "runtime"
    status = root / ".run/after-market-status.json"
    status.parent.mkdir(parents=True)
    status.write_bytes(b'{"schema_version":5,"current_run":null}\n')
    expected = hashlib.sha256(status.read_bytes()).hexdigest()
    _installed_writer(trusted_home, root, "a" * 40)
    monkeypatch.setenv("HOME", str(attacker_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: attacker_home))
    monkeypatch.setattr(module, "_account_home", lambda: trusted_home, raising=False)
    observed: list[Path] = []

    class Binding:
        after_market_state = "stopped"

        def __init__(self, *args, home: Path):
            observed.append(home)

        def check_runtime_heartbeats(self) -> None:
            pass

    authority = module.resolve_market_runtime_status_authority(
        candidate_root=tmp_path / "candidate",
        expected_stopped_status_sha256=expected,
        service_reader=lambda label, **kwargs: None,
        binding_factory=Binding,
    )

    assert authority.mode == "stopped_terminal"
    assert observed == [trusted_home]


def test_status_authority_requires_independent_expected_terminal_sha(
    tmp_path: Path, monkeypatch
) -> None:
    import app.market_data.runtime_status_authority as module

    home = tmp_path / "home"
    root = tmp_path / "runtime"
    status = root / ".run/after-market-status.json"
    status.parent.mkdir(parents=True)
    status.write_bytes(b'{"schema_version":5,"current_run":null}\n')
    _installed_writer(home, root, "a" * 40)
    monkeypatch.setattr(module, "_account_home", lambda: home, raising=False)
    called: list[object] = []

    with pytest.raises(ValueError):
        module.resolve_market_runtime_status_authority(
            candidate_root=tmp_path / "candidate",
            service_reader=lambda label, **kwargs: None,
            binding_factory=lambda *args, **kwargs: called.append((args, kwargs)),
        )

    assert called == []


def test_status_authority_rejects_terminal_replaced_before_binding_creation(
    tmp_path: Path, monkeypatch
) -> None:
    import app.market_data.runtime_status_authority as module

    home = tmp_path / "home"
    root = tmp_path / "runtime"
    status = root / ".run/after-market-status.json"
    status.parent.mkdir(parents=True)
    original = b'{"schema_version":5,"current_run":null}\n'
    status.write_bytes(original)
    expected = hashlib.sha256(original).hexdigest()
    _installed_writer(home, root, "a" * 40)
    monkeypatch.setattr(module, "_account_home", lambda: home, raising=False)
    status.write_bytes(b'{"schema_version":5,"current_run":null,"replacement":true}\n')
    called: list[object] = []

    with pytest.raises(ValueError):
        module.resolve_market_runtime_status_authority(
            candidate_root=tmp_path / "candidate",
            expected_stopped_status_sha256=expected,
            service_reader=lambda label, **kwargs: None,
            binding_factory=lambda *args, **kwargs: called.append((args, kwargs)),
        )

    assert called == []


def test_status_authority_rejects_installed_stopped_candidate_without_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    from app.market_data.runtime_status_authority import (
        resolve_market_runtime_status_authority,
    )

    home = tmp_path / "home"
    root = tmp_path / "runtime"
    (root / ".run").mkdir(parents=True)
    _installed_writer(home, root, "a" * 40)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    called = []
    try:
        resolve_market_runtime_status_authority(
            candidate_root=tmp_path / "candidate",
            expected_stopped_status_sha256="b" * 64,
            service_reader=lambda label, **kwargs: None,
            binding_factory=lambda *args, **kwargs: called.append((args, kwargs)),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("missing stopped-terminal status must fail closed")

    assert called == []


@pytest.mark.parametrize("installed_root", ["", "relative/runtime"])
def test_status_authority_rejects_invalid_installed_root(
    tmp_path: Path, monkeypatch, installed_root: str
) -> None:
    from app.market_data.runtime_status_authority import (
        resolve_market_runtime_status_authority,
    )

    home = tmp_path / "home"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    path = _installed_writer(home, candidate, "a" * 40)
    payload = plistlib.loads(path.read_bytes())
    payload["EnvironmentVariables"]["GUIYI_PROJECT_ROOT"] = installed_root
    payload["WorkingDirectory"] = installed_root
    path.write_bytes(plistlib.dumps(payload))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    with pytest.raises(ValueError):
        resolve_market_runtime_status_authority(
            candidate_root=candidate,
            service_reader=lambda label, **kwargs: "loaded",
        )


def test_status_authority_rejects_non_mapping_installed_plist(
    tmp_path: Path, monkeypatch
) -> None:
    from app.market_data.runtime_status_authority import (
        resolve_market_runtime_status_authority,
    )

    home = tmp_path / "home"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    path = _installed_writer(home, candidate, "a" * 40)
    path.write_bytes(plistlib.dumps(["not", "a", "mapping"]))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    with pytest.raises(ValueError):
        resolve_market_runtime_status_authority(
            candidate_root=candidate,
            service_reader=lambda label, **kwargs: "loaded",
        )


def test_status_authority_rejects_loaded_and_installed_root_disagreement(
    tmp_path: Path, monkeypatch
) -> None:
    import app.market_data.runtime_status_authority as module

    installed_root = tmp_path / "installed"
    loaded_root = tmp_path / "loaded"
    installed_root.mkdir()
    loaded_root.mkdir()
    commit = "a" * 40
    monkeypatch.setattr(
        module, "_installed_identity", lambda *args: (installed_root, commit)
    )
    monkeypatch.setattr(module, "verify_runtime_release_identity", lambda *args: None)
    monkeypatch.setattr(module, "_verify_after_market_plist", lambda **kwargs: None)
    output = (
        "gui/501/com.guiyi.quant-after-market = {\n"
        "state = not running\n"
        f"working directory = {loaded_root}\n"
        "environment = {\n"
        f"GUIYI_PROJECT_ROOT => {loaded_root}\n"
        f"GUIYI_RUNTIME_COMMIT => {commit}\n"
        "}\n}\n"
    )

    with pytest.raises(ValueError):
        module.resolve_market_runtime_status_authority(
            candidate_root=tmp_path,
            service_reader=lambda label, **kwargs: output,
        )


def test_status_authority_preserves_loaded_owner_and_rechecks(tmp_path: Path, monkeypatch) -> None:
    import app.market_data.runtime_status_authority as module

    root = tmp_path / "runtime"
    root.mkdir()
    commit = "a" * 40
    installed = (root, commit)
    monkeypatch.setattr(module, "_installed_identity", lambda *args: installed)
    release_checks: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        module,
        "verify_runtime_release_identity",
        lambda observed_root, observed_commit: release_checks.append(
            (observed_root, observed_commit)
        ),
    )
    monkeypatch.setattr(module, "_verify_after_market_plist", lambda **kwargs: None)
    output = (
        "gui/501/com.guiyi.quant-after-market = {\n"
        "state = not running\n"
        f"working directory = {root}\n"
        "environment = {\n"
        f"GUIYI_PROJECT_ROOT => {root}\n"
        f"GUIYI_RUNTIME_COMMIT => {commit}\n"
        "}\n}\n"
    )

    authority = module.resolve_market_runtime_status_authority(
        candidate_root=tmp_path,
        service_reader=lambda label, **kwargs: output,
    )

    assert authority.path == root / ".run/after-market-status.json"
    assert authority.mode == "loaded"
    authority.recheck()
    assert release_checks == [installed, installed]


def test_status_authority_preserves_genuine_first_install_and_rejects_reappearance(
    tmp_path: Path, monkeypatch
) -> None:
    import app.market_data.runtime_status_authority as module

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    installed: list[tuple[Path, str]] = []
    loaded: list[str] = []
    monkeypatch.setattr(
        module, "_installed_identity", lambda *args: installed[0] if installed else None
    )

    authority = module.resolve_market_runtime_status_authority(
        candidate_root=candidate,
        service_reader=lambda label, **kwargs: loaded[0] if loaded else None,
    )

    assert authority.path == candidate / ".run/after-market-status.json"
    assert authority.mode == "first_install"
    loaded.append("writer reappeared")
    with pytest.raises(ValueError):
        authority.recheck()


@pytest.mark.parametrize(
    "contents",
    [
        b'{"schema_version":2,"current_run":null,"last_run":{"status":"passed"}}\n',
        b'{"schema_version":5,"current_run":null,"last_run":{"status":"interrupted"}}\n',
    ],
)
def test_genuine_first_install_rejects_any_candidate_status_residue(
    tmp_path: Path, monkeypatch, contents: bytes
) -> None:
    import app.market_data.runtime_status_authority as module

    candidate = tmp_path / "candidate"
    status = candidate / ".run/after-market-status.json"
    status.parent.mkdir(parents=True)
    status.write_bytes(contents)
    monkeypatch.setattr(module, "_installed_identity", lambda *args: None)

    with pytest.raises(ValueError):
        module.resolve_market_runtime_status_authority(
            candidate_root=candidate,
            service_reader=lambda label, **kwargs: None,
        )
