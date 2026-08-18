"""Foreground owner for the notification-only Weixin context monitor child."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
from typing import Any

from app.alerts.recipient_registry import (
    RecipientRegistryDocument,
    load_recipient_registry,
)
from app.alerts.weixin import (
    ADAPTER_PATH,
    OpenClawWeixinDependency,
    openclaw_child_environment,
    resolve_openclaw_weixin_dependency,
)
from app.core.env import PROJECT_ROOT


@dataclass(frozen=True, slots=True)
class WeixinContextStatus:
    schema_version: int
    status: str
    recipient_count: int
    last_poll_at: datetime | None
    last_context_refresh_at: datetime | None
    last_error_code: str | None


PopenFactory = Callable[..., Any]


class WeixinContextMonitor:
    def __init__(
        self,
        dependency: OpenClawWeixinDependency,
        registry: RecipientRegistryDocument,
        *,
        status_path: Path,
        popen: PopenFactory = subprocess.Popen,
    ) -> None:
        self._dependency = dependency
        self._registry = registry
        self._status_path = status_path
        self._popen = popen

    def run_forever(self) -> None:
        bootstrap = {
            "plugin_root": str(self._dependency.plugin_root),
            "account_id": self._registry.account_id,
            "approved_recipients": [
                {"alias": recipient.alias, "target": recipient.target}
                for recipient in self._registry.enabled_recipients
            ],
            "status_path": str(self._status_path),
        }
        process = self._popen(
            [
                str(self._dependency.node_executable),
                str(ADAPTER_PATH),
                "monitor",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env=openclaw_child_environment(self._dependency.root),
        )
        if process.stdin is None:
            self._stop_child(process)
            raise RuntimeError("WEIXIN_CONTEXT_MONITOR_FAILED")
        try:
            process.stdin.write(json.dumps(bootstrap, separators=(",", ":")))
            process.stdin.close()
        except (OSError, BrokenPipeError) as exc:
            self._stop_child(process)
            raise RuntimeError("WEIXIN_CONTEXT_MONITOR_FAILED") from exc

        stopping = False

        def stop_handler(_signum: int, _frame: object) -> None:
            nonlocal stopping
            stopping = True
            self._stop_child(process)

        previous_handlers = {
            selected: signal.getsignal(selected) for selected in (signal.SIGTERM, signal.SIGINT)
        }
        try:
            for selected in previous_handlers:
                signal.signal(selected, stop_handler)
            try:
                return_code = process.wait()
            except KeyboardInterrupt:
                stopping = True
                self._stop_child(process)
                return
            if return_code != 0 and not stopping:
                raise RuntimeError("WEIXIN_CONTEXT_MONITOR_FAILED")
        finally:
            for selected, previous in previous_handlers.items():
                signal.signal(selected, previous)

    @staticmethod
    def _stop_child(process: Any) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=10.0)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("WEIXIN_CONTEXT_MONITOR_FAILED") from exc


def _required_absolute_path(name: str) -> Path:
    value = os.getenv(name, "")
    selected = Path(value)
    if not value or not selected.is_absolute():
        raise RuntimeError("WEIXIN_CONTEXT_MONITOR_CONFIG_INVALID")
    return selected


def build_weixin_context_monitor_from_env() -> WeixinContextMonitor:
    root = _required_absolute_path("GUIYI_OPENCLAW_ROOT")
    registry_path = _required_absolute_path("GUIYI_ALERT_RECIPIENTS_PATH")
    registry = load_recipient_registry(registry_path)
    dependency = resolve_openclaw_weixin_dependency(root)
    return WeixinContextMonitor(
        dependency,
        registry,
        status_path=PROJECT_ROOT / ".run/weixin-context-status.json",
    )
