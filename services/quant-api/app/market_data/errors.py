"""Market data adapters shared stable error interface."""

from __future__ import annotations

from collections.abc import Mapping


class InfrastructureError(RuntimeError):
    """Adapter/coverage failure with a stable public code and bounded samples."""

    def __init__(
        self, code: str, *, samples: tuple[Mapping[str, str], ...] = ()
    ) -> None:
        self.code = code
        self.samples = samples
        super().__init__(code)
