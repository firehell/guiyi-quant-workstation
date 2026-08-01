"""Canonical read-only DCE JM trading-session contract."""

from __future__ import annotations

from datetime import date, time, timedelta
from types import MappingProxyType
from typing import Final


JM_CONTRACT_TRADING_HOURS: Final = (
    "21:01-23:00,09:01-10:15,10:31-11:30,13:31-15:00"
)
JM_SESSION_ROWS: Final = (
    ("night", time(21, 0), time(23, 0)),
    ("day_am_1", time(9, 0), time(10, 15)),
    ("day_am_2", time(10, 30), time(11, 30)),
    ("day_pm", time(13, 30), time(15, 0)),
)
JM_SESSION_PROVIDER: Final = "rqdata_contract_v1"
JM_SESSION_POLICY_VERSION: Final = "jm-dce-effective-session-v1"
JM_SESSION_DATA_VERSION_SUFFIX: Final = "jm-session-v1"
JM_SESSION_MANIFEST_VERSION: Final = "canonical-manifest-v2-jm-session"
JM_HISTORICAL_CALENDAR_FLAG_START: Final = date(2023, 1, 3)
JM_SESSION_BOUNDS: Final = MappingProxyType(
    {name: (start, end) for name, start, end in JM_SESSION_ROWS}
)
JM_SESSION_RANK: Final = MappingProxyType(
    {name: index for index, (name, _start, _end) in enumerate(JM_SESSION_ROWS)}
)

_JM_NIGHT_LAUNCH: Final = date(2014, 12, 26)
_JM_NIGHT_2330_START: Final = date(2015, 5, 8)
_JM_NIGHT_2300_START: Final = date(2019, 3, 29)
_JM_NIGHT_SUSPENDED_START: Final = date(2020, 2, 3)
_JM_NIGHT_RESUMED_START: Final = date(2020, 5, 6)


def jm_historical_night_bounds(
    *,
    trading_day: date,
    previous_trading_day: date | None,
) -> tuple[time, time] | None:
    """Return the authoritative JM night window for pre-2023 history."""
    if previous_trading_day is None:
        return None
    expected_anchor = trading_day - timedelta(
        days=3 if trading_day.weekday() == 0 else 1
    )
    if previous_trading_day != expected_anchor:
        return None
    anchor = previous_trading_day
    if anchor < _JM_NIGHT_LAUNCH:
        return None
    if _JM_NIGHT_SUSPENDED_START <= anchor < _JM_NIGHT_RESUMED_START:
        return None
    if anchor < _JM_NIGHT_2330_START:
        return time(21, 0), time(2, 30)
    if anchor < _JM_NIGHT_2300_START:
        return time(21, 0), time(23, 30)
    return time(21, 0), time(23, 0)


def jm_session_policy_document() -> dict[str, object]:
    """Return the JSON-safe policy identity bound into historical packets."""
    return {
        "policy_version": JM_SESSION_POLICY_VERSION,
        "exchange": "DCE",
        "product": "jm",
        "historical_calendar_flag_start": (
            JM_HISTORICAL_CALENDAR_FLAG_START.isoformat()
        ),
        "night_regimes": [
            {
                "effective_start": _JM_NIGHT_LAUNCH.isoformat(),
                "effective_end": _JM_NIGHT_2330_START.isoformat(),
                "start": "21:00:00",
                "end": "02:30:00",
            },
            {
                "effective_start": _JM_NIGHT_2330_START.isoformat(),
                "effective_end": _JM_NIGHT_2300_START.isoformat(),
                "start": "21:00:00",
                "end": "23:30:00",
            },
            {
                "effective_start": _JM_NIGHT_2300_START.isoformat(),
                "effective_end": None,
                "start": "21:00:00",
                "end": "23:00:00",
            },
        ],
        "night_suspensions": [
            {
                "effective_start": _JM_NIGHT_SUSPENDED_START.isoformat(),
                "effective_end": _JM_NIGHT_RESUMED_START.isoformat(),
            }
        ],
        "holiday_rule": "previous_trading_day_must_be_prior_natural_weekday_or_friday_before_monday",
    }
