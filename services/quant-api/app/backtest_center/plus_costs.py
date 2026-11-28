"""Audited, offline execution terms for the supported SHFE FU research windows."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from .codec import digest
from .errors import BacktestError

COST_PROFILE = "shfe_fu2603_rqdata_dated_terms_v1"
RESEARCH_PROFILE = "newow_trend_fu_5m_rqalpha_plus_dated_costs_trial_v2"
CONTRACT = "FU2603"
SOURCE = "rqdatac.futures.get_trading_parameters"
ROWS_SHA256 = "b7c8a54d7c586198e39e8eaa736fbe82ba6ace3d2874891172a3490d04f5beb9"
ADJACENT_ROWS_SHA256 = "8d32e0a4ef24ce2c17840e8718c000c434fb14fbb7e69f0c8354776c50056c56"
ADJACENT_COST_PROFILE = "shfe_fu2603_fu2604_rqdata_dated_terms_v2"
POINT_IN_TIME_EVIDENCE = (
    "https://www.shfe.com.cn/publicnotice/notice/202405/t20240529_801782.html",
    "https://www.shfe.com.cn/publicnotice/notice/202512/t20251205_829720.html",
    "https://www.shfe.com.cn/regulation/exchangerules/historicalversion/202508/t20250807_828542.html",
    "https://www.shfe.com.cn/publicnotice/notice/202511/t20251128_829643.html",
    "https://www.shfe.com.cn/services/calenderandholidays/holiday/",
)
ADJACENT_EFFECTIVE_EVIDENCE = (
    "https://www.shfe.com.cn/regulation/exchangerules/productrules/202512/t20251231_829966.html",
    "https://www.shfe.com.cn/publicnotice/notice/202602/t20260203_830354.html",
    "https://www.shfe.com.cn/publicnotice/notice/202602/t20260209_830421.html",
)
MAX_PROFILE_BYTES = 64 * 1024
# SHFE applies the 10th-trading-day requirement at the preceding settlement.
# These boundaries apply to the audited FU2603 window, including clipped Runs.
MARGIN_CHANGES_AT_SETTLEMENT = {date(2026, 1, 15): date(2026, 1, 16)}
HOLIDAY_SETTLEMENT = {
    date(2026, 2, 12): date(2026, 2, 13),
    date(2026, 2, 24): date(2026, 2, 25),
}
ADJACENT_SETTLEMENT = {
    "FU2603": {**MARGIN_CHANGES_AT_SETTLEMENT, **HOLIDAY_SETTLEMENT, date(2026, 2, 5): date(2026, 2, 6)},
    "FU2604": HOLIDAY_SETTLEMENT,
}


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_PROFILE_BYTES + 1)
    if len(data) > MAX_PROFILE_BYTES:
        raise BacktestError("PLUS_COST_PROFILE_TOO_LARGE")
    return data


@dataclass(frozen=True, slots=True)
class DatedCosts:
    path: Path
    artifact_sha256: str
    rows_sha256: str
    rows: dict[date, dict]
    margin_at_settlement: dict[date, dict]
    contract: str
    profile_id: str
    evidence: tuple[str, ...]
    effective_at_settlement: dict[date, date]

    @classmethod
    def load(cls, path: Path | None, contract: str, days) -> "DatedCosts":
        if path is None or not path.is_absolute() or contract not in ADJACENT_SETTLEMENT:
            raise BacktestError("PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE")
        try:
            path = path.resolve(strict=True)
            if not path.is_file():
                raise BacktestError("PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE")
            data = _read(path)
            raw = json.loads(data)
            rows = raw["rows"]
            rows_sha256 = digest(rows)
            if raw["source"] != SOURCE:
                raise BacktestError("PLUS_COST_PROFILE_NOT_VERIFIED")
            if rows_sha256 == ADJACENT_ROWS_SHA256:
                profile, evidence = ADJACENT_COST_PROFILE, POINT_IN_TIME_EVIDENCE + ADJACENT_EFFECTIVE_EVIDENCE
                effective = ADJACENT_SETTLEMENT[contract]
            elif rows_sha256 == ROWS_SHA256:
                if contract != CONTRACT:
                    raise BacktestError("PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE")
                profile, evidence, effective = COST_PROFILE, POINT_IN_TIME_EVIDENCE, MARGIN_CHANGES_AT_SETTLEMENT
            else:
                raise BacktestError("PLUS_COST_PROFILE_NOT_VERIFIED")
            by_day = {date.fromisoformat(row["trading_date"]): row for row in rows if row["contract"] == contract}
            required = tuple(days)
            if not required or any(
                day not in by_day or effective.get(day, day) not in by_day for day in required
            ):
                raise BacktestError("PLUS_COST_PROFILE_COVERAGE_MISSING")
        except BacktestError:
            raise
        except (OSError, TypeError, ValueError, KeyError):
            raise BacktestError("PLUS_COST_PROFILE_UNREADABLE") from None
        settlement = {day: by_day[effective.get(day, day)] for day in required}
        return cls(
            path, sha256(data).hexdigest(), rows_sha256, {day: by_day[day] for day in required}, settlement,
            contract, profile, evidence, {day: successor for day, successor in effective.items() if day in required},
        )

    def settlement_long_margin(self, day: date) -> Decimal:
        return Decimal(self.margin_at_settlement[day]["long_margin_ratio"])

    def snapshot(self) -> dict:
        return {"cost_profile_id": self.profile_id, "cost_source": SOURCE, "cost_rows_sha256": self.rows_sha256,
                "cost_artifact_sha256": self.artifact_sha256, "cost_effective_evidence": self.evidence,
                "margin_change_at_preceding_settlement": {
                    day.isoformat(): effective.isoformat() for day, effective in self.effective_at_settlement.items()
                }}

    def verify_unchanged(self) -> None:
        try:
            unchanged = sha256(_read(self.path)).hexdigest() == self.artifact_sha256
        except OSError:
            unchanged = False
        if not unchanged:
            raise BacktestError("PLUS_COST_PROFILE_CHANGED_DURING_RUN")


class DatedCostDataSource:
    """Let Plus's native data proxy, fee and margin engines consume exact dated terms."""

    def __init__(self, native, costs: DatedCosts):
        from rqalpha.const import COMMISSION_TYPE
        from rqalpha.data.base_data_source.storages import FuturesTradingParameters

        self._native = native
        self._settling = None
        self._contract = costs.contract
        self._effective = costs.effective_at_settlement
        self._settlement_terms = costs.margin_at_settlement
        self._parameters = {
            day: FuturesTradingParameters(
                close_commission_ratio=float(row["close_commission"]),
                close_commission_today_ratio=float(row["close_commission_today"]),
                commission_type=COMMISSION_TYPE[row["commission_type"].upper()],
                open_commission_ratio=float(row["open_commission"]),
                long_margin_ratio=float(row["long_margin_ratio"]),
                short_margin_ratio=float(row["short_margin_ratio"]),
            )
            for day, row in costs.rows.items()
        }

    def begin_settlement(self, day: date, instrument) -> None:
        self._settling = day
        if day in self._effective:
            instrument.get_long_margin_ratio.cache_clear()
            instrument.get_short_margin_ratio.cache_clear()

    def get_futures_trading_parameters(self, instrument, dt):
        day = dt.date() if isinstance(dt, datetime) else dt
        if instrument.order_book_id != self._contract or day not in self._parameters:
            raise BacktestError("PLUS_COST_PROFILE_COVERAGE_MISSING")
        parameters = self._parameters[day]
        if day == self._settling:
            margins = self._settlement_terms[day]
            return parameters._replace(long_margin_ratio=float(margins["long_margin_ratio"]),
                                       short_margin_ratio=float(margins["short_margin_ratio"]))
        return parameters

    def __getattr__(self, name):
        return getattr(self._native, name)
