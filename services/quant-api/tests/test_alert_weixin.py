from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import app.alerts.weixin as weixin
from app.alerts.recipient_registry import (
    NotificationRecipient,
    RecipientRegistryDocument,
)
from app.alerts.weixin import (
    OpenClawWeixinAdapterRunner,
    OpenClawWeixinDependency,
    WeixinDependencyError,
    resolve_openclaw_weixin_dependency,
)


def _versions_file(tmp_path: Path) -> Path:
    path = tmp_path / "versions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "openclaw": "2026.8.1",
                "openclaw_weixin": "2.4.6",
                "node": "24.15.0",
            }
        ),
        encoding="utf-8",
    )
    return path


def _dependency_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "openclaw"
    cli = root / "runtime/bin/openclaw"
    node = root / "runtime/tools/node/bin/node"
    plugin = root / "runtime/npm/projects/weixin/node_modules/@tencent-weixin/openclaw-weixin"
    for executable in (cli, node):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o700)
    plugin.mkdir(parents=True)
    return root, plugin


def _inspect_payload(plugin: Path, **overrides: object) -> dict[str, object]:
    plugin_fields: dict[str, object] = {
        "id": "openclaw-weixin",
        "version": "2.4.6",
        "rootDir": str(plugin),
        "enabled": True,
        "activated": True,
        "status": "loaded",
    }
    plugin_fields.update(overrides)
    return {
        "plugin": plugin_fields,
        "install": {
            "installPath": str(plugin),
            "version": "2.4.6",
            "resolvedVersion": "2.4.6",
        },
    }


def test_dependency_discovery_uses_fixed_argv_and_sanitized_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, plugin = _dependency_tree(tmp_path)
    monkeypatch.setattr(weixin, "VERSIONS_FILE", _versions_file(tmp_path))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", "/private/hostile-state")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run_process(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        calls.append((argv, environment))
        if argv == [str(root / "runtime/bin/openclaw"), "--version"]:
            stdout = "2026.8.1\n"
        elif argv == [str(root / "runtime/tools/node/bin/node"), "--version"]:
            stdout = "v24.15.0\n"
        else:
            stdout = json.dumps(_inspect_payload(plugin))
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    dependency = resolve_openclaw_weixin_dependency(root, run_process=run_process)

    assert dependency == OpenClawWeixinDependency(
        root=root.resolve(),
        cli_executable=(root / "runtime/bin/openclaw").resolve(),
        node_executable=(root / "runtime/tools/node/bin/node").resolve(),
        plugin_root=plugin.resolve(),
        openclaw_version="2026.8.1",
        plugin_version="2.4.6",
    )
    assert calls[2][0] == [
        str(root / "runtime/bin/openclaw"),
        "plugins",
        "inspect",
        "openclaw-weixin",
        "--json",
    ]
    expected_environment = {
        "GUIYI_OPENCLAW_ROOT": str(root.resolve()),
        "OPENCLAW_PREFIX": str(root.resolve() / "runtime"),
        "OPENCLAW_STATE_DIR": str(root.resolve() / "state"),
        "OPENCLAW_CONFIG_PATH": str(root.resolve() / "state/openclaw.json"),
        "OPENCLAW_CONFIG": str(root.resolve() / "state/openclaw.json"),
        "TMPDIR": str(root.resolve() / "tmp"),
        "OPENCLAW_LOG_LEVEL": "FATAL",
        "npm_config_cache": str(root.resolve() / "cache/npm"),
    }
    assert calls[0][1] == expected_environment
    assert calls[1][1] == expected_environment
    assert calls[2][1] == expected_environment
    assert "/private/hostile-state" not in calls[0][1].values()


@pytest.mark.parametrize(
    "failure",
    (
        "wrong_openclaw",
        "wrong_node",
        "wrong_plugin",
        "disabled",
        "not_loaded",
        "malformed",
        "escaping_path",
        "missing_node",
    ),
)
def test_dependency_discovery_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    root, plugin = _dependency_tree(tmp_path)
    monkeypatch.setattr(weixin, "VERSIONS_FILE", _versions_file(tmp_path))
    if failure == "missing_node":
        (root / "runtime/tools/node/bin/node").unlink()

    def run_process(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv == [str(root / "runtime/bin/openclaw"), "--version"]:
            stdout = "2026.7.0\n" if failure == "wrong_openclaw" else "2026.8.1\n"
        elif argv == [str(root / "runtime/tools/node/bin/node"), "--version"]:
            stdout = "v24.14.0\n" if failure == "wrong_node" else "v24.15.0\n"
        elif failure == "malformed":
            stdout = "not-json"
        else:
            selected = plugin
            overrides: dict[str, object] = {}
            if failure == "wrong_plugin":
                overrides["version"] = "2.4.5"
            elif failure == "disabled":
                overrides["enabled"] = False
            elif failure == "not_loaded":
                overrides["status"] = "error"
            elif failure == "escaping_path":
                selected = tmp_path / "outside"
                selected.mkdir()
            payload = _inspect_payload(selected, **overrides)
            if failure == "wrong_plugin":
                payload["install"]["version"] = "2.4.5"  # type: ignore[index]
                payload["install"]["resolvedVersion"] = "2.4.5"  # type: ignore[index]
            stdout = json.dumps(payload)
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    with pytest.raises(WeixinDependencyError):
        resolve_openclaw_weixin_dependency(root, run_process=run_process)


def test_probe_sends_only_enabled_projection_and_collapses_child_output(
    tmp_path: Path,
) -> None:
    root, plugin = _dependency_tree(tmp_path)
    dependency = OpenClawWeixinDependency(
        root.resolve(),
        (root / "runtime/bin/openclaw").resolve(),
        (root / "runtime/tools/node/bin/node").resolve(),
        plugin.resolve(),
        "2026.8.1",
        "2.4.6",
    )
    document = RecipientRegistryDocument(
        1,
        "openclaw-weixin",
        "account-fixture",
        (
            NotificationRecipient("owner", "u1@im.wechat", True),
            NotificationRecipient("paused", "u2@im.wechat", False),
        ),
    )
    observed: dict[str, object] = {}

    def run_process(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed["input"] = json.loads(str(kwargs["input"]))
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"status":"ready","recipient_count":1}\n',
            "private raw stderr",
        )

    OpenClawWeixinAdapterRunner(dependency, run_process=run_process).probe(document)

    assert observed["argv"] == [
        str(dependency.node_executable),
        str(weixin.ADAPTER_PATH),
        "probe",
    ]
    assert observed["input"] == {
        "plugin_root": str(plugin.resolve()),
        "account_id": "account-fixture",
        "enabled_recipients": [{"alias": "owner", "target": "u1@im.wechat"}],
    }


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    ((1, "{}"), (0, "not-json"), (0, '{"status":"ready","recipient_count":2}')),
)
def test_probe_fails_closed_on_child_failure(
    tmp_path: Path,
    returncode: int,
    stdout: str,
) -> None:
    root, plugin = _dependency_tree(tmp_path)
    dependency = OpenClawWeixinDependency(
        root.resolve(),
        (root / "runtime/bin/openclaw").resolve(),
        (root / "runtime/tools/node/bin/node").resolve(),
        plugin.resolve(),
        "2026.8.1",
        "2.4.6",
    )
    document = RecipientRegistryDocument(
        1,
        "openclaw-weixin",
        "account-fixture",
        (NotificationRecipient("owner", "u1@im.wechat", True),),
    )

    def run_process(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode, stdout, "private")

    with pytest.raises(RuntimeError, match="^WEIXIN_ADAPTER_UNAVAILABLE$"):
        OpenClawWeixinAdapterRunner(dependency, run_process=run_process).probe(document)
