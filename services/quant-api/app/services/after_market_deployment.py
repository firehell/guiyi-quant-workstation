"""Retired after-market deployment helpers."""

from __future__ import annotations

from typing import Any


class AfterMarketDeploymentError(RuntimeError):
    """Raised when retired deployment helpers are invoked."""


def build_deployment_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise AfterMarketDeploymentError("after-market deployment path is retired")
