from __future__ import annotations


class DataSourceAccessError(ValueError):
    """Raised when a data source request violates V1 access rules."""


class DataSourceUnavailableError(RuntimeError):
    """Raised when a provider is intentionally not available in this phase."""
