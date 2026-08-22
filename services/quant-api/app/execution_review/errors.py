"""Stable public failures shared by Execution Review services."""

from __future__ import annotations


class ExecutionReviewDomainError(RuntimeError):
    """Stable public Execution Review failure without infrastructure detail."""

    def __init__(self, code: str, *, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def not_found(code: str) -> ExecutionReviewDomainError:
    return ExecutionReviewDomainError(code, status_code=404)


def invalid(code: str) -> ExecutionReviewDomainError:
    return ExecutionReviewDomainError(code, status_code=422)


def conflict(code: str) -> ExecutionReviewDomainError:
    return ExecutionReviewDomainError(code, status_code=409)


def persistence_failure() -> ExecutionReviewDomainError:
    return ExecutionReviewDomainError(
        "EXECUTION_REVIEW_PERSIST_FAILED",
        status_code=503,
    )
