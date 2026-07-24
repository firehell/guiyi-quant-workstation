from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.services.trading_session_clock import SessionWindow

SOURCE_PERIOD = "1m"
AGGREGATED_PERIODS = ("5m", "15m", "30m", "60m", "1d")
WEEKLY_AGGREGATED_PERIOD = "1w"
RQDATA_DIRECT_PERIODS = ("1w", "1m")

_REQUIRED_COLUMNS = {
    "symbol",
    "contract",
    "exchange",
    "vt_symbol",
    "datetime",
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "open_interest",
    "source",
    "provider",
    "data_role",
    "created_at",
}


@dataclass(frozen=True)
class StrictAggregationDiagnostics:
    source_gap_count: int = 0
    incomplete_bucket_count: int = 0
    excluded_partial_bucket_count: int = 0
    unmatched_source_row_count: int = 0


@dataclass(frozen=True)
class StrictAggregationResult:
    frame: pd.DataFrame
    diagnostics: StrictAggregationDiagnostics


def aggregate_standard_bars(frame: pd.DataFrame, period: str, *, source_period: str = SOURCE_PERIOD) -> pd.DataFrame:
    normalized = period.strip().lower()
    supported = (*AGGREGATED_PERIODS, WEEKLY_AGGREGATED_PERIOD)
    if normalized not in supported:
        raise ValueError(f"unsupported aggregation period: {period}; supported: {supported}")

    missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"standard frame missing required columns for aggregation: {missing}")

    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data["trading_day"] = pd.to_datetime(data["trading_day"], errors="coerce").dt.date
    data = data.dropna(subset=["datetime", "trading_day", "open", "high", "low", "close"])
    data = data.sort_values(["contract", "trading_day", "datetime"]).reset_index(drop=True)
    if data.empty:
        return data

    if normalized == "1d":
        return _aggregate_daily_bars(data, source_period=source_period)
    if normalized == WEEKLY_AGGREGATED_PERIOD:
        return _aggregate_weekly_bars(data, source_period=source_period)

    minutes = int(normalized.removesuffix("m"))
    previous_datetime = data.groupby(["contract", "trading_day"])["datetime"].shift()
    gap_seconds = (data["datetime"] - previous_datetime).dt.total_seconds()
    data["_block"] = gap_seconds.isna() | (gap_seconds > 90)
    data["_block"] = data.groupby(["contract", "trading_day"])["_block"].cumsum()
    data["_offset"] = data.groupby(["contract", "trading_day", "_block"]).cumcount()
    data["_bucket_index"] = data["_offset"] // minutes
    data["_bucket"] = list(zip(data["contract"], data["trading_day"], data["_block"], data["_bucket_index"], strict=False))

    grouped = data.groupby("_bucket", sort=False, dropna=False)
    first = grouped.head(1).set_index("_bucket")
    last = grouped.tail(1).set_index("_bucket")
    source_contract_col = "source_contract" if "source_contract" in last.columns else "source_symbol" if "source_symbol" in last.columns else None
    result = pd.DataFrame(
        {
            "symbol": first["symbol"],
            "contract": first["contract"],
            "exchange": first["exchange"],
            "vt_symbol": first["vt_symbol"],
            "datetime": last["datetime"],
            "trading_day": first["trading_day"],
            "interval": normalized,
            "period": normalized,
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "turnover": grouped["turnover"].sum(),
            "open_interest": grouped["open_interest"].last(),
            "source": first["source"],
            "provider": first["provider"],
            "data_role": first["data_role"],
            "quality_status": "unchecked",
            "data_version": first["data_version"],
            "source_contract": last[source_contract_col] if source_contract_col else last["contract"],
            "created_at": first["created_at"],
            "source_interval": source_period,
            "source_bar_count": grouped.size(),
        }
    )
    if "source_symbol" in last.columns:
        result["source_symbol"] = last["source_symbol"]
    elif source_contract_col:
        result["source_symbol"] = last[source_contract_col]
    else:
        result["source_symbol"] = last["contract"]
    return result.sort_values("datetime").reset_index(drop=True)


def aggregate_standard_bars_strict(
    frame: pd.DataFrame,
    period: str,
    *,
    session_windows: tuple[SessionWindow, ...] | list[SessionWindow],
    source_period: str = SOURCE_PERIOD,
) -> StrictAggregationResult:
    """Aggregate complete, session-anchored buckets and expose source gaps.

    The legacy aggregator remains unchanged. This strict entrypoint is used by
    full-history verification and controlled rebuilds where a data gap must not
    silently become a new session boundary.
    """

    normalized = period.strip().lower()
    if normalized == "1d":
        completeness = aggregate_standard_bars_strict(
            frame,
            "60m",
            session_windows=session_windows,
            source_period=source_period,
        )
        return StrictAggregationResult(
            aggregate_standard_bars(frame, normalized, source_period=source_period),
            completeness.diagnostics,
        )
    if normalized not in AGGREGATED_PERIODS:
        raise ValueError(f"unsupported aggregation period: {period}; supported: {AGGREGATED_PERIODS}")

    minutes = int(normalized.removesuffix("m"))
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data["trading_day"] = pd.to_datetime(data["trading_day"], errors="coerce").dt.date
    data = data.dropna(subset=["datetime", "trading_day"]).sort_values(
        ["contract", "trading_day", "datetime"]
    )
    if data.empty:
        return StrictAggregationResult(
            aggregate_standard_bars(frame, normalized, source_period=source_period),
            StrictAggregationDiagnostics(),
        )

    windows = tuple(sorted(session_windows, key=lambda item: item.start))
    window_by_key = {(item.trading_day, item.name): item for item in windows}
    windows_by_day: dict[date, list[SessionWindow]] = {}
    for item in windows:
        windows_by_day.setdefault(item.trading_day, []).append(item)
    assignments: list[tuple[int, str, int] | None] = []
    for row in data.itertuples():
        matched = next(
            (
                item
                for item in windows_by_day.get(row.trading_day, ())
                if item.start < row.datetime <= item.end
            ),
            None,
        )
        if matched is None:
            assignments.append(None)
            continue
        elapsed = int((row.datetime - matched.start).total_seconds() // 60)
        assignments.append((row.Index, matched.name, (elapsed - 1) // minutes))

    unmatched = sum(item is None for item in assignments)
    assigned = [item for item in assignments if item is not None]
    if not assigned:
        return StrictAggregationResult(
            aggregate_standard_bars(data.iloc[0:0], normalized, source_period=source_period),
            StrictAggregationDiagnostics(unmatched_source_row_count=unmatched),
        )

    index_to_bucket = {index: (name, bucket) for index, name, bucket in assigned}
    data = data.loc[data.index.isin(index_to_bucket)].copy()
    data["_strict_window"] = [index_to_bucket[index][0] for index in data.index]
    data["_strict_bucket"] = [index_to_bucket[index][1] for index in data.index]

    source_gap_count = 0
    incomplete_count = 0
    partial_count = 0
    observed_window_keys = {
        (contract, trading_day, window_name)
        for contract, trading_day, window_name in data[
            ["contract", "trading_day", "_strict_window"]
        ].itertuples(index=False, name=None)
    }
    for contract in sorted(set(data["contract"].astype(str))):
        for window in windows:
            if (contract, window.trading_day, window.name) in observed_window_keys:
                continue
            expected_count = int((window.end - window.start).total_seconds() // 60)
            if expected_count > 0:
                source_gap_count += expected_count
                incomplete_count += 1
    for key, observed in data.groupby(
        ["contract", "trading_day", "_strict_window"],
        sort=False,
    ):
        _, trading_day, window_name = key
        window = window_by_key[(trading_day, window_name)]
        observed_indexes = {int(item) for item in observed["_strict_bucket"].unique()}
        if not observed_indexes:
            continue
        for bucket_index in range(min(observed_indexes), max(observed_indexes) + 1):
            if bucket_index in observed_indexes:
                continue
            bucket_start = window.start + timedelta(minutes=bucket_index * minutes)
            bucket_end = min(window.end, bucket_start + timedelta(minutes=minutes))
            expected_count = int((bucket_end - bucket_start).total_seconds() // 60)
            if expected_count > 0:
                source_gap_count += expected_count
                incomplete_count += 1
    window_frame = pd.DataFrame(
        {
            "trading_day": [item.trading_day for item in windows],
            "_strict_window": [item.name for item in windows],
            "_window_start": [item.start for item in windows],
            "_window_end": [item.end for item in windows],
        }
    )
    data = data.merge(window_frame, on=["trading_day", "_strict_window"], how="left", validate="many_to_one")
    data["_bucket_start"] = data["_window_start"] + pd.to_timedelta(data["_strict_bucket"] * minutes, unit="min")
    data["_bucket_end"] = (data["_bucket_start"] + pd.Timedelta(minutes=minutes)).where(
        data["_bucket_start"] + pd.Timedelta(minutes=minutes) <= data["_window_end"],
        data["_window_end"],
    )
    data["_expected_count"] = ((data["_bucket_end"] - data["_bucket_start"]).dt.total_seconds() // 60).astype(int)
    group_columns = ["contract", "trading_day", "_strict_window", "_strict_bucket"]
    grouped = data.groupby(group_columns, sort=False, dropna=False)
    data["_actual_count"] = grouped["datetime"].transform("size")
    data["_unique_count"] = grouped["datetime"].transform("nunique")
    data["_actual_min"] = grouped["datetime"].transform("min")
    data["_actual_max"] = grouped["datetime"].transform("max")
    data["_step_seconds"] = grouped["datetime"].diff().dt.total_seconds()
    data["_max_step_seconds"] = data.groupby(group_columns, sort=False, dropna=False)["_step_seconds"].transform("max").fillna(0)
    expected_first = data["_bucket_start"] + pd.Timedelta(minutes=1)
    complete_mask = (
        (data["_actual_count"] == data["_expected_count"])
        & (data["_unique_count"] == data["_expected_count"])
        & (data["_actual_min"] == expected_first)
        & (data["_actual_max"] == data["_bucket_end"])
        & (data["_max_step_seconds"] <= 60)
    )
    duplicate_count = data["_actual_count"] - data["_unique_count"]
    boundary_partial_mask = (
        ~complete_mask
        & (duplicate_count == 0)
        & (data["_max_step_seconds"] <= 60)
        & (
            ((data["_actual_min"] > expected_first) & (data["_actual_max"] == data["_bucket_end"]))
            | ((data["_actual_min"] == expected_first) & (data["_actual_max"] < data["_bucket_end"]))
        )
    )
    group_state = data.assign(
        _complete=complete_mask,
        _boundary_partial=boundary_partial_mask,
        _missing_count=(data["_expected_count"] - data["_unique_count"]).clip(lower=0),
        _duplicate_count=duplicate_count,
    ).drop_duplicates(group_columns)
    incomplete_groups = group_state.loc[~group_state["_complete"]]
    incomplete_count += len(incomplete_groups)
    partial_count += int(incomplete_groups["_boundary_partial"].sum())
    gap_groups = incomplete_groups.loc[~incomplete_groups["_boundary_partial"]]
    gap_errors = gap_groups["_missing_count"] + gap_groups["_duplicate_count"]
    source_gap_count += int(gap_errors.where(gap_errors > 0, 1).sum())

    helper_columns = [column for column in data.columns if column.startswith("_strict_") or column.startswith("_window_") or column.startswith("_bucket_") or column.startswith("_actual_") or column.startswith("_unique_") or column.startswith("_expected_") or column.startswith("_step_") or column.startswith("_max_step_")]
    complete = data.loc[complete_mask].drop(columns=helper_columns)
    result = aggregate_standard_bars(complete, normalized, source_period=source_period)
    return StrictAggregationResult(
        result,
        StrictAggregationDiagnostics(
            source_gap_count=source_gap_count,
            incomplete_bucket_count=incomplete_count,
            excluded_partial_bucket_count=partial_count,
            unmatched_source_row_count=unmatched,
        ),
    )


def _aggregate_daily_bars(data: pd.DataFrame, *, source_period: str) -> pd.DataFrame:
    data = data.copy()
    data["_bucket"] = list(zip(data["contract"], data["trading_day"], strict=False))
    grouped = data.groupby("_bucket", sort=False, dropna=False)
    first = grouped.head(1).set_index("_bucket")
    last = grouped.tail(1).set_index("_bucket")
    source_contract_col = "source_contract" if "source_contract" in last.columns else "source_symbol" if "source_symbol" in last.columns else None
    result = pd.DataFrame(
        {
            "symbol": first["symbol"],
            "contract": first["contract"],
            "exchange": first["exchange"],
            "vt_symbol": first["vt_symbol"],
            "datetime": pd.to_datetime(first["trading_day"]),
            "trading_day": first["trading_day"],
            "interval": "1d",
            "period": "1d",
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "turnover": grouped["turnover"].sum(),
            "open_interest": grouped["open_interest"].last(),
            "source": first["source"],
            "provider": first["provider"],
            "data_role": first["data_role"],
            "quality_status": "unchecked",
            "data_version": first["data_version"],
            "source_contract": last[source_contract_col] if source_contract_col else last["contract"],
            "created_at": first["created_at"],
            "source_interval": source_period,
            "source_bar_count": grouped.size(),
        }
    )
    if "source_symbol" in last.columns:
        result["source_symbol"] = last["source_symbol"]
    elif source_contract_col:
        result["source_symbol"] = last[source_contract_col]
    else:
        result["source_symbol"] = last["contract"]
    return result.sort_values("datetime").reset_index(drop=True)


def _aggregate_weekly_bars(data: pd.DataFrame, *, source_period: str) -> pd.DataFrame:
    data = data.copy()
    iso = data["trading_day"].map(date.isocalendar)
    data["_iso_year"] = iso.map(lambda item: item.year)
    data["_iso_week"] = iso.map(lambda item: item.week)
    data["_bucket"] = list(
        zip(data["contract"], data["_iso_year"], data["_iso_week"], strict=False)
    )
    grouped = data.groupby("_bucket", sort=False, dropna=False)
    first = grouped.head(1).set_index("_bucket")
    last = grouped.tail(1).set_index("_bucket")
    source_contract_col = (
        "source_contract"
        if "source_contract" in last.columns
        else "source_symbol"
        if "source_symbol" in last.columns
        else None
    )
    result = pd.DataFrame(
        {
            "symbol": first["symbol"],
            "contract": first["contract"],
            "exchange": first["exchange"],
            "vt_symbol": first["vt_symbol"],
            "datetime": pd.to_datetime(grouped["trading_day"].max()),
            "trading_day": grouped["trading_day"].max(),
            "interval": WEEKLY_AGGREGATED_PERIOD,
            "period": WEEKLY_AGGREGATED_PERIOD,
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "turnover": grouped["turnover"].sum(),
            "open_interest": grouped["open_interest"].last(),
            "source": first["source"],
            "provider": first["provider"],
            "data_role": first["data_role"],
            "quality_status": "unchecked",
            "data_version": first["data_version"],
            "source_contract": (
                last[source_contract_col] if source_contract_col else last["contract"]
            ),
            "created_at": first["created_at"],
            "source_interval": source_period,
            "source_bar_count": grouped.size(),
        }
    )
    if "source_symbol" in last.columns:
        result["source_symbol"] = last["source_symbol"]
    elif source_contract_col:
        result["source_symbol"] = last[source_contract_col]
    else:
        result["source_symbol"] = last["contract"]
    return result.sort_values("datetime").reset_index(drop=True)
