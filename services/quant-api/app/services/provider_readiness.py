from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
import hashlib
import time
from typing import Any, Callable, Protocol

import pandas as pd


class ProviderReadinessError(RuntimeError):
    """Raised when RQData has not finalized a required market-data category."""


class ProviderReadinessClient(Protocol):
    def market_data_readiness(
        self,
        *,
        expected_date: date,
        categories: tuple[str, ...],
    ) -> Mapping[str, Mapping[str, Any]]: ...


def require_provider_readiness(
    client: ProviderReadinessClient,
    *,
    expected_date: date,
    categories: Sequence[str],
) -> dict[str, dict[str, Any]]:
    requested = tuple(dict.fromkeys(str(category) for category in categories))
    return collect_provider_readiness(
        client,
        expected_date=expected_date,
        observed_categories=requested,
        required_categories=requested,
    )


def collect_provider_readiness(
    client: ProviderReadinessClient,
    *,
    expected_date: date,
    observed_categories: Sequence[str],
    required_categories: Sequence[str],
) -> dict[str, dict[str, Any]]:
    requested = tuple(dict.fromkeys(str(category) for category in observed_categories))
    required = tuple(dict.fromkeys(str(category) for category in required_categories))
    if not requested:
        raise ProviderReadinessError("provider_readiness_categories_missing")
    if set(required).difference(requested):
        raise ProviderReadinessError("provider_required_category_not_observed")
    try:
        observed = client.market_data_readiness(expected_date=expected_date, categories=requested)
    except Exception as exc:
        raise ProviderReadinessError(f"provider_readiness_unavailable:{type(exc).__name__}") from exc
    result: dict[str, dict[str, Any]] = {}
    for category in requested:
        row = observed.get(category)
        if not isinstance(row, Mapping):
            raise ProviderReadinessError(f"provider_readiness_missing:{category}")
        normalized = dict(row)
        result[category] = normalized
        if category not in required:
            continue
        if not bool(normalized.get("ready")):
            raise ProviderReadinessError(f"provider_data_pending:{category}")
        try:
            latest = date.fromisoformat(str(normalized.get("latest_date")))
        except ValueError as exc:
            raise ProviderReadinessError(f"provider_readiness_invalid_date:{category}") from exc
        if latest < expected_date:
            raise ProviderReadinessError(f"provider_data_stale:{category}")
        if str(normalized.get("expected_date")) != expected_date.isoformat():
            raise ProviderReadinessError(f"provider_expected_date_mismatch:{category}")
    return result


def provider_frame_identity(
    frame: pd.DataFrame,
    *,
    target: date,
    expected_row_count: int | None = None,
) -> dict[str, Any]:
    if frame is None or frame.empty:
        raise ProviderReadinessError("provider_target_rows_missing")
    date_column = next(
        (column for column in ("trading_date", "trade_date", "date", "datetime", "index") if column in frame.columns),
        None,
    )
    if date_column is None:
        raise ProviderReadinessError("provider_target_date_column_missing")
    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce").dt.date
    selected = frame.loc[parsed_dates == target].copy()
    if selected.empty:
        raise ProviderReadinessError(f"provider_target_rows_missing:{target.isoformat()}")
    if expected_row_count is not None and len(selected) != expected_row_count:
        raise ProviderReadinessError(f"provider_target_row_count_mismatch:{len(selected)}!={expected_row_count}")
    canonical_columns = sorted(
        column
        for column in (
            "datetime",
            "date",
            "trading_date",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "open_interest",
            "total_turnover",
            "settlement",
            "dominant_id",
        )
        if column in selected.columns
    )
    canonical = selected[canonical_columns].copy()
    sort_columns = [column for column in ("trading_date", "trade_date", "date", "datetime") if column in canonical]
    if sort_columns:
        canonical = canonical.sort_values(sort_columns, kind="stable")
    encoded = canonical.to_json(orient="records", date_format="iso", double_precision=15).encode()
    return {
        "target": target.isoformat(),
        "row_count": len(canonical),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def wait_for_provider_readiness(
    client: ProviderReadinessClient,
    *,
    expected_date: date,
    observed_categories: Sequence[str],
    required_categories: Sequence[str],
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, dict[str, Any]]:
    timeout = max(float(timeout_seconds), 0.0)
    poll = max(float(poll_seconds), 1.0)
    deadline = time.monotonic() + timeout
    while True:
        try:
            return collect_provider_readiness(
                client,
                expected_date=expected_date,
                observed_categories=observed_categories,
                required_categories=required_categories,
            )
        except ProviderReadinessError as exc:
            reason = str(exc)
            retryable = reason.startswith(("provider_data_pending:", "provider_data_stale:"))
            remaining = deadline - time.monotonic()
            if not retryable or timeout <= 0 or remaining <= 0:
                if retryable and timeout > 0 and remaining <= 0:
                    raise ProviderReadinessError(f"provider_readiness_timeout:{expected_date.isoformat()}") from exc
                raise
            sleep(min(poll, remaining))
