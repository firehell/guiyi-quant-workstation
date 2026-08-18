from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.alerts.recipient_registry import (
    NotificationRecipient,
    RecipientRegistryDocument,
)
from app.alerts.weixin import OpenClawWeixinDependency
from app.alerts.weixin_context import WeixinContextMonitor


def _fixture(tmp_path: Path) -> tuple[OpenClawWeixinDependency, RecipientRegistryDocument]:
    root = tmp_path / "openclaw"
    node = root / "runtime/tools/node/bin/node"
    cli = root / "runtime/bin/openclaw"
    plugin = root / "runtime/plugin"
    for executable in (node, cli):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("fixture", encoding="utf-8")
    plugin.mkdir(parents=True)
    dependency = OpenClawWeixinDependency(
        root,
        cli,
        node,
        plugin,
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
    return dependency, document


class _Input:
    def __init__(self) -> None:
        self.value = ""
        self.closed = False

    def write(self, value: str) -> None:
        self.value += value

    def close(self) -> None:
        self.closed = True


class _Process:
    def __init__(self, *, interrupt: bool = False, hang_after_terminate: bool = False) -> None:
        self.stdin = _Input()
        self.interrupt = interrupt
        self.hang_after_terminate = hang_after_terminate
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.interrupt and len(self.wait_calls) == 1:
            raise KeyboardInterrupt
        if self.terminated and self.hang_after_terminate and not self.killed:
            raise subprocess.TimeoutExpired("node", timeout)
        return -9 if self.killed else 0

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_context_monitor_uses_fixed_popen_and_enabled_projection(tmp_path: Path) -> None:
    dependency, document = _fixture(tmp_path)
    process = _Process()
    observed: dict[str, object] = {}

    def popen(argv: list[str], **kwargs: object) -> _Process:
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return process

    status_path = tmp_path / "status.json"
    WeixinContextMonitor(
        dependency,
        document,
        status_path=status_path,
        popen=popen,
    ).run_forever()

    assert observed["argv"] == [
        str(dependency.node_executable),
        str(
            Path(__file__).resolve().parents[3]
            / "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs"
        ),
        "monitor",
    ]
    kwargs = observed["kwargs"]
    assert kwargs["stdout"] is subprocess.DEVNULL  # type: ignore[index]
    assert kwargs["stderr"] is subprocess.DEVNULL  # type: ignore[index]
    assert process.stdin.closed is True
    assert json.loads(process.stdin.value) == {
        "plugin_root": str(dependency.plugin_root),
        "account_id": "account-fixture",
        "approved_recipients": [{"alias": "owner", "target": "u1@im.wechat"}],
        "status_path": str(status_path),
    }


def test_context_monitor_terminates_then_kills_bounded_child_on_interrupt(
    tmp_path: Path,
) -> None:
    dependency, document = _fixture(tmp_path)
    process = _Process(interrupt=True, hang_after_terminate=True)

    monitor = WeixinContextMonitor(
        dependency,
        document,
        status_path=tmp_path / "status.json",
        popen=lambda *_args, **_kwargs: process,
    )

    monitor.run_forever()

    assert process.terminated is True
    assert process.killed is True
    assert process.wait_calls == [None, 10.0, 10.0]


def test_context_monitor_collapses_unexpected_child_exit(tmp_path: Path) -> None:
    dependency, document = _fixture(tmp_path)
    process = _Process()
    process.wait = lambda timeout=None: 7  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="^WEIXIN_CONTEXT_MONITOR_FAILED$"):
        WeixinContextMonitor(
            dependency,
            document,
            status_path=tmp_path / "status.json",
            popen=lambda *_args, **_kwargs: process,
        ).run_forever()
