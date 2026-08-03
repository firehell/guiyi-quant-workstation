"""Stable error boundary for the read-only Lean Matrix CLI."""


class LeanMatrixError(ValueError):
    """A stable reason why a Lean Matrix contract cannot be rendered."""

    def __init__(self, error_type: str, detail: str) -> None:
        self.error_type = error_type
        self.detail = detail
        super().__init__(detail)
