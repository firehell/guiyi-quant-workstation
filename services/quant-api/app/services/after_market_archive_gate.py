"""Retired after-market archive gate (fail-closed stubs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ArchiveGateError(RuntimeError):
    """Raised when retired archive gate writers are invoked."""


@dataclass(frozen=True)
class ArchiveGateIdentity:
    task_id: str
    batch_prefix: str
    success_gate: str
    audit_namespace: str
    strict_recovery: bool = True


def collect_delegated_archive_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise ArchiveGateError("after-market archive gate is retired")


def execute_archive(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise ArchiveGateError("after-market archive gate is retired")


def validate_approval_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise ArchiveGateError("after-market archive gate is retired")


def _recover_committed_archive(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise ArchiveGateError("after-market archive gate is retired")
