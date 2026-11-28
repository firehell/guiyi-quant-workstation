"""Error codes safe to return from either the API or native worker."""
class BacktestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
