from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd

CHECK_RULE_VERSION = "tqsdk_main_1m_v0"


@dataclass(frozen=True)
class QualityResult:
    status: str
    missing_bars: int
    duplicated_bars: int
    abnormal_price_count: int
    abnormal_volume_count: int
    details: dict[str, Any]


def evaluate_1m_quality(frame: pd.DataFrame) -> QualityResult:
    if frame.empty:
        return QualityResult(
            status="failed",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={
                "check_rule_version": CHECK_RULE_VERSION,
                "empty": True,
                "gap_count": 0,
                "gap_samples": [],
                "duplicate_samples": [],
                "abnormal_price_samples": [],
                "abnormal_volume_samples": [],
                "abnormal_open_interest_count": 0,
                "abnormal_open_interest_samples": [],
            },
        )

    sorted_frame = frame.sort_values("datetime")
    duplicated_mask = sorted_frame["datetime"].duplicated()
    abnormal_price_mask = (sorted_frame["high"] < sorted_frame[["open", "close", "low"]].max(axis=1)) | (
        sorted_frame["low"] > sorted_frame[["open", "close", "high"]].min(axis=1)
    )
    abnormal_volume_mask = sorted_frame["volume"] < 0
    abnormal_open_interest_mask = sorted_frame["open_interest"].notna() & (sorted_frame["open_interest"] < 0)
    missing_bars, gap_samples = _missing_bars(sorted_frame)
    abnormal_price_count = int(abnormal_price_mask.sum())
    abnormal_volume_count = int(abnormal_volume_mask.sum())
    abnormal_open_interest_count = int(abnormal_open_interest_mask.sum())
    failed_count = abnormal_price_count + abnormal_volume_count + abnormal_open_interest_count
    warning_count = int(duplicated_mask.sum()) + missing_bars
    status = "failed" if failed_count > 0 else "warning" if warning_count > 0 else "passed"
    return QualityResult(
        status=status,
        missing_bars=missing_bars,
        duplicated_bars=int(duplicated_mask.sum()),
        abnormal_price_count=abnormal_price_count,
        abnormal_volume_count=abnormal_volume_count,
        details={
            "check_rule_version": CHECK_RULE_VERSION,
            "empty": False,
            "gap_count": len(gap_samples),
            "gap_samples": gap_samples,
            "duplicate_samples": _datetime_samples(sorted_frame.loc[duplicated_mask, "datetime"]),
            "abnormal_price_samples": _datetime_samples(sorted_frame.loc[abnormal_price_mask, "datetime"]),
            "abnormal_volume_samples": _datetime_samples(sorted_frame.loc[abnormal_volume_mask, "datetime"]),
            "abnormal_open_interest_count": abnormal_open_interest_count,
            "abnormal_open_interest_samples": _datetime_samples(sorted_frame.loc[abnormal_open_interest_mask, "datetime"]),
        },
    )


def _missing_bars(frame: pd.DataFrame) -> tuple[int, list[dict[str, Any]]]:
    unique_times = list(frame["datetime"].drop_duplicates().sort_values())
    missing = 0
    samples: list[dict[str, Any]] = []
    expected_delta = timedelta(minutes=1)
    for previous, current in zip(unique_times, unique_times[1:], strict=False):
        diff = current.to_pydatetime() - previous.to_pydatetime()
        if diff <= expected_delta:
            continue
        missing_for_gap = int(diff / expected_delta) - 1
        missing += missing_for_gap
        if len(samples) < 10:
            samples.append({"from": previous.isoformat(), "to": current.isoformat(), "missing_bars": missing_for_gap})
    return missing, samples


def _datetime_samples(values: pd.Series) -> list[str]:
    return [value.isoformat() for value in values.head(10)]

