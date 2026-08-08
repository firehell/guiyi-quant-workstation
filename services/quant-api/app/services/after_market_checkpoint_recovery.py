"""Retired after-market checkpoint recovery helpers."""

from __future__ import annotations

from typing import Any


class CheckpointRecoveryError(RuntimeError):
    """Raised when retired checkpoint recovery is invoked."""


def build_checkpoint_recovery_bound_facts(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise CheckpointRecoveryError("after-market checkpoint recovery is retired")


def validate_checkpoint_recovery_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise CheckpointRecoveryError("after-market checkpoint recovery is retired")
