from __future__ import annotations

from typing import Any

from app.vnpy_integration.errors import BacktestConfigurationError


class BacktestContractError(BacktestConfigurationError):
    """Stable, auditable formal Backtest contract rejection."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})
        self.status_code = status_code

    def payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }
