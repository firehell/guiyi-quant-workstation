from __future__ import annotations

import pandas as pd

SOURCE_PERIOD = "1m"
AGGREGATED_PERIODS = ("5m", "15m", "30m", "60m")
RQDATA_DIRECT_PERIODS = ("1d", "1w", "1m")

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


def aggregate_standard_bars(frame: pd.DataFrame, period: str, *, source_period: str = SOURCE_PERIOD) -> pd.DataFrame:
    normalized = period.strip().lower()
    if normalized not in AGGREGATED_PERIODS:
        raise ValueError(f"unsupported aggregation period: {period}; supported: {AGGREGATED_PERIODS}")

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
    if "source_symbol" in first.columns:
        result["source_symbol"] = first["source_symbol"]
    return result.sort_values("datetime").reset_index(drop=True)
