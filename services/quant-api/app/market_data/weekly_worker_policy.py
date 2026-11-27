"""Bounded diagnostics for the weekly data audit."""


def safe_error_type(exc: Exception) -> str:
    # Never persist exception text, arbitrary class names, SQL or tracebacks.
    from sqlalchemy.exc import SQLAlchemyError

    for kind, label in ((TimeoutError, "TIMEOUT"), (OSError, "IO_ERROR"),
                        (SQLAlchemyError, "DATABASE_ERROR"), (ValueError, "VALIDATION_ERROR")):
        if isinstance(exc, kind):
            return label
    return "AUDIT_ERROR"
