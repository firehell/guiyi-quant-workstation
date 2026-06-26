from __future__ import annotations


class VnpyIntegrationError(RuntimeError):
    """Base error for the vn.py adapter boundary."""


class VnpyNotInstalledError(VnpyIntegrationError):
    """Raised when vn.py is required but cannot be imported."""

    def __init__(self, package: str = "vnpy") -> None:
        super().__init__(
            f"{package} is not installed or cannot be imported. "
            "Install the project-approved vn.py dependency before using the adapter; "
            "this module will not install it automatically."
        )


class SymbolMappingError(VnpyIntegrationError, ValueError):
    """Raised when a symbol or exchange cannot be converted safely."""


class StrategyLoadError(VnpyIntegrationError):
    """Raised when a strategy class path cannot be loaded."""


class BacktestConfigurationError(VnpyIntegrationError, ValueError):
    """Raised when a vn.py backtest request is incomplete or unsupported."""
