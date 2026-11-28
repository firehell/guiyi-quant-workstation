"""Error codes safe to return from either the API or native worker."""


class BacktestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ExpiryInterrupted(BacktestError):
    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence
        super().__init__("ROLLOVER_INTERRUPTED")
