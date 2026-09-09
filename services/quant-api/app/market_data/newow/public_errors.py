"""Finite error policy shared by current and explicit historical Newow APIs."""

from app.market_data.diagnostics import (
    DATA_REASONS,
    MISSING_REASONS,
    data_reason,
    safe_context,
)
from app.market_data.errors import InfrastructureError
from app.market_data.market_data_service import MarketDataError

from .product_reader import NewowProductReadCancelled
from .inflight import NewowComputationCancelled


_INVALID = frozenset(
    {
        "NEWOW_INVALID_QUERY",
        "NEWOW_INVALID_PRODUCT",
        "NEWOW_INVALID_RANGE",
        "NEWOW_INVALID_AS_OF",
        "NEWOW_INVALID_SERIES",
        "NEWOW_INVALID_PERFORMANCE_WINDOW",
        "NEWOW_INVALID_CHART_LIMIT",
        "NEWOW_INVALID_HISTORY_LIMIT",
        "NEWOW_INVALID_HISTORY_CURSOR",
        "NEWOW_AUXILIARY_COMPONENT_REQUIRED",
        "NEWOW_SECTION_PARAMETER_INVALID",
    }
)
_CONFLICT = frozenset(
    {
        "NEWOW_DATA_IDENTITY_INVALID",
        "NEWOW_DATA_OUT_OF_ORDER",
        "NEWOW_DATA_UNAVAILABLE",
        "NEWOW_PREFIX_PAGINATION_INVALID",
        "NEWOW_COMPLETE_TRADING_DAY_MISSING",
        "NEWOW_COMPLETE_PERIOD_MISSING",
        "NEWOW_SNAPSHOT_GENERATION_CONFLICT",
        "NEWOW_CURSOR_GENERATION_CONFLICT",
        "NEWOW_CURSOR_INVALID",
        "NEWOW_CHART_CURSOR_INVALID",
        "NEWOW_REFERENCE_PAIRING_CONFLICT",
        "NEWOW_PAGE_COMPARATOR_CONFLICTING_FACT",
        "NEWOW_HISTORICAL_SNAPSHOT_INVALID",
        "NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE",
        "NEWOW_SOURCE_NONPOSITIVE_PRICE",
    }
)
_BUSY = frozenset(
    {
        "NEWOW_RESOURCE_BUSY",
        "NEWOW_REQUEST_CANCELLED",
        "NEWOW_HISTORICAL_RESOLUTION_TIMEOUT",
    }
)


def public_product_error(
    error: Exception, *, context: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    """Return only known literals and a sanitized optional diagnostic envelope."""
    if isinstance(error, (NewowProductReadCancelled, NewowComputationCancelled)):
        return 429, {"code": "NEWOW_REQUEST_CANCELLED"}
    code = getattr(error, "code", None)
    reason = None
    if isinstance(error, (MarketDataError, InfrastructureError)):
        reason = (
            error.reason
            if isinstance(error, MarketDataError)
            else data_reason(error.code)
        )
        if reason not in DATA_REASONS:
            return 500, {"code": "NEWOW_INTERNAL_ERROR"}
        code = "NEWOW_DATA_UNAVAILABLE"
    elif isinstance(error, ValueError) and code is None:
        code = str(error)
    if code == "NEWOW_SOURCE_NONPOSITIVE_PRICE":
        reason = "SOURCE_NONPOSITIVE_PRICE"
    if code in _INVALID:
        status = 422
    elif code in _CONFLICT:
        status = 409
    elif code in _BUSY:
        status = 429
    else:
        return 500, {"code": "NEWOW_INTERNAL_ERROR"}
    detail: dict[str, object] = {"code": code}
    if reason is not None:
        detail["diagnostic"] = {
            "reason": reason,
            "context": {
                **safe_context(context),
                **safe_context(getattr(error, "context", None)),
            },
            "historical_candidate_recoverable": reason in MISSING_REASONS,
        }
    return status, detail
