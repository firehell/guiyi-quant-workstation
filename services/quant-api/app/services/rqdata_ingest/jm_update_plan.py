from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd


PRODUCT = "JM"
SYMBOL = "jm"
EXCHANGE = "DCE"
FORMAL_START = date(2023, 1, 3)
CURRENT_FORMAL_END = date(2025, 12, 31)
PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")


@dataclass(frozen=True)
class MainContractSegment:
    contract: str
    start_date: date
    end_date: date
    trading_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "trading_days": self.trading_days,
        }


def build_jm_history_update_plan(
    client: Any,
    *,
    current_end: date = CURRENT_FORMAL_END,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Build a read-only plan for updating formal JM data after current_end."""
    probe_end = as_of or date.today()
    probe_start = current_end + timedelta(days=1)
    trading_dates = client.trading_dates(probe_start, probe_end)
    if not trading_dates:
        return {
            "mode": "rqdata-jm-history-update-plan",
            "status": "up_to_date",
            "current_formal_end": current_end.isoformat(),
            "probe_start": probe_start.isoformat(),
            "probe_end": probe_end.isoformat(),
            "reason": "no RQData trading dates after current formal end",
            "writes_data": False,
            "writes_database": False,
        }

    start_date = trading_dates[0]
    end_date = trading_dates[-1]
    mapping = _normalized_main_mapping(client.dominant_contracts(PRODUCT, start_date, end_date, rank=1))
    segments = _contract_segments(mapping, set(trading_dates))
    contracts = sorted({segment.contract for segment in segments})
    return {
        "mode": "rqdata-jm-history-update-plan",
        "status": "ready",
        "product": PRODUCT,
        "symbol": SYMBOL,
        "exchange": EXCHANGE,
        "current_formal_end": current_end.isoformat(),
        "update_start_date": start_date.isoformat(),
        "latest_trading_date": end_date.isoformat(),
        "trading_days": len(trading_dates),
        "source_contracts": contracts,
        "main_contract_segments": [segment.as_dict() for segment in segments],
        "periods": {
            period: {
                "data_version": _data_version(period, end_date),
                "raw_required": True,
                "standard_required": True,
                "quality_required": "passed",
                "source_method": "rqdata_direct",
            }
            for period in PERIODS
        },
        "commands": _recommended_commands(start_date, end_date, contracts),
        "safety": {
            "requires_checkpoint_before_apply": True,
            "writes_data": False,
            "writes_database": False,
            "dry_run_only": True,
            "do_not_use_continuous_contract_as_tradable_contract": True,
        },
    }


def _normalized_main_mapping(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("RQData returned no JM dominant contract mapping")
    data = frame.copy()
    date_column = _first_existing_column(data, ("date", "trade_date", "trading_date", "datetime", "index"))
    contract_column = _first_existing_column(data, ("contract", "dominant", "order_book_id", "symbol", 0, "0"))
    if date_column is None or contract_column is None:
        raise ValueError(f"JM dominant mapping missing date or contract columns: {list(data.columns)}")
    result = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(data[date_column], errors="coerce").dt.date,
            "contract": data[contract_column].astype(str).str.upper(),
        }
    ).dropna(subset=["trade_date", "contract"])
    result = result[result["contract"] != ""]
    if result.empty:
        raise ValueError("JM dominant mapping normalized to zero rows")
    return result.sort_values("trade_date").reset_index(drop=True)


def _contract_segments(mapping: pd.DataFrame, trading_dates: set[date]) -> list[MainContractSegment]:
    segments: list[MainContractSegment] = []
    current_contract: str | None = None
    segment_start: date | None = None
    segment_end: date | None = None
    segment_days = 0
    for record in mapping.to_dict("records"):
        trade_date = record["trade_date"]
        contract = record["contract"]
        if trade_date not in trading_dates:
            continue
        if current_contract is None:
            current_contract = contract
            segment_start = trade_date
        elif contract != current_contract:
            segments.append(
                MainContractSegment(
                    contract=current_contract,
                    start_date=_required_date(segment_start),
                    end_date=_required_date(segment_end),
                    trading_days=segment_days,
                )
            )
            current_contract = contract
            segment_start = trade_date
            segment_days = 0
        segment_end = trade_date
        segment_days += 1
    if current_contract is not None:
        segments.append(
            MainContractSegment(
                contract=current_contract,
                start_date=_required_date(segment_start),
                end_date=_required_date(segment_end),
                trading_days=segment_days,
            )
        )
    if not segments:
        raise ValueError("JM dominant mapping did not overlap requested trading dates")
    return segments


def _recommended_commands(start_date: date, end_date: date, contracts: list[str]) -> list[str]:
    contract_args = " ".join(f"--contract {contract}" for contract in contracts)
    return [
        f"uv run python scripts/rqdata_main_mapping_sync.py run --product jm --start-date {start_date} --end-date {end_date}",
        f"uv run python scripts/rqdata_contract_universe_sync.py run --product jm --start-date {start_date} --end-date {end_date}",
        f"uv run python scripts/rqdata_daily_baseline_sync.py run {contract_args} --start-date {start_date} --end-date {end_date}",
        f"uv run python scripts/rqdata_trading_params_sync.py run {contract_args} --start-date {start_date} --end-date {end_date}",
    ]


def _data_version(period: str, end_date: date) -> str:
    return f"rqdata_jm_standard_{period}_{FORMAL_START:%Y%m%d}_{end_date:%Y%m%d}_v2"


def _first_existing_column(frame: pd.DataFrame, names: tuple[Any, ...]) -> Any | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _required_date(value: date | None) -> date:
    if value is None:
        raise ValueError("missing segment date")
    return value
