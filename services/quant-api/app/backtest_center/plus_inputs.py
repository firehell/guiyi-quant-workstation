"""Read-only admission for the pinned Plus HDF5 futures bundle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import file_digest, sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .errors import BacktestError
from .plus_costs import RESEARCH_PROFILE

SHANGHAI = ZoneInfo("Asia/Shanghai")
MINUTE = timedelta(minutes=1)
ENGINE_DEPENDENCIES = {"rqalpha-plus": "4.5.0", "rqalpha": "6.3.0", "rqalpha-mod-ricequant-data": "2.6.3"}
BASE_FILES = ("instruments.pk", "trading_dates.npy", "future_info.json", "futures.h5", "yield_curve.h5")
DAY_SESSIONS = ((time(9), time(10, 15)), (time(10, 30), time(11, 30)), (time(13, 30), time(15)))


def engine_versions() -> dict[str, str]:
    try:
        actual = {name: version(name) for name in ENGINE_DEPENDENCIES}
    except PackageNotFoundError:
        raise BacktestError("PLUS_ENGINE_NOT_INSTALLED") from None
    if actual != ENGINE_DEPENDENCIES:
        raise BacktestError("PLUS_ENGINE_VERSION_UNVERIFIED")
    return actual


def local(stamp: datetime) -> datetime:
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=SHANGHAI)
    return stamp.astimezone(SHANGHAI)


def finite(value, *, positive: bool = False) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise BacktestError("PLUS_INVALID_NATIVE_VALUE")
    return result


@dataclass(frozen=True, slots=True)
class NativeConfig:
    contract: str
    warmup_start: date
    start: date
    end: date
    initial_capital: Decimal
    commission_multiplier: Decimal
    slippage_ticks: int
    sample_type: str
    execution_delay_minutes: int = 0

    @classmethod
    def from_effective(cls, raw: dict) -> NativeConfig:
        contract = raw["contract"]
        dates = tuple(date.fromisoformat(raw[name]) for name in ("warmup_start", "start", "end"))
        parameters = raw["parameters"]
        delay = finite(parameters.get("execution_delay_minutes", 0))
        if (
            not re.fullmatch(r"FU[0-9]{2}(?:0[1-9]|1[0-2])", contract)
            or not dates[0] < dates[1] <= dates[2] or (dates[2] - dates[0]).days > 730
            or raw["strategy_id"] != "newow_trend" or raw["contract_selection"] != "physical"
            or raw["signal_frequency"] != "5m" or raw["execution_frequency"] != "1m"
            or raw["rollover_policy"] != "interrupt" or raw["benchmark"] != "cash"
            or parameters.keys() - {"execution_delay_minutes"} or delay > 3 or delay != int(delay)
        ):
            raise BacktestError("PLUS_NATIVE_CONFIG_NOT_ADMITTED")
        capital = finite(raw["initial_capital"], positive=True)
        commission = finite(raw["commission_multiplier"])
        slippage = raw["slippage_ticks"]
        if not 1 <= capital <= 1_000_000_000 or commission > 10 or type(slippage) is not int or not 0 <= slippage <= 20:
            raise BacktestError("PLUS_NATIVE_CONFIG_NOT_ADMITTED")
        return cls(contract, *dates, capital, commission, slippage, raw["sample_type"], int(delay))


@dataclass(frozen=True, slots=True)
class Session:
    day: date
    start: datetime
    end: datetime

    def minute_ends(self):
        for i in range(1, (self.end - self.start) // MINUTE + 1):
            yield self.start + i * MINUTE


@dataclass(frozen=True, slots=True)
class Minute:
    end: datetime
    session: Session
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
    open_interest: int


@dataclass(frozen=True, slots=True)
class Day:
    day: date
    limit_up: Decimal
    limit_down: Decimal
    settlement: Decimal
    previous_settlement: Decimal
    last_close: Decimal


@dataclass(frozen=True, slots=True)
class InputSlice:
    root: Path
    paths: tuple[Path, ...]
    file_hashes: tuple[str, ...]
    stamps: tuple[tuple[int, ...], ...]
    minutes: dict[datetime, Minute]
    days: dict[date, Day]
    sessions: tuple[Session, ...]
    dataset_revision: str
    slice_hash: str
    compatibility: dict[str, str]

    def snapshot(self) -> dict:
        return {
            "data_revision": self.dataset_revision,
            "input_sha256": self.slice_hash,
            "engine": {"name": "rqalpha-plus", "version": self.compatibility["rqalpha-plus"],
                       "modules": self.compatibility},
            "qualification": "TRIAL",
            "research_profile_id": RESEARCH_PROFILE,
            "data_source": "rqalpha_plus_local_bundle",
            "data_files": dict(zip((*BASE_FILES, self.paths[-1].name), self.file_hashes, strict=True)),
        }

    def verify_unchanged(self) -> None:
        hashes = tuple(_hash(path) for path in self.paths)
        if hashes != self.file_hashes or tuple(_stat(path) for path in self.paths) != self.stamps:
            raise BacktestError("PLUS_BUNDLE_CHANGED_DURING_RUN")


def _stat(path: Path) -> tuple[int, ...]:
    record = path.stat()
    return (record.st_dev, record.st_ino, record.st_size, record.st_mtime_ns, record.st_ctime_ns)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _bundle_file(root: Path, relative: str, code: str) -> Path:
    path = root / relative
    if not path.is_file() or path.resolve() != path:
        raise BacktestError(code)
    return path


def _day(raw: int) -> date:
    value = str(int(raw))
    if len(value) != 8:
        raise BacktestError("PLUS_NATIVE_TRADING_DATE_INVALID")
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")


def _calendar_days(path: Path, start: date, end: date, np) -> tuple[tuple[date, date], ...]:
    calendar = tuple(map(_day, np.load(path, allow_pickle=False)))
    if len(calendar) < 2 or calendar != tuple(sorted(set(calendar))) or end > calendar[-1] or start <= calendar[0]:
        raise BacktestError("PLUS_TRADING_CALENDAR_COVERAGE_MISSING")
    return tuple((day, previous) for previous, day in zip(calendar, calendar[1:]) if start <= day <= end)


def _sessions(day: date, previous: date) -> tuple[Session, ...]:
    # A normal Friday night belongs to Monday. No night session is attached
    # across a statutory interruption with an intervening closed weekday.
    next_weekday = previous + timedelta(days=1)
    while next_weekday.weekday() > 4:
        next_weekday += timedelta(days=1)
    clock = SHANGHAI
    night = (Session(day, datetime.combine(previous, time(21), clock),
                     datetime.combine(previous, time(23), clock)),) if next_weekday == day else ()
    return night + tuple(
        Session(day, datetime.combine(day, opening, clock), datetime.combine(day, closing, clock))
        for opening, closing in DAY_SESSIONS
    )


def _cash_day(day: date, row) -> Day:
    result = Day(day, *(finite(row[key], positive=True)
                       for key in ("limit_up", "limit_down", "settlement", "prev_settlement", "close")))
    if not result.limit_down <= result.settlement <= result.limit_up or not (
        result.limit_down <= result.last_close <= result.limit_up
    ) or result.limit_down >= result.limit_up:
        raise BacktestError("PLUS_DAILY_TRADING_FACTS_INVALID")
    return result


def _volume(value) -> int:
    raw = finite(value)
    if raw != int(raw):
        raise BacktestError("PLUS_NATIVE_FRACTIONAL_VOLUME")
    return int(raw)


def _minute(expected: datetime, session: Session, row, daily: Day) -> Minute:
    if int(row["datetime"]) != int(expected.strftime("%Y%m%d%H%M%S")) or _day(row["trading_date"]) != session.day:
        raise BacktestError("PLUS_EXECUTION_MINUTE_COVERAGE_MISSING")
    o, h, low, c = (finite(row[field], positive=True) for field in ("open", "high", "low", "close"))
    if not daily.limit_down <= low <= min(o, c) <= max(o, c) <= h <= daily.limit_up:
        raise BacktestError("PLUS_MINUTE_PRICE_OR_LIMITS_INVALID")
    return Minute(expected, session, o, h, low, c, _volume(row["volume"]),
                  finite(row["total_turnover"]), _volume(row["open_interest"]))


def preflight(config: NativeConfig, bundle: Path) -> InputSlice:
    compatibility = engine_versions()
    try:
        import h5py
        import numpy as np
    except ImportError:
        raise BacktestError("PLUS_BUNDLE_READER_UNAVAILABLE") from None
    try:
        root = bundle.resolve(strict=True)
    except OSError:
        raise BacktestError("PLUS_LOCAL_BUNDLE_MISSING") from None
    paths = tuple(_bundle_file(root, file, "PLUS_BASE_BUNDLE_INCOMPLETE") for file in BASE_FILES) + (
        _bundle_file(root, f"h5/future/{config.contract}.h5", "PLUS_EXECUTION_MINUTES_MISSING"),
    )
    try:
        stamps = tuple(_stat(path) for path in paths)
        hashes = tuple(_hash(path) for path in paths)
        dates = _calendar_days(paths[1], config.warmup_start, config.end, np)
        if not dates or not dates[0][0] < config.start <= dates[-1][0]:
            raise BacktestError("PLUS_WARMUP_OR_EVALUATION_COVERAGE_MISSING")
        sessions_by_day = {day: _sessions(day, previous) for day, previous in dates}
        days = {}
        minutes = {}
        selection_hash = sha256()
        with h5py.File(paths[3], "r") as daily, h5py.File(paths[-1], "r") as intraday:
            if config.contract not in daily:
                raise BacktestError("PLUS_PHYSICAL_DAILY_FACTS_MISSING")
            if not {"data", "index"}.issubset(intraday):
                raise BacktestError("PLUS_EXECUTION_MINUTES_MISSING")
            index = intraday["index"][:]
            values = intraday["data"]
            daily_rows = daily[config.contract][:]
            daily_by_day = {_day(int(row["datetime"]) // 1_000_000): row for row in daily_rows}
            if len(daily_by_day) != len(daily_rows):
                raise BacktestError("PLUS_DAILY_TRADING_FACTS_INVALID")
            positions = {_day(row["date"]): i for i, row in enumerate(index)}
            if len(positions) != len(index) or list(positions) != sorted(positions):
                raise BacktestError("PLUS_NATIVE_MINUTE_INDEX_INVALID")
            for day, sessions in sessions_by_day.items():
                if day not in daily_by_day:
                    raise BacktestError("PLUS_PHYSICAL_DAILY_FACTS_MISSING")
                if day not in positions:
                    raise BacktestError("PLUS_EXECUTION_MINUTE_COVERAGE_MISSING")
                daily_record = daily_by_day[day]
                daily_fact = _cash_day(day, daily_record)
                if days and daily_fact.previous_settlement != days[next(reversed(days))].settlement:
                    raise BacktestError("PLUS_DAILY_SETTLEMENT_CHAIN_MISMATCH")
                days[day] = daily_fact
                position = positions[day]
                opening = int(index[position]["line_no"])
                closing = int(index[position + 1]["line_no"]) if position + 1 < len(index) else len(values)
                if not 0 <= opening < closing <= len(values):
                    raise BacktestError("PLUS_NATIVE_MINUTE_INDEX_INVALID")
                rows = values[opening:closing]
                coverage = tuple((session, stamp) for session in sessions for stamp in session.minute_ends())
                if len(coverage) != len(rows):
                    raise BacktestError("PLUS_EXECUTION_MINUTE_COVERAGE_MISSING")
                for (session, stamp), row in zip(coverage, rows, strict=True):
                    minutes[stamp] = _minute(stamp, session, row, daily_fact)
                if minutes[sessions[-1].end].close != daily_fact.last_close:
                    raise BacktestError("PLUS_DAILY_MINUTE_CLOSE_MISMATCH")
                selection_hash.update(daily_record.tobytes())
                selection_hash.update(rows.tobytes())
        common_hash = sha256("\n".join(hashes[:-1]).encode()).hexdigest()
        selection_hash.update(
            f"{common_hash}\n{config.contract}\n{config.warmup_start}\n{config.start}\n{config.end}".encode()
        )
        if tuple(_stat(path) for path in paths) != stamps:
            raise BacktestError("PLUS_BUNDLE_CHANGED_DURING_RUN")
    except BacktestError:
        raise
    except (OSError, TypeError, ValueError, KeyError, OverflowError, ArithmeticError):
        raise BacktestError("PLUS_NATIVE_BUNDLE_READ_FAILED") from None
    return InputSlice(root, paths, hashes, stamps, minutes, days, tuple(
        session for sessions in sessions_by_day.values() for session in sessions
    ), common_hash, selection_hash.hexdigest(), compatibility)
