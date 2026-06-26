import pandas as pd


def aggregate_bars(frame: pd.DataFrame, period: str) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if frame.empty:
        return frame.copy(), warnings
    if period == "1d":
        minutes = None
    else:
        minutes = int(period.removesuffix("m"))
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    group_columns = ["trading_day"]
    if "session_id" in data.columns:
        group_columns.append("session_id")
    else:
        warnings.append("missing session_id; used trading_day-only grouping")
    if minutes is None:
        data["bucket"] = data["trading_day"]
    else:
        data["bucket"] = data.groupby(group_columns).cumcount() // minutes
    grouped = data.groupby([*group_columns, "bucket"], as_index=False, sort=True)
    result = grouped.agg(
        datetime=("datetime", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        turnover=("turnover", "sum"),
        open_interest=("open_interest", "last"),
    )
    result["period"] = period
    ordered = ["datetime", "trading_day"]
    if "session_id" in result.columns:
        ordered.append("session_id")
    ordered += ["open", "high", "low", "close", "volume", "turnover", "open_interest", "period"]
    return result[ordered], warnings
