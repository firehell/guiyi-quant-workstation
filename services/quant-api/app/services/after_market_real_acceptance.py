"""Retired after-market real acceptance helpers."""

from __future__ import annotations

from typing import Any


class RealAcceptanceError(RuntimeError):
    """Raised when retired real-acceptance path is invoked."""


def build_real_acceptance_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise RealAcceptanceError("after-market real acceptance is retired")


def validate_real_acceptance_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise RealAcceptanceError("after-market real acceptance is retired")
