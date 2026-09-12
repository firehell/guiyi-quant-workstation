"""Resolve the supervised after-market status owner without shell-side policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import plistlib
import re
from typing import Protocol

from app.market_data.after_market_closeout import verify_runtime_release_identity
from app.market_data.captured_recovery_runtime import (
    _read_launchd_service,
    _verify_after_market_plist,
    _verify_loaded_service,
)
from app.market_data.closeout_binding import RuntimeDataBinding, _snapshot


_LABEL = "com.guiyi.quant-after-market"


class _Binding(Protocol):
    after_market_state: str

    def check_runtime_heartbeats(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeStatusAuthority:
    """A pinned status path plus the recheck required immediately before use."""

    path: Path
    mode: str
    recheck: Callable[[], None]


def _installed_identity() -> tuple[Path, str] | None:
    path = Path.home() / "Library/LaunchAgents" / f"{_LABEL}.plist"
    if not os.path.lexists(path):
        return None
    content, _identity = _snapshot(path)
    try:
        payload = plistlib.loads(content)
        if not isinstance(payload, dict):
            raise ValueError
        environment = payload.get("EnvironmentVariables")
        if not isinstance(environment, dict):
            raise ValueError
        root = Path(environment["GUIYI_PROJECT_ROOT"])
        commit = environment["GUIYI_RUNTIME_COMMIT"]
        launcher = (
            Path.home()
            / "Library/Application Support/GuiyiQuant/run-local-service.sh"
        )
        if (
            payload.get("Label") != _LABEL
            or not isinstance(commit, str)
            or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or not root.is_absolute()
            or root != root.resolve(strict=True)
            or tuple(payload.get("ProgramArguments", ()))
            != ("/bin/bash", str(launcher), "after-market")
            or payload.get("WorkingDirectory") != str(root)
        ):
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError, plistlib.InvalidFileException):
        raise ValueError from None
    return root, commit


def _status_sha256(root: Path) -> str:
    try:
        content, _identity = _snapshot(root / ".run/after-market-status.json")
    except (OSError, ValueError):
        raise ValueError from None
    return hashlib.sha256(content).hexdigest()


def resolve_market_runtime_status_authority(
    *,
    candidate_root: Path,
    service_reader: Callable[..., str | None] = _read_launchd_service,
    binding_factory: Callable[[Path, str, str], _Binding] = RuntimeDataBinding,
) -> RuntimeStatusAuthority:
    """Resolve loaded, exact stopped-terminal, or genuine first-install ownership."""
    installed = _installed_identity()
    output = service_reader(_LABEL, root=candidate_root)
    if output is not None:
        if installed is None:
            raise ValueError
        root, commit = installed

        def recheck_loaded() -> None:
            if _installed_identity() != installed:
                raise ValueError
            verify_runtime_release_identity(root, commit)
            _verify_after_market_plist(root=root, commit=commit)
            current = service_reader(_LABEL, root=root)
            if current is None:
                raise ValueError
            _verify_loaded_service(
                current,
                root=root,
                commit=commit,
                allow_idle=True,
                require_idle=True,
                working_directory=root,
            )

        recheck_loaded()
        return RuntimeStatusAuthority(
            root / ".run/after-market-status.json", "loaded", recheck_loaded
        )
    if installed is None:
        root = candidate_root.resolve(strict=True)

        def recheck_first_install() -> None:
            if _installed_identity() is not None or service_reader(_LABEL, root=root) is not None:
                raise ValueError

        recheck_first_install()
        return RuntimeStatusAuthority(
            root / ".run/after-market-status.json", "first_install", recheck_first_install
        )
    root, commit = installed
    binding = binding_factory(root, commit, _status_sha256(root))
    if binding.after_market_state != "stopped":
        raise ValueError
    binding.check_runtime_heartbeats()
    return RuntimeStatusAuthority(
        root / ".run/after-market-status.json",
        "stopped_terminal",
        binding.check_runtime_heartbeats,
    )
